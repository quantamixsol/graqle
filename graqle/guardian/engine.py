"""PR Guardian engine — orchestrates governance checks for PR diffs.

Wraps existing GovernanceMiddleware.check() and graq_impact BFS
infrastructure to produce a unified GuardianReport per PR.

Fail-open: any internal error produces a WARN verdict, never a crash.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from graqle.core.governance import (
    GateResult,
    GovernanceConfig,
    GovernanceMiddleware,
)

logger = logging.getLogger("graqle.guardian.engine")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class Verdict(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class BlastRadiusEntry:
    """One module's blast radius summary."""

    module: str
    files_changed: int
    risk_level: str  # T1, T2, T3, TS-BLOCK
    impact_radius: int
    domain: str = ""


@dataclass
class SHACLViolation:
    """A SHACL constraint violation."""

    shape: str
    focus_node: str
    severity: str  # Violation, Warning, Info
    message: str


@dataclass
class GuardianReport:
    """Complete PR Guardian analysis report."""

    verdict: Verdict = Verdict.PASS
    verdict_reasons: list[str] = field(default_factory=list)
    blast_radius: list[BlastRadiusEntry] = field(default_factory=list)
    total_impact_radius: int = 0
    shacl_violations: list[SHACLViolation] = field(default_factory=list)
    gate_results: list[GateResult] = field(default_factory=list)
    required_rbac_level: Optional[str] = None
    approval_satisfied: bool = False
    current_approvals: list[str] = field(default_factory=list)
    ts_block_triggered: bool = False
    breaking_count: int = 0
    timestamp: str = ""
    version: str = "0.1.0"

    def to_dict(self, *, public: bool = True) -> dict[str, Any]:
        """Serialize report to dict.

        Args:
            public: If True (default), redacts internal calibration values
                    (gate_score, tier names, thresholds) to prevent IP leakage.
                    Set False only for internal debugging — never for PR comments,
                    JSON output, or SARIF.
        """
        result: dict[str, Any] = {
            "verdict": self.verdict.value,
            "verdict_reasons": self.verdict_reasons,
            "blast_radius": self.total_impact_radius,
            "breaking_count": self.breaking_count,
            "ts_block_triggered": self.ts_block_triggered,
            "required_rbac_level": self.required_rbac_level,
            "approval_satisfied": self.approval_satisfied,
            "shacl_violation_count": len(self.shacl_violations),
            "timestamp": self.timestamp,
            "version": self.version,
        }
        if not public:
            # Internal only — never expose in PR comments, JSON output, or SARIF
            logger.warning("to_dict(public=False) called — verify not reaching external output")
            result["gate_results"] = [g.to_dict() for g in self.gate_results]
        return result


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class PRGuardianEngine:
    """Orchestrates governance checks for a PR diff.

    Delegates to GovernanceMiddleware (existing gate infrastructure)
    and aggregates per-file results into a unified report.

    Args:
        config: GovernanceConfig (from graqle.yaml governance: section)
        middleware: GovernanceMiddleware instance (reused, not recreated)
        graph: Optional loaded graph for blast radius BFS
    """

    def __init__(
        self,
        config: GovernanceConfig | None = None,
        middleware: GovernanceMiddleware | None = None,
        graph: Any | None = None,
    ) -> None:
        self._config = config or GovernanceConfig()
        self._mw = middleware or GovernanceMiddleware(self._config)
        self._graph = graph

    def evaluate(
        self,
        diff_entries: list[dict[str, str]],
        *,
        actor: str = "ci-bot",
        approved_by: str = "",
    ) -> GuardianReport:
        """Run full governance evaluation on PR diff entries.

        Each diff_entry: {"file_path": str, "diff": str, "content": str}

        Returns a GuardianReport with verdict, blast radius, gate results.
        """
        report = GuardianReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        try:
            self._run_governance_checks(diff_entries, report, actor, approved_by)
            self._compute_blast_radius(diff_entries, report)
            self._determine_approval_requirements(report, approved_by)
            self._compute_verdict(report)
        except Exception:
            logger.error("PR Guardian engine error — failing closed")
            report.verdict = Verdict.FAIL
            report.verdict_reasons.append(
                "Governance engine error — manual review required. Do not merge."
            )

        return report

    # -- private helpers ----------------------------------------------------

    def _run_governance_checks(
        self,
        diff_entries: list[dict[str, str]],
        report: GuardianReport,
        actor: str,
        approved_by: str,
    ) -> None:
        """Run GovernanceMiddleware.check() on each changed file."""
        for entry in diff_entries:
            file_path = entry.get("file_path", "")
            diff = entry.get("diff", "")
            content = entry.get("content", "")

            # Estimate impact radius from graph if available
            impact_radius = self._estimate_impact_radius(file_path)

            # Determine risk level heuristically from file path
            risk_level = self._estimate_risk_level(file_path)

            result = self._mw.check(
                diff=diff,
                content=content,
                file_path=file_path,
                risk_level=risk_level,
                impact_radius=impact_radius,
                approved_by=approved_by,
                actor=actor,
                action="review",
            )

            report.gate_results.append(result)

            if result.tier == "TS-BLOCK":
                report.ts_block_triggered = True

    def _compute_blast_radius(
        self,
        diff_entries: list[dict[str, str]],
        report: GuardianReport,
    ) -> None:
        """Group changed files by top-level module and compute blast radius."""
        module_map: dict[str, list[dict[str, str]]] = {}
        for entry in diff_entries:
            parts = Path(entry.get("file_path", "")).parts
            module = parts[0] if parts else "root"
            module_map.setdefault(module, []).append(entry)

        total = 0
        for module, entries in module_map.items():
            files_changed = len(entries)

            # Find the highest tier from gate results for files in this module
            risk_level = "T1"
            module_radius = 0
            for entry in entries:
                fp = entry.get("file_path", "")
                for gr in report.gate_results:
                    if gr.file_path == fp:
                        if _tier_order(gr.tier) > _tier_order(risk_level):
                            risk_level = gr.tier
                        module_radius = max(module_radius, gr.impact_radius)

            # Use graph-based impact if available, else file count heuristic
            impact = module_radius if module_radius > 0 else files_changed

            report.blast_radius.append(
                BlastRadiusEntry(
                    module=module,
                    files_changed=files_changed,
                    risk_level=risk_level,
                    impact_radius=impact,
                )
            )
            total += impact

        report.total_impact_radius = total

    def _estimate_impact_radius(self, file_path: str) -> int:
        """Estimate impact radius from the knowledge graph if loaded."""
        if not self._graph or not file_path:
            return 0

        # Use graph's get_node + neighbor traversal if available
        try:
            # Normalize path to node ID (strip extension, use module name)
            node_id = Path(file_path).stem
            neighbors = self._graph.get("nodes", {})
            # Count edges from this node
            edges = self._graph.get("links", [])
            count = sum(
                1
                for e in edges
                if e.get("source") == node_id or e.get("target") == node_id
            )
            return count
        except Exception:
            return 0

    def _estimate_risk_level(self, file_path: str) -> str:
        """Heuristic risk level based on file path patterns."""
        fp_lower = file_path.lower()
        if any(
            p in fp_lower
            for p in ("auth", "security", "governance", "rbac", "secret", "crypt")
        ):
            return "HIGH"
        if any(
            p in fp_lower
            for p in ("config", "settings", "deploy", "infra", "migration")
        ):
            return "MEDIUM"
        if "test" in fp_lower:
            return "LOW"
        return "MEDIUM"

    def _determine_approval_requirements(
        self,
        report: GuardianReport,
        approved_by: str,
    ) -> None:
        """Determine highest RBAC level required across all gate results."""
        max_tier = "T1"
        for gr in report.gate_results:
            if _tier_order(gr.tier) > _tier_order(max_tier):
                max_tier = gr.tier

        if max_tier in ("T3", "TS-BLOCK"):
            report.required_rbac_level = max_tier
        elif max_tier == "T2":
            report.required_rbac_level = "T2"

        if approved_by and report.required_rbac_level:
            report.current_approvals.append(approved_by)
            if report.required_rbac_level != "TS-BLOCK":
                report.approval_satisfied = True

    def _compute_verdict(self, report: GuardianReport) -> None:
        """Compute final verdict from all gate results."""
        if report.ts_block_triggered:
            report.verdict = Verdict.FAIL
            report.verdict_reasons.append(
                "TS-BLOCK: Trade secret pattern detected. Unconditional block."
            )
            return

        has_t3_blocked = any(
            gr.tier == "T3" and gr.blocked for gr in report.gate_results
        )
        has_t2_warnings = any(
            gr.tier == "T2" for gr in report.gate_results
        )
        has_secrets = any(
            "secret" in w.lower() for gr in report.gate_results for w in gr.warnings
        )

        report.breaking_count = sum(
            1 for gr in report.gate_results if gr.blocked
        )

        if has_t3_blocked:
            report.verdict = Verdict.FAIL
            report.verdict_reasons.append(
                f"T3: {report.breaking_count} file(s) require explicit approval."
            )
        elif has_secrets:
            report.verdict = Verdict.FAIL
            report.verdict_reasons.append(
                "Secret exposure detected in diff."
            )
        elif has_t2_warnings:
            report.verdict = Verdict.WARN
            report.verdict_reasons.append(
                "T2: Advisory warnings detected. Review recommended."
            )
        elif report.total_impact_radius > self._config.auto_pass_max_radius:
            logger.debug(
                "blast_radius=%d threshold=%d",
                report.total_impact_radius,
                self._config.auto_pass_max_radius,
            )
            report.verdict = Verdict.WARN
            report.verdict_reasons.append(
                "Blast radius exceeds auto-pass threshold. Review recommended."
            )
        else:
            report.verdict = Verdict.PASS
            report.verdict_reasons.append("All checks passed. Low risk, low blast radius.")


def _tier_order(tier: str) -> int:
    """Numeric ordering for governance tiers."""
    return {"T1": 0, "T2": 1, "T3": 2, "TS-BLOCK": 3}.get(tier, -1)
