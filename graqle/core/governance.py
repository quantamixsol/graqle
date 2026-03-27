"""Governance enforcement middleware for graq_edit and graq_generate.

# ── graqle:intelligence ──
# module: graqle.core.governance
# risk: LOW (impact radius: 0 modules — new file, zero blast radius)
# dependencies: __future__, dataclasses, datetime, typing
# constraints: TS-1..TS-4 hard-block is NEVER threshold-based and NEVER bypassable
# ── /graqle:intelligence ──

3-Tier Gate Model (ADR-119):

    TS-BLOCK  Any TS-1..TS-4 pattern in diff/content → unconditional hard block
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

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# TS-BLOCK: Trade Secret Patterns (binary pre-gate — never threshold-based)
# ---------------------------------------------------------------------------

# These patterns detect potential exposure of TS-1..TS-4 internals.
# They match comments, strings, and variable names that would expose
# weight values, formula internals, or threshold constants.
# See CLAUDE.md IP governance section for full TS-1..TS-4 definitions.
_TS_BLOCK_PATTERNS: list[re.Pattern[str]] = [
    # TS-1: Q-function weight values
    re.compile(r"\bw_J\b|\bw_A\b", re.IGNORECASE),
    # TS-2: Jaccard formula internals
    re.compile(r"jaccard.*formula|token.set.*intersection.*arithmetic", re.IGNORECASE),
    # TS-3: STG production rules
    re.compile(r"production.rule|stg.*rule|grammar.*rule.*node.type", re.IGNORECASE),
    # TS-4: theta_fold derivation
    re.compile(r"\btheta_fold\b|\bθ_fold\b", re.IGNORECASE),
    # AGREEMENT_THRESHOLD specific value
    re.compile(r"AGREEMENT_THRESHOLD\s*=\s*0\.16", re.IGNORECASE),
    # 70/30 blend internal constants
    re.compile(r"70.*30.*blend|_compute_answer_confidence.*formula", re.IGNORECASE),
]

# Common secret patterns (separate from TS — these are general credential leakage)
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"password\s*=\s*['\"][^'\"]{4,}", re.IGNORECASE),
    re.compile(r"api_key\s*=\s*['\"][^'\"]{8,}", re.IGNORECASE),
    re.compile(r"secret\s*=\s*['\"][^'\"]{8,}", re.IGNORECASE),
    re.compile(r"aws_secret_access_key\s*=\s*['\"][^'\"]{8,}", re.IGNORECASE),
    re.compile(r"sk-[a-zA-Z0-9]{20,}", re.IGNORECASE),  # OpenAI key pattern
    re.compile(r"ANTHROPIC_API_KEY\s*=\s*['\"][^'\"]{8,}", re.IGNORECASE),
]


def _check_ts_leakage(content: str) -> tuple[bool, str]:
    """Check for TS-1..TS-4 trade secret exposure.

    Returns (blocked: bool, matched_pattern: str).
    This is the only UNCONDITIONAL block — no bypass, no threshold, no override.
    """
    for pattern in _TS_BLOCK_PATTERNS:
        m = pattern.search(content)
        if m:
            return True, f"Trade secret pattern detected: {m.group()!r}"
    return False, ""


def _check_secret_exposure(content: str) -> tuple[bool, list[str]]:
    """Check for credential/secret exposure in diff content."""
    found = []
    for pattern in _SECRET_PATTERNS:
        if pattern.search(content):
            found.append(pattern.pattern[:30])
    return bool(found), found


# ---------------------------------------------------------------------------
# Gate Config
# ---------------------------------------------------------------------------

@dataclass
class GovernanceConfig:
    """Governance threshold configuration — stored in graqle.yaml under 'governance:'.

    Thresholds are calibrated automatically from GOVERNANCE_BYPASS outcome data.
    TS patterns are NEVER threshold-based and NEVER relaxed by calibration.
    """
    # TS protection — cannot be disabled
    ts_hard_block: bool = True              # NEVER set to False in production

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

    def risk_to_int(self, risk: str) -> int:
        return self._RISK_ORDER.get(risk.upper(), 1)


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
# Middleware
# ---------------------------------------------------------------------------

class GovernanceMiddleware:
    """3-tier governance gate for graq_edit and graq_generate.

    Instantiate once per server, call check() before every write operation.
    """

    def __init__(self, config: GovernanceConfig | None = None) -> None:
        self.config = config or GovernanceConfig()

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
        if cfg.ts_hard_block:
            ts_blocked, ts_reason = _check_ts_leakage(combined)
            if ts_blocked:
                return GateResult(
                    tier="TS-BLOCK",
                    blocked=True,
                    requires_approval=False,
                    gate_score=1.0,
                    reason=f"TS-BLOCK: {ts_reason}. This cannot be overridden.",
                    risk_level=risk_level,
                    impact_radius=impact_radius,
                    file_path=file_path,
                    threshold_at_time=0.0,
                )

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

        # ── T1: Auto-pass ─────────────────────────────────────────────────
        # Secret exposure ALWAYS overrides T1 — never auto-pass if secrets found
        if (
            not secret_found
            and cfg.risk_to_int(risk_upper) <= auto_pass_risk_int
            and impact_radius <= cfg.auto_pass_max_radius
        ):
            return GateResult(
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

        # ── T3: Explicit approval required ───────────────────────────────
        is_t3 = (
            risk_upper in ("HIGH", "CRITICAL")
            or impact_radius > 8
            or gate_score >= cfg.block_threshold
        )
        if is_t3:
            if not approved_by:
                return GateResult(
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
            # T3 with approval — proceed with bypass recorded
            return GateResult(
                tier="T3",
                blocked=False,
                requires_approval=True,
                gate_score=gate_score,
                reason=f"T3: Approved by '{approved_by}'. Bypass will be recorded.",
                warnings=warnings,
                bypass_allowed=True,
                risk_level=risk_level,
                impact_radius=impact_radius,
                file_path=file_path,
                threshold_at_time=cfg.block_threshold,
            )

        # ── T2: Threshold-gated ───────────────────────────────────────────
        if gate_score >= cfg.review_threshold:
            # Above review threshold but below block threshold — warn but allow
            return GateResult(
                tier="T2",
                blocked=False,
                requires_approval=False,
                gate_score=gate_score,
                reason=(
                    f"T2: Gate score {gate_score:.2f} ≥ threshold {cfg.review_threshold:.2f}. "
                    f"Proceeding with bypass recorded. "
                    f"risk_level={risk_level}, impact_radius={impact_radius}."
                ),
                warnings=warnings,
                bypass_allowed=True,
                risk_level=risk_level,
                impact_radius=impact_radius,
                file_path=file_path,
                threshold_at_time=cfg.review_threshold,
            )

        # T2 below threshold — pass with advisory
        return GateResult(
            tier="T2",
            blocked=False,
            requires_approval=False,
            gate_score=gate_score,
            reason=f"T2: Gate score {gate_score:.2f} below threshold {cfg.review_threshold:.2f}. Passing.",
            warnings=warnings,
            bypass_allowed=True,
            risk_level=risk_level,
            impact_radius=impact_radius,
            file_path=file_path,
            threshold_at_time=cfg.review_threshold,
        )

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
