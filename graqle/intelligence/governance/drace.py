"""DRACE Scoring Engine — Development governance quality scoring.

Mapped from TAMR+ TRACE scoring (T+R+A+C+E) to development domain (D+R+A+C+E).

TRACE (regulatory) → DRACE (development):
- T (Transparency) → D (Dependency): coverage of impact analysis
- R (Reasoning)    → R (Reasoning): evidence chain depth & quality
- A (Auditability) → A (Auditability): audit trail integrity & completeness
- C (Compliance)   → C (Constraint): scope boundary & rule adherence
- E (Explainability) → E (Explainability): decision record clarity

Each pillar evaluator receives TYPED governance objects — not raw text.
This mirrors the TAMR+ pipeline where each TRACE evaluator receives
structured regulatory artifacts (filings, audit logs, compliance records).

Pipeline flow:
  AuditSession + EvidenceChain + ScopeViolations + ImpactData
    → DRACEPillarEvaluator (per pillar)
      → DRACEScore (composite)

See ADR-105 §DRACE Scoring, TAMR+ §TRACE Pipeline Architecture.
"""

# ── graqle:intelligence ──
# module: graqle.intelligence.governance.drace
# risk: MEDIUM (impact radius: 3 modules)
# consumers: middleware, __init__, test_drace
# dependencies: __future__, logging, typing, pydantic
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("graqle.intelligence.governance.drace")


# ── Score Model ─────────────────────────────────────────────────────


class DRACEScore(BaseModel):
    """DRACE score breakdown for a reasoning session."""

    # Individual pillar scores (0.0 - 1.0)
    dependency: float = 0.0     # D: impact coverage
    reasoning: float = 0.0     # R: evidence chain depth
    auditability: float = 0.0  # A: audit log completeness
    constraint: float = 0.0    # C: constraint registry coverage
    explainability: float = 0.0  # E: reasoning clarity

    # Metadata
    session_id: str = ""
    module: str = ""
    details: dict[str, Any] = Field(default_factory=dict)

    @property
    def total(self) -> float:
        """Weighted total DRACE score (0.0 - 1.0).

        Weights mirror TAMR+ TRACE:
        - D + R = 50% (core reasoning quality, like T + R in TRACE)
        - A = 20% (auditability is non-negotiable in both domains)
        - C + E = 30% (compliance/constraint + human readability)
        """
        return round(
            0.25 * self.dependency +
            0.25 * self.reasoning +
            0.20 * self.auditability +
            0.15 * self.constraint +
            0.15 * self.explainability,
            3,
        )

    @property
    def grade(self) -> str:
        """Human-readable grade."""
        t = self.total
        if t >= 0.9:
            return "EXCELLENT"
        if t >= 0.75:
            return "GOOD"
        if t >= 0.5:
            return "ADEQUATE"
        if t >= 0.25:
            return "POOR"
        return "CRITICAL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "D_dependency": self.dependency,
            "R_reasoning": self.reasoning,
            "A_auditability": self.auditability,
            "C_constraint": self.constraint,
            "E_explainability": self.explainability,
            "total": self.total,
            "grade": self.grade,
            "session_id": self.session_id,
            "module": self.module,
        }


# ── Pillar Input Models ─────────────────────────────────────────────
# Each pillar evaluator receives typed data, not raw text.
# This mirrors TAMR+ where each TRACE evaluator gets structured artifacts.


class DependencyInput(BaseModel):
    """Structured input for D-pillar evaluation.

    Maps to TRACE T-pillar (Transparency): did the analysis cover
    all affected entities?
    """

    total_consumers: int = 0
    consumers_analyzed: int = 0
    impact_matrix_consulted: bool = False
    cross_module_edges_checked: int = 0


