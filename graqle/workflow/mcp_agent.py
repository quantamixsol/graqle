# graqle/workflow/mcp_agent.py
"""
MCP-backed ActionAgent — bridges AutonomousExecutor to existing MCP tools.

Delegates plan/generate/apply/test/rollback to KogniDevServer handlers
without subclassing BaseAgent (respects 402-dep blast-radius constraint).

v2 design: apply() uses apply_diff() from core/file_writer.py for existing
files and atomic write for new files (/dev/null). ADR-112: hard errors only.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from graqle.core.file_writer import apply_diff
from graqle.workflow.action_agent_protocol import ExecutionResult
from graqle.workflow.diff_applicator import DiffApplicator

if TYPE_CHECKING:
    from graqle.plugins.mcp_dev_server import KogniDevServer

logger = logging.getLogger("graqle.workflow.mcp_agent")

_TEST_TIMEOUT_SECONDS: int = 300

# A-004: Tools whose plan steps carry a file_path to forward to graq_generate
_GENERATE_TOOLS: frozenset[str] = frozenset({"graq_generate"})

# Patent-scan patterns from _handle_write (mcp_dev_server.py:5396-5406)
_TS_PATTERNS: list[str] = [
    r"w_J", r"w_A", r"\b0\.16\b", r"theta_fold",
    r"jaccard.*formula", r"70.*30.*blend", r"AGREEMENT_THRESHOLD",
]


class McpActionAgent:
    """Delegates plan/generate/apply/test/rollback to KogniDevServer handlers.

    Satisfies ActionAgentProtocol via structural subtyping (duck typing).
    Does NOT import or inherit from BaseAgent.
    """

    def __init__(self, server: KogniDevServer, working_dir: Path) -> None:
        self._server = server
        self._working_dir = working_dir.resolve()
        self._diff = DiffApplicator(str(self._working_dir))

    # ------------------------------------------------------------------
    # plan()
    # ------------------------------------------------------------------

    async def plan(self, task: str, context: dict[str, Any]) -> str:
        """Delegate planning to graq_plan, fallback to graq_preflight.

        Falls back to preflight ONLY on tool-unavailable (exception).
        Domain errors (error key in response) are propagated, not downgraded.
        """
        try:
            result_json = await self._server.handle_tool(
                "graq_plan",
                {
                    "goal": task,
                    "scope": context.get("scope", context.get("file_path", "")),
                    "dry_run": True,
                },
            )
        except Exception as exc:
            logger.warning(
                "graq_plan unavailable (%s), falling back to preflight",
                exc,
                exc_info=True,
            )
        else:
            try:
                result = json.loads(result_json) if isinstance(result_json, str) else result_json
            except (json.JSONDecodeError, TypeError) as parse_exc:
                logger.warning("graq_plan returned unparseable response: %s", parse_exc)
                return result_json
            if "error" not in result:
                return result_json
            logger.warning("graq_plan returned error: %s", str(result.get("error", ""))[:200])
            return result_json

        try:
            result_json = await self._server.handle_tool(
                "graq_preflight",
                {"action": task},
            )
            return result_json
        except Exception as fallback_exc:
            logger.error("graq_preflight also unavailable: %s", fallback_exc, exc_info=True)
            return json.dumps({"error": f"Both graq_plan and graq_preflight unavailable: {fallback_exc}"})

    # ------------------------------------------------------------------
    # generate_diff()
    # ------------------------------------------------------------------

    async def generate_diff(
        self,
        task: str,
        plan: str | dict[str, Any],
        error_context: str | None = None,
    ) -> str:
        """Delegate code generation to graq_generate.

        Accepts plan as JSON string or dict. Extracts file_path from
        the first graq_generate step in plan.steps (A-004 fix).
        """
        # Parse plan into dict for file_path extraction
        plan_obj: dict[str, Any] | None = None
        if isinstance(plan, dict):
            plan_obj = plan
        elif isinstance(plan, str):
            try:
                parsed = json.loads(plan)
                if isinstance(parsed, dict):
                    plan_obj = parsed
            except json.JSONDecodeError:
                logger.debug("plan is not valid JSON, skipping file_path extraction")

        # Serialize for the tool boundary
        if plan_obj is not None:
            try:
                plan_str = json.dumps(plan_obj)
            except TypeError:
                plan_str = str(plan)
        else:
            plan_str = plan if isinstance(plan, str) else str(plan)

        args: dict[str, Any] = {
            "description": task,
            "plan": plan_str,
        }

        # A-004 fix: extract file_path from plan steps so graq_generate
        # targets the correct file instead of "(inferred from graph)"
        if plan_obj is not None:
            steps = plan_obj.get("steps", [])
            if not isinstance(steps, list):
                steps = []
            for step in steps:
                if not isinstance(step, dict):
                    continue
                if step.get("tool") in _GENERATE_TOOLS:
                    step_args = step.get("args")
                    if isinstance(step_args, dict):
                        file_path = step_args.get("file_path")
                        if isinstance(file_path, str) and file_path:
                            args["file_path"] = file_path
                            break

        if error_context is not None:
            args["error_context"] = error_context

        result_json = await self._server.handle_tool("graq_generate", args)
        return result_json

    # ------------------------------------------------------------------
    # apply() — v2: patches[] + apply_diff() + /dev/null two-path
    # ------------------------------------------------------------------

    async def apply(self, diff: str) -> ExecutionResult:
        """Apply patches from CodeGenerationResult JSON.

        Two-path design (research team V2 validated):
          - Existing files: apply_diff() from core/file_writer.py
          - New files (--- /dev/null): extract +lines, patent scan, atomic write

        ADR-112: hard error on any failure, no fallback tiers.
        CWE-22: abort ALL patches on any path traversal attempt.
        """
        rollback_token = uuid.uuid4().hex
        modified_files: list[str] = []
        stdout_parts: list[str] = []

        # -- Step 1: Parse JSON envelope ---------------------------------
        try:
            payload = json.loads(diff)
        except (json.JSONDecodeError, TypeError) as exc:
            return ExecutionResult(
                exit_code=1, stdout="", modified_files=[],
                stderr=f"ADR-112: diff is not valid JSON: {exc}",
                rollback_token=rollback_token,
            )

        if not isinstance(payload, dict):
            return ExecutionResult(
                exit_code=1, stdout="", modified_files=[],
                stderr=f"ADR-112: expected JSON object, got {type(payload).__name__}",
                rollback_token=rollback_token,
            )

        if "error" in payload:
            return ExecutionResult(
                exit_code=1, stdout="", modified_files=[],
                stderr=f"Generate returned error: {str(payload['error'])[:500]}",
                rollback_token=rollback_token,
            )

        # -- Step 2: Validate patches key --------------------------------
        if "patches" not in payload:
            return ExecutionResult(
                exit_code=1, stdout="", modified_files=[],
                stderr="ADR-112: 'patches' key missing from CodeGenerationResult",
                rollback_token=rollback_token,
            )

        patches = payload["patches"]
        if not isinstance(patches, list):
            return ExecutionResult(
                exit_code=1, stdout="", modified_files=[],
                stderr=f"ADR-112: 'patches' must be list, got {type(patches).__name__}",
                rollback_token=rollback_token,
            )

        if not patches:
            return ExecutionResult(
                exit_code=0, stdout="No patches to apply.", modified_files=[],
                stderr="", rollback_token=rollback_token,
            )

        # Validate each patch has required keys
        for i, patch in enumerate(patches):
            if not isinstance(patch, dict):
                return ExecutionResult(
                    exit_code=1, stdout="", modified_files=[],
                    stderr=f"ADR-112: patch[{i}] is not a dict",
                    rollback_token=rollback_token,
                )
            for key in ("file_path", "unified_diff"):
                if key not in patch:
                    return ExecutionResult(
                        exit_code=1, stdout="", modified_files=[],
                        stderr=f"ADR-112: patch[{i}] missing required key '{key}'",
                        rollback_token=rollback_token,
                    )

        # -- Step 3: CWE-22 abort-all on ANY path traversal --------------
        for patch in patches:
            file_path = patch["file_path"]
            resolved = (self._working_dir / file_path).resolve()
            if not resolved.is_relative_to(self._working_dir):
                return ExecutionResult(
                    exit_code=1, stdout="", modified_files=[],
                    stderr=f"CWE-22 PATH TRAVERSAL BLOCKED: '{file_path}' resolves outside working dir. All patches aborted.",
                    rollback_token=rollback_token,
                )

        # -- Step 4: Apply each patch ------------------------------------
        for patch in patches:
            file_path = patch["file_path"]
            unified_diff: str = patch["unified_diff"]
            resolved = (self._working_dir / file_path).resolve()

            # Detect new file via header lines ONLY (not full-string substring)
            diff_lines = unified_diff.splitlines()
            is_new_file = any(
                line.strip() == "--- /dev/null" for line in diff_lines[:5]
            )

            # Patent scan on ALL diffs (new + existing) — scan +lines only
            added_content = "\n".join(
                line[1:]
                for line in diff_lines
                if line.startswith("+") and not line.startswith("+++")
            )
            for pat in _TS_PATTERNS:
                if re.search(pat, added_content):
                    return ExecutionResult(
                        exit_code=1, stdout="\n".join(stdout_parts),
                        modified_files=modified_files,
                        stderr=f"PATENT_GATE: pattern '{pat}' matched in '{file_path}'. All patches aborted.",
                        rollback_token=rollback_token,
                    )

            if is_new_file:
                # -- New file: extract +lines, atomic write --
                content = added_content
                if content and not content.endswith("\n"):
                    content += "\n"

                # Atomic write: tempfile -> fsync -> os.replace
                resolved.parent.mkdir(parents=True, exist_ok=True)
                fd: int | None = None
                tmp_path: str | None = None
                try:
                    fd, tmp_path = tempfile.mkstemp(
                        dir=str(resolved.parent), suffix=".tmp"
                    )
                    with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                        fd = None  # os.fdopen took ownership
                        tmp.write(content)
                        tmp.flush()
                        os.fsync(tmp.fileno())
                    os.replace(tmp_path, str(resolved))
                    tmp_path = None  # replace succeeded
                except Exception as exc:
                    if tmp_path is not None:
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass
                    if fd is not None:
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                    return ExecutionResult(
                        exit_code=1, stdout="\n".join(stdout_parts),
                        modified_files=modified_files,
                        stderr=f"Atomic write FAILED for '{file_path}': {exc}. Hard error per ADR-112.",
                        rollback_token=rollback_token,
                    )

                modified_files.append(file_path)
                stdout_parts.append(f"Created {file_path} ({len(content.splitlines())} lines)")

            else:
                # -- Existing file: apply_diff() from core/file_writer ----
                result = apply_diff(
                    resolved,
                    unified_diff,
                    dry_run=False,
                    skip_syntax_check=not file_path.endswith(".py"),
                )
                if not result.success:
                    return ExecutionResult(
                        exit_code=1, stdout="\n".join(stdout_parts),
                        modified_files=modified_files,
                        stderr=f"apply_diff FAILED for '{file_path}': {result.error}. Hard error per ADR-112.",
                        rollback_token=rollback_token,
                    )

                modified_files.append(file_path)
                stdout_parts.append(f"Patched {file_path}: {result.lines_changed} lines changed")

        return ExecutionResult(
            exit_code=0,
            stdout="\n".join(stdout_parts),
            stderr="",
            modified_files=modified_files,
            rollback_token=rollback_token,
        )

    # ------------------------------------------------------------------
    # run_tests()
    # ------------------------------------------------------------------

    async def run_tests(
        self, test_paths: list[str] | None = None
    ) -> ExecutionResult:
        """Run pytest via subprocess (non-blocking via asyncio.to_thread)."""
        cmd = [sys.executable, "-m", "pytest", "-x", "-q"]
        if test_paths:
            for p in test_paths:
                if p.startswith("-"):
                    return ExecutionResult(
                        exit_code=1, stdout="",
                        stderr=f"Invalid test path (flag injection): {p}",
                        test_passed=False,
                    )
                resolved = (self._working_dir / p).resolve()
                if not resolved.is_relative_to(self._working_dir):
                    return ExecutionResult(
                        exit_code=1, stdout="",
                        stderr=f"Invalid test path (traversal): {p}",
                        test_passed=False,
                    )
                cmd.append(str(resolved))

        try:
            proc = await asyncio.to_thread(self._run_subprocess, cmd)
            return ExecutionResult(
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                test_passed=proc.returncode == 0,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                exit_code=124, stdout="",
                stderr=f"Test timed out after {_TEST_TIMEOUT_SECONDS}s",
                test_passed=False,
            )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return ExecutionResult(
                exit_code=1, stdout="",
                stderr=f"Test execution error: {exc}",
                test_passed=False,
            )

    def _run_subprocess(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        """Blocking subprocess call — invoked via asyncio.to_thread."""
        return subprocess.run(
            cmd,
            cwd=str(self._working_dir),
            capture_output=True,
            text=True,
            timeout=_TEST_TIMEOUT_SECONDS,
        )

    # ------------------------------------------------------------------
    # rollback()
    # ------------------------------------------------------------------

    async def rollback(self, token: str) -> ExecutionResult:
        """Rollback via DiffApplicator (run in thread to avoid blocking)."""
        try:
            return await asyncio.to_thread(self._diff.rollback, token)
        except Exception as exc:
            logger.error("Rollback failed: %s", exc, exc_info=True)
            return ExecutionResult(
                exit_code=1, stdout="",
                stderr=f"Rollback failed: {exc}",
                modified_files=[],
            )
