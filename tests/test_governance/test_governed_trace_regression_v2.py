"""Regression-pin tests for cr-017 schema v2 — byte-for-byte specification
of the EXISTING pre-cr-017 ``GovernedTrace`` contract.

Layer 3 of the cr-017 test plan. These tests intentionally duplicate
parts of Layer 1's coverage to provide a NAMED, EXPLICIT contract that
any future refactor of ``GovernedTrace`` must keep passing.

Pinned behaviours (must hold AFTER cr-017 ships, exactly as they did
BEFORE cr-017):

  P1: Legacy parse — a dict missing both schema_version and
      policy_version still parses cleanly via Pydantic defaults.
  P2: Pre-cr-017 mandatory fields are unchanged (tool_name, query,
      outcome, confidence, etc. are still required).
  P3: extra="forbid" still rejects unknown fields.
  P4: model_dump() round-trips all pre-cr-017 fields with identical
      values.
  P5: to_public_dict still excludes governance_decisions.
  P6: The validator_override invariant still fires for human_override
      without override_reason.

If any of these fail post-cr-017, a regression has been introduced.
"""

# ── graqle:intelligence ──
# module: tests.test_governance.test_governed_trace_regression_v2
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, pydantic, graqle.governance.trace_schema
# constraints: pin pre-cr-017 GovernedTrace contract byte-for-byte
# ── /graqle:intelligence ──

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from graqle.governance.trace_schema import (
    ClearanceLevel,
    GovernedTrace,
    Outcome,
)


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------


def _minimal_trace(**overrides) -> GovernedTrace:
    defaults = {
        "tool_name": "graq_inspect",
        "query": "test query",
        "outcome": Outcome.SUCCESS,
        "confidence": 0.8,
    }
    defaults.update(overrides)
    return GovernedTrace(**defaults)


# -------------------------------------------------------------------------
# P1 — Legacy parse: pre-cr-017 dicts must still parse
# -------------------------------------------------------------------------


class TestP1LegacyParse:
    """Pre-cr-017 records on disk have neither schema_version nor
    policy_version. Reading them via GovernedTrace.model_validate must
    succeed with defaults applied (v2 + None)."""

    def test_parse_legacy_dict_without_new_fields(self):
        # A JSONL line written by a pre-cr-017 SDK.
        legacy = {
            "tool_name": "graq_inspect",
            "query": "old trace",
            "outcome": "SUCCESS",
            "confidence": 0.9,
        }
        trace = GovernedTrace.model_validate(legacy)
        # cr-017 defaults populate the new fields.
        assert trace.schema_version == "2"
        assert trace.policy_version is None
        # Pre-cr-017 fields preserve original values.
        assert trace.tool_name == "graq_inspect"
        assert trace.confidence == 0.9

    def test_parse_legacy_dict_with_full_pre_cr017_field_set(self):
        # The full pre-cr-017 field set, exactly as it was on master pre-CR.
        legacy = {
            "tool_name": "graq_review",
            "query": "review query",
            "context_nodes": ["graqle/core/graph.py"],
            "tool_calls": [],
            "clearance_level": "CONFIDENTIAL",
            "outcome": "SUCCESS",
            "confidence": 0.75,
            "cost_usd": 0.05,
            "latency_ms": 123.4,
            "human_override": False,
            "override_reason": None,
            "error": None,
        }
        trace = GovernedTrace.model_validate(legacy)
        # All pre-cr-017 fields preserve original values.
        assert trace.tool_name == "graq_review"
        assert trace.context_nodes == ["graqle/core/graph.py"]
        assert trace.clearance_level == ClearanceLevel.CONFIDENTIAL
        assert trace.cost_usd == 0.05
        # New fields use defaults.
        assert trace.schema_version == "2"
        assert trace.policy_version is None


# -------------------------------------------------------------------------
# P2 — Pre-cr-017 mandatory fields unchanged
# -------------------------------------------------------------------------


class TestP2MandatoryFieldsUnchanged:
    """The required fields from pre-cr-017 must still be required.
    cr-017 must NOT have relaxed any validation."""

    def test_tool_name_still_required(self):
        with pytest.raises(ValidationError, match="tool_name"):
            GovernedTrace(query="x", outcome=Outcome.SUCCESS, confidence=0.9)

    def test_query_still_required(self):
        with pytest.raises(ValidationError, match="query"):
            GovernedTrace(
                tool_name="x", outcome=Outcome.SUCCESS, confidence=0.9
            )

    def test_outcome_still_required(self):
        with pytest.raises(ValidationError, match="outcome"):
            GovernedTrace(tool_name="x", query="y", confidence=0.9)

    def test_confidence_range_still_enforced(self):
        # confidence must be in [0.0, 1.0] — cr-017 must not have weakened.
        with pytest.raises(ValidationError):
            _minimal_trace(confidence=1.5)
        with pytest.raises(ValidationError):
            _minimal_trace(confidence=-0.1)