class ReasoningInput(BaseModel):
    """Structured input for R-pillar evaluation.

    Maps to TRACE R-pillar: was the reasoning chain deep enough,
    with evidence at each step?
    """

    evidence_chain_length: int = 0       # number of decisions in chain
    total_evidence_items: int = 0        # total evidence pieces
    evidenced_decisions: int = 0         # decisions with >= 2 evidence items
    total_decisions: int = 0
    kg_nodes_consulted: int = 0          # graph nodes read during reasoning
    evidence_types_used: int = 0         # diversity of evidence sources


class AuditabilityInput(BaseModel):
    """Structured input for A-pillar evaluation.

    Maps to TRACE A-pillar: is the full trail recorded and tamper-evident?
    """

    session_entries: int = 0
    complete_entries: int = 0            # entries with all required fields
    hash_chain_valid: bool = False       # SHA-256 chain integrity
    session_persisted: bool = False      # saved to .graqle/governance/audit/


class ConstraintInput(BaseModel):
    """Structured input for C-pillar evaluation.

    Maps to TRACE C-pillar (Compliance): were all governance rules checked?
    """

    total_constraints: int = 0
    constraints_checked: int = 0
    scope_violations: int = 0            # from ScopeGate
    blocking_violations: int = 0         # BLOCK-severity violations


class ExplainabilityInput(BaseModel):
    """Structured input for E-pillar evaluation.

    Maps to TRACE E-pillar: can a human follow the reasoning?
    """

    decisions_with_reasoning: int = 0    # decisions that have reasoning text
    total_decisions: int = 0
    avg_reasoning_length: float = 0.0    # average chars in reasoning field
    has_final_outcome: bool = False       # chain completed with summary


# ── Pillar Evaluators ───────────────────────────────────────────────
# Each evaluator is a pure function: TypedInput → float (0.0-1.0).
# This is the TAMR+ pattern: one evaluator per TRACE pillar.


def evaluate_dependency(inp: DependencyInput) -> float:
    """D-pillar: Dependency coverage.

    Full score requires: impact matrix was consulted AND
    a meaningful fraction of consumers were analyzed.
    """
    if inp.total_consumers == 0:
        # No consumers = leaf module, full score if matrix was checked
        return 1.0 if inp.impact_matrix_consulted else 0.5

    coverage = inp.consumers_analyzed / inp.total_consumers
    matrix_bonus = 0.2 if inp.impact_matrix_consulted else 0.0
    edge_bonus = min(0.2, inp.cross_module_edges_checked * 0.04)

    return min(1.0, round(coverage * 0.6 + matrix_bonus + edge_bonus, 3))


def evaluate_reasoning(inp: ReasoningInput) -> float:
    """R-pillar: Reasoning chain depth & evidence quality.

    Mirrors TRACE R-pillar: deeper chains with diverse evidence score higher.
    """
    if inp.total_decisions == 0:
        return 0.0

    # Evidence ratio: what fraction of decisions are properly evidenced?
    evidence_ratio = inp.evidenced_decisions / inp.total_decisions

    # Chain depth: longer chains = deeper analysis (cap at 5)
    depth_score = min(1.0, inp.evidence_chain_length / 5)

    # KG usage: more nodes consulted = broader graph coverage (cap at 10)
    kg_score = min(1.0, inp.kg_nodes_consulted / 10)

    # Evidence diversity: using multiple evidence types is better (cap at 4)
    diversity_score = min(1.0, inp.evidence_types_used / 4)

    return round(
        0.35 * evidence_ratio +
        0.25 * depth_score +
        0.20 * kg_score +
        0.20 * diversity_score,
        3,
    )


def evaluate_auditability(inp: AuditabilityInput) -> float:
    """A-pillar: Audit trail completeness & integrity.

    This is binary-heavy: hash chain MUST be valid, session MUST be persisted.
    Mirrors TAMR+ where audit trail integrity is a hard requirement.
    """
    if inp.session_entries == 0:
        return 0.0

    # Completeness: fraction of entries with all required fields
    completeness = inp.complete_entries / inp.session_entries

    # Integrity: hash chain must be valid (hard requirement)
    integrity = 1.0 if inp.hash_chain_valid else 0.0

    # Persistence: session must be saved to disk
    persistence = 1.0 if inp.session_persisted else 0.0

    return round(
        0.40 * completeness +
        0.35 * integrity +
        0.25 * persistence,
        3,
    )


