"""SDK-B3 — Fast-path tests (21 cases, injection-based)."""
from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from graqle.activation import ActivationLayer, TierMode
from graqle.activation.default_providers import (
    FakeChunkScoringProvider,
    FakeSafetyGateProvider,
    FakeSubgraphActivationProvider,
)
from graqle.activation.providers import SafetyVerdict
from graqle.chat.agent_loop import ChatAgentLoop, TurnResult
from graqle.chat.fast_path import (
    FastPathIntent,
    classify_intent,
    is_fast_path_candidate,
    is_path_safe,
)
from graqle.chat.permission_manager import TurnState
from graqle.chat.streaming import ChatEventType


# ═══════════════════════════════════════════════════════════════════════════
# flag defaults (CI guard)
# ═══════════════════════════════════════════════════════════════════════════

def test_fast_path_flag_defaults_on():
    """fast_path_enabled MUST default True at construction.

    Guards against the same flag-forgotten failure mode that motivated
    the v0.4.15 incident. If a PR flips this to False, CI fails
    loudly with a message explaining why.
    """
    sig = inspect.signature(ChatAgentLoop.__init__)
    default = sig.parameters["fast_path_enabled"].default
    assert default is True, (
        "fast_path_enabled regression violated: fast_path_enabled must default to True. "
        "If you have a legitimate reason to flip this, update the test "
        "and this test with the rationale."
    )


def test_env_var_override_disables_fast_path(monkeypatch):
    """GRAQLE_FAST_PATH_ENABLED=0 must override constructor default ON."""
    monkeypatch.setenv("GRAQLE_FAST_PATH_ENABLED", "0")
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
    assert loop.fast_path_enabled is False


# ═══════════════════════════════════════════════════════════════════════════
# classify_intent — positive cases
# ═══════════════════════════════════════════════════════════════════════════

def test_classify_create_file_intent():
    result = classify_intent("create file notes.md")
    assert result is not None
    assert result.kind == "file_create"
    assert result.target_path == "notes.md"


def test_classify_create_with_content():
    result = classify_intent("create file todo.md with content: buy milk")
    assert result is not None
    assert result.target_path == "todo.md"
    assert "buy milk" in result.content_hint


def test_classify_polite_phrasing():
    result = classify_intent("please create a new file called plan.md")
    assert result is not None
    assert result.target_path == "plan.md"


# ═══════════════════════════════════════════════════════════════════════════
# classify_intent — rejection cases
# ═══════════════════════════════════════════════════════════════════════════

def test_classify_rejects_refactor():
    assert classify_intent("refactor the authentication module") is None


def test_classify_rejects_edit():
    assert classify_intent("edit main.py to add logging") is None


def test_classify_rejects_ambiguous():
    assert classify_intent("do something with a file maybe") is None


def test_classify_rejects_negation():
    assert classify_intent("don't create file foo.md") is None
    assert classify_intent("never create the backup file") is None


def test_classify_rejects_multiple_path_tokens():
    # Two .md tokens → ambiguous
    assert classify_intent("create file foo.md and bar.md together") is None


def test_classify_rejects_non_string():
    assert classify_intent(None) is None
    assert classify_intent(123) is None
    assert classify_intent("") is None
    assert classify_intent("   ") is None


# ═══════════════════════════════════════════════════════════════════════════
# is_path_safe — containment + blocklist
# ═══════════════════════════════════════════════════════════════════════════

def test_path_safety_accepts_simple_relative(tmp_path):
    assert is_path_safe("notes.md", tmp_path) is True


def test_path_safety_rejects_dotdot_traversal(tmp_path):
    assert is_path_safe("../../etc/passwd", tmp_path) is False


def test_path_safety_rejects_absolute_outside_cwd(tmp_path):
    # /etc/* is absolute AND in blocklist
    assert is_path_safe("/etc/something.conf", tmp_path) is False


def test_path_safety_rejects_ssh_magic(tmp_path):
    # Build a target that resolves inside cwd but matches blocked fragment
    (tmp_path / ".ssh").mkdir(exist_ok=True)
    assert is_path_safe(".ssh/authorized_keys", tmp_path) is False


def test_path_safety_rejects_code_file(tmp_path):
    # CG-03 handles these; fast-path must reject
    assert is_path_safe("utils.py", tmp_path) is False
    assert is_path_safe("server.ts", tmp_path) is False


def test_path_safety_rejects_none_and_empty(tmp_path):
    assert is_path_safe(None, tmp_path) is False
    assert is_path_safe("", tmp_path) is False
    assert is_path_safe("   ", tmp_path) is False
    assert is_path_safe("notes.md", None) is False


# ═══════════════════════════════════════════════════════════════════════════
# is_fast_path_candidate — combined classifier + safety
# ═══════════════════════════════════════════════════════════════════════════

