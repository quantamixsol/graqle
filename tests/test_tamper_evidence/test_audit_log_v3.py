"""Tests for audit-log v3 commit-status sidecar (v0.59.0 PR-5, R25-EU01)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from graqle.governance.tamper_evidence.audit_log_v3 import (
    CommitRecord,
    CommitStatus,
)


def _cr() -> CommitRecord:
    return CommitRecord(trace_id=uuid4(), record_hash="a" * 64)


# ---- CommitStatus enum --------------------------------------------------------


def test_commit_status_values_are_the_total_set():
    """The 5 states are exactly the no-silent-drop lifecycle (no 'unknown')."""
    assert {s.value for s in CommitStatus} == {
        "pending", "committed", "anchored", "replay_queued", "failed",
    }


def test_commit_status_is_str_enum():
    assert CommitStatus.ANCHORED == "anchored"  # str-comparable for serialization


# ---- initial state ------------------------------------------------------------


def test_new_record_is_pending():
    cr = _cr()
    assert cr.commit_status == CommitStatus.PENDING
    assert cr.schema_version == "3"
    assert cr.is_terminal is False
    assert cr.batch_id is None


# ---- transitions --------------------------------------------------------------


def test_mark_committed_sets_batch_root_and_timestamp():
    cr = _cr()
    cr.mark_committed("batch1", "f" * 64)
    assert cr.commit_status == CommitStatus.COMMITTED
    assert cr.batch_id == "batch1"
    assert cr.merkle_root_hex == "f" * 64
    assert cr.committed_at_iso is not None and cr.committed_at_iso.endswith("Z")
    assert cr.is_terminal is False  # COMMITTED still progresses to ANCHORED


def test_mark_anchored_is_terminal():
    cr = _cr()
    cr.mark_committed("batch1", "f" * 64)
    cr.mark_anchored(12345, "logid")
    assert cr.commit_status == CommitStatus.ANCHORED
    assert cr.rekor_log_index == 12345
    assert cr.rekor_log_id == "logid"
    assert cr.anchored_at_iso is not None
    assert cr.is_terminal is True


def test_mark_replay_queued_sets_batch_and_is_not_terminal():
    cr = _cr()
    cr.mark_replay_queued("batch2", "e" * 64)
    assert cr.commit_status == CommitStatus.REPLAY_QUEUED
    assert cr.batch_id == "batch2"
    assert cr.merkle_root_hex == "e" * 64
    assert cr.committed_at_iso is not None  # committed locally, anchor deferred
    assert cr.is_terminal is False  # a later drain advances it to ANCHORED


def test_replay_queued_preserves_existing_committed_timestamp():
    cr = _cr()
    cr.mark_committed("batch1", "f" * 64)
    first_ts = cr.committed_at_iso
    cr.mark_replay_queued("batch1", "f" * 64)
    assert cr.committed_at_iso == first_ts  # not overwritten


def test_mark_failed_is_terminal_and_truncates():
    cr = _cr()
    cr.mark_failed("x" * 5000)
    assert cr.commit_status == CommitStatus.FAILED
    assert cr.error is not None and len(cr.error) == 1000  # truncated
    assert cr.is_terminal is True


# ---- serialization ------------------------------------------------------------


def test_to_dict_round_trip_shape():
    cr = _cr()
    cr.mark_committed("batch1", "f" * 64)
    cr.mark_anchored(7, "log7")
    d = cr.to_dict()
    assert d["schema_version"] == "3"
    assert d["commit_status"] == "anchored"
    assert d["batch_id"] == "batch1"
    assert d["merkle_root_hex"] == "f" * 64
    assert d["rekor_log_index"] == 7
    assert d["trace_id"] == str(cr.trace_id)
    assert d["record_hash"] == "a" * 64


def test_to_dict_pending_has_nulls():
    cr = _cr()
    d = cr.to_dict()
    assert d["commit_status"] == "pending"
    assert d["batch_id"] is None
    assert d["rekor_log_index"] is None
    assert d["error"] is None


# ---- snapshot / restore (full-state rollback) ---------------------------------


def test_snapshot_restore_round_trip_full_state():
    """restore(snapshot()) returns the record to its EXACT prior state."""
    cr = _cr()
    snap = cr.snapshot()  # pristine PENDING
    cr.mark_committed("batch1", "f" * 64)
    cr.mark_anchored(7, "log7")
    assert cr.commit_status == CommitStatus.ANCHORED
    cr.restore(snap)
    # Every mutable field is back to pristine — no stale batch/root/anchor data.
    assert cr.commit_status == CommitStatus.PENDING
    assert cr.batch_id is None
    assert cr.merkle_root_hex is None
    assert cr.rekor_log_index is None
    assert cr.rekor_log_id is None
    assert cr.committed_at_iso is None
    assert cr.anchored_at_iso is None
    assert cr.error is None


def test_snapshot_captures_committed_state():
    """A snapshot taken mid-lifecycle restores to THAT point, not pristine."""
    cr = _cr()
    cr.mark_committed("batch1", "f" * 64)
    snap = cr.snapshot()  # COMMITTED
    cr.mark_anchored(7, "log7")
    cr.restore(snap)
    assert cr.commit_status == CommitStatus.COMMITTED
    assert cr.batch_id == "batch1"
    assert cr.rekor_log_index is None  # anchor undone
