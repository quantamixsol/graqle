"""Tests for SHACLGate — node output validation."""

# ── graqle:intelligence ──
# module: tests.test_ontology.test_shacl_gate
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, shacl_gate
# constraints: none
# ── /graqle:intelligence ──


from graqle.ontology.shacl_gate import SHACLGate, ValidationResult


class TestSHACLGate:
    def setup_method(self):
        self.gate = SHACLGate({
            "GOV_ENFORCEMENT": {
                "must_reference": ["penalty_amount_or_percentage", "enforcement_authority"],
                "must_include_if_relevant": ["timeline", "enforcement_type"],
                "max_length_words": 150,
                "min_length_words": 15,
                "forbidden_patterns": [
                    "I'm not sure about penalties",
                    "I don't know the penalty",
                ],
            },
            "GOV_REQUIREMENT": {
                "must_reference": ["article_number"],
                "must_include_if_relevant": ["penalty", "timeline"],
                "max_length_words": 150,
                "min_length_words": 15,
                "forbidden_patterns": ["I don't know", "not in my domain"],
            },
        })

    def test_valid_enforcement_output(self):
        output = (
            "Under Article 83 GDPR, the penalty amount is up to 4% of annual global "
            "turnover or EUR 20 million, whichever is higher. The enforcement authority "
            "is the national Data Protection Authority (DPA). Fines are imposed for "
            "violations of data processing principles. Confidence: 90%"
        )
        result = self.gate.validate("GOV_ENFORCEMENT", output)
        assert result.valid is True
        assert len(result.violations) == 0

    def test_invalid_enforcement_evasion(self):
        output = "I'm not sure about penalties for this regulation."
        result = self.gate.validate("GOV_ENFORCEMENT", output)
        assert result.valid is False
        assert any("forbidden" in v.lower() for v in result.violations)

    def test_invalid_enforcement_missing_refs(self):
        output = (
            "This regulation has some enforcement mechanisms that apply "
            "to organizations operating within the EU jurisdiction. "
            "Various measures may be taken against non-compliant entities."
        )
        result = self.gate.validate("GOV_ENFORCEMENT", output)
        assert result.valid is False
        # Missing penalty_amount_or_percentage and enforcement_authority
        assert len(result.violations) >= 1

    def test_too_long_output(self):
        output = " ".join(["word"] * 200)
        result = self.gate.validate("GOV_ENFORCEMENT", output)
        assert result.valid is False
        assert any("too long" in v.lower() for v in result.violations)

    def test_too_short_output(self):
        output = "Yes, penalties apply."
        result = self.gate.validate("GOV_ENFORCEMENT", output)
        assert result.valid is False
        assert any("too short" in v.lower() for v in result.violations)

    def test_no_shape_passes(self):
        result = self.gate.validate("UNKNOWN_TYPE", "Any output is fine.")
        assert result.valid is True

    def test_requirement_must_reference_article(self):
        output = (
            "Organizations must implement comprehensive data protection "
            "measures including privacy impact assessments and record keeping. "
            "Non-compliance may result in penalties."
        )
        result = self.gate.validate("GOV_REQUIREMENT", output)
        assert result.valid is False
        assert any("article_number" in v for v in result.violations)

    def test_requirement_with_article_reference(self):
        output = (
            "Under Article 35 GDPR, organizations must conduct Data Protection "
            "Impact Assessments when processing is likely to result in high risk. "
            "The article number specifies the criteria for assessment necessity. "
            "Confidence: 85%"
        )
        result = self.gate.validate("GOV_REQUIREMENT", output)
        assert result.valid is True

    def test_stats_tracking(self):
        self.gate.reset_stats()
        self.gate.validate("UNKNOWN", "pass through")
        self.gate.validate(
            "GOV_REQUIREMENT",
            "Under Article 5, this requirement mandates transparency. "
            "The article number is clearly referenced. "
            "Confidence: 80%"
        )
        stats = self.gate.stats
        assert stats["passes"] >= 1

    def test_conditional_field_relevance(self):
        output = (
            "Article 83 GDPR establishes the enforcement authority as the national DPA. "
            "The penalty amount is up to 4% of turnover. This is clearly enforced."
        )
        result = self.gate.validate(
            "GOV_ENFORCEMENT", output, query="What are the penalties?"
        )
        # Query mentions penalty, so timeline should be suggested if relevant
        assert result.valid is True

    def test_register_shapes(self):
        self.gate.register_shapes({
            "NEW_TYPE": {
                "must_reference": ["source"],
                "max_length_words": 100,
                "min_length_words": 5,
            }
        })
        result = self.gate.validate("NEW_TYPE", "Too short")
        assert result.valid is False

    def test_feedback_format(self):
        result = ValidationResult()
        result.add_violation("Missing article reference")
        result.add_suggestion("Consider adding timeline")
        feedback = result.to_feedback()
        assert "VIOLATIONS" in feedback
        assert "SUGGESTIONS" in feedback
        assert "Missing article reference" in feedback
