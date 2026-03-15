"""Tests for graqle.intelligence.governance.drace — DRACE Scoring Engine.

Tests both:
1. Typed pillar evaluators (new TAMR+ pipeline interface)
2. Raw dict interface (backwards-compatible)
"""

# ── graqle:intelligence ──
# module: tests.test_intelligence.test_drace
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: pytest, drace
# constraints: none
# ── /graqle:intelligence ──

import pytest

from graqle.intelligence.governance.drace import (
    AuditabilityInput,
    ConstraintInput,
    DependencyInput,
    DRACEScore,
    DRACEScorer,
    ExplainabilityInput,
    ReasoningInput,
    evaluate_auditability,
    evaluate_constraint,
    evaluate_dependency,
    evaluate_explainability,
    evaluate_reasoning,
)

# ── DRACEScore Model ────────────────────────────────────────────────


class TestDRACEScore:
    def test_default_all_zeros(self):
        score = DRACEScore()
        assert score.total == 0.0
        assert score.grade == "CRITICAL"

    def test_perfect_score(self):
        score = DRACEScore(
            dependency=1.0,
            reasoning=1.0,
            auditability=1.0,
            constraint=1.0,
            explainability=1.0,
        )
        assert score.total == 1.0
        assert score.grade == "EXCELLENT"

    def test_weighted_total(self):
        """Verify weights: D=0.25, R=0.25, A=0.20, C=0.15, E=0.15."""
        score = DRACEScore(dependency=1.0)
        assert score.total == 0.25

    def test_grade_thresholds(self):
        assert DRACEScore(dependency=1.0, reasoning=1.0, auditability=1.0, constraint=1.0, explainability=1.0).grade == "EXCELLENT"
        assert DRACEScore(dependency=0.8, reasoning=0.8, auditability=0.7, constraint=0.7, explainability=0.7).grade == "GOOD"
        assert DRACEScore(dependency=0.5, reasoning=0.5, auditability=0.5, constraint=0.5, explainability=0.5).grade == "ADEQUATE"
        assert DRACEScore(dependency=0.3, reasoning=0.3, auditability=0.2, constraint=0.2, explainability=0.2).grade == "POOR"
        assert DRACEScore(dependency=0.1, reasoning=0.1, auditability=0.1, constraint=0.1, explainability=0.1).grade == "CRITICAL"

    def test_to_dict(self):
        score = DRACEScore(
            dependency=0.8, reasoning=0.7, auditability=0.6,
            constraint=0.5, explainability=0.4,
            session_id="s1", module="core.graph",
        )
        d = score.to_dict()
        assert d["D_dependency"] == 0.8
        assert d["R_reasoning"] == 0.7
        assert d["A_auditability"] == 0.6
        assert d["C_constraint"] == 0.5
        assert d["E_explainability"] == 0.4
        assert d["session_id"] == "s1"
        assert d["module"] == "core.graph"
        assert "total" in d
        assert "grade" in d

    def test_metadata_stored(self):
        score = DRACEScore(details={"context": "test run"})
        assert score.details["context"] == "test run"


# ── Typed Pillar Evaluators (TAMR+ Pipeline) ────────────────────────


class TestEvaluateDependency:
    def test_no_consumers_with_matrix(self):
        inp = DependencyInput(total_consumers=0, impact_matrix_consulted=True)
        assert evaluate_dependency(inp) == 1.0

    def test_no_consumers_without_matrix(self):
        inp = DependencyInput(total_consumers=0, impact_matrix_consulted=False)
        assert evaluate_dependency(inp) == 0.5

    def test_full_coverage(self):
        inp = DependencyInput(
            total_consumers=5, consumers_analyzed=5,
            impact_matrix_consulted=True, cross_module_edges_checked=5,
        )
        score = evaluate_dependency(inp)
        assert score >= 0.8

    def test_partial_coverage(self):
        inp = DependencyInput(
            total_consumers=10, consumers_analyzed=3,
            impact_matrix_consulted=True,
        )
        score = evaluate_dependency(inp)
        assert 0.0 < score < 1.0

    def test_zero_coverage(self):
        inp = DependencyInput(total_consumers=5, consumers_analyzed=0)
        score = evaluate_dependency(inp)
        assert score <= 0.2


class TestEvaluateReasoning:
    def test_empty(self):
        assert evaluate_reasoning(ReasoningInput()) == 0.0

    def test_deep_evidenced_chain(self):
        inp = ReasoningInput(
            evidence_chain_length=5,
            total_evidence_items=15,
            evidenced_decisions=4,
            total_decisions=5,
            kg_nodes_consulted=12,
            evidence_types_used=4,
        )
        score = evaluate_reasoning(inp)
        assert score >= 0.8

    def test_shallow_chain(self):
        inp = ReasoningInput(
            evidence_chain_length=1,
            total_evidence_items=0,
            evidenced_decisions=0,
            total_decisions=1,
            kg_nodes_consulted=0,
            evidence_types_used=0,
        )
        score = evaluate_reasoning(inp)
        assert score < 0.3

    def test_diversity_matters(self):
        """Using multiple evidence types should score higher."""
        low_div = ReasoningInput(
            evidence_chain_length=3, evidenced_decisions=2,
            total_decisions=3, kg_nodes_consulted=5, evidence_types_used=1,
        )
        high_div = ReasoningInput(
            evidence_chain_length=3, evidenced_decisions=2,
            total_decisions=3, kg_nodes_consulted=5, evidence_types_used=4,
        )
        assert evaluate_reasoning(high_div) > evaluate_reasoning(low_div)


