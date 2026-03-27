"""Policy-as-code YAML DSL for Graqle governance gate.

Layer 4 — Per-file-glob tier overrides, dry_run mode, policy versioning,
actor whitelist pre-approvals, and inline RBAC actor registration.

# ── graqle:intelligence ──
# module: graqle.core.governance_policy
# risk: LOW (impact radius: 1 — governance.py only)
# dependencies: fnmatch, json, os, pathlib, sys, dataclasses, typing (stdlib only)
# constraints: MUST remain a pure stdlib leaf module — no graqle.* imports ever
#              MUST NOT import from graqle.core.governance — circular import risk
# ── /graqle:intelligence ──

Compliance mapping:
  SOC2  CC6.2 — Access control: per-glob tier policy enforces minimum approval authority
  SOC2  CC6.1 — Responsibility assignment: inline actors map roles to file regions
  ISO27001 A.12.1.1 — Documented operating procedures: policy-as-code

Policy YAML schema::

    version: "1.0"
    dry_run: false

    rules:
      # Most specific first — first-match-wins semantics
      - glob: "graqle/core/*.py"
        min_tier: "T3"
        approved_actors:
          - "alice"
          - "lead-bot"
        justification: "Core modules — always require T3 review"

      - glob: "tests/**"
        min_tier: "T1"
        approved_actors: []
        justification: "Test files — no production impact"

    actors:
      - actor_id: "alice"
        role: "lead"
        email: "alice@graqle.com"
        display_name: "Alice (Lead Engineer)"
      - actor_id: "ci-bot"
        role: "ci_pipeline"
        email: "ci@graqle.com"

Glob matching:
  - Uses fnmatch.fnmatch for pattern matching
  - First-match-wins: order rules from most specific to least specific
  - Paths normalized to forward slashes before matching (Windows compatible)
  - Absolute paths are relativized against CWD before matching

Tier elevation:
  - Policy can only ELEVATE tier, never downgrade it
  - TS-BLOCK is always preserved regardless of any policy rule
  - dry_run=true: gate checks log but never block (except TS-BLOCK — always hard)
"""
from __future__ import annotations

import fnmatch
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Tier ordering (for comparison and elevation logic)
# ---------------------------------------------------------------------------

_TIER_ORDER: dict[str, int] = {
    "T1": 1,
    "T2": 2,
    "T3": 3,
    "TS-BLOCK": 99,  # Never overridden by policy
}

#: Environment variable for policy file path
_POLICY_PATH_ENV = "GRAQLE_POLICY_PATH"

#: Default policy file name (relative to CWD)
_DEFAULT_POLICY_FILE = "governance_policy.yaml"


# ---------------------------------------------------------------------------
# Policy dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PolicyRule:
    """A single governance policy rule matching a file glob pattern."""
    glob: str                               # fnmatch pattern: "graqle/core/*.py"
    min_tier: str                           # Floor tier: "T1" | "T2" | "T3"
    approved_actors: list[str] = field(default_factory=list)
    justification: str = ""                 # Human rationale — written to audit log

    def __post_init__(self) -> None:
        if self.min_tier not in _TIER_ORDER:
            # Unknown tier — default to T1 (permissive) rather than crashing
            self.min_tier = "T1"


@dataclass
class InlineActor:
    """An actor defined inline in the policy YAML actors: section."""
    actor_id: str
    role: str
    email: str = ""
    display_name: str = ""


# ---------------------------------------------------------------------------
# GovernancePolicyConfig — main loader and rule engine
# ---------------------------------------------------------------------------

