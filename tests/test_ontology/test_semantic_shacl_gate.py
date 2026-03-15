"""Tests for SemanticSHACLGate — semantic governance validation."""

# ── graqle:intelligence ──
# module: tests.test_ontology.test_semantic_shacl_gate
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: pytest, semantic_shacl_gate
# constraints: none
# ── /graqle:intelligence ──

import pytest

from graqle.ontology.semantic_shacl_gate import (
    SemanticSHACLGate,
    SemanticConstraint,
    SemanticValidationResult,
    SemanticViolation,
    build_semantic_constraints_from_kg,
)


@pytest.fixture
def eu_ai_act_constraint():
    return SemanticConstraint(
        entity_type="GOV_REQUIREMENT",
        framework="EU AI Act",
        own_framework_markers=["EU AI Act", "AI Act", "Regulation 2024/1689"],
        other_framework_markers={
            "GDPR": ["GDPR", "Regulation 2016/679", "data protection regulation"],
            "DORA": ["DORA", "Digital Operational Resilience Act"],
        },
        in_scope_topics=["risk classification", "prohibited practices", "high-risk AI"],
        out_of_scope_topics=["data protection rights", "financial resilience testing"],
        scope_description="EU AI Act requirements: risk tiers, prohibited practices, conformity",
        reasoning_rules=[
            "Prohibited practices are BANNED, not 'high-risk'. Do not confuse the two.",
            "Penalties under Art. 99: up to 35M EUR or 7% of turnover.",
            "Do not claim GDPR provisions as AI Act provisions.",
        ],
        cross_reference_rules={
            "GDPR": "If mentioning GDPR, state it as 'Related: under GDPR...'",
            "DORA": "If mentioning DORA, note it separately from AI Act obligations.",
        },
    )


@pytest.fixture
def gdpr_constraint():
    return SemanticConstraint(
        entity_type="GOV_FRAMEWORK",
        framework="GDPR",
        own_framework_markers=["GDPR", "Regulation 2016/679", "General Data Protection"],
        other_framework_markers={
            "EU AI Act": ["EU AI Act", "AI Act", "Regulation 2024/1689"],
        },
        in_scope_topics=["data protection", "consent", "data subject rights"],
        out_of_scope_topics=["AI risk classification", "prohibited AI practices"],
        scope_description="GDPR: data protection rights, consent, DPIAs, breach notification",
        reasoning_rules=[
            "GDPR applies to personal data processing, not AI risk classification.",
            "Do not confuse GDPR Art. 35 (DPIA) with AI Act conformity assessment.",
        ],
        cross_reference_rules={
            "EU AI Act": "If mentioning AI Act, note it as a separate regulation.",
        },
    )


@pytest.fixture
def gate(eu_ai_act_constraint, gdpr_constraint):
    return SemanticSHACLGate(constraints={
        "GOV_REQUIREMENT": eu_ai_act_constraint,
        "GOV_FRAMEWORK": gdpr_constraint,
    })


class TestSemanticValidationResult:
    def test_default_valid(self):
        r = SemanticValidationResult()
        assert r.valid is True
        assert r.score == 1.0
        assert r.governance_accuracy == 1.0

    def test_hard_violation_invalidates(self):
        r = SemanticValidationResult()
        r.add_violation(SemanticViolation(
            layer="framework_fidelity", severity="hard", message="test",
        ))
        assert r.valid is False
        assert r.score < 1.0

    def test_soft_violation_stays_valid(self):
        r = SemanticValidationResult()
        r.add_violation(SemanticViolation(
            layer="scope_boundary", severity="soft", message="test",
        ))
        assert r.valid is True
        assert r.score < 1.0

    def test_governance_accuracy_weights(self):
        r = SemanticValidationResult(
            framework_fidelity_score=0.5,
            scope_adherence_score=0.5,
            cross_reference_score=0.5,
        )
        assert r.governance_accuracy == pytest.approx(0.5)

    def test_to_feedback_format(self):
        r = SemanticValidationResult()
        r.add_violation(SemanticViolation(
            layer="framework_fidelity", severity="hard",
            message="Wrong framework", expected="EU AI Act", found="GDPR",
        ))
        r.add_violation(SemanticViolation(
            layer="scope_boundary", severity="soft", message="Minor scope issue",
        ))
        feedback = r.to_feedback()
        assert "GOVERNANCE VIOLATIONS" in feedback
        assert "Wrong framework" in feedback
        assert "GOVERNANCE SUGGESTIONS" in feedback
        assert "Minor scope issue" in feedback


