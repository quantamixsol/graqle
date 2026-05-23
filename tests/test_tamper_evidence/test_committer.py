"""Tests for the Layer 5 committer orchestrator (v0.59.0 PR-5, R25-EU01 Task 1.5).

Offline + deterministic: a real (tested) WalBatcher is used for the durable
enqueue/flush wiring, while the anchor, replay queue, and kg_persist seam are
fakes. Covers the full no-silent-drop lifecycle (PENDING -> COMMITTED ->
ANCHORED / REPLAY_QUEUED / FAILED), batched rollback, idempotency, the
trace-observer hook, and crash-recovery tracking.
"""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from graqle.config.attestation_config import AttestationConfig, ReplayQueueConfig
from graqle.governance.tamper_evidence.anchors.sigstore_rekor import (
    AnchorError,
    RekorAnchor,
    RekorReceipt,
)
from graqle.governance.tamper_evidence.audit_log_v3 import CommitStatus
from graqle.governance.tamper_evidence.batcher import WalBatcher
from graqle.governance.tamper_evidence.committer import (
    BatchCommit,
    Committer,
    CommitterError,
    _record_hash,
    _trace_to_record,
)
from graqle.governance.tamper_evidence.local_replay_queue import LocalReplayQueue


# ---- fakes / helpers ----------------------------------------------------------


def _record(i: int) -> dict:
    return {
        "proof_format_version": "1.0.0",
        "record_id": f"tr_{i:06d}",
        "content_hash": hashlib.sha256(f"payload-{i}".encode()).hexdigest(),
        "timestamp_unix": 1_700_000_000 + i,
        "governance_metadata": {"decision": "ALLOW", "seq": i},
    }


def _receipt(i: int = 1) -> RekorReceipt:
    return RekorReceipt(i, "logid", "sth", "cert", 1_700_000_000 + i)


class _OkTransport:
    def __init__(self):
        self.calls = 0

    def submit(self, root_bytes):
        self.calls += 1
        return _receipt(self.calls)


class _FailTransport:
    def submit(self, root_bytes):
        raise RuntimeError("rekor down")


def _ok_anchor() -> RekorAnchor:
    return RekorAnchor(transport=_OkTransport(), sleep=lambda _s: None)


def _fail_anchor() -> RekorAnchor:
    return RekorAnchor(
        config=__import__("graqle.config.attestation_config", fromlist=["RekorConfig"]).RekorConfig(retry_max_attempts=1),
        transport=_FailTransport(),
        sleep=lambda _s: None,
    )


def _config(**over) -> AttestationConfig:
    base = {"batch_max_records": 1000, "batch_max_seconds": 5}
    base.update(over)
    return AttestationConfig(**base)


def _batcher(tmp_path, **cfg_over) -> WalBatcher:
    # The committer installs its own flush handler; do NOT pass a committer here.
    return WalBatcher(_config(**cfg_over), wal_root=tmp_path)


def _replay_queue(tmp_path, anchor=None) -> LocalReplayQueue:
    return LocalReplayQueue(ReplayQueueConfig(), queue_root=tmp_path, anchor=anchor)


# ---- submit / PENDING ---------------------------------------------------------


def test_submit_tracks_pending(tmp_path):
    c = Committer(_config(), batcher=_batcher(tmp_path), anchor=_ok_anchor())
    cr = c.submit(_record(1))
    assert cr.commit_status == CommitStatus.PENDING
    assert cr.record_hash == _record_hash(_record(1))


def test_submit_rejects_non_dict(tmp_path):
    c = Committer(_config(), batcher=_batcher(tmp_path))
    with pytest.raises(CommitterError, match="must be a dict"):
        c.submit("nope")  # type: ignore[arg-type]


def test_submit_is_idempotent(tmp_path):
    c = Committer(_config(), batcher=_batcher(tmp_path), anchor=_ok_anchor())
    cr1 = c.submit(_record(1))
    cr2 = c.submit(_record(1))
    assert cr1 is cr2  # same content -> same CommitRecord
    assert c.status_counts()["pending"] == 1


def test_submit_uses_provided_trace_id(tmp_path):
    c = Committer(_config(), batcher=_batcher(tmp_path))
    tid = uuid4()
    cr = c.submit(_record(1), trace_id=tid)
    assert cr.trace_id == tid


# ---- happy path: COMMITTED -> ANCHORED ----------------------------------------


def test_flush_commits_and_anchors(tmp_path):
    c = Committer(_config(), batcher=_batcher(tmp_path), anchor=_ok_anchor())
    for i in range(3):
        c.submit(_record(i))
    committed = c.flush()
    assert committed == 3
    counts = c.status_counts()
    assert counts["anchored"] == 3
    cr = c.commit_record_for(_record(0))
    assert cr.commit_status == CommitStatus.ANCHORED
    assert cr.batch_id is not None
    assert cr.merkle_root_hex is not None
    assert cr.rekor_log_index is not None