def test_fast_path_candidate_accepts_safe_create(tmp_path):
    result = is_fast_path_candidate("create file notes.md", cwd=tmp_path)
    assert result is not None
    assert result.target_path == "notes.md"


def test_fast_path_candidate_rejects_unsafe_target(tmp_path):
    result = is_fast_path_candidate("create file ../../etc/passwd", cwd=tmp_path)
    assert result is None


def test_fast_path_candidate_rejects_non_create(tmp_path):
    result = is_fast_path_candidate("refactor the auth module", cwd=tmp_path)
    assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# ChatAgentLoop integration — the real wiring
# ═══════════════════════════════════════════════════════════════════════════

def _make_loop(tmp_path, tier=TierMode.ADVISORY, safety_score=1.0,
               should_block=False, pre_reason=True, fast_path=True):
    """Build a minimal ChatAgentLoop with injectable providers."""
    layer = ActivationLayer(
        FakeChunkScoringProvider(),
        FakeSafetyGateProvider(
            SafetyVerdict(score=safety_score, should_block=should_block,
                          reason="unsafe" if should_block else "ok"),
        ),
        FakeSubgraphActivationProvider(),
        tier_mode=tier,
    )

    tcg_mock = MagicMock()
    activation_mock = MagicMock()
    activation_mock.intent_label = "file_create"
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
        activation_layer=layer,
        pre_reason_activation_enabled=pre_reason,
        fast_path_enabled=fast_path,
        fast_path_cwd=tmp_path,
    )
    loop.ledger = None
    return loop


def test_fast_path_happy_path_returns_completed_turn(tmp_path):
    loop = _make_loop(tmp_path)
    result = asyncio.run(
        loop.run_turn(turn_id="t1", user_message="create file notes.md")
    )
    assert isinstance(result, TurnResult)
    assert result.state == TurnState.COMPLETED
    assert (tmp_path / "notes.md").exists()
    # No tool_executions because we bypassed the LLM loop
    assert result.tool_executions == []


def test_fast_path_advisory_tier_still_writes(tmp_path):
    """ADVISORY tier + DRACE flagged: upgrade chip emitted, but fast-path still runs."""
    loop = _make_loop(tmp_path, tier=TierMode.ADVISORY,
                      safety_score=0.2, should_block=True)
    result = asyncio.run(
        loop.run_turn(turn_id="t2", user_message="create file memo.md")
    )
    # Advisory mode: turn completes (fast-path OR full pipeline continues).
    # In this case fast-path takes it.
    assert result.state == TurnState.COMPLETED
    assert (tmp_path / "memo.md").exists()


def test_fast_path_respects_drace_block_in_enforced_tier(tmp_path):
    """ENFORCED + should_block → activation layer raises, Step 3.5 returns FAILED.

    Fast-path (Step 3.75) MUST NOT execute. No file must be written.
    """
    loop = _make_loop(tmp_path, tier=TierMode.ENFORCED,
                      safety_score=0.2, should_block=True)
    result = asyncio.run(
        loop.run_turn(turn_id="t3", user_message="create file unsafe.md")
    )
    assert result.state == TurnState.FAILED
    # Critical invariant: no file written
    assert not (tmp_path / "unsafe.md").exists()


def test_fast_path_skipped_when_flag_off(tmp_path, monkeypatch):
    """fast_path_enabled=False → falls through to Step 4 (the llm_driver chain)."""
    loop = _make_loop(tmp_path, fast_path=False)
    # With fast_path disabled, the run_turn enters Step 4 with a mocked
    # llm_driver that doesn't support next_tool. The call will raise or
    # return a default, which is fine — what we care about is: no file.
    try:
        asyncio.run(
            loop.run_turn(turn_id="t4", user_message="create file skip.md")
        )
    except Exception:
        pass  # the minimal loop may fail in Step 4; we only assert no file
    assert not (tmp_path / "skip.md").exists()


def test_fast_path_skipped_when_target_exists(tmp_path):
    """TOCTOU safety: if target exists, fast-path must not overwrite."""
    (tmp_path / "existing.md").write_text("original")
    loop = _make_loop(tmp_path)
    try:
        asyncio.run(
            loop.run_turn(turn_id="t5", user_message="create file existing.md")
        )
    except Exception:
        pass  # full pipeline may fail with stubs; that's expected fallthrough
    # Must NOT have overwritten
    assert (tmp_path / "existing.md").read_text() == "original"


def test_blocked_activation_never_reaches_fast_path(tmp_path):
    """BLOCKER 2 regression: blocked activation must never trigger fast-path."""
    loop = _make_loop(tmp_path, tier=TierMode.ENFORCED,
                      safety_score=0.1, should_block=True)
    result = asyncio.run(
        loop.run_turn(turn_id="t6", user_message="create file trojan.md")
    )
    # Turn is FAILED via Step 3.5 blocked path, NOT Step 3.75
    assert result.state == TurnState.FAILED
    assert not (tmp_path / "trojan.md").exists()