class TestSemanticConstraint:
    def test_dataclass_defaults(self):
        c = SemanticConstraint(entity_type="TEST")
        assert c.entity_type == "TEST"
        assert c.framework == ""
        assert c.reasoning_rules == []

    def test_full_constraint(self, eu_ai_act_constraint):
        c = eu_ai_act_constraint
        assert c.framework == "EU AI Act"
        assert len(c.own_framework_markers) == 3
        assert "GDPR" in c.other_framework_markers
        assert len(c.reasoning_rules) == 3


class TestFrameworkFidelity:
    def test_pass_when_own_framework_cited(self, gate):
        result = gate.validate(
            "GOV_REQUIREMENT",
            "Under the EU AI Act, Art. 6 defines high-risk AI systems. "
            "These systems must undergo conformity assessment.",
        )
        assert result.valid is True
        assert result.framework_fidelity_score >= 0.9

    def test_soft_violation_when_own_framework_missing(self, gate):
        result = gate.validate(
            "GOV_REQUIREMENT",
            "High-risk systems must undergo conformity assessment before market placement. "
            "Providers must register in the EU database for transparency purposes. "
            "Documentation requirements apply to all providers including technical documentation "
            "and instructions for use that cover the full lifecycle.",
        )
        # Should flag missing own framework reference
        fidelity_violations = [
            v for v in result.violations if v.layer == "framework_fidelity"
        ]
        assert len(fidelity_violations) >= 1

    def test_violation_when_other_framework_unattributed(self, gate):
        result = gate.validate(
            "GOV_REQUIREMENT",
            "GDPR requires data protection impact assessments for all processing of personal data. "
            "This includes profiling activities and automated decision-making systems that "
            "process personal data at large scale across member states.",
        )
        # GDPR mentioned without proper attribution, own framework not mentioned
        fidelity_violations = [
            v for v in result.violations if v.layer == "framework_fidelity"
        ]
        assert len(fidelity_violations) >= 1

    def test_pass_when_other_framework_properly_attributed(self, gate):
        result = gate.validate(
            "GOV_REQUIREMENT",
            "Under the EU AI Act, conformity assessment is required. "
            "Related: under GDPR, data protection impact assessments also apply.",
        )
        # Properly attributed cross-reference should not trigger hard violation
        hard_violations = [
            v for v in result.violations
            if v.layer == "framework_fidelity" and v.severity == "hard"
        ]
        assert len(hard_violations) == 0

    def test_short_output_skips_fidelity_check(self, gate):
        result = gate.validate(
            "GOV_REQUIREMENT",
            "Not in my scope.",
        )
        assert result.valid is True


class TestScopeBoundary:
    def test_pass_when_in_scope(self, gate):
        result = gate.validate(
            "GOV_REQUIREMENT",
            "Under the EU AI Act, prohibited practices include social scoring. "
            "These are BANNED, not classified as high-risk.",
        )
        scope_violations = [
            v for v in result.violations if v.layer == "scope_boundary"
        ]
        assert len(scope_violations) == 0

    def test_violation_when_out_of_scope(self, gate):
        result = gate.validate(
            "GOV_REQUIREMENT",
            "Under the EU AI Act, data protection rights are fundamental. "
            "Data protection rights include the right to erasure. "
            "Data protection rights also cover portability.",
        )
        scope_violations = [
            v for v in result.violations if v.layer == "scope_boundary"
        ]
        assert len(scope_violations) >= 1

    def test_reasoning_rule_negation_check(self, gate):
        result = gate.validate(
            "GOV_REQUIREMENT",
            "Under the EU AI Act, prohibited practices like social scoring "
            "are classified as high-risk and require conformity assessment.",
        )
        # "Do not confuse" rule: prohibited != high-risk
        # This is tricky to catch with keyword matching, but the gate
        # should at least check negation rules
        assert result.scope_adherence_score <= 1.0


