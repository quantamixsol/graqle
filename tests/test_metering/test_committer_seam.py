"""Integration tests for the Committer meter_observer seam (WS-B count point 2).

Exercises the additive seam in graqle/governance/tamper_evidence/committer.py
against a REAL WalBatcher + Committer with a fake anchor, covering:
* the per-leaf observer fire on the ANCHORED transition,
* the per-leaf guard's except branch (a raising observer never breaks the anchor),
* local-only (no anchor) emitting zero billable events (free/paid line),
* anchor-failure path (REPLAY_QUEUED) emitting zero,
* cross-path exactly-once when count point 1 and 2 share a MeterDedupeStore.

Offline + deterministic (no network, no Neo4j): the anchor/transport are fakes.
"""

from __future__ import annotations

import hashlib

import pytest

from graqle.config.attestation_config import AttestationConfig, RekorConfig, ReplayQueueConfig
from graqle.governance.tamper_evidence.anchors.sigstore_rekor import RekorAnchor, RekorReceipt
from graqle.governance.tamper_evidence.audit_log_v3 import CommitStatus
from graqle.governance.tamper_evidence.batcher import WalBatcher
from graqle.governance.tamper_evidence.committer import Committer
from graqle.governance.tamper_evidence.local_replay_queue import LocalReplayQueue
from graqle.metering import MeterDedupeStore, MeteredAttestationSink, make_meter_observer
from graqle.metering.events import MeterEvent


# ---- fakes / helpers (mirror tests/test_tamper_evidence/test_committer.py) ----


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
        config=RekorConfig(retry_max_attempts=1),
        transport=_FailTransport(),
        sleep=lambda _s: None,
    )


def _config() -> AttestationConfig:
    return AttestationConfig(batch_max_records=1000, batch_max_seconds=5)


def _batcher(tmp_path) -> WalBatcher:
    return WalBatcher(_config(), wal_root=tmp_path)


class _CapMeter:
    def __init__(self):
        self.events: list[MeterEvent] = []

    def record(self, event):
        self.events.append(event)


# ---- the seam ----------------------------------------------------------------


def test_anchored_batch_bills_each_leaf(tmp_path):
    cap = _CapMeter()
    obs = make_meter_observer(meter=cap, dedupe=MeterDedupeStore(tmp_path / "dd"), edition="studio")
    committer = Committer(_config(), _batcher(tmp_path / "wal"), anchor=_ok_anchor(), meter_observer=obs)
    committer.submit(_record(1))
    committer.submit(_record(2))
    committer.submit(_record(3))
    n = committer.flush()
    assert n == 3
    assert len(cap.events) == 3
    assert all(e.unit == "proof_anchored" and e.edition == "studio" for e in cap.events)
    # carries the batch context for the meter API audit trail
    assert cap.events[0].metadata.get("rekor_log_index") == 1
    assert "batch_id" in cap.events[0].metadata and "merkle_root_hex" in cap.events[0].metadata


def test_no_observer_means_no_billing_machinery(tmp_path):
    # meter_observer=None (the Community default) — anchoring still works, no calls.
    committer = Committer(_config(), _batcher(tmp_path / "wal"), anchor=_ok_anchor())
    committer.submit(_record(1))
    assert committer.flush() == 1  # anchors fine without a meter


def test_local_only_no_anchor_bills_zero(tmp_path):
    cap = _CapMeter()
    obs = make_meter_observer(meter=cap, dedupe=MeterDedupeStore(tmp_path / "dd"))
    committer = Committer(_config(), _batcher(tmp_path / "wal"), anchor=None, meter_observer=obs)
    committer.submit(_record(1))
    committer.flush()
    # local commit (COMMITTED, never ANCHORED) => free/paid line => zero events
    assert cap.events == []
    cr = committer.commit_record_for(_record(1))
    assert cr.commit_status == CommitStatus.COMMITTED


def test_anchor_failure_replay_queued_bills_zero(tmp_path):
    cap = _CapMeter()
    obs = make_meter_observer(meter=cap, dedupe=MeterDedupeStore(tmp_path / "dd"))
    rq = LocalReplayQueue(ReplayQueueConfig(), queue_root=tmp_path / "rq")
    committer = Committer(
        _config(), _batcher(tmp_path / "wal"),
        anchor=_fail_anchor(), replay_queue=rq, meter_observer=obs,
    )
    committer.submit(_record(1))
    committer.flush()
    # anchor failed => REPLAY_QUEUED, never ANCHORED => not billable yet
    assert cap.events == []
    assert committer.commit_record_for(_record(1)).commit_status == CommitStatus.REPLAY_QUEUED


def test_raising_observer_never_breaks_anchor(tmp_path):
    # The per-leaf guard inside committer.py must swallow an observer exception:
    # the proof is durable in Rekor regardless.
    def _boom(record_hash, context):
        raise RuntimeError("observer blew up")

    committer = Committer(_config(), _batcher(tmp_path / "wal"), anchor=_ok_anchor(), meter_observer=_boom)
    committer.submit(_record(1))
    n = committer.flush()  # must NOT raise
    assert n == 1
    assert committer.commit_record_for(_record(1)).commit_status == CommitStatus.ANCHORED


def test_cross_path_exactly_once(tmp_path):
    # The SAME proof reaches count point 1 (runtime sink) and count point 2
    # (committer anchor). With a shared dedupe store, it bills exactly once.
    cap = _CapMeter()
    shared = MeterDedupeStore(tmp_path / "dd")

    class _Inner:
        def __init__(self):
            self.written = []

        def write(self, r):
            self.written.append(r)

    # Path 1: a runtime attest record carrying the leaf hash for record #1.
    leaf1 = hashlib.sha256(b"the-one-proof").hexdigest()
    runtime_sink = MeteredAttestationSink(_Inner(), meter=cap, dedupe=shared, edition="studio")
    runtime_sink.write({"leaf_hash_hex": leaf1, "record_id": "tr_000001"})
    assert len(cap.events) == 1  # billed via path 1

    # Path 2: the committer anchors a leaf with the SAME hash.
    obs = make_meter_observer(meter=cap, dedupe=shared, edition="studio")
    obs(leaf1, {"batch_id": "b1"})
    assert len(cap.events) == 1  # NOT re-billed — cross-path exactly-once

    # A different proof on path 2 does bill.
    obs(hashlib.sha256(b"another-proof").hexdigest(), {"batch_id": "b1"})
    assert len(cap.events) == 2
