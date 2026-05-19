"""Unit tests for cr-017 audit-log schema v2 fields on GovernedTrace.

Layer 1 of the cr-017 test plan. Targets the two new fields added in
:mod:`graqle.governance.trace_schema`:

  - ``schema_version: str`` (default ``"2"``)
  - ``policy_version: str | None`` (default ``None``)

Plus the module-level helpers introduced alongside the fields:

  - ``CURRENT_SCHEMA_VERSION``
  - ``LEGACY_POLICY_VERSION_SENTINEL``
  - :func:`classify_schema_version`
  - :func:`get_policy_version_or_sentinel`

These tests pin the v0.58.0 wire-format contract. Any future refactor
that breaks one of these is a regression and must be reverted (the
sentinel-string value in particular is part of the public OPSF Use B
audit-trail invariant per Research-Team v0.58.x directive item #2).
"""

# ── graqle:intelligence ──
# module: tests.test_governance.test_governed_trace_schema_v2
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, graqle.governance.trace_schema
# constraints: pin cr-017 wire-format contract
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import math

import pytest

from graqle.governance.trace_schema import (
    CURRENT_SCHEMA_VERSION,
    LEGACY_POLICY_VERSION_SENTINEL,
    ClearanceLevel,
    GovernedTrace,
    Outcome,
    ToolCall,
    classify_schema_version,
    get_policy_version_or_sentinel,
)


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------


def _minimal_trace(**overrides) -> GovernedTrace:
    """Build a minimal valid trace; callers can override any field."""
    defaults = {
        "tool_name": "graq_test",
        "query": "test query",
        "outcome": Outcome.SUCCESS,
        "confidence": 0.9,
    }
    defaults.update(overrides)
    return GovernedTrace(**defaults)


# -------------------------------------------------------------------------
# LAYER 1A — module-level constants (cr-017 contract surface)
# -------------------------------------------------------------------------


class TestModuleConstants:
    """Pin the public constants that downstream tooling depends on."""

    def test_current_schema_version_is_2(self):
        assert CURRENT_SCHEMA_VERSION == "2"

    def test_legacy_policy_version_sentinel_value(self):
        # The exact sentinel string is part of the public OPSF Use B contract;
        # changing it is a breaking change for any downstream auditor.
        assert LEGACY_POLICY_VERSION_SENTINEL == "legacy_pre_v058_unknown"

    def test_sentinel_is_string_not_none(self):
        # Helpers depend on this being a non-None, non-empty string.
        assert isinstance(LEGACY_POLICY_VERSION_SENTINEL, str)
        assert LEGACY_POLICY_VERSION_SENTINEL
        assert LEGACY_POLICY_VERSION_SENTINEL.strip() == LEGACY_POLICY_VERSION_SENTINEL


# -------------------------------------------------------------------------
# LAYER 1B — schema_version field on GovernedTrace
# -------------------------------------------------------------------------


class TestSchemaVersionField:
    def test_default_is_current_schema_version(self):
        t = _minimal_trace()
        assert t.schema_version == "2"
        assert t.schema_version == CURRENT_SCHEMA_VERSION

    def test_explicit_value_accepted(self):
        # Forward-compatibility: callers can set arbitrary version strings.
        t = _minimal_trace(schema_version="3")
        assert t.schema_version == "3"

    def test_appears_in_to_internal_dict(self):
        t = _minimal_trace()
        d = t.to_internal_dict()
        assert d["schema_version"] == "2"

    def test_appears_in_to_public_dict(self):
        # Public serialization must include schema_version (not gated by TS-2).
        t = _minimal_trace()
        d = t.to_public_dict()
        assert d["schema_version"] == "2"

    def test_appears_in_json_roundtrip(self):
        t = _minimal_trace()
        encoded = json.dumps(t.to_internal_dict(), default=str)
        parsed = json.loads(encoded)
        assert parsed["schema_version"] == "2"


# -------------------------------------------------------------------------
# LAYER 1C — policy_version field on GovernedTrace
# -------------------------------------------------------------------------


class TestPolicyVersionField:
    def test_default_is_none(self):
        t = _minimal_trace()
        assert t.policy_version is None

    def test_explicit_sha256_value_accepted(self):
        # The canonical shape is a "sha256:<hex>" string per baseline_doc.
        t = _minimal_trace(policy_version="sha256:abc123def456")
        assert t.policy_version == "sha256:abc123def456"

    def test_arbitrary_string_accepted(self):
        # The field is str|None — we do not enforce the sha256: prefix at
        # the Pydantic layer (downstream validators may apply stricter
        # checks). Pin the permissive behaviour.
        t = _minimal_trace(policy_version="anything-goes")
        assert t.policy_version == "anything-goes"

    def test_appears_in_to_internal_dict_when_none(self):
        t = _minimal_trace()
        d = t.to_internal_dict()
        # Pydantic v2 model_dump emits None for Optional fields by default.
        assert "policy_version" in d
        assert d["policy_version"] is None

    def test_appears_in_to_internal_dict_when_set(self):
        t = _minimal_trace(policy_version="sha256:test")
        d = t.to_internal_dict()
        assert d["policy_version"] == "sha256:test"

    def test_appears_in_to_public_dict(self):
        t = _minimal_trace(policy_version="sha256:public")
        d = t.to_public_dict()
        assert d["policy_version"] == "sha256:public"