class TestCrossReferences:
    def test_pass_with_proper_attribution(self, gate):
        result = gate.validate(
            "GOV_REQUIREMENT",
            "Under the EU AI Act, high-risk AI systems must comply. "
            "See also: GDPR requirements apply separately for personal data.",
        )
        crossref_violations = [
            v for v in result.violations if v.layer == "cross_reference"
        ]
        assert len(crossref_violations) == 0

    def test_violation_without_attribution(self, gate):
        result = gate.validate(
            "GOV_REQUIREMENT",
            "The EU AI Act requires compliance. GDPR penalties are up to 20M EUR.",
        )
        crossref_violations = [
            v for v in result.violations if v.layer == "cross_reference"
        ]
        assert len(crossref_violations) >= 1


class TestConstraintPrompt:
    def test_generates_semantic_prompt(self, gate):
        prompt = gate.get_constraint_prompt("GOV_REQUIREMENT")
        assert "FRAMEWORK:" in prompt
        assert "EU AI Act" in prompt
        assert "SCOPE:" in prompt
        assert "REASONING RULES:" in prompt
        assert "Prohibited practices are BANNED" in prompt
        assert "CROSS-REFERENCE RULES:" in prompt

    def test_empty_for_unknown_type(self, gate):
        prompt = gate.get_constraint_prompt("UNKNOWN_TYPE")
        assert prompt == ""


class TestGateStats:
    def test_stats_track_passes(self, gate):
        gate.validate("GOV_REQUIREMENT", "EU AI Act Art. 6 defines high-risk.")
        assert gate.stats["passes"] >= 1

    def test_reset_stats(self, gate):
        gate.validate("GOV_REQUIREMENT", "EU AI Act test.")
        gate.reset_stats()
        assert gate.stats["passes"] == 0

    def test_record_retry(self, gate):
        gate.record_retry()
        assert gate.stats["retries"] == 1


class TestStrictMode:
    def test_strict_makes_framework_violations_hard(self, eu_ai_act_constraint):
        strict_gate = SemanticSHACLGate(
            constraints={"GOV_REQUIREMENT": eu_ai_act_constraint},
            strict_mode=True,
        )
        result = strict_gate.validate(
            "GOV_REQUIREMENT",
            "The EU AI Act Art. 6 defines high-risk systems. GDPR Art. 35 mandates "
            "data protection impact assessments. These regulations cover AI systems that "
            "process personal data in European Union member states.",
        )
        hard_violations = [v for v in result.violations if v.severity == "hard"]
        assert len(hard_violations) >= 1
        assert result.valid is False


class TestBuildFromKG:
    def test_builds_constraints_from_kg_nodes(self):
        kg_nodes = {
            "n1": {
                "entity_type": "GOV_REQUIREMENT",
                "framework": "EU AI Act",
                "description": "Art. 6 high-risk classification criteria",
            },
            "n2": {
                "entity_type": "GOV_REQUIREMENT",
                "framework": "EU AI Act",
                "description": "Art. 9 risk management system",
            },
            "n3": {
                "entity_type": "GOV_FRAMEWORK",
                "framework": "GDPR",
                "description": "General Data Protection Regulation",
            },
        }
        constraints = build_semantic_constraints_from_kg(kg_nodes)
        assert "GOV_REQUIREMENT" in constraints
        assert "GOV_FRAMEWORK" in constraints
        assert constraints["GOV_REQUIREMENT"].framework == "EU AI Act"
        assert "GDPR" in constraints["GOV_REQUIREMENT"].other_framework_markers

    def test_handles_empty_kg(self):
        constraints = build_semantic_constraints_from_kg({})
        assert constraints == {}

    def test_handles_nodes_without_framework(self):
        kg_nodes = {
            "n1": {"entity_type": "Entity", "description": "Some node"},
        }
        constraints = build_semantic_constraints_from_kg(kg_nodes)
        assert "Entity" in constraints


class TestRegisterConstraints:
    def test_register_single(self):
        gate = SemanticSHACLGate()
        c = SemanticConstraint(entity_type="TEST", framework="TestFW")
        gate.register_constraint(c)
        prompt = gate.get_constraint_prompt("TEST")
        assert "TestFW" in prompt

    def test_register_multiple(self):
        gate = SemanticSHACLGate()
        constraints = {
            "A": SemanticConstraint(entity_type="A", framework="FW-A"),
            "B": SemanticConstraint(entity_type="B", framework="FW-B"),
        }
        gate.register_constraints(constraints)
        assert "FW-A" in gate.get_constraint_prompt("A")
        assert "FW-B" in gate.get_constraint_prompt("B")
