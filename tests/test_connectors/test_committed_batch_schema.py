"""Tests for the :CommittedBatch schema migration on Neo4jConnector (PR-6).

All tests mock the neo4j driver — no live database. They assert on the exact
Cypher emitted (idempotent CREATE ... IF NOT EXISTS, single-transaction MERGE,
COMMITTED_IN linking) and on the batch_quarter partition derivation.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from graqle.connectors.neo4j import _batch_quarter_of


def _make_connector(**kwargs):
    """Neo4jConnector with a mocked driver injected."""
    with patch.dict("sys.modules", {"neo4j": MagicMock()}):
        from graqle.connectors.neo4j import Neo4jConnector

        connector = Neo4jConnector(**kwargs)
        connector._driver = MagicMock()
        return connector


class _FakeTx:
    def __init__(self, log):
        self.log = log

    def run(self, cypher, **params):
        self.log.append((cypher, params))
        return MagicMock()


class _FakeSession:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, cypher, **params):
        self.log.append((cypher, params))
        return MagicMock()

    def execute_write(self, fn):
        return fn(_FakeTx(self.log))


class _FakeDriver:
    def __init__(self, log):
        self.log = log

    def session(self, database=None):
        return _FakeSession(self.log)


def _connector_with_fake():
    with patch.dict("sys.modules", {"neo4j": MagicMock()}):
        from graqle.connectors.neo4j import Neo4jConnector

        connector = Neo4jConnector()
        log: list[tuple[str, dict]] = []
        connector._driver = _FakeDriver(log)
        return connector, log


# ---- batch_quarter derivation ----------------------------------------------


class TestBatchQuarterOf:
    @pytest.mark.parametrize(
        "iso,expected",
        [
            ("2026-01-01T00:00:00Z", "2026-Q1"),
            ("2026-03-31T23:59:59Z", "2026-Q1"),
            ("2026-04-01T00:00:00Z", "2026-Q2"),
            ("2026-06-14T11:23:45Z", "2026-Q2"),
            ("2026-07-01T00:00:00Z", "2026-Q3"),
            ("2026-10-01T00:00:00Z", "2026-Q4"),
            ("2026-12-31T23:59:59Z", "2026-Q4"),
            ("2026-06-14T11:23:45+00:00", "2026-Q2"),  # offset form, no Z
        ],
    )
    def test_valid_iso_buckets(self, iso, expected):
        assert _batch_quarter_of(iso) == expected

    @pytest.mark.parametrize("bad", [None, "", "not-a-date", 12345, "2026-13-99T00:00:00Z"])
    def test_invalid_falls_back_to_unknown(self, bad):
        assert _batch_quarter_of(bad) == "unknown"


# ---- create_committed_batch_schema -----------------------------------------


class TestCreateCommittedBatchSchema:
    def test_emits_constraint_and_three_indexes_all_idempotent(self):
        connector, log = _connector_with_fake()
        connector.create_committed_batch_schema()
        cyphers = [c for (c, _) in log]
        assert len(cyphers) == 4
        assert all("IF NOT EXISTS" in c for c in cyphers)
        assert any("CONSTRAINT batch_id_unique" in c and "b.batch_id IS UNIQUE" in c for c in cyphers)
        assert any("INDEX batch_committed_at" in c and "b.committed_at_iso" in c for c in cyphers)
        assert any("INDEX batch_rekor_index" in c and "b.rekor_log_index" in c for c in cyphers)
        assert any("INDEX batch_quarter_idx" in c and "b.batch_quarter" in c for c in cyphers)

    def test_single_label_only(self):
        # §8.1: NOT multi-label. The constraint/index target exactly :CommittedBatch.
        connector, log = _connector_with_fake()
        connector.create_committed_batch_schema()
        for cypher, _ in log:
            # no second label on the batch pattern
            assert ":CommittedBatch:" not in cypher


# ---- persist_committed_batch -----------------------------------------------


class TestPersistCommittedBatch:
    def test_merge_node_and_links_in_one_transaction(self):
        connector, log = _connector_with_fake()
        connector.persist_committed_batch(
            {
                "batch_id": "b1",
                "root_hex": "abc",
                "committed_at_iso": "2026-06-14T11:23:45Z",
                "rekor_log_index": 42,
            },
            record_hashes=["h1", "h2"],
        )
        assert len(log) == 2  # both via execute_write -> _FakeTx
        node_cypher, node_params = log[0]
        link_cypher, link_params = log[1]
        assert "MERGE (b:CommittedBatch {batch_id: $batch_id})" in node_cypher
        assert "ON CREATE SET b += $props" in node_cypher
        assert "OPTIONAL MATCH (n:CogniNode {record_hash: rh})" in link_cypher
        assert "MERGE (n)-[:COMMITTED_IN]->(b)" in link_cypher
        assert link_params["hashes"] == ["h1", "h2"]

    def test_batch_quarter_derived_when_absent(self):
        connector, log = _connector_with_fake()
        connector.persist_committed_batch(
            {"batch_id": "b1", "committed_at_iso": "2026-06-14T11:23:45Z"}
        )
        _, node_params = log[0]
        assert node_params["props"]["batch_quarter"] == "2026-Q2"

    def test_explicit_batch_quarter_preserved(self):
        connector, log = _connector_with_fake()
        connector.persist_committed_batch(
            {"batch_id": "b1", "committed_at_iso": "2026-06-14T11:23:45Z", "batch_quarter": "CUSTOM"}
        )
        _, node_params = log[0]
        assert node_params["props"]["batch_quarter"] == "CUSTOM"

    def test_no_record_hashes_skips_link_query(self):
        connector, log = _connector_with_fake()
        connector.persist_committed_batch({"batch_id": "b1"})
        assert len(log) == 1  # only the MERGE node, no link UNWIND
        assert "MERGE (b:CommittedBatch" in log[0][0]

    def test_missing_batch_id_raises_keyerror(self):
        connector, _ = _connector_with_fake()
        with pytest.raises(KeyError):
            connector.persist_committed_batch({"root_hex": "x"})

    @pytest.mark.parametrize("bad_id", ["", None, 123])
    def test_empty_or_nonstring_batch_id_raises_valueerror(self, bad_id):
        connector, _ = _connector_with_fake()
        with pytest.raises(ValueError):
            connector.persist_committed_batch({"batch_id": bad_id})


# ---- count_uncommitted_records ---------------------------------------------


class TestCountUncommittedRecords:
    def test_counts_governed_records_without_committed_in(self):
        connector = _make_connector()
        session = connector._driver.session().__enter__()
        result = MagicMock()
        result.single.return_value = {"cnt": 12}
        session.run.return_value = result
        n = connector.count_uncommitted_records()
        assert n == 12
        cypher = session.run.call_args[0][0]
        assert "governed_trace: true" in cypher
        assert "NOT (n)-[:COMMITTED_IN]->(:CommittedBatch)" in cypher

    def test_returns_zero_when_no_rows(self):
        connector = _make_connector()
        session = connector._driver.session().__enter__()
        result = MagicMock()
        result.single.return_value = None
        session.run.return_value = result
        assert connector.count_uncommitted_records() == 0
