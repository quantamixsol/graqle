"""Tests for the Community meter sinks + count point 1 (WS-B B1).

100% statement + branch coverage of graqle/metering/sinks.py:
LocalNullMeter (no-op) and MeteredAttestationSink (runtime-path decorator),
including the never-raise guard, leaf-hash extraction, dedupe gating, metadata
projection, and constructor validation.
"""

from __future__ import annotations

import hashlib

import pytest

from graqle.metering.events import PROOF_ANCHORED, MeterEvent, MeterSink
from graqle.metering.dedupe import MeterDedupeStore
from graqle.metering.sinks import LocalNullMeter, MeteredAttestationSink


def _key(s: str = "p") -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class _CapMeter:
    def __init__(self):
        self.events: list[MeterEvent] = []

    def record(self, event):
        self.events.append(event)


class _InnerSink:
    def __init__(self):
        self.written: list[dict] = []

    def write(self, record):
        self.written.append(record)


# ---- LocalNullMeter -----------------------------------------------------------


def test_local_null_meter_is_a_metersink():
    assert isinstance(LocalNullMeter(), MeterSink)


def test_local_null_meter_records_nothing():
    # No exception, returns None — and there is nowhere for an event to go.
    assert LocalNullMeter().record(MeterEvent(idempotency_key=_key())) is None


# ---- MeteredAttestationSink: construction ------------------------------------


def test_requires_inner_with_write():
    with pytest.raises(ValueError, match="AttestationSink"):
        MeteredAttestationSink(None)
    with pytest.raises(ValueError, match="AttestationSink"):
        MeteredAttestationSink(object())  # no .write


def test_defaults_to_local_null_meter():
    inner = _InnerSink()
    sink = MeteredAttestationSink(inner)
    # a meterable record: no configured meter => LocalNullMeter, write still happens
    sink.write({"leaf_hash_hex": _key()})
    assert inner.written == [{"leaf_hash_hex": _key()}]


# ---- count point 1: write delegation + metering ------------------------------


def test_bills_once_and_delegates(tmp_path):
    inner, cap = _InnerSink(), _CapMeter()
    store = MeterDedupeStore(tmp_path)
    sink = MeteredAttestationSink(inner, meter=cap, dedupe=store, edition="studio")
    rec = {"leaf_hash_hex": _key(), "record_id": "r1", "domain": "d", "policy_id": "p1"}
    sink.write(rec)
    assert inner.written == [rec]  # always delegates
    assert len(cap.events) == 1
    ev = cap.events[0]
    assert ev.idempotency_key == _key()
    assert ev.unit == PROOF_ANCHORED and ev.edition == "studio"
    # metadata projected from the record (only the whitelisted keys)
    assert ev.metadata == {"record_id": "r1", "domain": "d", "policy_id": "p1"}


def test_retry_does_not_double_bill(tmp_path):
    inner, cap = _InnerSink(), _CapMeter()
    store = MeterDedupeStore(tmp_path)
    sink = MeteredAttestationSink(inner, meter=cap, dedupe=store)
    rec = {"leaf_hash_hex": _key()}
    sink.write(rec)
    sink.write(rec)  # retry
    assert len(inner.written) == 2  # both writes delegated
    assert len(cap.events) == 1  # billed once (exactly-once)


def test_record_without_leaf_hash_passthrough(tmp_path):
    inner, cap = _InnerSink(), _CapMeter()
    sink = MeteredAttestationSink(inner, meter=cap, dedupe=MeterDedupeStore(tmp_path))
    sink.write({"no_leaf": "x"})  # not a meterable proof
    assert inner.written == [{"no_leaf": "x"}]
    assert cap.events == []


def test_non_string_leaf_hash_passthrough(tmp_path):
    inner, cap = _InnerSink(), _CapMeter()
    sink = MeteredAttestationSink(inner, meter=cap, dedupe=MeterDedupeStore(tmp_path))
    sink.write({"leaf_hash_hex": 12345})  # wrong type
    assert inner.written and cap.events == []


def test_non_dict_record_passthrough_to_inner():
    # A non-dict record can't carry a leaf hash; it must still be delegated.
    inner = _InnerSink()
    sink = MeteredAttestationSink(inner)
    sink.write("not-a-dict")  # type: ignore[arg-type]
    assert inner.written == ["not-a-dict"]


def test_metadata_projection_skips_absent_keys(tmp_path):
    inner, cap = _InnerSink(), _CapMeter()
    sink = MeteredAttestationSink(inner, meter=cap, dedupe=MeterDedupeStore(tmp_path))
    sink.write({"leaf_hash_hex": _key()})  # no record_id/domain/policy_id
    assert cap.events[0].metadata == {}


def test_no_dedupe_store_still_bills_each_call():
    inner, cap = _InnerSink(), _CapMeter()
    sink = MeteredAttestationSink(inner, meter=cap)  # dedupe=None
    rec = {"leaf_hash_hex": _key()}
    sink.write(rec)
    sink.write(rec)
    assert len(cap.events) == 2  # without a store, no cross-call dedupe


# ---- never-raise guard --------------------------------------------------------


def test_meter_fault_never_breaks_write(tmp_path):
    class _BoomMeter:
        def record(self, event):
            raise RuntimeError("meter down")

    inner = _InnerSink()
    sink = MeteredAttestationSink(inner, meter=_BoomMeter(), dedupe=MeterDedupeStore(tmp_path))
    rec = {"leaf_hash_hex": _key()}
    sink.write(rec)  # must NOT raise
    assert inner.written == [rec]  # durable write still happened


def test_dedupe_fault_never_breaks_write(tmp_path):
    # A dedupe-store failure (e.g. disk error) must also not break the write.
    class _BoomStore:
        def mark_if_new(self, key):
            raise OSError("disk full")

    inner, cap = _InnerSink(), _CapMeter()
    sink = MeteredAttestationSink(inner, meter=cap, dedupe=_BoomStore())
    rec = {"leaf_hash_hex": _key()}
    sink.write(rec)  # must NOT raise
    assert inner.written == [rec]
    assert cap.events == []  # dedupe failed before billing
