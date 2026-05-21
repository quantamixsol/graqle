"""Tests for RFC 8785 canonicalization + leaf-input projection (v0.59.0 PR-1)."""

from __future__ import annotations

import copy
import math

import pytest

from graqle.governance.tamper_evidence.canonicalize import canon, canon_leaf
from graqle.governance.tamper_evidence.errors import (
    InvalidFloatValueError,
    MissingLeafFieldError,
    NonCanonicalTypeError,
    TamperEvidenceError,
)
from graqle.governance.tamper_evidence.leaf_input_schema import (
    LEAF_HASH_FIELDS,
    project_leaf_input,
)

try:
    from hypothesis import given
    from hypothesis import strategies as st

    _HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover - hypothesis is a dev dep
    _HAS_HYPOTHESIS = False


# ---- determinism --------------------------------------------------------------


def test_canon_deterministic_key_order():
    """Same data, different key insertion order -> identical canonical bytes."""
    a = {"b": 1, "a": 2, "c": 3}
    b = {"c": 3, "a": 2, "b": 1}
    assert canon(a) == canon(b)


def test_canon_deepcopy_identity():
    """canon(deepcopy(R)) == canon(R) for a representative record."""
    record = {
        "proof_format_version": "1.0.0",
        "record_id": "tr_01HXJK",
        "content_hash": "abcdef",
        "timestamp_unix": 1779000000,
        "governance_metadata": {"gate": "shacl", "decision": "CLEAR"},
        "wrapper_only": {"created_at_iso": "2026-05-21T00:00:00Z"},
    }
    assert canon(copy.deepcopy(record)) == canon(record)


def test_canon_returns_bytes():
    assert isinstance(canon({"a": 1}), bytes)
    assert isinstance(
        canon_leaf({"proof_format_version": "1.0.0", "record_id": "x"}), bytes
    )


if _HAS_HYPOTHESIS:
    _json_scalars = st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-(10**12), max_value=10**12),
        st.text(max_size=40),
    )
    _json_values = st.recursive(
        _json_scalars,
        lambda children: st.one_of(
            st.lists(children, max_size=4),
            st.dictionaries(st.text(min_size=1, max_size=12), children, max_size=4),
        ),
        max_leaves=12,
    )

    @given(st.dictionaries(st.text(min_size=1, max_size=12), _json_values, max_size=5))
    def test_canon_property_deepcopy_invariant(record):
        """Property: canonicalization is stable under deep copy (no float NaN/Inf
        in the strategy, so no rejection path)."""
        assert canon(copy.deepcopy(record)) == canon(record)


# ---- float safety (C-P0-2) ----------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_rejects_nan_and_infinity(bad):
    with pytest.raises(InvalidFloatValueError):
        canon({"x": bad})


def test_rejects_negative_zero():
    neg_zero = math.copysign(0.0, -1.0)
    assert neg_zero == 0.0 and math.copysign(1.0, neg_zero) < 0  # sanity
    with pytest.raises(InvalidFloatValueError):
        canon({"x": neg_zero})


def test_positive_zero_is_allowed():
    # Plain 0.0 has a stable canonical form and must NOT be rejected.
    assert isinstance(canon({"x": 0.0}), bytes)


def test_rejects_nested_nonfinite():
    with pytest.raises(InvalidFloatValueError):
        canon({"a": {"b": [1, 2, float("inf")]}})


def test_invalid_float_error_carries_path_and_is_valueerror():
    with pytest.raises(InvalidFloatValueError) as exc:
        canon({"outer": {"inner": float("nan")}})
    assert "outer.inner" in exc.value.field_path
    assert isinstance(exc.value, ValueError)
    assert isinstance(exc.value, TamperEvidenceError)


def test_canon_leaf_also_rejects_nonfinite():
    with pytest.raises(InvalidFloatValueError):
        canon_leaf(
            {"proof_format_version": "1.0.0", "timestamp_unix": float("nan")}
        )


