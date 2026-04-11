"""TB-F4 tests for graqle.chat.permission_manager.

Covers:
  - TurnState enum + allowed transitions
  - TurnStore CAS contract (success / wrong-state rejection / terminal lockout)
  - TurnBusyError on second create for same session
  - Idempotent resume via tool_result_cache
  - crash_recover tombstones non-terminal turns
  - PermissionManager: GREEN auto-approve, YELLOW/RED prompt+cache
  - Revocation re-prompts on next check
  - Session clear drops cache + pending
"""

# ── graqle:intelligence ──
# module: tests.test_chat.test_permission_manager
# risk: LOW
# dependencies: pytest, asyncio, graqle.chat.permission_manager
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import asyncio

import pytest

from graqle.chat.permission_manager import (
    PermissionDecision,
    PermissionManager,
    TurnBusyError,
    TurnCheckpoint,
    TurnState,
    TurnStore,
)


# ──────────────────────────────────────────────────────────────────────
# TurnState
# ──────────────────────────────────────────────────────────────────────


def test_terminal_states_correct() -> None:
    terminal = TurnState.terminal()
    assert TurnState.COMPLETED in terminal
    assert TurnState.FAILED in terminal
    assert TurnState.CANCELLED in terminal
    assert TurnState.ABANDONED in terminal
    assert TurnState.PENDING not in terminal
    assert TurnState.ACTIVE not in terminal
    assert TurnState.PAUSED not in terminal


def test_non_terminal_states_correct() -> None:
    nt = TurnState.non_terminal()
    assert nt == {TurnState.PENDING, TurnState.ACTIVE, TurnState.PAUSED}


def test_turn_checkpoint_to_dict() -> None:
    cp = TurnCheckpoint(turn_id="t1", session_id="s1", user_message="hi")
    d = cp.to_dict()
    assert d["turn_id"] == "t1"
    assert d["state"] == "pending"


# ──────────────────────────────────────────────────────────────────────
# TurnStore (async)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_turn() -> None:
    store = TurnStore()
    cp = await store.create("t1", "s1", "hello", model_id="anthropic:sonnet")
    assert cp.state == TurnState.PENDING
    assert cp.user_message == "hello"
    assert cp.model_id == "anthropic:sonnet"


@pytest.mark.asyncio
async def test_create_busy_raises() -> None:
    store = TurnStore()
    await store.create("t1", "s1", "first")
    with pytest.raises(TurnBusyError):
        await store.create("t2", "s1", "second")


@pytest.mark.asyncio
async def test_transition_pending_to_active() -> None:
    store = TurnStore()
    await store.create("t1", "s1", "x")
    ok = await store.transition("t1", TurnState.PENDING, TurnState.ACTIVE)
    assert ok is True
    cp = await store.get("t1")
    assert cp is not None
    assert cp.state == TurnState.ACTIVE


@pytest.mark.asyncio
async def test_transition_wrong_expected_state_rejected() -> None:
    store = TurnStore()
    await store.create("t1", "s1", "x")
    # Real state is PENDING; we expect ACTIVE → CAS must reject.
    ok = await store.transition("t1", TurnState.ACTIVE, TurnState.COMPLETED)
    assert ok is False
    cp = await store.get("t1")
    assert cp is not None
    assert cp.state == TurnState.PENDING


@pytest.mark.asyncio
async def test_transition_disallowed_by_state_machine() -> None:
    store = TurnStore()
    await store.create("t1", "s1", "x")
    # PENDING → COMPLETED is not allowed by the state machine.
    ok = await store.transition("t1", TurnState.PENDING, TurnState.COMPLETED)
    assert ok is False


@pytest.mark.asyncio
async def test_terminal_state_locked() -> None:
    store = TurnStore()
    await store.create("t1", "s1", "x")
    await store.transition("t1", TurnState.PENDING, TurnState.ACTIVE)
    await store.transition("t1", TurnState.ACTIVE, TurnState.COMPLETED)
    cp = await store.get("t1")
    assert cp is not None
    assert cp.is_terminal()
    # No outgoing transitions from terminal.
    ok = await store.transition("t1", TurnState.COMPLETED, TurnState.ACTIVE)
    assert ok is False


@pytest.mark.asyncio
async def test_terminal_clears_active_session_slot() -> None:
    store = TurnStore()
    await store.create("t1", "s1", "x")
    await store.transition("t1", TurnState.PENDING, TurnState.ACTIVE)
    await store.transition("t1", TurnState.ACTIVE, TurnState.COMPLETED)
    # Now we should be able to start a new turn for the same session.
    cp = await store.create("t2", "s1", "next")
    assert cp.state == TurnState.PENDING


@pytest.mark.asyncio
async def test_pause_resume_cycle() -> None:
    store = TurnStore()
    await store.create("t1", "s1", "x")
    await store.transition("t1", TurnState.PENDING, TurnState.ACTIVE)
    assert await store.transition("t1", TurnState.ACTIVE, TurnState.PAUSED) is True
    assert await store.transition("t1", TurnState.PAUSED, TurnState.ACTIVE) is True
    cp = await store.get("t1")
    assert cp is not None
    assert cp.state == TurnState.ACTIVE


@pytest.mark.asyncio
async def test_tool_result_cache_idempotent() -> None:
    store = TurnStore()
    await store.create("t1", "s1", "x")
    await store.cache_tool_result("t1", "call_abc", {"answer": 42})
    found, value = await store.get_cached_tool_result("t1", "call_abc")
    assert found is True
    assert value == {"answer": 42}
    miss_found, miss_value = await store.get_cached_tool_result("t1", "call_xyz")
    assert miss_found is False
    assert miss_value is None


