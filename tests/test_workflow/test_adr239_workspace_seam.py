"""
ADR-239 Stage 2: AutonomousExecutor workspace/test seam.

Verifies the pluggable checkpoint (CheckpointProtocol) + optional test stage
(run_tests) added so the one engine serves both the SDK's git/pytest workflow
AND cloud consumers with a non-git checkpoint and no test stage.

Acceptance criteria (ADR-239):
  AC-239-01  defaults are byte-identical: no checkpoint + run_tests=True
             ⇒ self._diff is a DiffApplicator, existing callers unchanged.
  AC-239-02  run_tests=False ⇒ TEST stage never spawns a subprocess.
  AC-239-03  an injected CheckpointProtocol receives create_stash/rollback,
             not DiffApplicator.
  AC-239-04  no ActionAgentProtocol change (a FILE:-block agent satisfies it).
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from graqle.workflow.action_agent_protocol import ActionAgentProtocol, ExecutionResult
from graqle.workflow.autonomous_executor import AutonomousExecutor, ExecutorConfig
from graqle.workflow.diff_applicator import DiffApplicator
from graqle.workflow.protocols import CheckpointProtocol


# ── Minimal fakes ─────────────────────────────────────────────────────────────

class _FakeAgent:
    """A minimal ActionAgentProtocol impl that emits an opaque (non-diff) payload."""

    async def plan(self, task, context):
        return "plan: " + task

    async def generate_diff(self, task, plan, error_context=None):
        return "FILE: app.py\n<opaque non-diff payload>"

    async def apply(self, diff):
        return ExecutionResult(exit_code=0, stdout="", stderr="", modified_files=["app.py"])

    async def run_tests(self, test_paths=None):
        return ExecutionResult(exit_code=0, stdout="", stderr="", test_passed=True)

    async def rollback(self, token):
        return ExecutionResult(exit_code=0, stdout="", stderr="")


class _RecordingCheckpoint:
    """A CheckpointProtocol that records calls and never touches git."""

    def __init__(self):
        self.stash_calls = []
        self.rollback_calls = []

    def create_stash(self, message="checkpoint"):
        self.stash_calls.append(message)
        return "cloud-token-1"

    def rollback(self, token):
        self.rollback_calls.append(token)
        return ExecutionResult(exit_code=0, stdout="", stderr="")


# ── AC-239-04: no protocol change ─────────────────────────────────────────────

def test_file_block_agent_satisfies_action_agent_protocol():
    assert isinstance(_FakeAgent(), ActionAgentProtocol)


def test_recording_checkpoint_satisfies_checkpoint_protocol():
    assert isinstance(_RecordingCheckpoint(), CheckpointProtocol)


def test_diff_applicator_satisfies_checkpoint_protocol():
    # The default must satisfy the new protocol with zero changes.
    assert isinstance(DiffApplicator("."), CheckpointProtocol)


# ── AC-239-01: defaults byte-identical ────────────────────────────────────────

def test_default_config_uses_diff_applicator():
    ex = AutonomousExecutor(_FakeAgent())
    assert isinstance(ex._diff, DiffApplicator), \
        "no injected checkpoint ⇒ DiffApplicator, exactly as before"


def test_default_config_run_tests_true():
    assert ExecutorConfig().run_tests is True
    assert ExecutorConfig().checkpoint is None


# ── AC-239-03: injected checkpoint is used ────────────────────────────────────

def test_injected_checkpoint_replaces_diff_applicator():
    cp = _RecordingCheckpoint()
    ex = AutonomousExecutor(_FakeAgent(), ExecutorConfig(checkpoint=cp))
    assert ex._diff is cp
    assert not isinstance(ex._diff, DiffApplicator)


# ── AC-239-02: run_tests=False never spawns a subprocess ──────────────────────

def test_run_tests_false_skips_subprocess():
    cp = _RecordingCheckpoint()
    cfg = ExecutorConfig(checkpoint=cp, run_tests=False, max_retries=0)
    ex = AutonomousExecutor(_FakeAgent(), cfg)

    with patch("subprocess.run") as mock_run:
        result = asyncio.run(ex.execute("build a welcome page"))

    assert not mock_run.called, "run_tests=False must never spawn the test subprocess"
    assert result.success, "a no-test build with a clean apply must succeed"
    assert "app.py" in result.modified_files


def test_run_tests_true_default_still_runs_tests():
    """Guard the default path: with run_tests=True the executor DOES call the
    test subprocess (existing behaviour preserved)."""
    cp = _RecordingCheckpoint()
    cfg = ExecutorConfig(checkpoint=cp, run_tests=True, max_retries=0)
    ex = AutonomousExecutor(_FakeAgent(), cfg)

    import subprocess as _sp

    class _Proc:
        returncode = 0
        stdout = "1 passed"
        stderr = ""

    with patch("subprocess.run", return_value=_Proc()) as mock_run:
        asyncio.run(ex.execute("build a thing"))

    assert mock_run.called, "run_tests=True (default) must still run the test subprocess"


# ── AC-239 Stage 2.1: test_via_agent routes TEST through agent.run_tests() ────

def test_test_via_agent_never_spawns_subprocess():
    """test_via_agent=True ⇒ TEST delegates to agent.run_tests(), no subprocess."""
    cp = _RecordingCheckpoint()
    cfg = ExecutorConfig(checkpoint=cp, run_tests=True, test_via_agent=True, max_retries=0)
    ex = AutonomousExecutor(_FakeAgent(), cfg)
    with patch("subprocess.run") as mock_run:
        result = asyncio.run(ex.execute("build a page"))
    assert not mock_run.called, "test_via_agent must not spawn the test subprocess"
    assert result.success


def test_test_via_agent_failure_drives_fix_loop_then_recovers():
    """A failing agent.run_tests() must drive RED_FIX→GENERATE (native repair),
    then a subsequent pass reaches DONE. Proves validation-repair works with no
    pytest — the ADR-239 Stage 3 mechanism."""
    calls = {"tests": 0, "generate": 0}

    class _FlakyAgent(_FakeAgent):
        async def generate_diff(self, task, plan, error_context=None):
            calls["generate"] += 1
            # error_context must be threaded on the repair iteration
            return "FILE: app.py\n<payload>" + (f" (fixing: {error_context})" if error_context else "")

        async def run_tests(self, test_paths=None):
            calls["tests"] += 1
            if calls["tests"] == 1:
                # first validation fails → RED_FIX
                return ExecutionResult(exit_code=1, stdout="", stderr="validation: bad output",
                                       test_passed=False)
            # second passes → DONE
            return ExecutionResult(exit_code=0, stdout="ok", stderr="", test_passed=True)

    cfg = ExecutorConfig(
        checkpoint=_RecordingCheckpoint(),
        run_tests=True, test_via_agent=True, max_retries=2,
    )
    ex = AutonomousExecutor(_FlakyAgent(), cfg)
    with patch("subprocess.run") as mock_run:
        result = asyncio.run(ex.execute("build a page"))
    assert not mock_run.called
    assert result.success, "loop must recover after a failed then passing validation"
    assert calls["tests"] == 2, "TEST (agent.run_tests) ran twice: fail then pass"
    assert calls["generate"] == 2, "GENERATE ran twice — the RED_FIX loop re-generated"


def test_test_via_agent_persistent_failure_exhausts_to_failed():
    """If agent.run_tests() always fails, the loop exhausts max_retries and
    reports failure — not a false success."""
    class _AlwaysFailAgent(_FakeAgent):
        async def run_tests(self, test_paths=None):
            return ExecutionResult(exit_code=1, stdout="", stderr="still bad")

    cfg = ExecutorConfig(
        checkpoint=_RecordingCheckpoint(),
        run_tests=True, test_via_agent=True, max_retries=1,
    )
    ex = AutonomousExecutor(_AlwaysFailAgent(), cfg)
    with patch("subprocess.run"):
        result = asyncio.run(ex.execute("build a page"))
    assert not result.success, "persistent validation failure must not report success"


def test_test_via_agent_uses_test_passed_not_exit_code():
    """Sentinel BLOCKER-1 regression: a harness exiting 0 but reporting
    test_passed=False must be treated as FAILED — we key on the semantic
    field, never exit_code."""
    class _ExitZeroButFailed(_FakeAgent):
        async def run_tests(self, test_paths=None):
            # exit_code 0 (process ok) but tests DID NOT pass
            return ExecutionResult(exit_code=0, stdout="", stderr="3 failed", test_passed=False)

    cfg = ExecutorConfig(
        checkpoint=_RecordingCheckpoint(),
        run_tests=True, test_via_agent=True, max_retries=0,
    )
    ex = AutonomousExecutor(_ExitZeroButFailed(), cfg)
    with patch("subprocess.run"):
        result = asyncio.run(ex.execute("build a page"))
    assert not result.success, "exit_code==0 must NOT override test_passed=False"


def test_test_via_agent_none_stderr_does_not_crash():
    """Sentinel BLOCKER-2 regression: a failing result with stderr=None must
    not raise TypeError on slicing."""
    class _NoneStderrFail(_FakeAgent):
        async def run_tests(self, test_paths=None):
            return ExecutionResult(exit_code=1, stdout=None, stderr=None, test_passed=False)

    cfg = ExecutorConfig(
        checkpoint=_RecordingCheckpoint(),
        run_tests=True, test_via_agent=True, max_retries=0,
    )
    ex = AutonomousExecutor(_NoneStderrFail(), cfg)
    with patch("subprocess.run"):
        result = asyncio.run(ex.execute("build a page"))  # must not raise
    assert not result.success