def evaluate_constraint(inp: ConstraintInput) -> float:
    """C-pillar: Constraint & scope boundary adherence.

    Any BLOCK violation = max 0.3. Mirrors TAMR+ where compliance
    failures cap the score regardless of other factors.
    """
    # Hard cap: blocking violations severely limit score (checked FIRST)
    if inp.blocking_violations > 0:
        return min(0.3, 0.3 / inp.blocking_violations)

    if inp.total_constraints == 0 and inp.scope_violations == 0:
        return 1.0  # No constraints to violate

    # Constraint coverage
    if inp.total_constraints > 0:
        coverage = inp.constraints_checked / inp.total_constraints
    else:
        coverage = 1.0

    # Scope violation penalty
    violation_penalty = min(0.5, inp.scope_violations * 0.15)

    return max(0.0, round(coverage - violation_penalty, 3))


def evaluate_explainability(inp: ExplainabilityInput) -> float:
    """E-pillar: Human-readability of decisions.

    Mirrors TAMR+ E-pillar: every decision should be understandable
    by a non-technical stakeholder.
    """
    if inp.total_decisions == 0:
        return 0.0

    # Reasoning coverage: what fraction of decisions have reasoning?
    reasoning_ratio = inp.decisions_with_reasoning / inp.total_decisions

    # Reasoning quality: average length (20 chars = 1 sentence minimum)
    quality = min(1.0, inp.avg_reasoning_length / 80)  # 80 chars ~ 1 good sentence

    # Outcome: did the chain produce a final summary?
    outcome_bonus = 0.15 if inp.has_final_outcome else 0.0

    return min(1.0, round(
        0.45 * reasoning_ratio +
        0.40 * quality +
        outcome_bonus,
        3,
    ))


# ── Scorer (Pipeline Orchestrator) ──────────────────────────────────


