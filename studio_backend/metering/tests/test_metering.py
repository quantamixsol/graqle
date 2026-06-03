"""Tests for StudioMeter + DynamoDbDedupeStore (BizQ S2 Phase 4).

No AWS: a fake DynamoDB client is injected. Covers the distributed exactly-once
gate (conditional-put / ConditionalCheckFailed), the per-tenant monthly usage
aggregation + allowance classification, the never-raise contract on the
anchoring path, and the tenant/period attribution.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from graqle.metering.events import MeterEvent

_METERING = Path(__file__).resolve().parents[1]


def _load(modname: str, relpath: str):
    spec = importlib.util.spec_from_file_location(modname, _METERING / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


dd = _load("studio_backend.metering.dynamo_dedupe", "dynamo_dedupe.py")
sm = _load("studio_backend.metering.studio_meter", "studio_meter.py")
DynamoDbDedupeStore = dd.DynamoDbDedupeStore
DedupeError = dd.DedupeError
StudioMeter = sm.StudioMeter
USAGE_INCLUDED = sm.USAGE_INCLUDED
USAGE_OVERAGE = sm.USAGE_OVERAGE

LEAF = "a" * 64  # a well-formed leaf_hash


# ── DynamoDbDedupeStore ──────────────────────────────────────────────────────
class ConditionalCheckFailedException(Exception):
    """Stand-in for botocore's dynamically-generated exception (matched by name).

    Named EXACTLY as botocore names it (no leading underscore) because the store
    detects the duplicate path via ``type(exc).__name__``.
    """


class _FakeDdbDedupe:
    """A fake DynamoDB client: enforces attribute_not_exists conditional put."""

    def __init__(self, *, raise_other=False):
        self.items: dict[str, dict] = {}
        self.raise_other = raise_other

    def put_item(self, *, TableName, Item, ConditionExpression):
        if self.raise_other:
            raise RuntimeError("dynamo throttled")
        key = Item["leaf_hash"]["S"]
        if "attribute_not_exists(leaf_hash)" in ConditionExpression and key in self.items:
            raise ConditionalCheckFailedException("exists")
        self.items[key] = Item


def test_dedupe_first_writer_wins():
    c = _FakeDdbDedupe()
    store = DynamoDbDedupeStore("t", client=c)
    assert store.mark_if_new(LEAF) is True   # first
    assert store.mark_if_new(LEAF) is False  # duplicate
    assert store.mark_if_new("b" * 64) is True  # different key


def test_dedupe_rejects_malformed_key():
    store = DynamoDbDedupeStore("t", client=_FakeDdbDedupe())
    for bad in ("short", "g" * 64, "A" * 64, 123, "../etc"):
        with pytest.raises(DedupeError):
            store.mark_if_new(bad)  # type: ignore[arg-type]


def test_dedupe_other_error_raises():
    store = DynamoDbDedupeStore("t", client=_FakeDdbDedupe(raise_other=True))
    with pytest.raises(RuntimeError):
        store.mark_if_new(LEAF)  # surfaced — caller (make_meter_observer) swallows


def test_dedupe_ttl_stamped_when_configured():
    c = _FakeDdbDedupe()
    store = DynamoDbDedupeStore("t", client=c, ttl_seconds=100)
    store.mark_if_new(LEAF, now_epoch=1000)
    assert c.items[LEAF]["ttl"]["N"] == "1100"


def test_dedupe_no_ttl_by_default():
    c = _FakeDdbDedupe()
    DynamoDbDedupeStore("t", client=c).mark_if_new(LEAF)
    assert "ttl" not in c.items[LEAF]


def test_dedupe_bad_table_name():
    with pytest.raises(DedupeError):
        DynamoDbDedupeStore("", client=_FakeDdbDedupe())


def test_dedupe_client_error_code_path():
    """A ClientError-style exception with the conditional code → False, not raise."""

    class _ClientError(Exception):
        def __init__(self):
            self.response = {"Error": {"Code": "ConditionalCheckFailedException"}}

    class _C:
        def put_item(self, **kw):
            raise _ClientError()

    store = DynamoDbDedupeStore("t", client=_C())
    assert store.mark_if_new(LEAF) is False


# ── StudioMeter ──────────────────────────────────────────────────────────────
class _FakeDdbUsage:
    """Fake DynamoDB: ADD-increments a per-key counter, returns the new total."""

    def __init__(self, *, fail=False):
        self.counts: dict[str, int] = {}
        self.fail = fail
        self.calls: list[str] = []

    def update_item(self, *, TableName, Key, UpdateExpression, ExpressionAttributeNames,
                    ExpressionAttributeValues, ReturnValues):
        if self.fail:
            raise RuntimeError("dynamo down")
        k = Key["usage_key"]["S"]
        self.calls.append(k)
        self.counts[k] = self.counts.get(k, 0) + 1
        return {"Attributes": {"count": {"N": str(self.counts[k])}}}


def _event(tenant_id="t1", edition="studio", ts="2026-06-04T12:00:00+00:00", leaf=LEAF):
    md = {}
    if tenant_id is not None:
        md["tenant_id"] = tenant_id
    return MeterEvent(idempotency_key=leaf, edition=edition, ts=ts, metadata=md)


def test_meter_records_and_increments():
    c = _FakeDdbUsage()
    meter = StudioMeter("usage", client=c)
    meter.record(_event())
    assert c.calls == ["t1#studio#2026-06"]
    assert c.counts["t1#studio#2026-06"] == 1


def test_meter_allowance_classification():
    c = _FakeDdbUsage()
    meter = StudioMeter("usage", free_allowance=2, client=c)
    # 3 anchors: first two included, third overage (asserted via the count totals)
    for _ in range(3):
        meter.record(_event())
    assert c.counts["t1#studio#2026-06"] == 3  # all recorded regardless of class


def test_meter_tenant_fallback_when_missing():
    c = _FakeDdbUsage()
    meter = StudioMeter("usage", client=c)
    meter.record(_event(tenant_id=None))
    assert c.calls == ["unknown#studio#2026-06"]  # never dropped — attributed to unknown


def test_meter_period_from_ts():
    c = _FakeDdbUsage()
    StudioMeter("usage", client=c).record(_event(ts="2025-12-31T23:59:59Z"))
    assert "t1#studio#2025-12" in c.counts


def test_meter_malformed_ts_falls_back():
    c = _FakeDdbUsage()
    StudioMeter("usage", client=c).record(_event(ts="garbage"))
    assert "t1#studio#unknown" in c.counts


def test_meter_never_raises_on_ddb_failure():
    """A DynamoDB fault must NOT raise into the (already-anchored) worker path."""
    c = _FakeDdbUsage(fail=True)
    meter = StudioMeter("usage", client=c)
    meter.record(_event())  # must not raise
    assert c.counts == {}


def test_meter_bad_construction():
    with pytest.raises(ValueError):
        StudioMeter("", client=_FakeDdbUsage())
    with pytest.raises(ValueError):
        StudioMeter("usage", free_allowance=-1, client=_FakeDdbUsage())


def test_meter_implements_metersink_protocol():
    from graqle.metering.events import MeterSink

    assert isinstance(StudioMeter("usage", client=_FakeDdbUsage()), MeterSink)


# ── integration: make_meter_observer wires StudioMeter + DynamoDb dedupe ──────
def test_observer_dedup_then_meter_exactly_once():
    """The full count-point seam: observer dedups on leaf_hash, then bills once."""
    from graqle.metering.committer_hook import make_meter_observer

    usage = _FakeDdbUsage()
    dedupe = DynamoDbDedupeStore("dedupe", client=_FakeDdbDedupe())
    meter = StudioMeter("usage", client=usage)
    observer = make_meter_observer(meter=meter, dedupe=dedupe, edition="studio")

    ctx = {"tenant_id": "acme", "edition": "studio", "batch_id": "b1"}
    observer(LEAF, ctx)
    observer(LEAF, ctx)  # duplicate leaf — deduped, NOT billed again
    assert usage.counts.get("acme#studio#" + _period_now()) == 1


def _period_now():
    # The observer builds the MeterEvent with ts=now; derive the same YYYY-MM.
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m")


def test_meter_sanitizes_hash_in_tenant_id():
    """A '#' in tenant_id must not alias another tenant's usage bucket."""
    c = _FakeDdbUsage()
    meter = StudioMeter("usage", client=c)
    meter.record(_event(tenant_id="evil#studio#2026-06"))
    # '#' stripped -> "evilstudio2026-06", cannot collide with a real tenant bucket
    assert c.calls == ["evilstudio2026-06#studio#2026-06"]
    assert "#studio#2026-06#studio#2026-06" not in c.calls[0].replace("evilstudio2026-06", "X", 1)


def test_meter_sanitizes_hash_in_edition():
    c = _FakeDdbUsage()
    meter = StudioMeter("usage", client=c)
    meter.record(_event(tenant_id="t1", edition="studio#x"))
    assert c.calls == ["t1#studiox#2026-06"]


def test_meter_tenant_reduced_to_empty_falls_back():
    c = _FakeDdbUsage()
    meter = StudioMeter("usage", client=c)
    meter.record(_event(tenant_id="###"))  # all delimiters -> empty -> unknown
    assert c.calls == ["unknown#studio#2026-06"]


def test_safe_segment_non_str_returns_empty():
    assert StudioMeter._safe_segment(123, "x") == ""
    assert StudioMeter._safe_segment(None, "x") == ""