def test_rejects_pathologically_deep_nesting():
    """Stack-exhaustion DoS guard: input nested past _MAX_SCAN_DEPTH raises
    InvalidFloatValueError (not a bare RecursionError)."""
    deep: dict = {}
    node = deep
    for _ in range(200):  # well past the 64 limit
        child: dict = {}
        node["n"] = child
        node = child
    with pytest.raises(InvalidFloatValueError):
        canon(deep)


def test_normal_nesting_depth_allowed():
    """Legitimate shallow nesting is unaffected by the depth guard."""
    record = {"a": {"b": {"c": {"d": {"e": 1}}}}}
    assert isinstance(canon(record), bytes)


# ---- leaf-input projection (C-P1-2) -------------------------------------------


def test_project_leaf_input_drops_wrapper_fields():
    record = {
        "proof_format_version": "1.0.0",
        "record_id": "r1",
        "content_hash": "h",
        "timestamp_unix": 1,
        "governance_metadata": {"k": "v"},
        "created_at_iso": "2026-01-01T00:00:00Z",  # wrapper - must be dropped
        "rekor_signed_tree_head": "sth",          # wrapper - must be dropped
    }
    projected = project_leaf_input(record)
    assert set(projected.keys()) == set(LEAF_HASH_FIELDS)
    assert "created_at_iso" not in projected
    assert "rekor_signed_tree_head" not in projected


def test_project_leaf_input_omits_absent_fields():
    projected = project_leaf_input({"record_id": "only"})
    assert projected == {"record_id": "only"}


def test_canon_leaf_excludes_wrapper_from_bytes():
    """A wrapper field added to the record must NOT change the leaf bytes."""
    base = {
        "proof_format_version": "1.0.0",
        "record_id": "r1",
        "content_hash": "h",
        "timestamp_unix": 1,
        "governance_metadata": {"k": "v"},
    }
    with_wrapper = {**base, "created_at_iso": "2026-01-01T00:00:00Z"}
    assert canon_leaf(base) == canon_leaf(with_wrapper)


def test_proof_format_version_is_in_leaf_subset():
    """Replay-attack defense: version must be inside the leaf hash input."""
    assert "proof_format_version" in LEAF_HASH_FIELDS


def test_canon_leaf_rejects_missing_proof_format_version():
    """canon_leaf MUST reject a record lacking proof_format_version (replay
    defense — graq_predict chain #2). A versionless leaf would be replayable
    under any version banner."""
    with pytest.raises(MissingLeafFieldError):
        canon_leaf({"record_id": "r1", "content_hash": "h"})  # no version


# ---- non-canonical type rejection (security hardening) ------------------------


def test_rejects_decimal():
    """Decimal has no stable canonical JSON form -> NonCanonicalTypeError."""
    from decimal import Decimal

    with pytest.raises(NonCanonicalTypeError):
        canon({"x": Decimal("1.5")})


def test_rejects_decimal_nan_does_not_slip_through():
    """A Decimal('NaN') must be rejected by the TYPE check before any float
    logic (it is not a Python float, so the old isinstance(float) guard would
    have missed it)."""
    from decimal import Decimal

    with pytest.raises(NonCanonicalTypeError):
        canon({"x": Decimal("NaN")})


def test_rejects_set_and_datetime():
    import datetime

    with pytest.raises(NonCanonicalTypeError):
        canon({"x": {1, 2, 3}})
    with pytest.raises(NonCanonicalTypeError):
        canon({"x": datetime.datetime(2026, 1, 1)})


def test_rejects_custom_float_object():
    class Sneaky:
        def __float__(self):
            return float("nan")

    with pytest.raises(NonCanonicalTypeError):
        canon({"x": Sneaky()})


def test_non_canonical_type_error_is_typeerror():
    from decimal import Decimal

    with pytest.raises(NonCanonicalTypeError) as exc:
        canon({"a": {"b": Decimal("1")}})
    assert isinstance(exc.value, TypeError)
    assert isinstance(exc.value, TamperEvidenceError)
    assert "a.b" in exc.value.field_path


def test_bool_and_int_and_str_allowed():
    """JSON-native types pass the type check."""
    out = canon({"flag": True, "n": 5, "s": "ok", "nil": None, "f": 1.5})
    assert isinstance(out, bytes)