class DRACEScorer:
    """Orchestrates the DRACE scoring pipeline.

    Mirrors TAMR+ TRACE pipeline architecture:
    1. Collect structured inputs from governance artifacts
    2. Run each pillar evaluator independently
    3. Compose weighted total score

    Accepts BOTH typed inputs (new pipeline) AND raw dicts (backwards compat).
    """

    def score_session(
        self,
        session_entries: list[dict[str, Any]],
        module_context: dict[str, Any] | None = None,
        impact_data: dict[str, Any] | None = None,
        constraints: list[str] | None = None,
    ) -> DRACEScore:
        """Score from raw session entries (backwards-compatible interface).

        Extracts structured pillar inputs from raw data, then delegates
        to typed evaluators. This is the migration path — callers start
        with raw dicts, then gradually adopt typed inputs.
        """
        score = DRACEScore()

        if not session_entries:
            return score

        # Extract typed inputs from raw data
        dep_input = self._extract_dependency_input(session_entries, impact_data)
        rea_input = self._extract_reasoning_input(session_entries)
        aud_input = self._extract_auditability_input(session_entries)
        con_input = self._extract_constraint_input(session_entries, constraints)
        exp_input = self._extract_explainability_input(session_entries)

        # Run each pillar evaluator
        score.dependency = evaluate_dependency(dep_input)
        score.reasoning = evaluate_reasoning(rea_input)
        score.auditability = evaluate_auditability(aud_input)
        score.constraint = evaluate_constraint(con_input)
        score.explainability = evaluate_explainability(exp_input)

        return score

    def score_typed(
        self,
        dependency: DependencyInput | None = None,
        reasoning: ReasoningInput | None = None,
        auditability: AuditabilityInput | None = None,
        constraint: ConstraintInput | None = None,
        explainability: ExplainabilityInput | None = None,
        session_id: str = "",
        module: str = "",
    ) -> DRACEScore:
        """Score from typed pillar inputs (full pipeline interface).

        This is the preferred interface — callers build typed inputs
        from governance objects and pass them directly.
        """
        return DRACEScore(
            dependency=evaluate_dependency(dependency or DependencyInput()),
            reasoning=evaluate_reasoning(reasoning or ReasoningInput()),
            auditability=evaluate_auditability(auditability or AuditabilityInput()),
            constraint=evaluate_constraint(constraint or ConstraintInput()),
            explainability=evaluate_explainability(explainability or ExplainabilityInput()),
            session_id=session_id,
            module=module,
        )

    # ── Extractors: raw dicts → typed inputs ────────────────────────
    # These bridge the old interface to the new typed evaluators.

    def _extract_dependency_input(
        self,
        entries: list[dict[str, Any]],
        impact_data: dict[str, Any] | None,
    ) -> DependencyInput:
        if not impact_data:
            return DependencyInput()

        consumers = impact_data.get("consumers", [])
        all_text = " ".join(
            e.get("output_summary", "") + " " + e.get("input_summary", "")
            for e in entries
        )
        mentioned = sum(
            1 for c in consumers
            if c.rsplit(".", 1)[-1].lower() in all_text.lower()
        )

        return DependencyInput(
            total_consumers=len(consumers),
            consumers_analyzed=mentioned,
            impact_matrix_consulted=bool(impact_data),
            cross_module_edges_checked=len(consumers),
        )

    def _extract_reasoning_input(
        self, entries: list[dict[str, Any]]
    ) -> ReasoningInput:
        evidence_entries = sum(1 for e in entries if e.get("evidence_count", 0) > 0)
        total_nodes = sum(e.get("nodes_consulted", 0) for e in entries)
        evidence_types = set()
        for e in entries:
            if e.get("evidence_count", 0) > 0:
                evidence_types.add(e.get("action", "unknown"))

        return ReasoningInput(
            evidence_chain_length=len(entries),
            total_evidence_items=sum(e.get("evidence_count", 0) for e in entries),
            evidenced_decisions=evidence_entries,
            total_decisions=len(entries),
            kg_nodes_consulted=total_nodes,
            evidence_types_used=len(evidence_types),
        )

    def _extract_auditability_input(
        self, entries: list[dict[str, Any]]
    ) -> AuditabilityInput:
        complete = 0
        for e in entries:
            has_input = bool(e.get("input_summary"))
            has_output = bool(e.get("output_summary"))
            has_action = bool(e.get("action"))
            has_timestamp = bool(e.get("timestamp"))
            if has_input and has_output and has_action and has_timestamp:
                complete += 1

        return AuditabilityInput(
            session_entries=len(entries),
            complete_entries=complete,
            hash_chain_valid=True,   # assumed valid for raw entries
            session_persisted=True,  # assumed persisted for raw entries
        )

    def _extract_constraint_input(
        self,
        entries: list[dict[str, Any]],
        constraints: list[str] | None,
    ) -> ConstraintInput:
        if not constraints:
            return ConstraintInput()

        all_text = " ".join(e.get("output_summary", "") for e in entries)
        checked = sum(
            1 for c in constraints
            if any(word.lower() in all_text.lower() for word in c.split()[:3])
        )

        return ConstraintInput(
            total_constraints=len(constraints),
            constraints_checked=checked,
        )

    def _extract_explainability_input(
        self, entries: list[dict[str, Any]]
    ) -> ExplainabilityInput:
        with_reasoning = sum(
            1 for e in entries if len(e.get("output_summary", "")) >= 20
        )
        total_length = sum(len(e.get("output_summary", "")) for e in entries)
        avg_length = total_length / len(entries) if entries else 0.0

        return ExplainabilityInput(
            decisions_with_reasoning=with_reasoning,
            total_decisions=len(entries),
            avg_reasoning_length=avg_length,
            has_final_outcome=len(entries) >= 2,  # multi-step = has conclusion
        )