class TestEvaluateAuditability:
    def test_empty(self):
        assert evaluate_auditability(AuditabilityInput()) == 0.0

    def test_full_integrity(self):
        inp = AuditabilityInput(
            session_entries=5, complete_entries=5,
            hash_chain_valid=True, session_persisted=True,
        )
        assert evaluate_auditability(inp) == 1.0

    def test_broken_hash_chain(self):
        """Invalid hash chain severely penalizes auditability — hard requirement."""
        inp = AuditabilityInput(
            session_entries=5, complete_entries=5,
            hash_chain_valid=False, session_persisted=True,
        )
        score = evaluate_auditability(inp)
        assert score <= 0.65  # Missing 35% from integrity

    def test_not_persisted(self):
        inp = AuditabilityInput(
            session_entries=5, complete_entries=5,
            hash_chain_valid=True, session_persisted=False,
        )
        score = evaluate_auditability(inp)
        assert score <= 0.75  # Missing 25% from persistence

    def test_incomplete_entries(self):
        inp = AuditabilityInput(
            session_entries=4, complete_entries=1,
            hash_chain_valid=True, session_persisted=True,
        )
        score = evaluate_auditability(inp)
        assert score < 1.0


class TestEvaluateConstraint:
    def test_no_constraints(self):
        assert evaluate_constraint(ConstraintInput()) == 1.0

    def test_all_checked(self):
        inp = ConstraintInput(total_constraints=3, constraints_checked=3)
        assert evaluate_constraint(inp) == 1.0

    def test_blocking_violations_cap_score(self):
        """BLOCK violations cap score at 0.3 — mirrors TAMR+ compliance failures."""
        inp = ConstraintInput(
            total_constraints=3, constraints_checked=3,
            blocking_violations=1,
        )
        score = evaluate_constraint(inp)
        assert score <= 0.3

    def test_multiple_blocking_violations(self):
        inp = ConstraintInput(blocking_violations=3)
        score = evaluate_constraint(inp)
        assert score <= 0.1

    def test_scope_violations_penalize(self):
        inp = ConstraintInput(
            total_constraints=3, constraints_checked=3,
            scope_violations=2,
        )
        score = evaluate_constraint(inp)
        assert score < 1.0

    def test_partial_constraint_coverage(self):
        inp = ConstraintInput(total_constraints=4, constraints_checked=2)
        assert evaluate_constraint(inp) == 0.5


class TestEvaluateExplainability:
    def test_empty(self):
        assert evaluate_explainability(ExplainabilityInput()) == 0.0

    def test_well_explained(self):
        inp = ExplainabilityInput(
            decisions_with_reasoning=5, total_decisions=5,
            avg_reasoning_length=100.0, has_final_outcome=True,
        )
        score = evaluate_explainability(inp)
        assert score >= 0.9

    def test_no_reasoning_text(self):
        inp = ExplainabilityInput(
            decisions_with_reasoning=0, total_decisions=5,
            avg_reasoning_length=0.0,
        )
        assert evaluate_explainability(inp) == 0.0

    def test_short_reasoning(self):
        inp = ExplainabilityInput(
            decisions_with_reasoning=3, total_decisions=3,
            avg_reasoning_length=15.0,
        )
        score = evaluate_explainability(inp)
        assert score < 0.7  # Short reasoning penalized


# ── DRACEScorer — Typed Pipeline Interface ──────────────────────────


class TestDRACEScorerTyped:
    @pytest.fixture()
    def scorer(self):
        return DRACEScorer()

    def test_score_typed_all_defaults(self, scorer: DRACEScorer):
        score = scorer.score_typed()
        # All defaults = mostly zeros except constraint (no constraints = 1.0)
        assert score.constraint == 1.0
        assert score.dependency == 0.5  # no consumers, no matrix
        assert score.total > 0.0

    def test_score_typed_full_pipeline(self, scorer: DRACEScorer):
        score = scorer.score_typed(
            dependency=DependencyInput(
                total_consumers=3, consumers_analyzed=3,
                impact_matrix_consulted=True, cross_module_edges_checked=3,
            ),
            reasoning=ReasoningInput(
                evidence_chain_length=5, total_evidence_items=12,
                evidenced_decisions=4, total_decisions=5,
                kg_nodes_consulted=10, evidence_types_used=4,
            ),
            auditability=AuditabilityInput(
                session_entries=5, complete_entries=5,
                hash_chain_valid=True, session_persisted=True,
            ),
            constraint=ConstraintInput(
                total_constraints=2, constraints_checked=2,
            ),
            explainability=ExplainabilityInput(
                decisions_with_reasoning=5, total_decisions=5,
                avg_reasoning_length=100.0, has_final_outcome=True,
            ),
            session_id="typed-001",
            module="core.graph",
        )
        assert score.total >= 0.8
        assert score.grade in ("EXCELLENT", "GOOD")
        assert score.session_id == "typed-001"
        assert score.module == "core.graph"


