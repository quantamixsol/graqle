"""P4 (ADR-222): the cost meter is ADVISORY ONLY — cost is a story to tell,
never a governance or quality gate.

These tests pin the hard contract:
- `_accumulate_cost_advisory` accumulates per-session spend and surfaces it.
- It attaches a one-time advisory note once over budget.
- It NEVER raises, NEVER removes/blocks payload data, and NEVER returns a
  block/error — it only ADDS observability fields.
- `session_start` resets the meter.
"""

from __future__ import annotations

import types

import pytest

from graqle.plugins.mcp_dev_server import KogniDevServer


def _server() -> KogniDevServer:
    """A server instance with the cost-meter state, without full init I/O."""
    srv = KogniDevServer.__new__(KogniDevServer)
    srv._session_cost_usd = 0.0
    srv._cost_advisory_emitted = False
    # minimal config carrying a cost budget
    srv._config = types.SimpleNamespace(
        cost=types.SimpleNamespace(budget_per_query=0.15)
    )
    return srv


def test_accumulates_cost_across_calls() -> None:
    srv = _server()
    p1 = {"answer": "x", "cost_usd": 0.05}
    srv._accumulate_cost_advisory(p1)
    assert p1["session_cost_usd"] == 0.05
    p2 = {"answer": "y", "estimated_cost_usd": 0.04}
    srv._accumulate_cost_advisory(p2)
    assert p2["session_cost_usd"] == pytest.approx(0.09)


def test_advisory_attached_once_over_budget() -> None:
    srv = _server()
    p1 = {"cost_usd": 0.10}
    srv._accumulate_cost_advisory(p1)
    assert "cost_advisory" not in p1  # under budget
    p2 = {"cost_usd": 0.10}  # now 0.20 >= 0.15 budget
    srv._accumulate_cost_advisory(p2)
    assert "cost_advisory" in p2
    assert "ADVISORY only" in p2["cost_advisory"]
    # one-time: a later call does NOT re-attach
    p3 = {"cost_usd": 0.10}
    srv._accumulate_cost_advisory(p3)
    assert "cost_advisory" not in p3


def test_never_blocks_or_removes_payload() -> None:
    srv = _server()
    payload = {"answer": "important", "data": [1, 2, 3], "cost_usd": 0.99}
    srv._accumulate_cost_advisory(payload)
    # original content untouched; no error/block injected
    assert payload["answer"] == "important"
    assert payload["data"] == [1, 2, 3]
    assert "error" not in payload
    assert "blocked" not in payload
    # only additive observability fields
    assert "session_cost_usd" in payload


def test_never_raises_on_malformed_input() -> None:
    srv = _server()
    # weird/missing cost fields must not raise
    for bad in ({}, {"cost_usd": "nan-ish"}, {"cost_usd": None}, {"total_cost_usd": []}):
        srv._accumulate_cost_advisory(bad)  # must not raise
    # no budget config at all -> still safe
    srv._config = types.SimpleNamespace(cost=None)
    srv._accumulate_cost_advisory({"cost_usd": 999.0})  # no raise, no advisory crash


def test_rejects_non_finite_and_negative_cost() -> None:
    # Security: NaN/Infinity/negative/bool must NOT poison the meter (would
    # silently disable or permanently pin the advisory). They are ignored.
    srv = _server()
    srv._accumulate_cost_advisory({"cost_usd": float("nan")})
    assert srv._session_cost_usd == 0.0
    srv._accumulate_cost_advisory({"cost_usd": float("inf")})
    assert srv._session_cost_usd == 0.0
    srv._accumulate_cost_advisory({"cost_usd": -5.0})
    assert srv._session_cost_usd == 0.0
    srv._accumulate_cost_advisory({"cost_usd": True})  # bool is not a cost
    assert srv._session_cost_usd == 0.0
    # a real value still accumulates after the poison attempts
    srv._accumulate_cost_advisory({"cost_usd": 0.03})
    assert srv._session_cost_usd == pytest.approx(0.03)


def test_zero_or_no_cost_is_safe() -> None:
    srv = _server()
    p = {"answer": "free op"}  # no cost fields
    srv._accumulate_cost_advisory(p)
    assert p["session_cost_usd"] == 0.0
    assert "cost_advisory" not in p