def test_size_trigger_anchors_inline(tmp_path):
    c = Committer(_config(batch_max_records=2), batcher=_batcher(tmp_path, batch_max_records=2), anchor=_ok_anchor())
    c.submit(_record(0))
    assert c.status_counts()["pending"] == 1
    c.submit(_record(1))  # hits ceiling -> inline flush -> anchored
    assert c.status_counts()["anchored"] == 2


def test_commit_without_anchor_stays_committed(tmp_path):
    """No anchor configured: records commit locally (COMMITTED), not anchored."""
    c = Committer(_config(), batcher=_batcher(tmp_path), anchor=None)
    c.submit(_record(1))
    c.flush()
    cr = c.commit_record_for(_record(1))
    assert cr.commit_status == CommitStatus.COMMITTED  # no silent drop, no anchor


# ---- anchor failure -> REPLAY_QUEUED ------------------------------------------


def test_anchor_failure_queues_for_replay(tmp_path):
    rq = _replay_queue(tmp_path / "rq")
    c = Committer(_config(), batcher=_batcher(tmp_path), anchor=_fail_anchor(), replay_queue=rq)
    c.submit(_record(1))
    c.flush()
    cr = c.commit_record_for(_record(1))
    assert cr.commit_status == CommitStatus.REPLAY_QUEUED
    assert cr.batch_id is not None
    assert rq.depth == 1  # root durably queued


def test_anchor_failure_without_queue_marks_failed(tmp_path):
    """No replay queue: anchor failure marks FAILED (surfaced), never dropped."""
    c = Committer(_config(), batcher=_batcher(tmp_path), anchor=_fail_anchor(), replay_queue=None)
    c.submit(_record(1))
    c.flush()
    cr = c.commit_record_for(_record(1))
    assert cr.commit_status == CommitStatus.FAILED
    assert cr.error is not None


def test_anchor_and_queue_both_fail_marks_failed(tmp_path):
    """If both the anchor and the replay-queue enqueue fail, mark FAILED."""

    class _BrokenQueue:
        def enqueue(self, *a, **k):
            raise OSError("queue write failed")

    c = Committer(_config(), batcher=_batcher(tmp_path), anchor=_fail_anchor(), replay_queue=_BrokenQueue())
    c.submit(_record(1))
    c.flush()
    cr = c.commit_record_for(_record(1))
    assert cr.commit_status == CommitStatus.FAILED
    assert "replay-queue" in cr.error


# ---- batched persist + rollback -----------------------------------------------


def test_kg_persist_called_with_batch_commit(tmp_path):
    seen: list[BatchCommit] = []
    c = Committer(_config(), batcher=_batcher(tmp_path), anchor=_ok_anchor(), kg_persist=seen.append)
    for i in range(3):
        c.submit(_record(i))
    c.flush()
    assert len(seen) == 1
    batch = seen[0]
    assert batch.anchored is True
    assert len(batch.commit_records) == 3
    assert batch.receipt is not None
    assert batch.merkle_root_hex is not None


def test_kg_persist_failure_unanchored_rolls_back_and_retries(tmp_path):
    """KG-persist failure on an UNANCHORED batch rolls back fully + retries cleanly.

    With no anchor configured, nothing irreversible happened, so a persist
    failure rolls every record back to pristine PENDING and re-raises (batcher
    keeps the WAL intact). A clean retry then commits.
    """
    state = {"fail": True}

    def flaky_persist(_batch):
        if state["fail"]:
            raise RuntimeError("neo4j unavailable")

    # anchor=None => batch is COMMITTED but not anchored => safe to roll back.
    c = Committer(_config(), batcher=_batcher(tmp_path), anchor=None, kg_persist=flaky_persist)
    c.submit(_record(1))
    with pytest.raises(Exception):
        c.flush()
    cr = c.commit_record_for(_record(1))
    # FULL rollback: NO stale batch/root fields remain.
    assert cr.commit_status == CommitStatus.PENDING
    assert cr.batch_id is None
    assert cr.merkle_root_hex is None
    assert cr.committed_at_iso is None
    # Retry: persist now succeeds -> WAL entry drains, record COMMITTED.
    state["fail"] = False
    c.flush()
    cr = c.commit_record_for(_record(1))
    assert cr.commit_status == CommitStatus.COMMITTED


