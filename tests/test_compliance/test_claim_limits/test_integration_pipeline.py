"""End-to-end integration test: taxonomy -> validator -> backfill -> gate.

Per sentinel pass 4 MAJOR-1 finding (CR-010 PR-010c), this file exercises
the full R25-EU11 + CG-MKT-01 pipeline so that a regression in one layer
(taxonomy / validator / backfill / Article 14 gate) trips a clear,
locatable test failure.

Scope boundaries:
    - Concurrency / thread-safety on backfill is OUT of scope. The
      backfill is a one-time, operator-driven migration; multi-worker
      migration is deferred to a future R25-EU11 v1.1 amendment if it
      emerges.
    - Adversarial / timing-attack tests are OUT of scope: the gate is
      operator-side governance; the threat model is regulatory audit,
      not a malicious end-user manipulating gate state.
    - Performance / load tests on the 17-item canonical set are OUT
      of scope: O(n) over a 17-item frozenset is not a load surface.
"""

from __future__ import annotations

import pytest

from graqle.compliance.article_14_gate import check_article_14_human_review
from graqle.compliance.claim_limits.backfill import (
    backfill_graph,
    backfill_node,
)
from graqle.compliance.claim_limits.taxonomy import (
    CANONICAL_CLAIM_LIMITS,
    LEGACY_BACKFILL_VALUE,
    is_valid_claim_limit,
)
from graqle.compliance.claim_limits.validator import (
    ClaimLimitsValidationError,
    require_non_empty_claim_limits,
    validate_for_write,
)


class FakeNode:
    def __init__(self, entity_type: str, properties: dict | None = None, nid: str = "n1"):
        self.entity_type = entity_type
        self.properties = properties if properties is not None else {}
        self.id = nid


class FakeGraph:
    def __init__(self, nodes: list[FakeNode]):
        self._nodes = {n.id: n for n in nodes}

    @property
    def nodes(self):
        return self._nodes


class TestFullPipelineHappyPath:
    """A fresh record flows through taxonomy → validator → audit-write."""

    def test_fresh_record_passes_all_layers(self):
        # Operator constructs a new ResponseSnapshot with two canonical
        # claim limits.
        claim_limits = ["not_legal_advice", "low_confidence_synthesised"]

        # Layer 1: taxonomy.is_valid_claim_limit on each entry
        for cl in claim_limits:
            assert is_valid_claim_limit(cl)

        # Layer 2: validator.require_non_empty_claim_limits (L19 audit gate)
        validated = require_non_empty_claim_limits(claim_limits)
        assert validated == claim_limits
        assert validated is not claim_limits  # copy

        # Layer 3: validate_for_write structured form (envelope build path)
        result = validate_for_write(claim_limits)
        assert result.ok is True
        assert result.taxonomy_version == "1.0"

    def test_fresh_record_with_extension_passes(self):
        claim_limits = ["not_legal_advice", "x-acme-internal-use-only"]
        validated = require_non_empty_claim_limits(claim_limits)
        assert validated == claim_limits


class TestFullPipelineDefaultDenyPath:
    """A record with missing/empty claim_limits is rejected at the gate."""

    def test_empty_claim_limits_rejected(self):
        with pytest.raises(ClaimLimitsValidationError) as exc:
            require_non_empty_claim_limits([])
        assert "claim_limits_empty" in exc.value.reasons

        # And the non-raising form returns a structured envelope
        result = validate_for_write([])
        assert result.ok is False
        assert "claim_limits_empty" in result.reasons

    def test_unknown_value_rejected(self):
        with pytest.raises(ClaimLimitsValidationError) as exc:
            require_non_empty_claim_limits(["totally_made_up_limit"])
        assert "claim_limits_invalid" in exc.value.reasons
        assert "totally_made_up_limit" in exc.value.invalid_values

    def test_sentinel_in_new_write_rejected(self):
        with pytest.raises(ClaimLimitsValidationError) as exc:
            require_non_empty_claim_limits([LEGACY_BACKFILL_VALUE])
        assert "claim_limits_legacy_backfill_in_new_write" in exc.value.reasons