@pytest.mark.asyncio
async def test_crash_recover_tombstones_active() -> None:
    store = TurnStore()
    await store.create("t1", "s1", "x")
    await store.transition("t1", TurnState.PENDING, TurnState.ACTIVE)
    await store.create("t2", "s2", "y")  # leave PENDING
    affected = await store.crash_recover()
    assert set(affected) == {"t1", "t2"}
    cp1 = await store.get("t1")
    cp2 = await store.get("t2")
    assert cp1 is not None and cp1.state == TurnState.ABANDONED
    assert cp2 is not None and cp2.state == TurnState.ABANDONED
    assert cp1.exit_reason == "crash_recovery"


@pytest.mark.asyncio
async def test_concurrent_create_serialized() -> None:
    """Two concurrent creates for the same session must serialize:
    one wins, one raises TurnBusyError. Verifies the asyncio.Lock.
    """
    store = TurnStore()
    results: list[Exception | TurnCheckpoint] = []

    async def attempt(turn_id: str) -> None:
        try:
            cp = await store.create(turn_id, "s1", "x")
            results.append(cp)
        except TurnBusyError as exc:
            results.append(exc)

    await asyncio.gather(attempt("a"), attempt("b"))
    successes = [r for r in results if isinstance(r, TurnCheckpoint)]
    busy = [r for r in results if isinstance(r, TurnBusyError)]
    assert len(successes) == 1
    assert len(busy) == 1


# ──────────────────────────────────────────────────────────────────────
# PermissionManager
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_green_auto_approves() -> None:
    pm = PermissionManager()
    decision, pending = await pm.check(
        session_id="s1", tool_name="graq_read",
        resource_scope="repo", tier="GREEN",
    )
    assert decision == PermissionDecision.APPROVE
    assert pending is None


@pytest.mark.asyncio
async def test_yellow_first_call_prompts() -> None:
    pm = PermissionManager()
    decision, pending = await pm.check(
        session_id="s1", tool_name="graq_write",
        resource_scope="repo", tier="YELLOW",
    )
    assert decision == PermissionDecision.PROMPT
    assert pending is not None


@pytest.mark.asyncio
async def test_resolve_caches_decision() -> None:
    pm = PermissionManager()
    decision, pending = await pm.check(
        session_id="s1", tool_name="graq_write",
        resource_scope="repo", tier="YELLOW",
    )
    assert pending is not None
    await pm.resolve(pending, PermissionDecision.APPROVE)
    # Second call: same key auto-approves from cache.
    second_decision, second_pending = await pm.check(
        session_id="s1", tool_name="graq_write",
        resource_scope="repo", tier="YELLOW",
    )
    assert second_decision == PermissionDecision.APPROVE
    assert second_pending is None


@pytest.mark.asyncio
async def test_deny_caches_too() -> None:
    pm = PermissionManager()
    _, pending = await pm.check(
        session_id="s1", tool_name="graq_bash",
        resource_scope="cmd", tier="RED",
    )
    assert pending is not None
    await pm.resolve(pending, PermissionDecision.DENY)
    decision, _ = await pm.check(
        session_id="s1", tool_name="graq_bash",
        resource_scope="cmd", tier="RED",
    )
    assert decision == PermissionDecision.DENY


@pytest.mark.asyncio
async def test_revoke_reprompts() -> None:
    pm = PermissionManager()
    _, pending = await pm.check(
        session_id="s1", tool_name="graq_write",
        resource_scope="repo", tier="YELLOW",
    )
    assert pending is not None
    await pm.resolve(pending, PermissionDecision.APPROVE)
    revoked = await pm.revoke(
        session_id="s1", tool_name="graq_write", resource_scope="repo",
    )
    assert revoked is True
    decision, new_pending = await pm.check(
        session_id="s1", tool_name="graq_write",
        resource_scope="repo", tier="YELLOW",
    )
    assert decision == PermissionDecision.PROMPT
    assert new_pending is not None


@pytest.mark.asyncio
async def test_clear_session_drops_cache() -> None:
    pm = PermissionManager()
    _, p1 = await pm.check(
        session_id="s1", tool_name="graq_write", resource_scope="repo", tier="YELLOW",
    )
    assert p1 is not None
    await pm.resolve(p1, PermissionDecision.APPROVE)
    cleared = await pm.clear_session("s1")
    assert cleared >= 1
    # Next check re-prompts.
    decision, _ = await pm.check(
        session_id="s1", tool_name="graq_write",
        resource_scope="repo", tier="YELLOW",
    )
    assert decision == PermissionDecision.PROMPT


@pytest.mark.asyncio
async def test_resolve_unknown_pending_returns_false() -> None:
    pm = PermissionManager()
    ok = await pm.resolve("nonexistent", PermissionDecision.APPROVE)
    assert ok is False


@pytest.mark.asyncio
async def test_session_isolated_cache() -> None:
    """Approval in session s1 must NOT affect session s2."""
    pm = PermissionManager()
    _, p1 = await pm.check(
        session_id="s1", tool_name="graq_write", resource_scope="repo", tier="YELLOW",
    )
    assert p1 is not None
    await pm.resolve(p1, PermissionDecision.APPROVE)
    decision, _ = await pm.check(
        session_id="s2", tool_name="graq_write", resource_scope="repo", tier="YELLOW",
    )
    assert decision == PermissionDecision.PROMPT
