"""Tests for the PR-6 Neo4j kg_persist seam (committer -> :CommittedBatch).

All tests are offline: the Neo4jConnector is a MagicMock or a hand-rolled fake
driver, so no live Neo4j is required and coverage is realistic (the real Cypher
shapes are asserted on the captured calls).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from graqle.governance.tamper_evidence.kg_persist import (
    KgPersistError,
    Neo4jBatchPersister,
    batch_commit_to_props,
)


# ---- lightweight stand-ins for the PR-4/PR-5 data classes -------------------


@dataclass
class _Receipt:
    log_index: int = 99
    log_id: str = "log-id"
    inclusion_cert: str = "CERT_B64"
    signed_tree_head: str = "STH_B64"


@dataclass
class _CR:
    record_hash: str
    committed_at_iso: str | None = "2026-06-14T11:23:45Z"


@dataclass
class _Batch:
    batch_id: str
    merkle_root_hex: str
    receipt: object
    commit_records: list
    anchored: bool


def _anchored_batch() -> _Batch:
    return _Batch("bx", "root123", _Receipt(), [_CR("h1"), _CR("h2")], True)


def _unanchored_batch() -> _Batch:
    return _Batch("by", "root456", None, [_CR("h3")], False)


# ---- batch_commit_to_props -------------------------------------------------


class TestBatchCommitToProps:
    def test_anchored_maps_all_commitment_fields(self):
        props = batch_commit_to_props(_anchored_batch())
        assert props["batch_id"] == "bx"
        assert props["root_hex"] == "root123"
        assert props["size"] == 2
        assert props["committed_at_iso"] == "2026-06-14T11:23:45Z"
        assert props["anchor_backend"] == "sigstore_rekor"
        assert props["proof_format_version"] == "1.0.0"
        assert props["rekor_log_index"] == 99
        assert props["rekor_log_id"] == "log-id"
        assert props["rekor_inclusion_cert_b64"] == "CERT_B64"
        assert props["rekor_signed_tree_head_b64"] == "STH_B64"

    def test_unanchored_omits_rekor_fields(self):
        props = batch_commit_to_props(_unanchored_batch())
        assert props["batch_id"] == "by"
        assert props["size"] == 1
        for k in (
            "rekor_log_index",
            "rekor_log_id",
            "rekor_inclusion_cert_b64",
            "rekor_signed_tree_head_b64",
        ):
            assert k not in props

    def test_anchored_flag_true_but_receipt_none_omits_rekor(self):
        # Defensive: anchored=True with no receipt must not write null anchor ids.
        batch = _Batch("bz", "r", None, [_CR("h")], True)
        props = batch_commit_to_props(batch)
        assert "rekor_log_index" not in props

    def test_committed_at_iso_falls_back_to_none_when_no_record_has_it(self):
        batch = _Batch("bn", "r", None, [_CR("h", committed_at_iso=None)], False)
        props = batch_commit_to_props(batch)
        assert props["committed_at_iso"] is None

    def test_receipt_without_optional_cert_fields_still_maps_core_ids(self):
        @dataclass
        class _MinReceipt:
            log_index: int = 7
            log_id: str = "L"

        batch = _Batch("bm", "r", _MinReceipt(), [_CR("h")], True)
        props = batch_commit_to_props(batch)
        assert props["rekor_log_index"] == 7
        assert props["rekor_log_id"] == "L"
        assert "rekor_inclusion_cert_b64" not in props
        assert "rekor_signed_tree_head_b64" not in props


# ---- Neo4jBatchPersister ---------------------------------------------------


class _FakeConnector:
    """Records calls; raises on demand to exercise the wrap-and-propagate path."""

    def __init__(self, fail_persist=False, fail_count=False, fail_schema=False):
        self.schema_calls = 0
        self.persist_calls: list[tuple[dict, list]] = []
        self.count_calls = 0
        self._fail_persist = fail_persist
        self._fail_count = fail_count
        self._fail_schema = fail_schema

    def create_committed_batch_schema(self):
        self.schema_calls += 1
        if self._fail_schema:
            raise RuntimeError("schema boom")

    def persist_committed_batch(self, props, record_hashes):
        self.persist_calls.append((props, list(record_hashes)))
        if self._fail_persist:
            raise RuntimeError("persist boom")

    def count_uncommitted_records(self):
        self.count_calls += 1
        if self._fail_count:
            raise RuntimeError("count boom")
        return 7


class TestNeo4jBatchPersister:
    def test_persist_ensures_schema_then_persists(self):
        conn = _FakeConnector()
        p = Neo4jBatchPersister(conn)
        p(_anchored_batch())
        assert conn.schema_calls == 1
        assert len(conn.persist_calls) == 1
        props, hashes = conn.persist_calls[0]
        assert props["batch_id"] == "bx"
        assert hashes == ["h1", "h2"]

    def test_schema_ensured_only_once_across_batches(self):
        conn = _FakeConnector()
        p = Neo4jBatchPersister(conn)
        p(_anchored_batch())
        p(_unanchored_batch())
        assert conn.schema_calls == 1
        assert len(conn.persist_calls) == 2

    def test_ensure_schema_false_skips_schema(self):
        conn = _FakeConnector()
        p = Neo4jBatchPersister(conn, ensure_schema=False)
        p(_anchored_batch())
        assert conn.schema_calls == 0
        assert len(conn.persist_calls) == 1

    def test_persist_failure_wrapped_as_kgpersisterror(self):
        conn = _FakeConnector(fail_persist=True)
        p = Neo4jBatchPersister(conn)
        with pytest.raises(KgPersistError) as ei:
            p(_anchored_batch())
        assert "persist boom" in str(ei.value)
        assert ei.value.__cause__ is not None

    def test_schema_failure_wrapped_as_kgpersisterror(self):
        conn = _FakeConnector(fail_schema=True)
        p = Neo4jBatchPersister(conn)
        with pytest.raises(KgPersistError) as ei:
            p(_anchored_batch())
        assert "schema boom" in str(ei.value)
        # schema failed, so it never reached persist
        assert len(conn.persist_calls) == 0

    def test_kgpersisterror_from_connector_is_not_double_wrapped(self):
        class _Conn(_FakeConnector):
            def persist_committed_batch(self, props, record_hashes):
                raise KgPersistError("already typed")

        p = Neo4jBatchPersister(_Conn())
        with pytest.raises(KgPersistError) as ei:
            p(_anchored_batch())
        assert str(ei.value) == "already typed"

    def test_backfill_count_passthrough(self):
        conn = _FakeConnector()
        p = Neo4jBatchPersister(conn)
        assert p.backfill_count() == 7
        assert conn.count_calls == 1

    def test_backfill_count_wraps_error(self):
        conn = _FakeConnector(fail_count=True)
        p = Neo4jBatchPersister(conn)
        with pytest.raises(KgPersistError) as ei:
            p.backfill_count()
        assert "count boom" in str(ei.value)