class GovernancePolicyConfig:
    """Loads and evaluates governance_policy.yaml rules.

    Never raises on I/O or parse failure — returns a permissive default
    config (no rules, dry_run=False) to ensure policy load errors never
    silently disable governance checks.

    Thread safety: immutable after construction — safe to share across threads.
    """

    def __init__(
        self,
        *,
        version: str = "1.0",
        dry_run: bool = False,
        rules: list[PolicyRule] | None = None,
        actors: list[InlineActor] | None = None,
    ) -> None:
        self.version = version
        self._dry_run = dry_run
        self._rules: list[PolicyRule] = rules or []
        self._actors: list[InlineActor] = actors or []

    @classmethod
    def load(cls, path: str | Path | None = None) -> "GovernancePolicyConfig":
        """Load policy YAML from path, env var, CWD default, or return permissive default.

        Resolution order:
          1. Explicit ``path`` argument (if provided and not None)
          2. ``GRAQLE_POLICY_PATH`` environment variable
          3. ``governance_policy.yaml`` in current working directory
          4. Permissive default (empty rules, dry_run=False) if none found

        Never raises — I/O and parse failures produce a permissive default
        and print a warning to stderr (never blocks gate checks on load failure).
        """
        # Resolve path
        resolved: Path | None = None
        if path is not None:
            resolved = Path(path)
        else:
            env_path = os.environ.get(_POLICY_PATH_ENV, "").strip()
            if env_path:
                resolved = Path(env_path)
            else:
                cwd_path = Path.cwd() / _DEFAULT_POLICY_FILE
                if cwd_path.exists():
                    resolved = cwd_path

        if resolved is None:
            return cls()  # No policy file — permissive default

        try:
            raw = resolved.read_text(encoding="utf-8")
            return cls._parse_yaml(raw)
        except FileNotFoundError:
            return cls()  # Missing file — permissive default
        except Exception as exc:
            print(
                f"[graqle.governance_policy] Failed to load {resolved}: {exc}",
                file=sys.stderr,
            )
            return cls()  # Parse/IO failure — permissive default

    @classmethod
    def _parse_yaml(cls, raw: str) -> "GovernancePolicyConfig":
        """Parse raw YAML string into GovernancePolicyConfig.

        Tries PyYAML (pyyaml>=6.0 is a graqle direct dependency).
        Falls back to permissive default with a stderr warning if unavailable.
        """
        try:
            import yaml  # PyYAML — graqle direct dep, but import inside method
            data = yaml.safe_load(raw)
        except ImportError:
            print(
                "[graqle.governance_policy] PyYAML not available — "
                "governance_policy.yaml will be ignored. "
                "Install pyyaml to enable policy-as-code.",
                file=sys.stderr,
            )
            return cls()
        except Exception as exc:
            print(
                f"[graqle.governance_policy] YAML parse error: {exc}",
                file=sys.stderr,
            )
            return cls()

        if not isinstance(data, dict):
            return cls()

        version = str(data.get("version", "1.0"))
        dry_run = bool(data.get("dry_run", False))

        rules: list[PolicyRule] = []
        for r in data.get("rules", []) or []:
            if not isinstance(r, dict) or "glob" not in r:
                continue
            rules.append(PolicyRule(
                glob=str(r["glob"]),
                min_tier=str(r.get("min_tier", "T1")).upper(),
                approved_actors=[str(a) for a in (r.get("approved_actors") or [])],
                justification=str(r.get("justification", "")),
            ))

        actors: list[InlineActor] = []
        for a in data.get("actors", []) or []:
            if not isinstance(a, dict) or "actor_id" not in a:
                continue
            actors.append(InlineActor(
                actor_id=str(a["actor_id"]),
                role=str(a.get("role", "developer")),
                email=str(a.get("email", "")),
                display_name=str(a.get("display_name", "")),
            ))

        return cls(version=version, dry_run=dry_run, rules=rules, actors=actors)

    # ------------------------------------------------------------------
    # Rule evaluation
    # ------------------------------------------------------------------

    def _normalize(self, path: str) -> str:
        """Normalize path to forward slashes, relativized against CWD if absolute."""
        normalized = path.replace("\\", "/")
        # Try to relativize absolute paths so glob patterns like "graqle/core/*.py" work
        if os.path.isabs(normalized):
            try:
                cwd = str(Path.cwd()).replace("\\", "/")
                if normalized.startswith(cwd):
                    normalized = normalized[len(cwd):].lstrip("/")
            except Exception:
                pass
        return normalized

    def get_rule_for_file(self, file_path: str) -> Optional[PolicyRule]:
        """Return the first matching PolicyRule for file_path, or None.

        Uses fnmatch.fnmatch with first-match-wins semantics.
        Normalizes paths to forward slashes for Windows compatibility.
        """
        if not file_path:
            return None
        normalized = self._normalize(file_path)
        for rule in self._rules:
            rule_glob = rule.glob.replace("\\", "/")
            if fnmatch.fnmatch(normalized, rule_glob):
                return rule
        return None

    def override_tier(self, file_path: str, computed_tier: str) -> str:
        """Return effective tier after applying policy min_tier for file_path.

        Policy only ELEVATES tier, never downgrades.
        TS-BLOCK is always preserved regardless of policy rules.

        Examples:
          computed=T1, rule.min_tier=T3 → returns T3  (elevated)
          computed=T3, rule.min_tier=T1 → returns T3  (no downgrade)
          computed=TS-BLOCK, rule.min_tier=T1 → returns TS-BLOCK  (preserved)
          no matching rule → returns computed_tier unchanged
        """
        if computed_tier == "TS-BLOCK":
            return "TS-BLOCK"  # Never overridden

        rule = self.get_rule_for_file(file_path)
        if rule is None:
            return computed_tier

        computed_order = _TIER_ORDER.get(computed_tier, 1)
        rule_order = _TIER_ORDER.get(rule.min_tier, 1)

        if rule_order > computed_order:
            return rule.min_tier  # Elevate
        return computed_tier  # Never downgrade

    def is_actor_approved(self, file_path: str, actor: str) -> bool:
        """Check if actor is in the approved_actors whitelist for file_path's rule.

        Returns False if:
        - No rule matches the file_path
        - The matching rule has an empty approved_actors list
        - The actor is not in the approved_actors list
        """
        if not actor:
            return False
        rule = self.get_rule_for_file(file_path)
        if rule is None:
            return False
        return actor in rule.approved_actors

    def get_rule_justification(self, file_path: str) -> str:
        """Return justification from matching rule, or empty string."""
        rule = self.get_rule_for_file(file_path)
        return rule.justification if rule else ""

    @property
    def dry_run(self) -> bool:
        """When True: gate checks log but never set blocked=True (except TS-BLOCK)."""
        return self._dry_run

    def inline_actors(self) -> list[InlineActor]:
        """Return actors defined inline in the policy YAML."""
        return list(self._actors)

    @property
    def rules(self) -> list[PolicyRule]:
        """Return the list of policy rules (read-only copy)."""
        return list(self._rules)

    def __repr__(self) -> str:
        return (
            f"GovernancePolicyConfig("
            f"version={self.version!r}, "
            f"dry_run={self._dry_run}, "
            f"rules={len(self._rules)}, "
            f"actors={len(self._actors)})"
        )