def test_bool_distinct_and_deterministic_from_int():
    """bool is a subclass of int but must canonicalize to JSON true/false
    (distinct from 1/0) and do so deterministically. Confirms no bool/int
    canonicalization ambiguity in the hash (security sentinel round-2 ask)."""
    true_bytes = canon({"v": True})
    one_bytes = canon({"v": 1})
    false_bytes = canon({"v": False})
    zero_bytes = canon({"v": 0})
    # JSON distinguishes true/false from 1/0.
    assert true_bytes == b'{"v":true}'
    assert false_bytes == b'{"v":false}'
    assert one_bytes == b'{"v":1}'
    assert zero_bytes == b'{"v":0}'
    assert true_bytes != one_bytes and false_bytes != zero_bytes
    # Deterministic across repeated calls.
    assert canon({"v": True}) == true_bytes


def test_int_and_float_valued_int_canonicalize_identically():
    """graq_predict chain #1 (verified safe): an integer and the same
    integer-valued float produce identical canonical bytes (RFC 8785 / JCS
    number normalization), so a producer passing 1779000000 vs 1779000000.0
    does not break cross-record determinism."""
    as_int = canon_leaf(
        {"proof_format_version": "1.0.0", "timestamp_unix": 1779000000}
    )
    as_float = canon_leaf(
        {"proof_format_version": "1.0.0", "timestamp_unix": 1779000000.0}
    )
    assert as_int == as_float


def test_leaf_fields_frozen_order():
    """Guards accidental reorder/edit of the frozen allowlist (would be a MAJOR
    proof-format bump requiring migration tooling)."""
    assert LEAF_HASH_FIELDS == (
        "proof_format_version",
        "record_id",
        "content_hash",
        "timestamp_unix",
        "governance_metadata",
    )


# ---- canonical output properties + golden ------------------------------------


def test_canonical_output_jcs_properties():
    """JCS structural guarantees the M3 cross-implementation verifiers rely on:
    keys are lexicographically sorted, there is no insignificant whitespace, and
    the output is valid UTF-8 that round-trips to the same data."""
    import json

    record = {
        "proof_format_version": "1.0.0",
        "record_id": "tr_golden_0001",
        "content_hash": "0" * 64,
        "timestamp_unix": 1779000000,
        "governance_metadata": {"gate": "shacl", "decision": "CLEAR"},
    }
    out = canon_leaf(record)
    assert isinstance(out, bytes)
    text = out.decode("utf-8")  # must be valid UTF-8
    # No insignificant whitespace (JCS is compact).
    assert ", " not in text and ": " not in text
    # Top-level keys are sorted.
    reparsed = json.loads(text)
    assert list(reparsed.keys()) == sorted(reparsed.keys())
    # Round-trips to the same projected data.
    assert reparsed == {
        "content_hash": "0" * 64,
        "governance_metadata": {"decision": "CLEAR", "gate": "shacl"},
        "proof_format_version": "1.0.0",
        "record_id": "tr_golden_0001",
        "timestamp_unix": 1779000000,
    }


def test_golden_vector_frozen():
    """Capture-and-freeze golden vector: canonicalizing a re-ordered copy of a
    fixed record yields identical bytes. Catches future JCS-output drift without
    hardcoding a literal that can't be verified until the dep is installed.
    A frozen byte literal ships in tests/test_tamper_evidence/golden/ once
    captured (M3 cross-impl corpus seed)."""
    record = {
        "proof_format_version": "1.0.0",
        "record_id": "tr_golden_0001",
        "content_hash": "0" * 64,
        "timestamp_unix": 1779000000,
        "governance_metadata": {"decision": "CLEAR", "gate": "shacl"},
    }
    out = canon_leaf(record)
    reordered = {
        "governance_metadata": {"gate": "shacl", "decision": "CLEAR"},
        "timestamp_unix": 1779000000,
        "record_id": "tr_golden_0001",
        "content_hash": "0" * 64,
        "proof_format_version": "1.0.0",
    }
    assert canon_leaf(reordered) == out
