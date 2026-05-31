"""Tests for the metering data model (WS-B): MeterEvent + MeterSink Protocol.

100% statement + branch coverage of graqle/metering/events.py, including every
validation branch in MeterEvent.__post_init__ (fault-injected, not hidden).
"""

from __future__ import annotations

import hashlib

import pytest

from graqle.metering.events import PROOF_ANCHORED, MeterEvent, MeterSink


def _key(s: str = "p") -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# ---- happy path ---------------------------------------------------------------


def test_minimal_event_defaults():
    ev = MeterEvent(idempotency_key=_key())
    assert ev.idempotency_key == _key()
    assert ev.edition == "community"
    assert ev.unit == PROOF_ANCHORED
    assert ev.count == 1
    assert isinstance(ev.ts, str) and ev.ts  # auto-set ISO timestamp
    assert ev.metadata == {}


def test_event_is_frozen():
    ev = MeterEvent(idempotency_key=_key())
    with pytest.raises(Exception):  # FrozenInstanceError
        ev.edition = "studio"  # type: ignore[misc]


def test_metadata_is_defensively_copied():
    md = {"batch_id": "b1"}
    ev = MeterEvent(idempotency_key=_key(), metadata=md)
    md["batch_id"] = "MUTATED"
    assert ev.metadata == {"batch_id": "b1"}  # event owns its own copy


def test_to_dict_roundtrip_shape():
    ev = MeterEvent(idempotency_key=_key(), edition="studio", metadata={"x": 1})
    d = ev.to_dict()
    assert d == {
        "idempotency_key": _key(),
        "edition": "studio",
        "unit": PROOF_ANCHORED,
        "count": 1,
        "ts": ev.ts,
        "metadata": {"x": 1},
    }
    # to_dict copies metadata too (mutating the returned dict must not touch event)
    d["metadata"]["x"] = 99
    assert ev.metadata == {"x": 1}


def test_explicit_count_and_ts():
    ev = MeterEvent(idempotency_key=_key(), count=3, ts="2026-05-31T00:00:00+00:00")
    assert ev.count == 3
    assert ev.ts == "2026-05-31T00:00:00+00:00"


# ---- validation branches (each one fault-injected) ---------------------------


@pytest.mark.parametrize("bad", ["", None, 123, b"x"])
def test_rejects_bad_idempotency_key(bad):
    with pytest.raises(ValueError, match="idempotency_key"):
        MeterEvent(idempotency_key=bad)  # type: ignore[arg-type]


def test_rejects_non_billable_unit():
    with pytest.raises(ValueError, match="unit must be"):
        MeterEvent(idempotency_key=_key(), unit="verify_at_scale")


@pytest.mark.parametrize("bad", ["", None, 5])
def test_rejects_bad_edition(bad):
    with pytest.raises(ValueError, match="edition"):
        MeterEvent(idempotency_key=_key(), edition=bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [0, -1, "1", 1.0, True])
def test_rejects_bad_count(bad):
    # bool is explicitly excluded even though isinstance(True, int) is True.
    with pytest.raises(ValueError, match="count"):
        MeterEvent(idempotency_key=_key(), count=bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["", None, 0])
def test_rejects_bad_ts(bad):
    with pytest.raises(ValueError, match="ts"):
        MeterEvent(idempotency_key=_key(), ts=bad)  # type: ignore[arg-type]


def test_rejects_non_dict_metadata():
    with pytest.raises(ValueError, match="metadata"):
        MeterEvent(idempotency_key=_key(), metadata=["not", "a", "dict"])  # type: ignore[arg-type]


# ---- MeterSink Protocol -------------------------------------------------------


def test_metersink_is_runtime_checkable():
    class Good:
        def record(self, event): ...

    class Bad:
        def nope(self): ...

    assert isinstance(Good(), MeterSink)
    assert not isinstance(Bad(), MeterSink)
