# graqle/workflow/autonomous_executor.py
"""
AutonomousExecutor — composition root for the autonomous loop.

Composes (does NOT extend):
  - LoopController (state machine)
  - ActionAgentProtocol (specialist agents)
  - ExecutionMemory (filesystem state tracking)
  - DiffApplicator (atomic apply + git-stash rollback)
  - TestResultParser (pytest output parsing)

Does NOT import WorkflowOrchestrator or BaseAgent directly.
They are composed at a higher level if needed.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from graqle.workflow.action_agent_protocol import ActionAgentProtocol, ExecutionResult
from graqle.workflow.diff_applicator import DiffApplicator
from graqle.workflow.execution_memory import ExecutionMemory
from graqle.workflow.loop_controller import LoopContext, LoopController, LoopState
from graqle.workflow.protocols import CheckpointProtocol
from graqle.workflow.test_result_parser import ParsedTestResult, TestResultParser

logger = logging.getLogger("graqle.workflow.autonomous_executor")


@dataclass
class ExecutorConfig:
    """Configuration for AutonomousExecutor."""

    max_retries: int = 3
    test_command: list[str] = field(
        default_factory=lambda: ["python", "-m", "pytest", "-x", "-q"]
    )
    test_paths: list[str] = field(default_factory=list)
    working_dir: str = "."
    dry_run: bool = False
    timeout_seconds: int = 300
    # ADR-239: pluggable checkpoint/rollback (default None → DiffApplicator).
    # A cloud consumer injects a non-git checkpoint (e.g. object-store file sink).
    checkpoint: "CheckpointProtocol | None" = None
    # ADR-239: skip the pytest TEST stage entirely (greenfield builds with
    # nothing to test yet). Default True preserves the existing git/pytest path.
    run_tests: bool = True
    # ADR-239 Stage 2.1: route the TEST stage through the agent instead of a
    # subprocess. When True, _on_test delegates to agent.run_tests() (which may
    # run any validation the consumer defines) so the native LoopController
    # RED_FIX loop drives repair on a failing result. Default False preserves
    # the existing subprocess(test_command) path exactly.
    test_via_agent: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_retries": self.max_retries,
            "test_command": self.test_command,
            "test_paths": self.test_paths,
            "working_dir": self.working_dir,
            "dry_run": self.dry_run,
            "timeout_seconds": self.timeout_seconds,
            "run_tests": self.run_tests,
            # `checkpoint` intentionally omitted — it is an injected object, not
            # a serialisable value; its presence is captured by run-time wiring.
        }


@dataclass
class ExecutorResult:
    """Final result of an autonomous execution run."""

    success: bool
    state: str
    attempts: int
    modified_files: list[str] = field(default_factory=list)
    test_output: str = ""
    error: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    memory_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "state": self.state,
            "attempts": self.attempts,
            "modified_files": self.modified_files,
            "test_output_len": len(self.test_output),
            "error": self.error,
            "memory": self.memory_summary,
        }


class AutonomousExecutor:
    """
    Composition root: drives the PLAN->GENERATE->WRITE->TEST->FIX loop.

    This is the main entry point for autonomous code generation and testing.
    It composes LoopController, ExecutionMemory, DiffApplicator, and
    TestResultParser without inheriting from or modifying any existing class.
    """

    def __init__(
        self,
        agent: ActionAgentProtocol,
        config: ExecutorConfig | None = None,
    ) -> None:
        self._config = config or ExecutorConfig()
        self._agent = agent
        self._loop = LoopController(max_retries=self._config.max_retries)
        self._memory = ExecutionMemory(self._config.working_dir)
        # ADR-239: checkpoint/rollback is pluggable. Default (None) constructs
        # DiffApplicator exactly as before — byte-identical for every existing
        # caller. A cloud consumer injects a non-git CheckpointProtocol.
        self._diff: CheckpointProtocol = (
            self._config.checkpoint
            if self._config.checkpoint is not None
            else DiffApplicator(self._config.working_dir)
        )
        self._parser = TestResultParser()

    @property
    def config(self) -> ExecutorConfig:
        return self._config

    @property
    def memory(self) -> ExecutionMemory:
        return self._memory

    # -- Callback implementations for LoopController.run() ---------------------

    async def _on_plan(self, ctx: LoopContext) -> str:
        """Delegate planning to the agent."""
        context: dict[str, Any] = {
            "working_dir": str(self._config.working_dir),
            "test_paths": self._config.test_paths,
        }
        if self._memory.history:
            context["error_context"] = self._memory.error_context_for_retry()
        return await self._agent.plan(ctx.task, context)

    async def _on_generate(self, ctx: LoopContext) -> str:
        """Delegate code generation to the agent."""
        error_context = None
        if ctx.attempt > 0 and self._memory.history:
            error_context = self._memory.error_context_for_retry()
        return await self._agent.generate_diff(
            ctx.task,
            ctx.plan,
            error_context=error_context,
        )

    async def _on_write(self, ctx: LoopContext) -> list[str]:
        """Apply the generated diff via the agent."""
        if self._config.dry_run:
            logger.info("Dry run — skipping write")
            return []

        # Create stash checkpoint before writing
        stash_ref = self._diff.create_stash(
            f"autoloop-attempt-{ctx.attempt}"
        )
        ctx.rollback_token = stash_ref  # set BEFORE apply for rollback on exception

        # Delegate application to the agent — rollback on failure
        try:
            result = await self._agent.apply(ctx.generated_diff)
            if not result.success:
                raise RuntimeError(f"Apply failed: {result.stderr}")
        except Exception:
            # Rollback orphaned stash on apply exception
            if stash_ref:
                self._diff.rollback(stash_ref)
            raise
        return result.modified_files

    async def _on_test(self, ctx: LoopContext) -> ParsedTestResult:
        """Run tests and parse results."""
        # ADR-239: consumers with nothing to test (e.g. greenfield builds) set
        # run_tests=False. Short-circuit to a passing result — never spawn the
        # test subprocess — while still recording to memory so the loop's state
        # machine and retry/convergence tracking stay consistent. Snapshots are
        # skipped: they capture file state at TEST time, meaningless with no test.
        if not self._config.run_tests:
            parsed = ParsedTestResult(passed=True, raw_output="tests skipped (run_tests=False)")
            self._memory.record(
                attempt=ctx.attempt,
                diff_applied=ctx.generated_diff[:2000],
                result_exit_code=0,
                test_output="tests skipped (run_tests=False)",
                modified_files=ctx.modified_files,
            )
            return parsed

        # ADR-239 Stage 2.1: route TEST through the agent instead of a
        # subprocess. The agent's run_tests() returns an ExecutionResult; its
        # .success maps to ParsedTestResult.passed, so a failing result drives
        # the native RED_FIX loop (agent regenerates with error_context). The
        # consumer decides what "testing" means (e.g. static validation of
        # generated files) — the SDK just wires the result into the FSM.
        if self._config.test_via_agent:
            agent_result = await self._agent.run_tests(self._config.test_paths or None)
            # Sentinel BLOCKER 1: use the protocol's SEMANTIC pass signal, not
            # exit_code — a harness can exit 0 while swallowing test failures.
            passed = bool(agent_result.test_passed)
            # Sentinel BLOCKER 2: None-guard stdout/stderr before slicing.
            stdout = agent_result.stdout or ""
            stderr = agent_result.stderr or ""
            output = stdout + (("\n" + stderr) if stderr else "")
            # Sentinel advisory: on failure, never leave error_messages empty —
            # the FIX loop's error_context would be blank and repair would run
            # blind. Fall back to output, then a generic marker.
            if passed:
                error_messages: list[str] = []
            elif stderr:
                error_messages = [stderr[:2000]]
            elif output:
                error_messages = [output[:2000]]
            else:
                error_messages = ["test_via_agent: validation failed, no output captured"]
            parsed = ParsedTestResult(
                passed=passed,
                raw_output=output,
                error_messages=error_messages,
            )
            self._memory.record(
                attempt=ctx.attempt,
                diff_applied=ctx.generated_diff[:2000],
                result_exit_code=agent_result.exit_code,
                test_output=output[:4000],
                modified_files=ctx.modified_files,
                error_message=("" if passed else (error_messages[0][:500] if error_messages else "")),
            )
            return parsed

        # Take before-snapshot
        if ctx.modified_files:
            before = self._memory.snapshot(ctx.modified_files)
        else:
            before = {}

        # Run the test command — A-006: scope tests to generated files
        test_cmd = list(self._config.test_command)
        if self._config.test_paths:
            # Explicit test paths configured — use those
            test_cmd.extend(self._config.test_paths)
        elif ctx.modified_files:
            # Auto-detect test files for modified source files
            for mf in ctx.modified_files:
                mf_path = Path(mf)
                # Check for corresponding test file
                test_file = mf_path.parent / f"test_{mf_path.name}"
                if test_file.exists():
                    test_cmd.append(str(test_file))
                # Also check tests/ directory mirroring source structure
                parts = list(mf_path.parts)
                if parts and parts[0] != "tests":
                    test_candidate = Path("tests") / "/".join(parts)
                    test_dir = test_candidate.parent / f"test_{test_candidate.name}"
                    if test_dir.exists():
                        test_cmd.append(str(test_dir))

        try:
            proc = subprocess.run(
                test_cmd,
                cwd=str(self._config.working_dir),
                capture_output=True,
                text=True,
                timeout=self._config.timeout_seconds,
            )
            raw_output = proc.stdout + "\n" + proc.stderr
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            raw_output = f"Test timed out after {self._config.timeout_seconds}s"
            exit_code = 124  # standard timeout exit code
        except Exception as exc:
            raw_output = f"Test execution error: {exc}"
            exit_code = 1

        # Parse results
        parsed = self._parser.parse(raw_output, exit_code)

        # Take after-snapshot and record
        if ctx.modified_files:
            after = self._memory.snapshot(ctx.modified_files)
        else:
            after = {}

        self._memory.record(
            attempt=ctx.attempt,
            diff_applied=ctx.generated_diff[:2000],
            result_exit_code=exit_code,
            test_output=raw_output[:4000],
            modified_files=ctx.modified_files,
            error_message="\n".join(parsed.error_messages[:5]),
            snapshots_before=before,
            snapshots_after=after,
        )

        return parsed

    async def _on_fix(self, ctx: LoopContext) -> None:
        """Prepare for retry: rollback if needed, build error context."""
        # Rollback when we have a token AND any failure signal (tests, errors, or last_error)
        should_rollback = ctx.rollback_token and (
            ctx.failed_tests or ctx.error_messages or ctx.last_error
        )
        if should_rollback:
            logger.info(
                "Rolling back attempt %d before retry", ctx.attempt
            )
            rollback_result = self._diff.rollback(ctx.rollback_token)
            if not rollback_result.success:
                logger.warning(
                    "Rollback failed: %s — continuing without rollback",
                    rollback_result.stderr,
                )
        else:
            logger.debug(
                "Skipping rollback: token=%s, failed=%s",
                ctx.rollback_token,
                bool(ctx.failed_tests),
            )
        # The error context is built by ExecutionMemory.error_context_for_retry()
        # and consumed by _on_generate on the next iteration

    # -- Main entry point ------------------------------------------------------

    async def execute(self, task: str) -> ExecutorResult:
        """
        Run the autonomous loop for the given task.

        Returns
        -------
        ExecutorResult
            Final result with success/failure status, files modified, etc.
        """
        self._memory.clear()

        # A-002: verify git is available before entering the loop
        if not shutil.which("git"):
            return ExecutorResult(
                success=False,
                state=LoopState.FAILED.value,
                attempts=0,
                error=(
                    "git not found in PATH. The autonomous executor requires git "
                    "for stash-based rollback. Install git and ensure it's in PATH."
                ),
            )

        ctx = self._loop.initial_context(task)

        logger.info(
            "AutonomousExecutor: starting task=%r, max_retries=%d",
            task[:80],
            self._config.max_retries,
        )

        try:
            ctx = await self._loop.run(
                ctx,
                on_plan=self._on_plan,
                on_generate=self._on_generate,
                on_write=self._on_write,
                on_test=self._on_test,
                on_fix=self._on_fix,
            )
        except asyncio.CancelledError:
            raise  # always propagate cooperative cancellation
        except Exception as exc:
            logger.exception("AutonomousExecutor: unhandled error")
            return ExecutorResult(
                success=False,
                state=LoopState.FAILED.value,
                attempts=ctx.attempt,
                error=str(exc),
                context=ctx.to_dict(),
                memory_summary=self._memory.summary(),
            )

        return ExecutorResult(
            success=ctx.state == LoopState.GREEN_DONE,
            state=ctx.state.value,
            attempts=ctx.attempt,
            modified_files=ctx.modified_files,
            test_output=ctx.test_output,
            error=ctx.last_error,
            context=ctx.to_dict(),
            memory_summary=self._memory.summary(),
        )
