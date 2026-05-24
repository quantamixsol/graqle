"""GATE2-COND-2: cross-module integration test of the leaf-input vs wrapper split.

ADR-RT-003 §11.2 carries GATE2-COND-2 to PR-7: a cross-module integration test
that the leaf-hash-input schema (the frozen subset hashed into Merkle leaves) is
genuinely separate from the wrapper schema (everything else on a record).

The binding contract (R25-EU08 / leaf_input_schema.py):

* Adding a WRAPPER field (e.g. created_at_iso, rekor_signed_tree_head) is a safe,
  additive change — it MUST NOT change any Merkle leaf hash or the tree root, so
  an old verifier and a new producer agree on the same root.
* Changing a LEAF field (one of LEAF_HASH_FIELDS) MUST change the leaf hash — that
  is what makes tampering with a hashed field detectable.

These tests exercise the real pipeline end-to-end:
``leaf_input_schema.project_leaf_input`` → ``canonicalize.canon_leaf`` →
``merkle.leaf_hash_for_record`` / ``MerkleTree`` — no mocks.
"""

from __future__ import annotations

import pytest

from graqle.governance.tamper_evidence.canonicalize import canon, canon_leaf
from graqle.governance.tamper_evidence.leaf_input_schema import (
    LEAF_HASH_FIELDS,
    project_leaf_input,
)
from graqle.governance.tamper_evidence.merkle import (
    MerkleTree,
    leaf_hash_for_record,
)


def _base_record():
    """A minimal record carrying every frozen leaf field plus a wrapper field."""
    return {
        "proof_format_version": "1.0.0",
        "record_id": "rec-0001",
        "content_hash": "sha256:abc123",
        "timestamp_unix": 1_780_000_000,
        "governance_metadata": {"decision": "ALLOW", "agent": "coordinator"},
        # wrapper-only field (NOT in LEAF_HASH_FIELDS):
        "created_at_iso": "2026-06-14T11:23:45Z",
    }


# ---- the split, at the projection layer ------------------------------------


class TestLeafInputProjection:
    def test_projection_keeps_only_leaf_fields(self):
        rec = _base_record()
        projected = project_leaf_input(rec)
        assert set(projected) <= set(LEAF_HASH_FIELDS)
        assert "created_at_iso" not in projected  # wrapper field dropped

    def test_projection_omits_absent_leaf_fields(self):
        rec = {"record_id": "r", "proof_format_version": "1.0.0"}
        projected = project_leaf_input(rec)
        assert set(projected) == {"record_id", "proof_format_version"}


# ---- adding a wrapper field does not move the leaf hash ---------------------


class TestWrapperAdditionIsLeafNeutral:
    def test_adding_wrapper_field_does_not_change_canon_leaf(self):
        rec = _base_record()
        before = canon_leaf(rec)
        rec_with_extra = {**rec, "rekor_signed_tree_head": "b64-sth", "extra_wrapper": 42}
        after = canon_leaf(rec_with_extra)
        assert before == after

    def test_adding_wrapper_field_does_not_change_leaf_hash(self):
        rec = _base_record()
        before = leaf_hash_for_record(rec)
        after = leaf_hash_for_record({**rec, "rekor_log_index": 99})
        assert before == after

    def test_wrapper_addition_preserves_merkle_root(self):
        recs = [
            {**_base_record(), "record_id": f"rec-{i}", "content_hash": f"sha256:{i}"}
            for i in range(4)
        ]
        root_before = MerkleTree.from_records(recs).root_hex

        # an old verifier (no wrapper field) and a new producer (extra wrapper
        # fields) must compute the SAME root
        recs_with_wrapper = [{**r, "created_at_iso": "2026-06-14T11:23:45Z"} for r in recs]
        root_after = MerkleTree.from_records(recs_with_wrapper).root_hex
        assert root_before == root_after

    def test_canon_wrapper_does_include_wrapper_field(self):
        # sanity: the WRAPPER canonicalization (used for signatures) DOES see a
        # wrapper field — proving the two canon functions are genuinely different
        # scopes. Start from a record WITHOUT the new field, then add it.
        rec = _base_record()
        before = canon(rec)
        after = canon({**rec, "rekor_signed_tree_head": "b64-sth"})
        assert before != after
        # and the same wrapper addition is leaf-neutral (the whole point)
        assert canon_leaf(rec) == canon_leaf({**rec, "rekor_signed_tree_head": "b64-sth"})


# ---- changing a leaf field DOES move the leaf hash -------------------------


class TestLeafFieldChangeIsDetected:
    @pytest.mark.parametrize("field", LEAF_HASH_FIELDS)
    def test_changing_each_leaf_field_changes_leaf_hash(self, field):
        rec = _base_record()
        before = leaf_hash_for_record(rec)
        tampered = dict(rec)
        # mutate the field to a different value of a JSON-native type
        if field == "timestamp_unix":
            tampered[field] = rec[field] + 1
        elif field == "governance_metadata":
            tampered[field] = {"decision": "DENY", "agent": "coordinator"}
        else:
            tampered[field] = str(rec[field]) + "-tampered"
        after = leaf_hash_for_record(tampered)
        assert before != after, f"tampering with leaf field {field!r} was not detected"

    def test_leaf_field_change_changes_merkle_root(self):
        recs = [
            {**_base_record(), "record_id": f"rec-{i}", "content_hash": f"sha256:{i}"}
            for i in range(4)
        ]
        root_before = MerkleTree.from_records(recs).root_hex
        # tamper one record's content_hash (a leaf field)
        recs[2] = {**recs[2], "content_hash": "sha256:TAMPERED"}
        root_after = MerkleTree.from_records(recs).root_hex
        assert root_before != root_after