class TestBackfillThenValidate:
    """Backfill writes the sentinel; subsequent reads via validator pass
    only when ``allow_legacy_backfill=True`` is explicitly set."""

    def test_backfill_then_validator_round_trip(self):
        # Operator runs a backfill migration.
        node = FakeNode("ResponseSnapshot", nid="r1")
        graph = FakeGraph([node])
        stats = backfill_graph(graph, dry_run=False)
        assert stats.backfilled == 1
        assert node.properties["claim_limits"] == [LEGACY_BACKFILL_VALUE]

        # Backfilled record passes the validator only with allow_legacy_backfill=True.
        validated = require_non_empty_claim_limits(
            node.properties["claim_limits"],
            allow_legacy_backfill=True,
        )
        assert validated == [LEGACY_BACKFILL_VALUE]

        # Same record would FAIL on a "new write" path (default deny).
        with pytest.raises(ClaimLimitsValidationError):
            require_non_empty_claim_limits(node.properties["claim_limits"])

    def test_idempotent_backfill_then_overwrite_with_real_values(self):
        # First pass: backfill sentinel.
        node = FakeNode("ResponseSnapshot", nid="r1")
        backfill_node(node, dry_run=False)
        assert node.properties["claim_limits"] == [LEGACY_BACKFILL_VALUE]

        # Second pass: backfill is idempotent — sentinel survives.
        status2 = backfill_node(node, dry_run=False)
        # Sentinel is a "compliant" non-empty list, so second pass reports
        # already-compliant (the backfill does NOT loop over its own writes).
        assert status2 == "already_compliant"

        # Operator's downstream pipeline rewrites with concrete values.
        node.properties["claim_limits"] = ["not_legal_advice"]

        # Third backfill pass: still already-compliant (real values present).
        status3 = backfill_node(node, dry_run=False)
        assert status3 == "already_compliant"
        assert node.properties["claim_limits"] == ["not_legal_advice"]


class TestArticle14GateConsumesValidator:
    """The Article 14 gate is the OTHER governance gate; this test
    proves the two coexist correctly under EU AI Act mode."""

    def test_both_gates_armed_under_eu_ai_act_mode(self, monkeypatch):
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")

        # Article 14: low confidence -> refused
        a14 = check_article_14_human_review(
            confidence=0.5,
            human_review_required=False,
        )
        assert a14.allowed is False

        # R25-EU11: empty claim_limits -> refused (independent of EU mode)
        with pytest.raises(ClaimLimitsValidationError):
            require_non_empty_claim_limits([])

    def test_high_confidence_record_with_valid_claim_limits_passes_both(self, monkeypatch):
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")

        a14 = check_article_14_human_review(
            confidence=0.95,
            human_review_required=True,
        )
        assert a14.allowed is True

        validated = require_non_empty_claim_limits(
            ["not_legal_advice", "eu_ai_act_article_14_oversight"]
        )
        assert "eu_ai_act_article_14_oversight" in validated


class TestTaxonomyIntegrity:
    """Cross-layer sanity: every value the validator accepts is in the
    taxonomy, and every category value is recognised by the validator."""

    def test_every_canonical_value_is_validator_recognised(self):
        for v in CANONICAL_CLAIM_LIMITS:
            # Each canonical value passes is_valid_claim_limit
            assert is_valid_claim_limit(v), f"{v!r} not recognised"
            # And the validator accepts a single-value list of it
            assert require_non_empty_claim_limits([v]) == [v]

    def test_validator_rejects_sentinel_but_taxonomy_does_not_list_it(self):
        # The sentinel is NOT in the canonical set
        assert LEGACY_BACKFILL_VALUE not in CANONICAL_CLAIM_LIMITS
        # And is_valid_claim_limit reports it as invalid
        assert is_valid_claim_limit(LEGACY_BACKFILL_VALUE) is False
        # But the validator accepts it under the explicit backfill flag
        assert require_non_empty_claim_limits(
            [LEGACY_BACKFILL_VALUE],
            allow_legacy_backfill=True,
        ) == [LEGACY_BACKFILL_VALUE]
