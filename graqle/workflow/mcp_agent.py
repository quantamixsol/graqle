# graqle/workflow/mcp_agent.py
"""
MCP-backed ActionAgent — bridges AutonomousExecutor to existing MCP tools.

Delegates plan/generate/apply/test/rollback to KogniDevServer handlers
without subclassing BaseAgent (respects 402-dep blast-radius constraint).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from graqle.workflow.action_agent_protocol import ExecutionResult
from graqle.workflow.diff_applicator import DiffApplicator

if TYPE_CHECKING:
    from graqle.plugins.mcp_dev_server import KogniDevServer

logger = logging.getLogger("graqle.workflow.mcp_agent")

_TEST_TIMEOUT_SECONDS: int = 300


class McpActionAgent:
    """Delegates plan/generate/apply/test/rollback to KogniDevServer handlers.

    Satisfies ActionAgentProtocol via structural subtyping (duck typing).
    Does NOT import or inherit from BaseAgent.
    """

    def __init__(self, server: KogniDevServer, working_dir: Path) -> None:
        self._server = server
        self._working_dir = working_dir.resolve()
        self._diff = DiffApplicator(str(self._working_dir))

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
            # Tool unavailable — fallback to preflight is appropriate
            logger.warning(
                "graq_plan unavailable (%s), falling back to preflight",
                exc,
                exc_info=True,
            )
        else:
            # Parse response — propagate domain errors, don't fall through
            try:
                result = json.loads(result_json) if isinstance(result_json, str) else result_json
            except (json.JSONDecodeError, TypeError) as parse_exc:
                logger.warning("graq_plan returned unparseable response: %s", parse_exc)
                return result_json  # propagate raw, do not fall back
            if "error" not in result:
                return result_json
            logger.warning("graq_plan returned error: %s", str(result.get("error", ""))[:200])
            return result_json

        # Fallback: use preflight as a lightweight plan (correct param: "action")
        try:
            result_json = await self._server.handle_tool(
                "graq_preflight",
                {"action": task},
            )
            return result_json
        except Exception as fallback_exc:
            logger.error("graq_preflight also unavailable: %s", fallback_exc, exc_info=True)
            return json.dumps({"error": f"Both graq_plan and graq_preflight unavailable: {fallback_exc}"})

    async def generate_diff(
        self,
        task: str,
        plan: str,
        error_context: str | None = None,
    ) -> str:
        """Delegate code generation to graq_generate."""
        # graq_generate expects "description" not "task"
        args: dict[str, Any] = {
            "description": task,
            "plan": plan,
        }
        if error_context is not None:
            args["error_context"] = error_context

        result_json = await self._server.handle_tool("graq_generate", args)
        return result_json

    async def apply(self, diff: str) -> ExecutionResult:
        """Apply generated code by parsing graq_generate JSON output.

        Validates paths against working_dir to prevent CWE-22 traversal.
        Uses tempfile.mkstemp + os.replace for crash-safe, collision-free writes.
        Always returns ExecutionResult — never raises.
        """
        try:
            diff_data = json.loads(diff)
        except (json.JSONDecodeError, TypeError):
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr="Unparseable diff payload — check graq_generate output",
                modified_files=[],
            )

        # Validate parsed type is a dict
        if not isinstance(diff_data, dict):
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=f"Expected JSON object from graq_generate, got {type(diff_data).__name__}",
                modified_files=[],
            )

        # Check for error key in generate output
        if "error" in diff_data:
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=f"Generate returned error: {diff_data['error']}",
                modified_files=[],
            )

        modified_files: list[str] = []

        # Extract files from graq_generate output format
        files = diff_data.get("files") or []
        if not isinstance(files, list):
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=f"files field must be a list, got {type(files).__name__}",
                modified_files=[],
            )
        if not files and "content" in diff_data:
            path = diff_data.get("path", "")
            if path:
                files = [{"path": path, "content": diff_data["content"]}]
            else:
                logger.warning("Single-file fallback: content present but path is empty")

        for file_entry in files:
            file_path = file_entry.get("path", "")
            content = file_entry.get("content")
            if not file_path or content is None:
                logger.warning("Skipping entry: missing path=%r or content is None", file_path)
                continue

            # CWE-22: Path traversal guard — abort entire apply on traversal attempt
            target = (self._working_dir / file_path).resolve()
            if not target.is_relative_to(self._working_dir):
                logger.error("Path traversal attempt blocked: %r", file_path)
                return ExecutionResult(
                    exit_code=1,
                    stdout="",
                    stderr=f"Path traversal attempt blocked: {file_path}",
                    modified_files=modified_files,
                )

            target.parent.mkdir(parents=True, exist_ok=True)

            # Atomic write: unique temp file + os.replace (no collision)
            tmp_path: str | None = None
            try:
                tmp_fd, tmp_path = tempfile.mkstemp(
                    dir=str(target.parent), suffix=".tmp"
                )
                os.close(tmp_fd)
                if not isinstance(content, str):
                    content = json.dumps(content)
                Path(tmp_path).write_text(content, encoding="utf-8")
                os.replace(tmp_path, target)
            except OSError as exc:
                if tmp_path:
                    Path(tmp_path).unlink(missing_ok=True)
                return ExecutionResult(
                    exit_code=1,
                    stdout="",
                    stderr=f"Write failed for {file_path}: {exc}",
                    modified_files=modified_files,
                )

            modified_files.append(file_path)

        if not modified_files:
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr="No files extracted from diff payload — check generate output",
                modified_files=[],
            )

        return ExecutionResult(
            exit_code=0,
            stdout=f"Applied {len(modified_files)} files",
            stderr="",
            modified_files=modified_files,
        )

    async def run_tests(
        self, test_paths: list[str] | None = None
    ) -> ExecutionResult:
        """Run pytest via subprocess (non-blocking via asyncio.to_thread)."""
        cmd = [sys.executable, "-m", "pytest", "-x", "-q"]
        if test_paths:
            for p in test_paths:
                # Reject flag injection (paths starting with -)
                if p.startswith("-"):
                    return ExecutionResult(
                        exit_code=1,
                        stdout="",
                        stderr=f"Invalid test path (flag injection): {p}",
                        test_passed=False,
                    )
                # CWE-22: validate paths stay within working dir
                resolved = (self._working_dir / p).resolve()
                if not resolved.is_relative_to(self._working_dir):
                    return ExecutionResult(
                        exit_code=1,
                        stdout="",
                        stderr=f"Invalid test path (traversal): {p}",
                        test_passed=False,
                    )
                cmd.append(str(resolved))

        try:
            proc = await asyncio.to_thread(
                self._run_subprocess, cmd
            )
            return ExecutionResult(
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                test_passed=proc.returncode == 0,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                exit_code=124,
                stdout="",
                stderr=f"Test timed out after {_TEST_TIMEOUT_SECONDS}s",
                test_passed=False,
            )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=f"Test execution error: {exc}",
                test_passed=False,
            )

    def _run_subprocess(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        """Run subprocess.run in a thread-safe manner."""
        return subprocess.run(
            cmd,
            cwd=str(self._working_dir),
            capture_output=True,
            text=True,
            timeout=_TEST_TIMEOUT_SECONDS,
        )

    async def rollback(self, token: str) -> ExecutionResult:
        """Rollback via DiffApplicator (run in thread to avoid blocking)."""
        try:
            return await asyncio.to_thread(self._diff.rollback, token)
        except Exception as exc:
            logger.error("Rollback failed: %s", exc, exc_info=True)
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=f"Rollback failed: {exc}",
                modified_files=[],
            )
