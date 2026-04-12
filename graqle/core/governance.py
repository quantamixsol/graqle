"""Governance enforcement middleware for graq_edit and graq_generate.

# ── graqle:intelligence ──
# module: graqle.core.governance
# risk: LOW (impact radius: 0 modules — new file, zero blast radius)
# dependencies: __future__, dataclasses, datetime, typing
# constraints: pattern hard-block is NEVER threshold-based and NEVER bypassable
# ── /graqle:intelligence ──

3-Tier Gate Model:

    TS-BLOCK  Any protected pattern in diff/content → unconditional hard block
    T1        risk_level=LOW  AND impact_radius ≤ 2   → auto-pass, logged only
    T2        risk_level=MEDIUM OR impact_radius 3–8   → threshold-gated, bypass recorded
    T3        risk_level=HIGH  OR impact_radius > 8    → explicit approved_by required

Every T2/T3 decision is written as a GOVERNANCE_BYPASS KG node.
Post-hoc outcome feedback enables automated threshold calibration.

Usage:
    from graqle.core.governance import GovernanceMiddleware, GovernanceConfig

    config = GovernanceConfig()
    middleware = GovernanceMiddleware(config)
    result = middleware.check(diff=unified_diff, file_path=file_path,
                               risk_level="MEDIUM", impact_radius=5)
    if result.blocked:
        return json.dumps({"error": result.reason, "tier": result.tier})
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import sys
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

_logger = logging.getLogger("graqle.core.governance")


# ---------------------------------------------------------------------------
# TS-BLOCK: protected internal patterns (binary pre-gate — never threshold-based)
# ---------------------------------------------------------------------------

# Internal pattern detectors — concrete patterns loaded from .graqle/ip_patterns.yml at runtime when available; built-in fallbacks used otherwise.
_BUILTIN_PATTERNS_DEFAULT: list[re.Pattern[str]] = [
    # Internal pattern A
    re.compile(r"\bw_J\b|\bw_A\b", re.IGNORECASE),
    # Internal pattern B
    re.compile(r"jaccard.*formula|token.set.*intersection.*arithmetic", re.IGNORECASE),
    # Internal pattern C
    re.compile(r"production.rule|stg.*rule|grammar.*rule.*node.type", re.IGNORECASE),
    # Internal pattern D
    re.compile(r"\btheta_fold\b|\bθ_fold\b", re.IGNORECASE),
    # AGREEMENT_THRESHOLD specific value
    re.compile(r"AGREEMENT_THRESHOLD\s*=\s*0\.16", re.IGNORECASE),
    # 70/30 blend internal constants
    re.compile(r"70.*30.*blend|_compute_answer_confidence.*formula", re.IGNORECASE),
]

# Module-level caches for externalized patterns
_pattern_cache: list[dict[str, Any]] | None = None
_pattern_exclude_paths: list[re.Pattern[str]] = []
_pattern_declassified: dict[str, list[re.Pattern[str]]] = {}


def _load_patterns(path: str | None = None) -> list[dict[str, Any]]:
    """Load externalized patterns from env var or YAML file.

    Resolution order:
      1. GRAQLE_PATTERNS env var (base64-encoded JSON array). The legacy
         GRAQLE_TS_PATTERNS name is also accepted for backward compatibility.
      2. ``path`` argument (YAML file, typically .graqle/ip_patterns.yml)
      3. Fall back to built-in ``_BUILTIN_PATTERNS_DEFAULT``

    Fail-closed: any parse error logs a warning and returns the built-in
    defaults so that Pattern protection is NEVER silently disabled.

    v0.51.0 robustness: env var name aligned, base64 decode explicit.
    """
    global _pattern_cache, _pattern_exclude_paths, _pattern_declassified  # noqa: PLW0603

    # 1. Environment variable (base64 JSON). Primary name is GRAQLE_PATTERNS;
    # legacy GRAQLE_TS_PATTERNS is tolerated for pre-v0.51.0 deployments.
    env_val = (
        os.environ.get("GRAQLE_PATTERNS", "").strip()
        or os.environ.get("GRAQLE_TS_PATTERNS", "").strip()
    )
    if env_val:
        try:
            # v0.51.0 robustness: explicit UTF-8 decode + schema validation
            decoded_bytes = base64.b64decode(env_val, validate=True)
            raw = json.loads(decoded_bytes.decode("utf-8"))
            if isinstance(raw, list) and len(raw) > 0:
                # Schema-validate each entry before caching.
                validated = [
                    e for e in raw
                    if isinstance(e, dict)
                    and "regex" in e
                    and isinstance(e["regex"], str)
                    and e["regex"]
                ]
                if not validated:
                    _logger.warning(
                        "GRAQLE_PATTERNS env contained no validly-shaped entries; using built-in defaults"
                    )
                    return []
                _pattern_cache = validated
                _logger.debug("Loaded %d protected patterns from GRAQLE_PATTERNS env", len(raw))
                return validated
        except Exception as exc:
            _logger.warning("GRAQLE_PATTERNS env parse failed (fail-closed): %s", exc)

    # 2. YAML file
    if path and yaml is not None:
        try:
            p = Path(path)
            if p.exists():
                data = yaml.safe_load(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    patterns = data.get("patterns", [])
                    if isinstance(patterns, list) and len(patterns) > 0:
                        _pattern_cache = patterns
                        # Load exclude paths
                        excludes = data.get("exclude_paths", [])
                        _pattern_exclude_paths = [re.compile(e) for e in excludes if isinstance(e, str)]
                        # Load declassified overrides
                        decl = data.get("declassified", {})
                        if isinstance(decl, dict):
                            for pid, globs in decl.items():
                                if isinstance(globs, list):
                                    _pattern_declassified[pid] = [re.compile(g) for g in globs]
                        _logger.debug("Loaded %d protected patterns from %s", len(patterns), path)
                        return patterns
        except Exception as exc:
            _logger.warning("Pattern file %s parse failed (fail-closed): %s", path, exc)

    # 3. Fall back to built-in defaults (fail-closed — v0.51.0 robustness:
    #    signal built-in mode via None, NEVER leave an empty list in the cache).
    _pattern_cache = None  # signal: using defaults
    return []


def invalidate_pattern_cache() -> None:
    """Clear the TS patterns cache — forces reload on next check."""
    global _pattern_cache, _pattern_exclude_paths, _pattern_declassified  # noqa: PLW0603
    _pattern_cache = None
    _pattern_exclude_paths = []
    _pattern_declassified = {}


def _is_path_excluded(file_path: str) -> bool:
    """Return True if file_path matches any exclude pattern."""
    for pat in _pattern_exclude_paths:
        if pat.search(file_path):
            return True
    return False


def _is_declassified(pattern_id: str, file_path: str) -> bool:
    """Return True if pattern_id is declassified for the given file_path."""
    globs = _pattern_declassified.get(pattern_id, [])
    for g in globs:
        if g.search(file_path):
            return True
    return False


# Layer 2: 200+ secret patterns — imported from secret_patterns module
# (pure stdlib leaf module — zero graqle.* imports, safe circular-import)
from graqle.core.secret_patterns import check_secrets_full as _check_secrets_full

# Backward-compat re-export for any code that imports _SECRET_PATTERNS directly
# (e.g., mcp_dev_server._redact uses its own SENSITIVE_KEYS — not this list)
_SECRET_PATTERNS: list = []  # Deprecated — use check_secrets_full instead


def _check_pattern_leakage(content: str, file_path: str = "") -> tuple[bool, str]:
    """Check for protected internal pattern exposure.

    Returns (blocked: bool, matched_pattern: str).
    This is the only UNCONDITIONAL block — no bypass, no threshold, no override.

    If externalized patterns are loaded, uses those with path exclusion and
    declassification support. Otherwise falls back to built-in defaults.
    """
    # Path-level exclusion (e.g. test fixtures)
    if file_path and _is_path_excluded(file_path):
        return False, ""

    # v0.51.0 robustness: treat empty or invalid cache as built-in mode.
    # The previous check only considered `_pattern_cache is None` as fallback,
    # which meant an external load that succeeded but produced an empty list
    # would leave _pattern_cache=[] and silently disable protection.
    _cache_valid = (
        _pattern_cache is not None
        and isinstance(_pattern_cache, list)
        and len(_pattern_cache) > 0
    )
    if _cache_valid:
        for entry in _pattern_cache:
            if not isinstance(entry, dict):
                continue  # skip malformed entries defensively
            pid = entry.get("id", "")
            regex = entry.get("regex", "")
            if not regex:
                continue
            # Declassification check
            if file_path and _is_declassified(pid, file_path):
                continue
            flags = re.IGNORECASE if entry.get("ignore_case", True) else 0
            try:
                m = re.search(regex, content, flags)
            except re.error:
                continue
            if m:
                label = entry.get("label", pid or regex)
                return True, f"Protected pattern detected: {label!r} ({m.group()!r})"
        return False, ""

    # Built-in defaults
    for pattern in _BUILTIN_PATTERNS_DEFAULT:
        m = pattern.search(content)
        if m:
            return True, f"Protected pattern detected: {m.group()!r}"
    return False, ""


def _check_secret_exposure(content: str) -> tuple[bool, list[str]]:
    """Check for credential/secret exposure in diff content.

    Layer 2A (regex 200+ patterns) + Layer 2B (AST structural detection).
    Layer 2B triggered automatically when regex score > 0.3.
    """
    found, matches = _check_secrets_full(content, use_ast=True)
    if not found:
        return False, []
    # v0.51.0 robustness: defensive access via getattr so a future
    # shape change in check_secrets_full cannot raise AttributeError here.
    labels: list[str] = []
    for m in matches[:10]:
        _g = getattr(m, "group", None)
        _n = getattr(m, "pattern_name", None)
        if _g is None or _n is None:
            continue
        labels.append(f"{_g}:{_n}")
    return True, labels


# ---------------------------------------------------------------------------
# Gate Config
# ---------------------------------------------------------------------------

@dataclass
class GovernanceConfig:
    """Governance threshold configuration — stored in graqle.yaml under 'governance:'.

    Thresholds are calibrated automatically from GOVERNANCE_BYPASS outcome data.
    Protected patterns are NEVER threshold-based and NEVER relaxed by calibration.
    """
    # Pattern protection — cannot be disabled
    ts_hard_block: bool = True              # NEVER set to False in production
    ts_patterns_file: Optional[str] = None  # Path to ip_patterns.yml

    # T1 auto-pass boundaries
    auto_pass_max_radius: int = 2           # impact_radius ≤ this → T1
    auto_pass_max_risk: str = "LOW"         # risk_level ≤ this → T1 (with radius check)

    # T2/T3 thresholds
    review_threshold: float = 0.70          # T2: gate_score below this → advisory warning
    block_threshold: float = 0.90           # T3: gate_score above this → explicit approval

    # Anti-gaming: cumulative radius per actor per window
    cumulative_radius_cap: int = 10         # T3 if actor's total radius > this in window
    cumulative_window_hours: int = 24

    # Risk level ordering (for comparison)
    _RISK_ORDER: dict[str, int] = field(default_factory=lambda: {
        "LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3
    }, repr=False)

    def risk_to_int(self, risk: Any) -> int:
        """Convert a risk level string to its numeric rank.

        v0.51.0 robustness: fail-safest on malformed input. Any
        ``None``, non-string, or unknown risk value is mapped to CRITICAL (3)
        so that unknown-is-dangerous semantics apply at the gate. Previously
        unknown values were silently downgraded to MEDIUM (1), which is
        unsafe for a governance gate where uncertainty must mean "block".
        """
        if not isinstance(risk, str) or not risk:
            return self._RISK_ORDER["CRITICAL"]
        rank = self._RISK_ORDER.get(risk.upper())
        if rank is None:
            return self._RISK_ORDER["CRITICAL"]
        return rank


# ---------------------------------------------------------------------------
# Gate Result
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    """Result of a governance gate check."""
    tier: str                   # "TS-BLOCK" | "T1" | "T2" | "T3"
    blocked: bool               # True if execution must stop
    requires_approval: bool     # True if explicit approved_by is needed
    gate_score: float           # 0.0–1.0 compound score
    reason: str                 # Human-readable gate decision
    warnings: list[str] = field(default_factory=list)
    bypass_allowed: bool = False  # T2: can proceed with warning logged
    # Context for GOVERNANCE_BYPASS node
    risk_level: str = "LOW"
    impact_radius: int = 0
    file_path: str = ""
    threshold_at_time: float = 0.70

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "blocked": self.blocked,
            "requires_approval": self.requires_approval,
            "gate_score": round(self.gate_score, 4),
            "reason": self.reason,
            "warnings": self.warnings,
            "bypass_allowed": self.bypass_allowed,
            "risk_level": self.risk_level,
            "impact_radius": self.impact_radius,
        }


# ---------------------------------------------------------------------------
# Bypass Node (written to KG on every T2/T3 decision)
# ---------------------------------------------------------------------------

@dataclass
class GovernanceBypassNode:
    """KG node recording a T2/T3 governance decision.

    Written to the knowledge graph via graph.add_node_simple() so that:
    - Future reasoning can reason about governance history
    - Post-hoc outcome feedback enables threshold calibration
    - Audit trail is never lost (atomic KG write)

    Outcome fields (actual_outcome, regret_score) are filled post-hoc
    by graq_learn or incident response.
    """
    bypass_id: str
    gate_tier: str                          # "T2" or "T3"
    timestamp: str                          # ISO 8601 UTC
    risk_level: str
    impact_radius: int
    gate_score: float
    threshold_at_time: float
    file_path: str
    actor: str
    approved_by: str                        # empty string for T2 (no approval required)
    justification: str
    action: str                             # "edit" | "generate"
    # Post-hoc fields (filled later)
    actual_outcome: str = "unknown"         # "safe" | "incident" | "rollback" | "unknown"
    regret_score: float = 0.0              # 0.0–1.0 (1.0 = high regret)

    def to_node_metadata(self) -> dict[str, Any]:
        return {
            "entity_type": "GOVERNANCE_BYPASS",
            "gate_tier": self.gate_tier,
            "timestamp": self.timestamp,
            "risk_level": self.risk_level,
            "impact_radius": self.impact_radius,
            "gate_score": self.gate_score,
            "threshold_at_time": self.threshold_at_time,
            "file_path": self.file_path,
            "actor": self.actor,
            "approved_by": self.approved_by,
            "justification": self.justification,
            "action": self.action,
            "actual_outcome": self.actual_outcome,
            "regret_score": self.regret_score,
        }


# ---------------------------------------------------------------------------
# Audit Log (append-only JSONL — Layer 4)
# ---------------------------------------------------------------------------

class GovernanceAuditLog:
    """Append-only JSONL audit log for all governance gate decisions.

    Compliance: SOC2 CC7.2 (audit trail), ISO27001 A.12.4.1 (event logging),
    ISO27001 A.12.4.2 (protection of log information — append-only, no rewrites).

    One JSONL entry is written per gate check — T1, T2, T3, and TS-BLOCK all logged.
    The file is opened in append mode on every write to allow safe external rotation.

    Path resolution:
      1. Explicit ``path`` argument to constructor
      2. ``GRAQLE_AUDIT_LOG_PATH`` environment variable
      3. Default: ``governance_audit.log`` (relative to CWD at construction time)

    Thread safety: a per-instance Lock protects append calls.
    I/O failure: silently no-ops with a stderr warning — never raises.
    """

    _DEFAULT_PATH = "governance_audit.log"
    _ENV_VAR = "GRAQLE_AUDIT_LOG_PATH"

    def __init__(self, path: Optional[str | Path] = None) -> None:
        if path is not None:
            self._path = Path(path).resolve()
        else:
            env_path = os.environ.get(self._ENV_VAR, "").strip()
            self._path = Path(env_path).resolve() if env_path else Path(self._DEFAULT_PATH).resolve()
        self._lock = threading.Lock()
        # v0.51.0 robustness: ensure the parent directory of the audit
        # log exists at construction time. Previously the first append() call
        # would raise FileNotFoundError if the configured parent directory did
        # not yet exist, and the broad except Exception swallowed it, silently
        # losing audit history. Creating the parent eagerly also surfaces a
        # permissions error at construction time rather than on first write.
        self._init_error: Optional[str] = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            self._init_error = (
                f"could not create audit log parent directory "
                f"{self._path.parent}: {exc}"
            )
            print(
                f"[graqle.governance] {self._init_error}",
                file=sys.stderr,
            )

    def append(
        self,
        gate_result: "GateResult",
        *,
        actor: str = "",
        approved_by: str = "",
        file_path: str = "",
    ) -> None:
        """Append one JSONL entry. Opens in append mode — never truncates. Never raises."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tier": gate_result.tier,
            "blocked": gate_result.blocked,
            "actor": actor,
            "approved_by": approved_by,
            "file_path": file_path or gate_result.file_path,
            "gate_score": round(gate_result.gate_score, 4),
            "reason": gate_result.reason,
        }
        line = json.dumps(entry, separators=(",", ":")) + "\n"
        with self._lock:
            try:
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(line)
            except Exception as exc:
                print(
                    f"[graqle.governance] audit log write failed: {exc}",
                    file=sys.stderr,
                )


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class GovernanceMiddleware:
    """3-tier governance gate for graq_edit and graq_generate.

    Instantiate once per server, call check() before every write operation.

    The cumulative_radius_cap is enforced across calls within the rolling
    cumulative_window_hours window. Each actor's impact_radius contributions
    are tracked in-memory. Exceeding the cap forces T3 (explicit approval required)
    regardless of the individual change's risk_level — preventing actors from
    splitting large changes into smaller ones to avoid T3 approval.
    """

    # Class-level lock: shared across all instances in the same process.
    # This ensures thread-safe atomic check-and-record for cumulative radius.
    _cumulative_lock: threading.Lock = threading.Lock()
    # Class-level state: persisted to disk on every write.
    # key: actor, value: list of [iso-timestamp, radius] pairs
    _cumulative: dict[str, list[list]] = defaultdict(list)
    _state_loaded: bool = False

    _STATE_FILE = Path(".graqle") / "gov_cumulative.json"

    def __init__(
        self,
        config: Optional[GovernanceConfig] = None,
        *,
        audit_log: Optional[GovernanceAuditLog] = None,
        learn_callback: Optional[Callable[[dict[str, Any]], None]] = None,
        policy: Optional[Any] = None,  # GovernancePolicyConfig | None
    ) -> None:
        self.config = config or GovernanceConfig()
        self._audit_log = audit_log if audit_log is not None else GovernanceAuditLog()
        self._learn_callback = learn_callback
        # Lazy policy load — governance_policy.py is a sibling module (pure stdlib)
        if policy is not None:
            self._policy = policy
        else:
            try:
                from graqle.core.governance_policy import GovernancePolicyConfig
                self._policy: Any = GovernancePolicyConfig.load()
            except Exception:
                self._policy = None
        self._ensure_state_loaded()

    @classmethod
    def _ensure_state_loaded(cls) -> None:
        """Load persisted cumulative state from disk on first call (once per process).

        v0.51.0 robustness: validate every actor entry as a
        [iso-timestamp:str, radius:int] pair. Corrupt, partial, or legacy
        shapes are skipped with a logged warning instead of letting a bad
        row crash datetime.fromisoformat / sum() later on.
        """
        with cls._cumulative_lock:
            if cls._state_loaded:
                return
            try:
                if cls._STATE_FILE.exists():
                    raw = json.loads(cls._STATE_FILE.read_text(encoding="utf-8"))
                    if not isinstance(raw, dict):
                        _logger.warning(
                            "Persisted cumulative state at %s is not a JSON object; ignoring",
                            cls._STATE_FILE,
                        )
                        raw = {}
                    for actor, entries in raw.items():
                        if not isinstance(entries, list):
                            continue
                        validated: list[list] = []
                        for entry in entries:
                            if (
                                isinstance(entry, (list, tuple))
                                and len(entry) == 2
                                and isinstance(entry[0], str)
                                and isinstance(entry[1], (int, float))
                            ):
                                validated.append([entry[0], int(entry[1])])
                        if validated:
                            cls._cumulative[actor] = validated
            except Exception:
                pass  # Corrupt state file — start fresh, never block on I/O error
            cls._state_loaded = True

    @classmethod
    def _persist_state(cls) -> None:
        """Persist cumulative state to disk. Called inside the lock."""
        try:
            cls._STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = cls._STATE_FILE.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({k: v for k, v in cls._cumulative.items()}, indent=2),
                encoding="utf-8",
            )
            tmp.replace(cls._STATE_FILE)
        except Exception:
            pass  # I/O failure must never block governance checks

    def _get_cumulative_radius_locked(self, actor: str) -> int:
        """Return total impact_radius for actor in the rolling window.

        MUST be called while holding _cumulative_lock.
        Prunes expired entries in place.
        """
        if not actor:
            return 0
        now = datetime.now(timezone.utc)
        window = timedelta(hours=self.config.cumulative_window_hours)
        GovernanceMiddleware._cumulative[actor] = [
            entry for entry in GovernanceMiddleware._cumulative[actor]
            if (now - datetime.fromisoformat(entry[0])) < window
        ]
        return sum(entry[1] for entry in GovernanceMiddleware._cumulative[actor])

    def _atomic_check_and_record(
        self, actor: str, impact_radius: int
    ) -> tuple[bool, int]:
        """Atomically check cumulative cap and record if not exceeded.

        Returns (anti_gaming_triggered: bool, cumulative_total: int).
        Thread-safe: uses class-level lock to prevent TOCTOU race.
        """
        if not actor:
            return False, impact_radius

        with GovernanceMiddleware._cumulative_lock:
            current = self._get_cumulative_radius_locked(actor)
            total = current + impact_radius
            triggered = total > self.config.cumulative_radius_cap
            if not triggered:
                # Record immediately inside lock — atomic check+write
                GovernanceMiddleware._cumulative[actor].append(
                    [datetime.now(timezone.utc).isoformat(), impact_radius]
                )
                GovernanceMiddleware._persist_state()
            return triggered, total

    def _record_cumulative(self, actor: str, impact_radius: int) -> None:
        """Record a gate-passed change (non-gaming path — already checked).

        For T1/T2/T3-approved passes where anti-gaming was NOT triggered
        but we still need to record for future window checks.
        No-op for anonymous actors.
        """
        if not actor:
            return
        with GovernanceMiddleware._cumulative_lock:
            GovernanceMiddleware._cumulative[actor].append(
                [datetime.now(timezone.utc).isoformat(), impact_radius]
            )
            GovernanceMiddleware._persist_state()

    def _emit_audit(
        self,
        result: "GateResult",
        *,
        actor: str,
        approved_by: str,
        file_path: str,
    ) -> None:
        """Write to audit log and fire learn_callback for T3 outcomes."""
        self._audit_log.append(
            result, actor=actor, approved_by=approved_by, file_path=file_path
        )
        # learn_callback: T3 only (approval or rejection)
        if result.tier == "T3" and self._learn_callback is not None:
            try:
                self._learn_callback({
                    "actor": actor,
                    "tier": result.tier,
                    "blocked": result.blocked,
                    "file_path": file_path,
                    "reason": result.reason,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "gate_score": result.gate_score,
                    "approved_by": approved_by,
                })
            except Exception:
                pass  # KG write failure must never break governance checks

    def _apply_dry_run(self, result: "GateResult") -> "GateResult":
        """If dry_run policy is active, convert blocked=True to a warning (except TS-BLOCK).

        TS-BLOCK is ALWAYS blocking even in dry_run mode — it is unconditional.
        dry_run converts T1/T2/T3 blocks to warnings only.
        """
        if (
            self._policy is not None
            and self._policy.dry_run
            and result.blocked
            and result.tier != "TS-BLOCK"
        ):
            result.blocked = False
            result.warnings = list(result.warnings) + [
                f"[DRY_RUN] This change would have been blocked "
                f"(tier={result.tier}). dry_run=true in governance_policy.yaml."
            ]
        return result

    def check(
        self,
        *,
        diff: str = "",
        content: str = "",
        file_path: str = "",
        risk_level: str = "LOW",
        impact_radius: int = 0,
        approved_by: str = "",
        justification: str = "",
        action: str = "edit",
        actor: str = "",
    ) -> GateResult:
        """Run the full 3-tier governance check.

        Args:
            diff: unified diff content (checked for TS + secrets)
            content: full file content if available (also checked)
            file_path: target file path
            risk_level: LOW | MEDIUM | HIGH | CRITICAL
            impact_radius: number of downstream consumers
            approved_by: explicit approver name (required for T3)
            justification: reason for the change (recorded in bypass node)
            action: "edit" or "generate"
            actor: who is requesting the change

        Returns:
            GateResult with tier, blocked, requires_approval, gate_score, reason
        """
        cfg = self.config
        combined = (diff + "\n" + content).strip()

        # ── TS-BLOCK: unconditional, no threshold, no bypass ──────────────
        # TS-BLOCK is NOT subject to dry_run — always hard-blocks.
        if cfg.ts_patterns_file and _pattern_cache is None:
            _load_patterns(path=cfg.ts_patterns_file)
        if cfg.ts_hard_block:
            pattern_blocked, pattern_reason = _check_pattern_leakage(combined, file_path=file_path)
            if pattern_blocked:
                _r = GateResult(
                    tier="TS-BLOCK",
                    blocked=True,
                    requires_approval=False,
                    gate_score=1.0,
                    reason=f"TS-BLOCK: {pattern_reason}. This cannot be overridden.",
                    risk_level=risk_level,
                    impact_radius=impact_radius,
                    file_path=file_path,
                    threshold_at_time=0.0,
                )
                self._emit_audit(_r, actor=actor, approved_by=approved_by, file_path=file_path)
                return _r  # TS-BLOCK: dry_run does NOT apply

        # Secret exposure check (separate from TS — advisory at T2, block at T3)
        secret_found, secret_matches = _check_secret_exposure(combined)
        warnings: list[str] = []
        if secret_found:
            warnings.append(f"Possible secret exposure: {secret_matches[:2]}")

        # ── Compute compound gate score ───────────────────────────────────
        # gate_score = (risk_weight × 0.5) + (radius_weight × 0.5)
        # Higher score = more dangerous
        risk_int = cfg.risk_to_int(risk_level)
        risk_weight = min(risk_int / 3.0, 1.0)          # 0=LOW, 1=CRITICAL

        max_tracked_radius = 26.0  # graph.py impact_radius (empirical codebase max)
        radius_weight = min(impact_radius / max_tracked_radius, 1.0)

        gate_score = (risk_weight * 0.5) + (radius_weight * 0.5)

        # If secret found, elevate score to ensure T3
        if secret_found and secret_matches:
            gate_score = max(gate_score, cfg.block_threshold + 0.01)
            warnings.append("Secret exposure elevates gate tier to T3")

        risk_upper = risk_level.upper()
        auto_pass_risk_int = cfg.risk_to_int(cfg.auto_pass_max_risk)

        # ── Anti-gaming: cumulative radius cap (atomic check — no TOCTOU) ──
        # Prevents splitting a large change into small ones to avoid T3.
        # Example: cumulative_radius_cap=10, window=24h.
        # If actor already has radius=8 in the window, a new radius=4 change
        # forces T3 (8+4=12 > 10) even though individually it would be T1/T2.
        # Uses class-level lock — thread-safe atomic read-check-write.
        anti_gaming_triggered, cumulative_total = self._atomic_check_and_record(
            actor, impact_radius
        ) if actor else (False, impact_radius)
        if anti_gaming_triggered:
            warnings.append(
                f"Anti-gaming: cumulative impact_radius {cumulative_total} "
                f"exceeds cap {cfg.cumulative_radius_cap} in {cfg.cumulative_window_hours}h window. "
                f"T3 required regardless of individual change size."
            )
            # Force T3 tier by elevating impact_radius for gate_score
            impact_radius = cumulative_total  # use cumulative for score calculation
            gate_score = max(gate_score, cfg.block_threshold + 0.01)

        # ── Policy tier override (per-glob min_tier rules — Layer 4) ─────
        # Policy can ELEVATE tier but never downgrade it.
        # TS-BLOCK is preserved unconditionally (already returned above).
        _policy_rule = None
        _policy_approved_by: str = ""
        if self._policy is not None and file_path:
            _policy_rule = self._policy.get_rule_for_file(file_path)
            if _policy_rule:
                # Check if actor is pre-approved by policy whitelist for T3
                if self._policy.is_actor_approved(file_path, actor or approved_by):
                    if not approved_by:
                        _policy_approved_by = f"policy:{_policy_rule.glob}"
                        justification = justification or _policy_rule.justification

        # ── T1: Auto-pass ─────────────────────────────────────────────────
        # Secret exposure ALWAYS overrides T1 — never auto-pass if secrets found
        # Anti-gaming ALWAYS overrides T1 — never auto-pass if cumulative cap exceeded
        # Policy min_tier=T2/T3 overrides T1 auto-pass
        _policy_min_tier = _policy_rule.min_tier if _policy_rule else "T1"
        _t1_policy_ok = _policy_min_tier == "T1"
        if (
            not secret_found
            and not anti_gaming_triggered
            and cfg.risk_to_int(risk_upper) <= auto_pass_risk_int
            and impact_radius <= cfg.auto_pass_max_radius
            and _t1_policy_ok
        ):
            _r = GateResult(
                tier="T1",
                blocked=False,
                requires_approval=False,
                gate_score=gate_score,
                reason="T1: Auto-pass (low risk, low impact radius). Logged.",
                warnings=warnings,
                bypass_allowed=True,
                risk_level=risk_level,
                impact_radius=impact_radius,
                file_path=file_path,
                threshold_at_time=cfg.review_threshold,
            )
            self._emit_audit(_r, actor=actor, approved_by=approved_by, file_path=file_path)
            return self._apply_dry_run(_r)

        # ── T3: Explicit approval required ───────────────────────────────
        is_t3 = (
            risk_upper in ("HIGH", "CRITICAL")
            or impact_radius > 8
            or gate_score >= cfg.block_threshold
        )
        # Policy min_tier elevation: force T3 if policy says so
        if _policy_rule and _policy_rule.min_tier == "T3" and not is_t3:
            is_t3 = True

        # Resolve effective approved_by: explicit > policy whitelist
        _effective_approved_by = approved_by or _policy_approved_by

        if is_t3:
            if not _effective_approved_by:
                _r = GateResult(
                    tier="T3",
                    blocked=True,
                    requires_approval=True,
                    gate_score=gate_score,
                    reason=(
                        f"T3: Explicit approval required. "
                        f"risk_level={risk_level}, impact_radius={impact_radius}, "
                        f"gate_score={gate_score:.2f}. "
                        f"Pass approved_by='your-name' with a justification."
                    ),
                    warnings=warnings,
                    risk_level=risk_level,
                    impact_radius=impact_radius,
                    file_path=file_path,
                    threshold_at_time=cfg.block_threshold,
                )
                self._emit_audit(_r, actor=actor, approved_by=approved_by, file_path=file_path)
                return self._apply_dry_run(_r)

            # T3 with approval — validate RBAC (skip if policy-whitelist approved)
            _skip_rbac = _effective_approved_by.startswith("policy:")
            if not _skip_rbac:
                try:
                    from graqle.core.rbac import check_approval as _rbac_check
                    _rbac_ok, _rbac_reason = _rbac_check(_effective_approved_by, tier="T3")
                    if not _rbac_ok:
                        _r = GateResult(
                            tier="T3",
                            blocked=True,
                            requires_approval=True,
                            gate_score=gate_score,
                            reason=f"T3: RBAC rejected — {_rbac_reason}",
                            warnings=warnings,
                            risk_level=risk_level,
                            impact_radius=impact_radius,
                            file_path=file_path,
                            threshold_at_time=cfg.block_threshold,
                        )
                        self._emit_audit(_r, actor=actor, approved_by=_effective_approved_by, file_path=file_path)
                        return self._apply_dry_run(_r)
                except ImportError:
                    pass  # RBAC module optional — allow approval without role check

            _r = GateResult(
                tier="T3",
                blocked=False,
                requires_approval=True,
                gate_score=gate_score,
                reason=f"T3: Approved by '{_effective_approved_by}'. Bypass will be recorded.",
                warnings=warnings,
                bypass_allowed=True,
                risk_level=risk_level,
                impact_radius=impact_radius,
                file_path=file_path,
                threshold_at_time=cfg.block_threshold,
            )
            self._emit_audit(_r, actor=actor, approved_by=_effective_approved_by, file_path=file_path)
            return self._apply_dry_run(_r)

        # ── T2: Threshold-gated ───────────────────────────────────────────
        if gate_score >= cfg.review_threshold:
            # T2: validate RBAC — CI pipelines (T1-only role) should not bypass T2
            t2_rbac_warnings = list(warnings)
            try:
                from graqle.core.rbac import check_approval as _rbac_check
                if actor:
                    _t2_ok, _t2_reason = _rbac_check(actor, tier="T2")
                    if not _t2_ok:
                        t2_rbac_warnings.append(f"RBAC advisory: {_t2_reason}")
            except ImportError:
                pass
            _r = GateResult(
                tier="T2",
                blocked=False,
                requires_approval=False,
                gate_score=gate_score,
                reason=(
                    f"T2: Gate score {gate_score:.2f} ≥ threshold {cfg.review_threshold:.2f}. "
                    f"Proceeding with bypass recorded. "
                    f"risk_level={risk_level}, impact_radius={impact_radius}."
                ),
                warnings=t2_rbac_warnings,
                bypass_allowed=True,
                risk_level=risk_level,
                impact_radius=impact_radius,
                file_path=file_path,
                threshold_at_time=cfg.review_threshold,
            )
            self._emit_audit(_r, actor=actor, approved_by=approved_by, file_path=file_path)
            return self._apply_dry_run(_r)

        # T2 below threshold — pass with advisory
        # RBAC advisory: CI pipeline actors cannot approve T2
        t2_below_warnings = list(warnings)
        try:
            from graqle.core.rbac import check_approval as _rbac_check
            if actor:
                _t2_ok, _t2_reason = _rbac_check(actor, tier="T2")
                if not _t2_ok:
                    t2_below_warnings.append(f"RBAC advisory: {_t2_reason}")
        except ImportError:
            pass
        _r = GateResult(
            tier="T2",
            blocked=False,
            requires_approval=False,
            gate_score=gate_score,
            reason=f"T2: Gate score {gate_score:.2f} below threshold {cfg.review_threshold:.2f}. Passing.",
            warnings=t2_below_warnings,
            bypass_allowed=True,
            risk_level=risk_level,
            impact_radius=impact_radius,
            file_path=file_path,
            threshold_at_time=cfg.review_threshold,
        )
        self._emit_audit(_r, actor=actor, approved_by=approved_by, file_path=file_path)
        return self._apply_dry_run(_r)

    def build_bypass_node(
        self,
        gate_result: GateResult,
        *,
        approved_by: str = "",
        justification: str = "",
        action: str = "edit",
        actor: str = "",
    ) -> GovernanceBypassNode:
        """Build a GovernanceBypassNode for KG persistence."""
        now = datetime.now(timezone.utc).isoformat()
        bypass_id = f"bypass_{hashlib.sha256(f'{now}{gate_result.file_path}'.encode()).hexdigest()[:12]}"
        return GovernanceBypassNode(
            bypass_id=bypass_id,
            gate_tier=gate_result.tier,
            timestamp=now,
            risk_level=gate_result.risk_level,
            impact_radius=gate_result.impact_radius,
            gate_score=gate_result.gate_score,
            threshold_at_time=gate_result.threshold_at_time,
            file_path=gate_result.file_path,
            actor=actor,
            approved_by=approved_by,
            justification=justification,
            action=action,
        )


# ---------------------------------------------------------------------------
# Layer 4 public surface — re-export for backward compat
# GovernancePolicyConfig, PolicyRule, InlineActor importable from this module.
# ---------------------------------------------------------------------------
try:
    from graqle.core.governance_policy import (  # noqa: E402
        GovernancePolicyConfig,
        InlineActor,
        PolicyRule,
    )
except ImportError:
    pass  # governance_policy.py not yet available — safe to ignore


# ---------------------------------------------------------------------------
# Backward-compat aliases for internal test imports.
# These aliases are NOT part of the public API and may be removed in a future
# release. The public pattern-check entry point is GovernanceMiddleware.check().
# ---------------------------------------------------------------------------
_check_ts_leakage = _check_pattern_leakage  # noqa: E305
_load_ts_patterns = _load_patterns
invalidate_ts_patterns_cache = invalidate_pattern_cache
_TS_BLOCK_PATTERNS_DEFAULT = _BUILTIN_PATTERNS_DEFAULT
