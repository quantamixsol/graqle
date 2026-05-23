"""Tests for the additive trace_capture observer hook (v0.59.0 PR-5, R25-EU01).

The PR-5 hook adds ONE optional ``observer`` param to TraceCapture, invoked
best-effort AFTER the trace is persisted. These tests verify: (1) the observer
sees the finalized trace, (2) it runs after persist, (3) an observer exception
never breaks the trace path or suppresses a handler exception, and (4) the
default (no observer) preserves prior behaviour.
"""

from __future__ import annotations

import asyncio

import pytest

from graqle.governance.trace_capture import TraceCapture


class _MemStore:
    """Minimal async trace store capturing appended traces in order."""

    def __init__(self):
        self.appended = []

    async def append(self, trace):
        self.appended.append(trace)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _capture(observer=None, store=None, raise_in_handler=False):
    tc = TraceCapture("graq_reason", {"question": "hello"}, store=store, observer=observer)
    async with tc:
        tc.set_result('{"confidence": 0.9}')
        if raise_in_handler:
            raise ValueError("handler boom")
    return tc


def test_observer_receives_finalized_trace():
    seen = []
    tc = _run(_capture(observer=seen.append))
    assert len(seen) == 1
    assert seen[0] is tc.trace
    from graqle.governance.trace_schema import Outcome

    assert tc.trace.outcome == Outcome.SUCCESS  # finalized before observer ran


def test_observer_runs_after_persist():
    """The observer must see the trace only after it is appended to the store."""
    store = _MemStore()
    order = []

    def observer(trace):
        order.append("observed")
        assert store.appended == [trace]  # persist already happened

    _run(_capture(observer=observer, store=store))
    assert order == ["observed"]
    assert len(store.appended) == 1


def test_observer_exception_does_not_break_trace_path():
    store = _MemStore()

    def boom(_trace):
        raise RuntimeError("observer boom")

    # Must complete normally despite the observer raising.
    tc = _run(_capture(observer=boom, store=store))
    assert len(store.appended) == 1  # trace still persisted
    assert tc.trace is not None


def test_observer_exception_does_not_suppress_handler_exception():
    def boom(_trace):
        raise RuntimeError("observer boom")

    # The handler's ValueError must still propagate (observer runs in __aexit__,
    # which returns False and never suppresses).
    with pytest.raises(ValueError, match="handler boom"):
        _run(_capture(observer=boom, raise_in_handler=True))


def test_no_observer_is_a_noop():
    """Default (observer=None) preserves prior behaviour: trace persisted, no error."""
    store = _MemStore()
    tc = _run(_capture(observer=None, store=store))
    assert len(store.appended) == 1
    assert tc.trace is not None


def test_observer_still_called_when_no_store():
    """Observer fires even without a store (it observes the in-memory trace)."""
    seen = []
    _run(_capture(observer=seen.append, store=None))
    assert len(seen) == 1
