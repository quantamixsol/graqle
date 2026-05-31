"""Tests for count point 2's observer factory (WS-B B1).

100% statement + branch coverage of graqle/metering/committer_hook.py:
make_meter_observer's emission, dedupe gating, empty-key guard, metadata
passthrough, and the never-raise guarantee.
"""

from __future__ import annotations

import hashlib

from graqle.metering.committer_hook import make_meter_observer
from graqle.metering.dedupe import MeterDedupeStore
from graqle.metering.events import PROOF_ANCHORED, MeterEvent


def _key(s: str = "p") -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class _CapMeter:
    def __init__(self):
        self.events: list[MeterEvent] = []

    def record(self, event):
        self.events.append(event)


def test_observer_bills_each_anchored_leaf(tmp_path):
    cap = _CapMeter()
    obs = make_meter_observer(meter=cap, dedupe=MeterDedupeStore(tmp_path), edition="studio")
    obs(_key("a"), {"batch_id": "b1", "rekor_log_index": 5})
    obs(_key("b"), {"batch_id": "b1", "rekor_log_index": 5})
    assert len(cap.events) == 2
    assert all(e.unit == PROOF_ANCHORED and e.edition == "studio" for e in cap.events)
    assert cap.events[0].metadata == {"batch_id": "b1", "rekor_log_index": 5}


def test_observer_dedupes_within_path(tmp_path):
    cap = _CapMeter()
    obs = make_meter_observer(meter=cap, dedupe=MeterDedupeStore(tmp_path))
    obs(_key("a"), {})
    obs(_key("a"), {})  # same leaf re-anchored / retry => no-op
    assert len(cap.events) == 1


def test_observer_empty_key_is_noop(tmp_path):
    cap = _CapMeter()
    obs = make_meter_observer(meter=cap, dedupe=MeterDedupeStore(tmp_path))
    obs("", {})
    obs(None, {})  # type: ignore[arg-type]
    assert cap.events == []


def test_observer_non_dict_context_coerced_to_empty(tmp_path):
    cap = _CapMeter()
    obs = make_meter_observer(meter=cap, dedupe=MeterDedupeStore(tmp_path))
    obs(_key("a"), None)
    obs(_key("b"), "not-a-dict")  # type: ignore[arg-type]
    assert cap.events[0].metadata == {} and cap.events[1].metadata == {}


def test_observer_defaults_to_local_null_meter(tmp_path):
    # No meter configured => LocalNullMeter, bills nothing but does not raise.
    obs = make_meter_observer(dedupe=MeterDedupeStore(tmp_path))
    obs(_key("a"), {})  # no exception


def test_observer_no_dedupe_bills_each_call():
    cap = _CapMeter()
    obs = make_meter_observer(meter=cap)  # dedupe=None
    obs(_key("a"), {})
    obs(_key("a"), {})
    assert len(cap.events) == 2


def test_observer_never_raises_on_meter_fault(tmp_path):
    class _Boom:
        def record(self, event):
            raise RuntimeError("meter down")

    obs = make_meter_observer(meter=_Boom(), dedupe=MeterDedupeStore(tmp_path))
    obs(_key("a"), {})  # must NOT raise


def test_observer_never_raises_on_dedupe_fault():
    class _BoomStore:
        def mark_if_new(self, key):
            raise OSError("disk full")

    cap = _CapMeter()
    obs = make_meter_observer(meter=cap, dedupe=_BoomStore())
    obs(_key("a"), {})  # must NOT raise
    assert cap.events == []
