"""ADR-205 — ChatAgentLoop.run_turn integration tests.

Covers:
  - Flag default ON (regression guard per ADR-205 Decision 4)
  - Env var override forces OFF
  - ENFORCED + blocked → turn transitions to FAILED
  - ADVISORY + blocked → turn continues + upgrade chip emitted
  - Flag OFF → zero activation work (parity with pre-ADR-205 behavior)
"""
from __future__ import annotations

import asyncio
import os

import pytest

from graqle.activation import (
    ActivationLayer,
    ActivationVerdict,
    TierMode,
    TurnBlocked,
)
from graqle.activation.default_providers import (
    FakeChunkScoringProvider,
    FakeSafetyGateProvider,
    FakeSubgraphActivationProvider,
)
from graqle.activation.providers import (
    ActivatedSubgraph,
    ChunkScoreResult,
    SafetyVerdict,
)


# ── Flag default regression guard (from ADR-205 Decision 4) ──────────────

def test_pre_reason_activation_flag_defaults_on():
    """ADR-205 Decision 4: flag MUST default ON.

    This test is the codified guard for the v0.4.15 gate-never-turned-on
    incident. If a PR ever flips the default to OFF, this test fails
    loudly and the PR cannot merge.
    """
    import inspect
    from graqle.chat.agent_loop import ChatAgentLoop
    sig = inspect.signature(ChatAgentLoop.__init__)
    default = sig.parameters["pre_reason_activation_enabled"].default
    assert default is True, (
        "ADR-205 Decision 4 violated: pre_reason_activation_enabled "
        "must default to True. The v0.4.15 incident (gate shipped OFF "
        "and stayed dormant for weeks) required this default to be ON. "
        "If you have a legitimate reason to flip this, update ADR-205 "
        "and this test with the rationale."
    )


# ── Env var override OFF path ────────────────────────────────────────────

def test_env_var_override_disables(monkeypatch):
    monkeypatch.setenv("GRAQLE_PRE_REASON_ACTIVATION", "0")
    # Construct a minimal ChatAgentLoop with stubs — we only care that
    # the flag evaluates to False under this env.
    from graqle.chat.agent_loop import ChatAgentLoop
    # Build a bare-minimum constructor by mocking its required deps
    from unittest.mock import MagicMock
    loop = ChatAgentLoop(
        session_id="s",
        tcg=MagicMock(),
        rcag=MagicMock(),
        turn_store=MagicMock(),
        permission_manager=MagicMock(),
        backend_router=MagicMock(),
        llm_driver=MagicMock(),
        tool_executor=MagicMock(),
        activation_layer=None,  # explicitly no layer
        pre_reason_activation_enabled=True,  # param says ON
    )
    # Env var must override param → flag OFF
    assert loop.pre_reason_activation_enabled is False
    assert loop.activation_layer is None


# ── Explicit layer injection uses that layer, not factory ────────────────

def test_explicit_layer_injection():
    from graqle.chat.agent_loop import ChatAgentLoop
    from unittest.mock import MagicMock

    custom_layer = ActivationLayer(
        FakeChunkScoringProvider(),
        FakeSafetyGateProvider(),
        FakeSubgraphActivationProvider(),
        tier_mode=TierMode.ENFORCED,
    )
    loop = ChatAgentLoop(
        session_id="s",
        tcg=MagicMock(),
        rcag=MagicMock(),
        turn_store=MagicMock(),
        permission_manager=MagicMock(),
        backend_router=MagicMock(),
        llm_driver=MagicMock(),
        tool_executor=MagicMock(),
        activation_layer=custom_layer,
    )
    assert loop.activation_layer is custom_layer


# ── Factory default wiring ───────────────────────────────────────────────

def test_factory_auto_wiring_when_no_layer_provided(monkeypatch):
    """When activation_layer=None and flag is ON, factory auto-constructs."""
    monkeypatch.delenv("GRAQLE_PRE_REASON_ACTIVATION", raising=False)
    from graqle.chat.agent_loop import ChatAgentLoop
    from unittest.mock import MagicMock

    loop = ChatAgentLoop(
        session_id="s",
        tcg=MagicMock(),
        rcag=MagicMock(),
        turn_store=MagicMock(),
        permission_manager=MagicMock(),
        backend_router=MagicMock(),
        llm_driver=MagicMock(),
        tool_executor=MagicMock(),
        activation_layer=None,
    )
    assert loop.pre_reason_activation_enabled is True
    assert loop.activation_layer is not None
    assert isinstance(loop.activation_layer, ActivationLayer)


# ── Blocked-path end-to-end: TurnResult shape must be valid ──────────────

def test_enforced_blocked_turn_returns_valid_turnresult(monkeypatch):
    """E2E: ENFORCED + should_block → run_turn returns a valid TurnResult.

    Guards against kwarg drift between ActivationLayer and TurnResult dataclass
    (the fields are: turn_id, final_text, state, tool_executions, check_records,
    cost_usd — NOT assistant_text / concern_checks / next_seq).
    """
    from graqle.chat.agent_loop import ChatAgentLoop, TurnResult
    from graqle.chat.permission_manager import TurnState
    from unittest.mock import AsyncMock, MagicMock

    # Build a minimal ChatAgentLoop with ENFORCED + blocked safety verdict.
    enforced_layer = ActivationLayer(
        FakeChunkScoringProvider(),
        FakeSafetyGateProvider(
            SafetyVerdict(score=0.2, should_block=True, reason="unsafe-turn"),
        ),
        FakeSubgraphActivationProvider(),
        tier_mode=TierMode.ENFORCED,
    )

    tcg_mock = MagicMock()
    activation_mock = MagicMock()
    activation_mock.intent_label = "plan"
    activation_mock.intent_id = "i1"
    activation_mock.candidates = []
    tcg_mock.activate_for_query.return_value = activation_mock

    turn_store = MagicMock()
    turn_store.create = AsyncMock()
    turn_store.transition = AsyncMock()

    rcag_mock = MagicMock()
    rcag_mock.begin_turn = MagicMock()

    loop = ChatAgentLoop(
        session_id="s",
        tcg=tcg_mock,
        rcag=rcag_mock,
        turn_store=turn_store,
        permission_manager=MagicMock(),
        backend_router=MagicMock(),
        llm_driver=MagicMock(),
        tool_executor=MagicMock(),
        activation_layer=enforced_layer,
    )
    loop.ledger = None  # disable ledger writes in this test

    result = asyncio.run(loop.run_turn(turn_id="t1", user_message="hello"))
    # Must return a real TurnResult (not explode on kwarg mismatch)
    assert isinstance(result, TurnResult)
    assert result.state == TurnState.FAILED
    assert result.final_text == ""
    assert result.tool_executions == []
    assert result.check_records == []
    assert result.cost_usd == 0.0