# -------------------------------------------------------------------------
# LAYER 1D — classify_schema_version helper
# -------------------------------------------------------------------------


class TestClassifySchemaVersion:
    """The helper that lets readers distinguish pre-cr-017 v1 records from
    post-cr-017 v2+ records based on the presence/absence of the field."""

    def test_explicit_v2_returns_2(self):
        assert classify_schema_version({"schema_version": "2"}) == "2"

    def test_missing_field_returns_1(self):
        # Pre-cr-017 records on disk have NO schema_version field.
        assert classify_schema_version({"tool_name": "x"}) == "1"

    def test_empty_dict_returns_1(self):
        assert classify_schema_version({}) == "1"

    def test_none_returns_1(self):
        # Defensive: callers passing None get v1 treatment, not crash.
        assert classify_schema_version(None) == "1"

    def test_explicit_v3_forward_compat(self):
        # Future schema bumps return their actual version string.
        assert classify_schema_version({"schema_version": "3"}) == "3"

    def test_empty_string_returns_1(self):
        # Empty string is treated as missing/legacy (truthy guard).
        assert classify_schema_version({"schema_version": ""}) == "1"

    def test_non_string_value_returns_1(self):
        # Defensive against corrupted records: numeric schema_version is
        # rejected as v1 (legacy).
        assert classify_schema_version({"schema_version": 2}) == "1"
        assert classify_schema_version({"schema_version": None}) == "1"

    def test_does_not_mutate_input(self):
        raw = {"schema_version": "2", "tool_name": "x"}
        snapshot = dict(raw)
        classify_schema_version(raw)
        assert raw == snapshot


# -------------------------------------------------------------------------
# LAYER 1E — get_policy_version_or_sentinel helper
# -------------------------------------------------------------------------


class TestGetPolicyVersionOrSentinel:
    """The helper that gives downstream tooling a guaranteed-non-null
    content-addressed identifier, falling back to the sentinel for legacy
    records."""

    def test_returns_value_when_set(self):
        result = get_policy_version_or_sentinel({"policy_version": "sha256:abc"})
        assert result == "sha256:abc"

    def test_returns_sentinel_when_none(self):
        result = get_policy_version_or_sentinel({"policy_version": None})
        assert result == LEGACY_POLICY_VERSION_SENTINEL

    def test_returns_sentinel_when_missing(self):
        # Pre-cr-017 records: no policy_version field at all.
        result = get_policy_version_or_sentinel({"tool_name": "x"})
        assert result == LEGACY_POLICY_VERSION_SENTINEL

    def test_returns_sentinel_when_empty_string(self):
        result = get_policy_version_or_sentinel({"policy_version": ""})
        assert result == LEGACY_POLICY_VERSION_SENTINEL

    def test_returns_sentinel_when_dict_is_none(self):
        result = get_policy_version_or_sentinel(None)
        assert result == LEGACY_POLICY_VERSION_SENTINEL

    def test_returns_sentinel_for_non_string_value(self):
        # Corrupted records (numeric, bool, list, etc.) treated as legacy.
        assert get_policy_version_or_sentinel({"policy_version": 0}) == LEGACY_POLICY_VERSION_SENTINEL
        assert get_policy_version_or_sentinel({"policy_version": False}) == LEGACY_POLICY_VERSION_SENTINEL
        assert get_policy_version_or_sentinel({"policy_version": []}) == LEGACY_POLICY_VERSION_SENTINEL

    def test_does_not_mutate_input(self):
        raw = {"policy_version": "sha256:abc"}
        snapshot = dict(raw)
        get_policy_version_or_sentinel(raw)
        assert raw == snapshot


# -------------------------------------------------------------------------
# LAYER 1F — cross-field invariants
# -------------------------------------------------------------------------


class TestSchemaVersionAndPolicyVersionInteraction:
    """The two new fields are independent: schema_version defaults to '2'
    regardless of whether policy_version is set."""

    def test_v2_record_can_have_null_policy_version(self):
        # A v2 record from an issuer that has not yet generated a baseline.
        t = _minimal_trace(schema_version="2", policy_version=None)
        d = t.to_internal_dict()
        assert d["schema_version"] == "2"
        assert d["policy_version"] is None

    def test_v2_record_with_policy_version_set(self):
        t = _minimal_trace(schema_version="2", policy_version="sha256:b")
        d = t.to_internal_dict()
        assert d["schema_version"] == "2"
        assert d["policy_version"] == "sha256:b"

    def test_legacy_dict_classifies_v1_and_sentinel(self):
        # Simulate reading a pre-cr-017 record from JSONL: no schema_version,
        # no policy_version. Both helpers must give legacy answers.
        legacy = {
            "tool_name": "graq_inspect",
            "query": "old trace",
            "outcome": "SUCCESS",
            "confidence": 0.9,
        }
        assert classify_schema_version(legacy) == "1"
        assert get_policy_version_or_sentinel(legacy) == LEGACY_POLICY_VERSION_SENTINEL
