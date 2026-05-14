"""CR-003d regression tests — neo4j_import schema parity.

Pre-CR-003d, ``_batch_save_nodes`` and ``_batch_save_edges`` annotated
their payload as ``dict[str, Any]`` and unconditionally called
``.items()``. When graq grow wrote the node_link_data **list-shape**
(``nodes: [{id: ..., ...}, ...]``), the import command crashed with
``AttributeError: 'list' object has no attribute 'items'`` at
``neo4j_import.py:98``.

CR-003d introduces ``_as_items()`` which accepts both shapes and yields
``(id, data)`` tuples with collision-safe IDs. Anonymous IDs are derived
via full SHA-256 of the JSON-sorted-keys payload; duplicate IDs receive
``_dup<N>`` suffixes.

EU AI Act note: anonymous-ID derivation is deterministic per-content so
the audit trail is reproducible. No PII leaks via these synthetic IDs.
"""

from __future__ import annotations

import pytest

from graqle.cli.commands.neo4j_import import _as_items
from graqle.core.exceptions import GraphSchemaError


# ── Accepted shapes ────────────────────────────────────────────────────────


class TestAcceptedShapes:
    """_as_items accepts both dict-shape and list-shape payloads."""

    def test_dict_shape_yields_pairs_verbatim(self) -> None:
        payload = {
            "n1": {"label": "Auth", "type": "Module"},
            "n2": {"label": "DB", "type": "Module"},
        }
        out = list(_as_items(payload, label="nodes"))
        assert out == [
            ("n1", {"label": "Auth", "type": "Module"}),
            ("n2", {"label": "DB", "type": "Module"}),
        ]

    def test_list_shape_with_explicit_ids_preserved(self) -> None:
        payload = [
            {"id": "a", "label": "A"},
            {"id": "b", "label": "B"},
        ]
        out = list(_as_items(payload, label="nodes"))
        assert [k for k, _ in out] == ["a", "b"]
        assert out[0][1]["label"] == "A"
        assert out[1][1]["label"] == "B"

    def test_empty_dict_yields_nothing(self) -> None:
        assert list(_as_items({}, label="nodes")) == []

    def test_empty_list_yields_nothing(self) -> None:
        assert list(_as_items([], label="nodes")) == []


# ── Anonymous ID derivation ────────────────────────────────────────────────


class TestAnonymousIds:
    """List-shape entries missing 'id' get deterministic SHA-256-derived IDs."""

    def test_missing_id_derives_anon_sha256_prefix(self) -> None:
        payload = [{"label": "no-id-here"}]
        out = list(_as_items(payload, label="nodes"))
        assert len(out) == 1
        nid, _ = out[0]
        assert nid.startswith("_anon_")
        # Full sha256 hex = 64 chars; total = "_anon_" (6) + 64 = 70.
        assert len(nid) == 70

    def test_same_content_same_anon_id_deterministic(self) -> None:
        """Two distinct calls with identical payload yield identical anon IDs."""
        payload_a = [{"label": "dup-content"}]
        payload_b = [{"label": "dup-content"}]
        id_a = list(_as_items(payload_a, label="nodes"))[0][0]
        id_b = list(_as_items(payload_b, label="nodes"))[0][0]
        assert id_a == id_b

    def test_thousand_distinct_anon_ids_all_unique(self) -> None:
        """1000 distinct payloads without 'id' produce 1000 unique anon IDs."""
        payload = [{"label": f"node-{i}"} for i in range(1000)]
        ids = [nid for nid, _ in _as_items(payload, label="nodes")]
        assert len(set(ids)) == 1000


# ── Duplicate-ID collision handling ────────────────────────────────────────


class TestDuplicateIdCollision:
    """Duplicate ids in list-shape get ``_dup<N>`` suffixes — never overwrite."""

    def test_first_collision_appends_dup1(self) -> None:
        payload = [
            {"id": "shared", "label": "first"},
            {"id": "shared", "label": "second"},
        ]
        out = list(_as_items(payload, label="nodes"))
        assert [k for k, _ in out] == ["shared", "shared_dup1"]
        # Bodies preserved separately
        assert out[0][1]["label"] == "first"
        assert out[1][1]["label"] == "second"

    def test_triple_collision_appends_dup1_dup2(self) -> None:
        payload = [{"id": "x"}, {"id": "x"}, {"id": "x"}]
        out = list(_as_items(payload, label="nodes"))
        assert [k for k, _ in out] == ["x", "x_dup1", "x_dup2"]


# ── Schema validation errors ───────────────────────────────────────────────


class TestSchemaErrors:
    """Malformed payloads raise GraphSchemaError with label-prefixed messages."""

    def test_str_payload_rejected(self) -> None:
        with pytest.raises(GraphSchemaError, match="nodes must be dict or list"):
            list(_as_items("not-a-container", label="nodes"))

    def test_none_payload_rejected(self) -> None:
        with pytest.raises(GraphSchemaError, match="nodes must be dict or list"):
            list(_as_items(None, label="nodes"))

    def test_dict_with_non_string_key_rejected(self) -> None:
        with pytest.raises(GraphSchemaError, match="non-str key"):
            list(_as_items({42: {"label": "bad"}}, label="nodes"))

    def test_dict_with_non_dict_value_rejected(self) -> None:
        with pytest.raises(GraphSchemaError, match=r"\['xyz'\] is not a dict"):
            list(_as_items({"xyz": "scalar"}, label="nodes"))

    def test_list_with_non_dict_element_rejected(self) -> None:
        with pytest.raises(GraphSchemaError, match=r"\[1\] is not a dict"):
            list(_as_items([{"id": "a"}, "scalar-not-dict"], label="nodes"))

    def test_error_message_uses_provided_label(self) -> None:
        with pytest.raises(GraphSchemaError, match="^edges must be dict or list"):
            list(_as_items(42, label="edges"))


# ── Regression: original failure mode ──────────────────────────────────────


def test_regression_attributeerror_no_longer_raised_on_list_shape() -> None:
    """The original bug: list payload + dict[str, Any] annotation + .items()
    call raised AttributeError at neo4j_import.py:98. _as_items must NEVER
    surface AttributeError on list-shape input."""
    payload = [{"id": "a"}, {"id": "b"}]
    # If the regression returns, this would raise AttributeError instead of
    # yielding cleanly.
    out = list(_as_items(payload, label="nodes"))
    assert len(out) == 2