# -------------------------------------------------------------------------
# P3 — extra="forbid" still rejects unknown fields
# -------------------------------------------------------------------------


class TestP3ExtraForbid:
    """The model_config has extra="forbid" — unknown fields on input
    must still be rejected. cr-017 must not have introduced a security
    regression by relaxing this guard."""

    def test_unknown_field_rejected_in_constructor(self):
        with pytest.raises(ValidationError, match="extra"):
            GovernedTrace(
                tool_name="x",
                query="y",
                outcome=Outcome.SUCCESS,
                confidence=0.9,
                some_invented_field="leak",  # type: ignore[call-arg]
            )

    def test_unknown_field_rejected_in_model_validate(self):
        legacy_plus_unknown = {
            "tool_name": "x",
            "query": "y",
            "outcome": "SUCCESS",
            "confidence": 0.9,
            "exfiltration_attempt": "secret",  # extra-forbid must reject
        }
        with pytest.raises(ValidationError, match="extra"):
            GovernedTrace.model_validate(legacy_plus_unknown)


# -------------------------------------------------------------------------
# P4 — model_dump round-trip for pre-cr-017 fields
# -------------------------------------------------------------------------


class TestP4ModelDumpRoundtrip:
    """Every pre-cr-017 field must round-trip through model_dump +
    model_validate with byte-identical values. cr-017 must not have
    silently changed any serialisation behaviour."""

    def test_full_roundtrip_preserves_all_fields(self):
        original = _minimal_trace(
            tool_name="graq_reason",
            query="reason query",
            clearance_level=ClearanceLevel.CONFIDENTIAL,
            outcome=Outcome.PARTIAL,
            confidence=0.65,
            cost_usd=0.012,
            latency_ms=456.7,
        )
        dumped = original.to_internal_dict()
        reconstructed = GovernedTrace.model_validate(dumped)
        assert reconstructed.tool_name == original.tool_name
        assert reconstructed.query == original.query
        assert reconstructed.clearance_level == original.clearance_level
        assert reconstructed.outcome == original.outcome
        assert reconstructed.confidence == pytest.approx(original.confidence)
        assert reconstructed.cost_usd == pytest.approx(original.cost_usd)
        assert reconstructed.latency_ms == pytest.approx(original.latency_ms)

    def test_json_roundtrip_preserves_id_uuid(self):
        # The auto-generated UUID id must survive JSON serialisation.
        original = _minimal_trace()
        encoded = json.dumps(original.to_internal_dict(), default=str)
        decoded = json.loads(encoded)
        reconstructed = GovernedTrace.model_validate(decoded)
        assert str(reconstructed.id) == str(original.id)


# -------------------------------------------------------------------------
# P5 — to_public_dict still excludes governance_decisions
# -------------------------------------------------------------------------


class TestP5PublicDictExcludesTrade2Gate:
    """to_public_dict() excludes the TS-2-gated governance_decisions
    field. cr-017 must not have leaked TS-2 internal IP into public
    serialisation."""

    def test_governance_decisions_excluded_from_public_dict(self):
        trace = _minimal_trace()
        public = trace.to_public_dict()
        assert "governance_decisions" not in public

    def test_governance_decisions_present_in_internal_dict(self):
        # And to_internal_dict still includes it (internal-only serialisation).
        trace = _minimal_trace()
        internal = trace.to_internal_dict()
        assert "governance_decisions" in internal


# -------------------------------------------------------------------------
# P6 — human_override / override_reason invariant
# -------------------------------------------------------------------------


class TestP6OverrideInvariant:
    """The model_validator that enforces override_reason consistency
    must still fire post-cr-017."""

    def test_human_override_without_reason_rejected(self):
        with pytest.raises(ValidationError, match="override_reason"):
            _minimal_trace(human_override=True, override_reason=None)

    def test_human_override_with_empty_reason_rejected(self):
        with pytest.raises(ValidationError, match="override_reason"):
            _minimal_trace(human_override=True, override_reason="   ")

    def test_human_override_with_reason_accepted(self):
        trace = _minimal_trace(
            human_override=True,
            override_reason="senior approved per ADR-209",
        )
        assert trace.human_override is True
        assert trace.override_reason == "senior approved per ADR-209"