def test_kg_persist_failure_after_anchor_does_not_double_anchor(tmp_path):
    """KG-persist failure AFTER a successful anchor must NOT roll back / re-anchor.

    graq_predict failure-chain #2: the Rekor anchor is permanent. If persist
    fails post-anchor, re-flushing would re-anchor the same root under a new
    batch_id, orphaning the first. So the records stay ANCHORED, the KG mirror is
    deferred (surfaced via kg_persist_pending), and the anchor transport is
    called EXACTLY ONCE.
    """
    transport = _OkTransport()
    anchor = RekorAnchor(transport=transport, sleep=lambda _s: None)

    def always_fail_persist(_batch):
        raise RuntimeError("neo4j unavailable")

    c = Committer(_config(), batcher=_batcher(tmp_path), anchor=anchor, kg_persist=always_fail_persist)
    c.submit(_record(1))
    c.flush()  # must NOT raise (anchored => deferred, not re-raised)
    cr = c.commit_record_for(_record(1))
    assert cr.commit_status == CommitStatus.ANCHORED  # no rollback, no silent drop
    assert c.kg_persist_pending  # the failed KG mirror is recorded for reconcile
    assert len(c.kg_persist_pending) == 1
    # The anchor transport was called exactly once — no double-anchor.
    assert transport.calls == 1
    # WAL was cleared (batcher did not re-raise) — record is genuinely committed.
    from graqle.governance.tamper_evidence.batcher import WAL_SUBDIR
    wal = tmp_path / WAL_SUBDIR
    remaining = list(wal.glob("*.wal.json")) if wal.exists() else []
    assert remaining == []


# ---- status census ------------------------------------------------------------


def test_status_counts_total(tmp_path):
    c = Committer(_config(), batcher=_batcher(tmp_path), anchor=_ok_anchor())
    for i in range(2):
        c.submit(_record(i))
    counts = c.status_counts()
    assert sum(counts.values()) == 2
    assert set(counts) == {"pending", "committed", "anchored", "replay_queued", "failed"}


# ---- crash-recovery tracking (record reaches flush without prior submit) ------


def test_recovered_record_gets_tracked(tmp_path):
    """A record drained from the WAL on restart (never submitted) is still tracked."""
    # Seed a WAL entry via one committer, then build a fresh committer over the
    # same WAL root: the batcher recovers the entry; flushing tracks it.
    b1 = _batcher(tmp_path)
    Committer(_config(), batcher=b1, anchor=_ok_anchor()).submit(_record(5))
    # New batcher over the same root drains the WAL on construction.
    b2 = _batcher(tmp_path)
    c2 = Committer(_config(), batcher=b2, anchor=_ok_anchor())
    assert b2.pending_count == 1  # recovered
    c2.flush()
    cr = c2.commit_record_for(_record(5))
    assert cr is not None and cr.commit_status == CommitStatus.ANCHORED  # no silent drop


# ---- trace observer -----------------------------------------------------------


class _FakeTrace:
    def __init__(self, tid=None, tool="graq_reason", query="q", outcome_val="success"):
        from datetime import datetime, timezone

        self.id = tid or uuid4()
        self.tool_name = tool
        self.query = query
        self.outcome = type("O", (), {"value": outcome_val})()
        self.timestamp = datetime(2026, 5, 23, tzinfo=timezone.utc)
        self.schema_version = "2"


def test_as_trace_observer_submits_record(tmp_path):
    c = Committer(_config(), batcher=_batcher(tmp_path), anchor=_ok_anchor())
    observe = c.as_trace_observer()
    trace = _FakeTrace()
    observe(trace)
    assert c.status_counts()["pending"] == 1


def test_trace_observer_never_raises_on_bad_trace(tmp_path):
    c = Committer(_config(), batcher=_batcher(tmp_path))
    observe = c.as_trace_observer()
    observe(object())  # garbage trace -> must not raise
    observe(None)  # also must not raise
    assert c.status_counts()["pending"] == 0  # nothing committed from garbage


def test_trace_to_record_shape():
    trace = _FakeTrace()
    rec = _trace_to_record(trace)
    assert rec["proof_format_version"] == "1.0.0"
    assert rec["record_id"] == str(trace.id)
    assert len(rec["content_hash"]) == 64
    assert rec["timestamp_unix"] > 0
    assert rec["governance_metadata"]["outcome"] == "success"


def test_trace_to_record_none_when_no_id():
    assert _trace_to_record(object()) is None


def test_trace_observer_submits_and_survives_submit_failure(tmp_path, monkeypatch):
    """The observer path: a valid trace submits; if submit raises, it's swallowed.

    Covers the observer's submit call + its defensive except (committer 197-198).
    """
    c = Committer(_config(), batcher=_batcher(tmp_path), anchor=_ok_anchor())
    observe = c.as_trace_observer()
    # Force submit to raise AFTER a record is extracted -> exercises the except.
    monkeypatch.setattr(c, "submit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    observe(_FakeTrace())  # must not raise despite submit blowing up


def test_trace_to_record_non_serializable_returns_none():
    """A trace whose fields can't be JSON-serialized (even with default=str) -> None.

    Covers the _trace_to_record except (TypeError/ValueError) arm (342-343).
    """

    class _Unserializable:
        id = uuid4()
        tool_name = "graq_reason"
        query = "q"

        @property
        def outcome(self):
            # json.dumps(default=str) will call str() on this; raise there to
            # trigger the serialization-failure branch.
            class _Boom:
                value = property(lambda self: (_ for _ in ()).throw(ValueError("nope")))

                def __str__(self):
                    raise ValueError("cannot stringify")

            return _Boom()

    # getattr(...outcome).value raises inside the dict build -> caught -> None.
    assert _trace_to_record(_Unserializable()) is None
