"""P5b (ADR-222): EU AI Act gate enforcement (CG-EU-AIA) tests.

Two layers:
1. `evaluate_gate` — the pure decision function (narrow scope, fail-safe).
2. `KogniDevServer._eu_ai_act_gate` — the gate-side wiring (off by default,
   latch-driven, fail-safe-for-usability).

Hard contract: cost/quality are never gated; only AIA-relevant WRITES, only when
the latch is enabled; reads never gated; the audited override always available;
any phase error -> allow (never block routine work).
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from graqle.compliance.eu_ai_act_latch import (
    AIA_GATED_TOOLS,
    EuAiActLatch,
    LatchState,
    evaluate_gate,
)

_T0 = "2026-06-09T00:00:00Z"


def _state(enabled, mode=None, risk="high") -> LatchState:
    return LatchState(
        enabled=enabled, mode=mode, risk_class=risk if enabled else None,
        event_count=1 if enabled else 0, override_count=0,
    )


# ── pure decision function ─────────────────────────────────────────────

def test_disabled_latch_allows_everything():
    d = evaluate_gate(state=_state(False), tool_name="graq_edit",
                      confidence=0.0, threshold=0.75)
    assert d.action == "allow"


def test_read_tool_never_gated_even_when_enabled():
    # narrow scope: only AIA_GATED_TOOLS are evaluated
    for tool in ("graq_reason", "graq_inspect", "graq_plan", "graq_context"):
        d = evaluate_gate(state=_state(True, "blocking"), tool_name=tool,
                          confidence=0.0, threshold=0.75)
        assert d.action == "allow", tool


def test_blocking_below_threshold_blocks_write():
    d = evaluate_gate(state=_state(True, "blocking"), tool_name="graq_edit",
                      confidence=0.40, threshold=0.75)
    assert d.action == "block"
    assert d.envelope["error"] == "CG-EU-AIA_OVERSIGHT"
    assert "override" in d.envelope["remediation"].lower()


def test_blocking_above_threshold_allows_write():
    d = evaluate_gate(state=_state(True, "blocking"), tool_name="graq_edit",
                      confidence=0.95, threshold=0.75)
    assert d.action == "allow"


def test_blocking_unknown_confidence_allows():
    # cannot assert below-threshold -> allow (never block on missing signal)
    d = evaluate_gate(state=_state(True, "blocking"), tool_name="graq_edit",
                      confidence=None, threshold=0.75)
    assert d.action == "allow"


def test_override_justification_allows_blocked_write():
    d = evaluate_gate(state=_state(True, "blocking"), tool_name="graq_edit",
                      confidence=0.10, threshold=0.75,
                      override_justification="reviewed by harish")
    assert d.action == "allow"


def test_advisory_mode_advises_never_blocks():
    d = evaluate_gate(state=_state(True, "advisory", risk="limited"),
                      tool_name="graq_write", confidence=0.0, threshold=0.75)
    assert d.action == "advise"
    assert d.advisory and "advisory" in d.advisory.lower()


def test_tampered_unknown_mode_treated_as_blocking():
    # mode None on an enabled latch -> strictest (blocking)
    st = LatchState(enabled=True, mode=None, risk_class="high",
                    event_count=1, override_count=0, tampered=True)
    d = evaluate_gate(state=st, tool_name="graq_edit", confidence=0.1, threshold=0.75)
    assert d.action == "block"


def test_gated_tools_are_writes_only():
    assert "graq_edit" in AIA_GATED_TOOLS
    assert "graq_write" in AIA_GATED_TOOLS
    assert "graq_generate" in AIA_GATED_TOOLS
    assert "graq_reason" not in AIA_GATED_TOOLS
    assert "graq_read" not in AIA_GATED_TOOLS


# ── gate-side wiring (_eu_ai_act_gate) ─────────────────────────────────

def _server_with_latch(tmp_path: Path, *, enabled_cfg: bool, threshold=0.75):
    from graqle.plugins.mcp_dev_server import KogniDevServer

    srv = KogniDevServer.__new__(KogniDevServer)
    srv._project_root = str(tmp_path)
    gov = types.SimpleNamespace(
        eu_ai_act=types.SimpleNamespace(enabled=enabled_cfg, mode="blocking", risk_class="high"),
        human_review_required_threshold=threshold,
    )
    srv._config = types.SimpleNamespace(governance=gov)
    return srv


def test_gate_inert_when_config_off(tmp_path):
    # config flag off -> phase inert even if a latch file somehow exists
    srv = _server_with_latch(tmp_path, enabled_cfg=False)
    assert srv._eu_ai_act_gate("graq_edit", {"confidence": 0.1}) is None


def test_gate_inert_when_no_latch(tmp_path):
    # config on but no latch recorded -> inert
    srv = _server_with_latch(tmp_path, enabled_cfg=True)
    assert srv._eu_ai_act_gate("graq_edit", {"confidence": 0.1}) is None


def test_gate_blocks_when_latch_enabled_blocking_low_conf(tmp_path):
    EuAiActLatch(tmp_path).enable(mode="blocking", risk_class="high", ts=_T0)
    srv = _server_with_latch(tmp_path, enabled_cfg=True)
    res = srv._eu_ai_act_gate("graq_edit", {"confidence": 0.30})
    assert res is not None
    action, payload = res
    assert action == "block"
    assert payload["error"] == "CG-EU-AIA_OVERSIGHT"


def test_gate_override_records_and_allows(tmp_path):
    EuAiActLatch(tmp_path).enable(mode="blocking", risk_class="high", ts=_T0)
    srv = _server_with_latch(tmp_path, enabled_cfg=True)
    res = srv._eu_ai_act_gate(
        "graq_edit", {"confidence": 0.30, "eu_aia_override_justification": "human reviewed"},
    )
    assert res is not None
    assert res[0] == "override"
    # the override is recorded in the latch chain (audit trail)
    assert EuAiActLatch(tmp_path).read_state().override_count == 1


def test_gate_allows_high_confidence(tmp_path):
    EuAiActLatch(tmp_path).enable(mode="blocking", risk_class="high", ts=_T0)
    srv = _server_with_latch(tmp_path, enabled_cfg=True)
    assert srv._eu_ai_act_gate("graq_edit", {"confidence": 0.95}) is None


def test_gate_ignores_out_of_range_confidence(tmp_path):
    # NaN / >1 / <0 confidence -> treated as unknown -> never blocks (Sentinel MINOR)
    EuAiActLatch(tmp_path).enable(mode="blocking", risk_class="high", ts=_T0)
    srv = _server_with_latch(tmp_path, enabled_cfg=True)
    for bad in (float("nan"), 1.5, -0.2, float("inf")):
        assert srv._eu_ai_act_gate("graq_edit", {"confidence": bad}) is None, bad


def test_gate_fail_safe_on_error(tmp_path):
    # a broken config must NOT crash or block — fail safe for usability
    from graqle.plugins.mcp_dev_server import KogniDevServer
    srv = KogniDevServer.__new__(KogniDevServer)
    srv._project_root = str(tmp_path)
    srv._config = types.SimpleNamespace(governance="not-a-namespace")  # broken
    assert srv._eu_ai_act_gate("graq_edit", {"confidence": 0.1}) is None
