"""Decision Chain Builder — Evidence-backed reasoning trails.

Mapped from TAMR+ evidence_chains.py.
Builds structured chains: Decision → Agent → Evidence → Code.

Every AI decision links back to the specific KG nodes, source files,
and intelligence packets that informed it. This makes every decision
auditable and explainable.

See ADR-105 §Governance Layer: evidence_chains.py → governance/evidence.py.
"""

# ── graqle:intelligence ──
# module: graqle.intelligence.governance.evidence
# risk: MEDIUM (impact radius: 3 modules)
# consumers: middleware, __init__, test_evidence
# dependencies: __future__, json, logging, datetime, pathlib +2 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger("graqle.intelligence.governance.evidence")


class EvidenceItem(BaseModel):
    """A single piece of evidence supporting a decision."""

    type: Literal["module_packet", "impact_analysis", "constraint", "incident", "source_code", "kg_node"]
    source: str                        # module name, file path, or node ID
    content: str                       # what the evidence says
    confidence: float = 1.0            # 0.0 - 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class DecisionRecord(BaseModel):
    """A single decision in the reasoning chain."""

    decision_id: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    action: str                        # "modify", "create", "delete", "approve", "reject"
    target: str                        # module or file being decided about
    reasoning: str                     # why this decision was made
    agent: str = ""                    # which AI tool/agent made this decision
    evidence: list[EvidenceItem] = Field(default_factory=list)
    outcome: Literal["approved", "rejected", "deferred", "pending"] = "pending"
    risk_level: str = "LOW"
    drace_score: float | None = None

    @property
    def evidence_count(self) -> int:
        return len(self.evidence)

    @property
    def is_evidenced(self) -> bool:
        """A decision is evidenced if it has at least 2 supporting items."""
        return len(self.evidence) >= 2

    def add_evidence(self, item: EvidenceItem) -> None:
        """Add evidence to this decision."""
        self.evidence.append(item)


class EvidenceChain(BaseModel):
    """A chain of decisions for one task — the full reasoning trail.

    Chain: Task → Decision₁ → Decision₂ → ... → Outcome
    Each decision links to evidence from the KG.
    """

    chain_id: str
    task: str                          # "Modify graqle.core.graph.add_node"
    started: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    decisions: list[DecisionRecord] = Field(default_factory=list)
    status: Literal["active", "completed", "abandoned"] = "active"
    final_outcome: str = ""
    final_drace_score: float | None = None

    @property
    def decision_count(self) -> int:
        return len(self.decisions)

    @property
    def total_evidence(self) -> int:
        return sum(d.evidence_count for d in self.decisions)

    @property
    def evidence_ratio(self) -> float:
        """Fraction of decisions that are properly evidenced."""
        if not self.decisions:
            return 0.0
        evidenced = sum(1 for d in self.decisions if d.is_evidenced)
        return round(evidenced / len(self.decisions), 3)

    def add_decision(self, decision: DecisionRecord) -> None:
        """Add a decision to the chain."""
        self.decisions.append(decision)

    def complete(self, outcome: str, drace_score: float | None = None) -> None:
        """Complete the chain with a final outcome."""
        self.status = "completed"
        self.final_outcome = outcome
        self.final_drace_score = drace_score


class EvidenceStore:
    """Persists evidence chains to .graqle/governance/evidence/."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.evidence_dir = root / ".graqle" / "governance" / "evidence"

    def _ensure_dir(self) -> None:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    def save_chain(self, chain: EvidenceChain) -> None:
        """Persist an evidence chain to disk."""
        self._ensure_dir()
        fpath = self.evidence_dir / f"{chain.chain_id}.json"
        fpath.write_text(
            json.dumps(chain.model_dump(), indent=2, default=str),
            encoding="utf-8",
        )

    def load_chain(self, chain_id: str) -> EvidenceChain | None:
        """Load an evidence chain from disk."""
        fpath = self.evidence_dir / f"{chain_id}.json"
        if not fpath.exists():
            return None
        data = json.loads(fpath.read_text(encoding="utf-8"))
        return EvidenceChain(**data)

    def list_chains(self, limit: int = 20) -> list[dict[str, Any]]:
        """List recent evidence chains (metadata only)."""
        if not self.evidence_dir.exists():
            return []

        chains = []
        for fpath in sorted(self.evidence_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                chains.append({
                    "chain_id": data.get("chain_id"),
                    "task": data.get("task"),
                    "status": data.get("status"),
                    "started": data.get("started"),
                    "decision_count": len(data.get("decisions", [])),
                    "total_evidence": sum(
                        len(d.get("evidence", []))
                        for d in data.get("decisions", [])
                    ),
                    "final_drace_score": data.get("final_drace_score"),
                })
            except (json.JSONDecodeError, OSError):
                continue
        return chains

    def build_evidence_from_gate(
        self,
        module_query: str,
        gate_result: dict[str, Any],
    ) -> list[EvidenceItem]:
        """Build evidence items from a graq_gate response."""
        items: list[EvidenceItem] = []

        if "error" in gate_result:
            return items

        # Module packet as evidence
        items.append(EvidenceItem(
            type="module_packet",
            source=gate_result.get("module", module_query),
            content=(
                f"Risk: {gate_result.get('risk_level', 'UNKNOWN')}, "
                f"Impact: {gate_result.get('impact_radius', 0)} modules, "
                f"Functions: {gate_result.get('function_count', 0)}"
            ),
            confidence=1.0,
        ))

        # Constraints as evidence
        for constraint in gate_result.get("constraints", []):
            items.append(EvidenceItem(
                type="constraint",
                source=gate_result.get("module", module_query),
                content=constraint,
                confidence=1.0,
            ))

        # Incidents as evidence
        for incident in gate_result.get("incidents", []):
            items.append(EvidenceItem(
                type="incident",
                source=gate_result.get("module", module_query),
                content=incident,
                confidence=0.9,
            ))

        # Consumers as evidence (impact)
        consumers = gate_result.get("consumers", [])
        if consumers:
            consumer_names = [
                c.get("module", c) if isinstance(c, dict) else c
                for c in consumers[:5]
            ]
            items.append(EvidenceItem(
                type="impact_analysis",
                source=gate_result.get("module", module_query),
                content=f"Consumed by {len(consumers)} modules: {', '.join(consumer_names)}",
                confidence=1.0,
            ))

        return items