# ── DRACEScorer — Backwards-Compatible Raw Dict Interface ───────────


class TestDRACEScorerBackwardsCompat:
    @pytest.fixture()
    def scorer(self):
        return DRACEScorer()

    def test_empty_session(self, scorer: DRACEScorer):
        score = scorer.score_session([])
        assert score.total == 0.0

    def test_full_session(self, scorer: DRACEScorer):
        entries = [
            {
                "action": "gate",
                "timestamp": "2026-01-01T00:00:00",
                "input_summary": "Check auth module safety",
                "output_summary": "Module auth.middleware has 3 consumers. Risk is HIGH due to session handling.",
                "evidence_count": 2,
                "nodes_consulted": 5,
            },
            {
                "action": "reason",
                "timestamp": "2026-01-01T00:01:00",
                "input_summary": "Why is auth high risk?",
                "output_summary": "Auth middleware handles session tokens for all routes. Any change affects login, logout, and API auth flows.",
                "evidence_count": 3,
                "nodes_consulted": 8,
            },
        ]
        score = scorer.score_session(entries)
        assert score.total > 0.0
        assert score.reasoning > 0.0
        assert score.auditability > 0.0
        assert score.explainability > 0.0

    def test_dependency_with_impact_data(self, scorer: DRACEScorer):
        entries = [
            {
                "action": "reason",
                "input_summary": "Check core",
                "output_summary": "The graph module and parser module depend on core.",
            },
        ]
        impact = {"consumers": ["graph", "parser", "cli"]}
        score = scorer.score_session(entries, impact_data=impact)
        assert score.dependency > 0.0

    def test_dependency_no_impact_data(self, scorer: DRACEScorer):
        entries = [{"action": "reason", "output_summary": "test"}]
        score = scorer.score_session(entries, impact_data=None)
        # No impact data = DependencyInput() defaults = no consumers, no matrix = 0.5
        assert score.dependency == 0.5

    def test_dependency_no_consumers(self, scorer: DRACEScorer):
        entries = [{"action": "reason", "output_summary": "test"}]
        score = scorer.score_session(entries, impact_data={"consumers": []})
        assert score.dependency == 1.0  # no consumers + matrix consulted

    def test_constraint_scoring(self, scorer: DRACEScorer):
        entries = [
            {
                "action": "gate",
                "output_summary": "Checked thread safety requirement. Verified no breaking changes.",
            },
        ]
        constraints = ["thread safety", "backwards compatible", "no breaking changes"]
        score = scorer.score_session(entries, constraints=constraints)
        assert score.constraint > 0.0

    def test_constraint_no_constraints(self, scorer: DRACEScorer):
        entries = [{"action": "gate", "output_summary": "ok"}]
        score = scorer.score_session(entries, constraints=None)
        assert score.constraint == 1.0

    def test_auditability_complete_entries(self, scorer: DRACEScorer):
        entries = [
            {
                "action": "gate",
                "timestamp": "2026-01-01T00:00:00",
                "input_summary": "Check module X",
                "output_summary": "Module X is safe to modify",
            },
        ]
        score = scorer.score_session(entries)
        assert score.auditability == 1.0

    def test_auditability_incomplete_entries(self, scorer: DRACEScorer):
        entries = [{"action": "gate"}]
        score = scorer.score_session(entries)
        # incomplete entry + hash_chain_valid=True + persisted=True
        # completeness=0, integrity=1.0, persistence=1.0 → 0.0*0.4 + 1.0*0.35 + 1.0*0.25 = 0.6
        assert score.auditability == 0.6

    def test_explainability_long_outputs(self, scorer: DRACEScorer):
        entries = [
            {"output_summary": "This is a detailed explanation of the reasoning process and the outcome."},
            {"output_summary": "Another detailed explanation covering all edge cases and trade-offs considered."},
        ]
        score = scorer.score_session(entries)
        assert score.explainability > 0.5

    def test_explainability_short_outputs(self, scorer: DRACEScorer):
        entries = [
            {"output_summary": "ok"},
            {"output_summary": "yes"},
        ]
        score = scorer.score_session(entries)
        assert score.explainability < 0.3

    def test_reasoning_depth(self, scorer: DRACEScorer):
        """More entries and evidence = higher reasoning score."""
        shallow = [{"action": "gate", "evidence_count": 0, "nodes_consulted": 0}]
        deep = [
            {"action": "gate", "evidence_count": 2, "nodes_consulted": 3},
            {"action": "reason", "evidence_count": 3, "nodes_consulted": 4},
            {"action": "impact", "evidence_count": 1, "nodes_consulted": 5},
            {"action": "verify", "evidence_count": 2, "nodes_consulted": 3},
            {"action": "learn", "evidence_count": 1, "nodes_consulted": 2},
        ]
        shallow_score = scorer.score_session(shallow)
        deep_score = scorer.score_session(deep)
        assert deep_score.reasoning > shallow_score.reasoning
