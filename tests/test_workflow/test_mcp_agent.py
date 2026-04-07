"""Tests for graqle.workflow.mcp_agent — McpActionAgent v2 design."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graqle.workflow.action_agent_protocol import ExecutionResult
from graqle.workflow.mcp_agent import McpActionAgent, _TEST_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_server() -> MagicMock:
    server = MagicMock()
    server.handle_tool = AsyncMock()
    return server


@pytest.fixture
def agent(mock_server: MagicMock, tmp_path: Path) -> McpActionAgent:
    return McpActionAgent(mock_server, tmp_path)


# ---------------------------------------------------------------------------
# plan() tests
# ---------------------------------------------------------------------------


class TestPlan:
    @pytest.mark.asyncio
    async def test_plan_returns_graq_plan_on_success(
        self, agent: McpActionAgent, mock_server: MagicMock
    ) -> None:
        mock_server.handle_tool.return_value = json.dumps({"steps": ["a", "b"]})
        result = await agent.plan("build X", {})
        data = json.loads(result)
        assert "steps" in data
        mock_server.handle_tool.assert_awaited_once_with(
            "graq_plan",
            {"goal": "build X", "scope": "", "dry_run": True},
        )

    @pytest.mark.asyncio
    async def test_plan_domain_error_propagated_not_downgraded(
        self, agent: McpActionAgent, mock_server: MagicMock
    ) -> None:
        mock_server.handle_tool.return_value = json.dumps({"error": "bad goal"})
        result = await agent.plan("bad task", {})
        data = json.loads(result)
        assert data["error"] == "bad goal"
        assert mock_server.handle_tool.await_count == 1

    @pytest.mark.asyncio
    async def test_plan_falls_back_to_preflight_on_exception(
        self, agent: McpActionAgent, mock_server: MagicMock
    ) -> None:
        mock_server.handle_tool.side_effect = [
            RuntimeError("graq_plan not found"),
            json.dumps({"risk_level": "low"}),
        ]
        result = await agent.plan("task", {})
        data = json.loads(result)
        assert data["risk_level"] == "low"
        assert mock_server.handle_tool.await_count == 2
        second_call = mock_server.handle_tool.call_args_list[1]
        assert second_call.args[0] == "graq_preflight"
        assert second_call.args[1] == {"action": "task"}

    @pytest.mark.asyncio
    async def test_plan_both_unavailable_returns_error(
        self, agent: McpActionAgent, mock_server: MagicMock
    ) -> None:
        mock_server.handle_tool.side_effect = RuntimeError("unavailable")
        result = await agent.plan("task", {})
        data = json.loads(result)
        assert "error" in data
        assert "unavailable" in data["error"]

    @pytest.mark.asyncio
    async def test_plan_unparseable_response_propagated(
        self, agent: McpActionAgent, mock_server: MagicMock
    ) -> None:
        """Malformed JSON from graq_plan is returned raw, not fallen through."""
        mock_server.handle_tool.return_value = "not json {{"
        result = await agent.plan("task", {})
        assert result == "not json {{"
        assert mock_server.handle_tool.await_count == 1


# ---------------------------------------------------------------------------
# generate_diff() tests
# ---------------------------------------------------------------------------


class TestGenerateDiff:
    @pytest.mark.asyncio
    async def test_passes_description_and_plan(
        self, agent: McpActionAgent, mock_server: MagicMock
    ) -> None:
        mock_server.handle_tool.return_value = json.dumps({"patches": []})
        await agent.generate_diff("write tests", "step 1")
        mock_server.handle_tool.assert_awaited_once_with(
            "graq_generate",
            {"description": "write tests", "plan": "step 1"},
        )

    @pytest.mark.asyncio
    async def test_forwards_error_context(
        self, agent: McpActionAgent, mock_server: MagicMock
    ) -> None:
        mock_server.handle_tool.return_value = json.dumps({})
        await agent.generate_diff("fix", "plan", error_context="AssertionError")
        args = mock_server.handle_tool.call_args.args[1]
        assert args["error_context"] == "AssertionError"

    @pytest.mark.asyncio
    async def test_none_error_context_not_sent(
        self, agent: McpActionAgent, mock_server: MagicMock
    ) -> None:
        mock_server.handle_tool.return_value = json.dumps({})
        await agent.generate_diff("fix", "plan", error_context=None)
        args = mock_server.handle_tool.call_args.args[1]
        assert "error_context" not in args


# ---------------------------------------------------------------------------
# apply() v2 — Schema Contract Tests
# ---------------------------------------------------------------------------


class TestApplySchemaContract:
    @pytest.mark.asyncio
    async def test_parses_patches_schema(
        self, agent: McpActionAgent, tmp_path: Path
    ) -> None:
        target = tmp_path / "x.py"
        target.write_text("old\n", encoding="utf-8")

        diff = json.dumps({
            "patches": [{
                "file_path": "x.py",
                "unified_diff": "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n",
                "lines_added": 1,
                "lines_removed": 1,
            }]
        })
        result = await agent.apply(diff)
        assert result.exit_code == 0
        assert "x.py" in result.modified_files
        assert target.read_text() == "new\n"

    @pytest.mark.asyncio
    async def test_rejects_files_schema_hard_error(
        self, agent: McpActionAgent
    ) -> None:
        diff = json.dumps({"files": [{"path": "x.py", "content": "hello"}]})
        result = await agent.apply(diff)
        assert result.exit_code == 1
        assert "patches" in result.stderr.lower()

    @pytest.mark.asyncio
    async def test_rejects_missing_patches_key(
        self, agent: McpActionAgent
    ) -> None:
        diff = json.dumps({"answer": "some text", "confidence": 0.8})
        result = await agent.apply(diff)
        assert result.exit_code == 1
        assert "patches" in result.stderr.lower()

    @pytest.mark.asyncio
    async def test_rejects_non_dict_payload(
        self, agent: McpActionAgent
    ) -> None:
        result = await agent.apply("[1, 2, 3]")
        assert result.exit_code == 1

    @pytest.mark.asyncio
    async def test_rejects_invalid_json(
        self, agent: McpActionAgent
    ) -> None:
        result = await agent.apply("not json {{")
        assert result.exit_code == 1
        assert "JSON" in result.stderr

    @pytest.mark.asyncio
    async def test_propagates_error_key(
        self, agent: McpActionAgent
    ) -> None:
        diff = json.dumps({"error": "GENERATION_BACKEND_UNAVAILABLE"})
        result = await agent.apply(diff)
        assert result.exit_code == 1
        assert "GENERATION_BACKEND_UNAVAILABLE" in result.stderr

    @pytest.mark.asyncio
    async def test_patches_not_list_rejected(
        self, agent: McpActionAgent
    ) -> None:
        diff = json.dumps({"patches": "not a list"})
        result = await agent.apply(diff)
        assert result.exit_code == 1
        assert "list" in result.stderr.lower()

    @pytest.mark.asyncio
    async def test_patch_missing_file_path_rejected(
        self, agent: McpActionAgent
    ) -> None:
        diff = json.dumps({"patches": [{"unified_diff": "---"}]})
        result = await agent.apply(diff)
        assert result.exit_code == 1
        assert "file_path" in result.stderr

    @pytest.mark.asyncio
    async def test_patch_missing_unified_diff_rejected(
        self, agent: McpActionAgent
    ) -> None:
        diff = json.dumps({"patches": [{"file_path": "x.py"}]})
        result = await agent.apply(diff)
        assert result.exit_code == 1
        assert "unified_diff" in result.stderr

    @pytest.mark.asyncio
    async def test_empty_patches_returns_success(
        self, agent: McpActionAgent
    ) -> None:
        diff = json.dumps({"patches": []})
        result = await agent.apply(diff)
        assert result.exit_code == 0
        assert result.modified_files == []


# ---------------------------------------------------------------------------
# apply() v2 — CWE-22 Path Traversal
# ---------------------------------------------------------------------------


class TestApplyPathTraversal:
    @pytest.mark.asyncio
    async def test_traversal_aborts_all_patches(
        self, agent: McpActionAgent, tmp_path: Path
    ) -> None:
        (tmp_path / "legit.py").write_text("ok\n")
        diff = json.dumps({"patches": [
            {"file_path": "legit.py", "unified_diff": "--- a/legit.py\n+++ b/legit.py\n@@ -1 +1 @@\n-ok\n+good\n"},
            {"file_path": "../../etc/evil.py", "unified_diff": "--- /dev/null\n+++ b/evil.py\n@@ -0,0 +1 @@\n+evil\n"},
        ]})
        result = await agent.apply(diff)
        assert result.exit_code == 1
        assert "CWE-22" in result.stderr
        assert (tmp_path / "legit.py").read_text() == "ok\n"


# ---------------------------------------------------------------------------
# apply() v2 — New File Creation (--- /dev/null)
# ---------------------------------------------------------------------------


class TestApplyNewFile:
    @pytest.mark.asyncio
    async def test_creates_new_file_from_dev_null(
        self, agent: McpActionAgent, tmp_path: Path
    ) -> None:
        diff = json.dumps({"patches": [{
            "file_path": "new_module.py",
            "unified_diff": (
                "--- /dev/null\n"
                "+++ b/new_module.py\n"
                "@@ -0,0 +1,3 @@\n"
                "+import os\n"
                "+\n"
                "+print('hello')\n"
            ),
        }]})
        result = await agent.apply(diff)
        assert result.exit_code == 0
        assert "new_module.py" in result.modified_files
        content = (tmp_path / "new_module.py").read_text()
        assert "import os" in content
        assert "print('hello')" in content

    @pytest.mark.asyncio
    async def test_creates_parent_dirs_for_new_file(
        self, agent: McpActionAgent, tmp_path: Path
    ) -> None:
        diff = json.dumps({"patches": [{
            "file_path": "sub/dir/new.py",
            "unified_diff": "--- /dev/null\n+++ b/sub/dir/new.py\n@@ -0,0 +1 @@\n+x = 1\n",
        }]})
        result = await agent.apply(diff)
        assert result.exit_code == 0
        assert (tmp_path / "sub" / "dir" / "new.py").exists()

    @pytest.mark.asyncio
    async def test_new_file_patent_scan_blocks(
        self, agent: McpActionAgent, tmp_path: Path
    ) -> None:
        diff = json.dumps({"patches": [{
            "file_path": "config.py",
            "unified_diff": "--- /dev/null\n+++ b/config.py\n@@ -0,0 +1 @@\n+AGREEMENT_THRESHOLD = 0.16\n",
        }]})
        result = await agent.apply(diff)
        assert result.exit_code == 1
        assert "PATENT_GATE" in result.stderr
        assert not (tmp_path / "config.py").exists()


# ---------------------------------------------------------------------------
# apply() v2 — Existing File via apply_diff()
# ---------------------------------------------------------------------------


class TestApplyExistingFile:
    @pytest.mark.asyncio
    async def test_existing_file_patent_scan_blocks(
        self, agent: McpActionAgent, tmp_path: Path
    ) -> None:
        """BLOCKER fix: patent scan must apply to existing-file diffs too."""
        target = tmp_path / "settings.py"
        target.write_text("threshold = 0.5\n", encoding="utf-8")

        diff = json.dumps({"patches": [{
            "file_path": "settings.py",
            "unified_diff": "--- a/settings.py\n+++ b/settings.py\n@@ -1 +1 @@\n-threshold = 0.5\n+AGREEMENT_THRESHOLD = 0.16\n",
        }]})
        result = await agent.apply(diff)
        assert result.exit_code == 1
        assert "PATENT_GATE" in result.stderr
        # Original file must be unchanged
        assert target.read_text() == "threshold = 0.5\n"

    @pytest.mark.asyncio
    async def test_applies_diff_to_existing_file(
        self, agent: McpActionAgent, tmp_path: Path
    ) -> None:
        target = tmp_path / "hello.py"
        target.write_text("old_value = 1\n", encoding="utf-8")

        diff = json.dumps({"patches": [{
            "file_path": "hello.py",
            "unified_diff": "--- a/hello.py\n+++ b/hello.py\n@@ -1 +1 @@\n-old_value = 1\n+new_value = 2\n",
        }]})
        result = await agent.apply(diff)
        assert result.exit_code == 0
        assert target.read_text() == "new_value = 2\n"

    @pytest.mark.asyncio
    async def test_stale_diff_rejected(
        self, agent: McpActionAgent, tmp_path: Path
    ) -> None:
        target = tmp_path / "stale.py"
        target.write_text("current_content = True\n", encoding="utf-8")

        diff = json.dumps({"patches": [{
            "file_path": "stale.py",
            "unified_diff": "--- a/stale.py\n+++ b/stale.py\n@@ -1 +1 @@\n-wrong_context = False\n+new_content = True\n",
        }]})
        result = await agent.apply(diff)
        assert result.exit_code == 1
        assert target.read_text() == "current_content = True\n"


# ---------------------------------------------------------------------------
# apply() v2 — No Fallback (ADR-112)
# ---------------------------------------------------------------------------


class TestApplyNoFallback:
    @pytest.mark.asyncio
    async def test_does_not_fallback_to_preview(
        self, agent: McpActionAgent, tmp_path: Path
    ) -> None:
        target = tmp_path / "file.py"
        target.write_text("original\n", encoding="utf-8")

        diff = json.dumps({"patches": [{
            "file_path": "file.py",
            "unified_diff": "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-wrong_context\n+new\n",
            "preview": "this should NOT be written",
        }]})
        result = await agent.apply(diff)
        assert result.exit_code == 1
        assert target.read_text() == "original\n"


# ---------------------------------------------------------------------------
# apply() v2 — Mixed New + Existing
# ---------------------------------------------------------------------------


class TestApplyMixed:
    @pytest.mark.asyncio
    async def test_mixed_new_and_existing_files(
        self, agent: McpActionAgent, tmp_path: Path
    ) -> None:
        existing = tmp_path / "exist.py"
        existing.write_text("x = 1\n", encoding="utf-8")

        diff = json.dumps({"patches": [
            {
                "file_path": "new.py",
                "unified_diff": "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+y = 2\n",
            },
            {
                "file_path": "exist.py",
                "unified_diff": "--- a/exist.py\n+++ b/exist.py\n@@ -1 +1 @@\n-x = 1\n+x = 99\n",
            },
        ]})
        result = await agent.apply(diff)
        assert result.exit_code == 0
        assert len(result.modified_files) == 2
        assert (tmp_path / "new.py").exists()
        assert (tmp_path / "exist.py").read_text() == "x = 99\n"


# ---------------------------------------------------------------------------
# run_tests() tests
# ---------------------------------------------------------------------------


class TestRunTests:
    @pytest.mark.asyncio
    async def test_blocks_path_traversal(self, agent: McpActionAgent) -> None:
        result = await agent.run_tests(["../../etc/evil.py"])
        assert result.exit_code == 1
        assert "traversal" in result.stderr

    @pytest.mark.asyncio
    async def test_blocks_flag_injection(self, agent: McpActionAgent) -> None:
        result = await agent.run_tests(["--collect-only"])
        assert result.exit_code == 1
        assert "flag injection" in result.stderr

    @pytest.mark.asyncio
    async def test_timeout_returns_124(self, agent: McpActionAgent) -> None:
        with patch.object(agent, "_run_subprocess", side_effect=subprocess.TimeoutExpired("cmd", 300)):
            result = await agent.run_tests()
        assert result.exit_code == 124
        assert "timed out" in result.stderr

    @pytest.mark.asyncio
    async def test_os_error(self, agent: McpActionAgent) -> None:
        with patch.object(agent, "_run_subprocess", side_effect=OSError("not found")):
            result = await agent.run_tests()
        assert result.exit_code == 1
        assert "not found" in result.stderr

    @pytest.mark.asyncio
    async def test_uses_sys_executable(self, agent: McpActionAgent) -> None:
        import sys
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        with patch.object(agent, "_run_subprocess", return_value=mock_proc) as mock_run:
            await agent.run_tests()
            assert mock_run.call_args.args[0][0] == sys.executable


# ---------------------------------------------------------------------------
# rollback() tests
# ---------------------------------------------------------------------------


class TestRollback:
    @pytest.mark.asyncio
    async def test_failure_returns_execution_result(
        self, agent: McpActionAgent
    ) -> None:
        with patch.object(agent._diff, "rollback", side_effect=RuntimeError("stash gone")):
            result = await agent.rollback("abc123")
        assert result.exit_code == 1
        assert "stash gone" in result.stderr


# ---------------------------------------------------------------------------
# Import safety
# ---------------------------------------------------------------------------


class TestImportSafety:
    def test_no_circular_import(self) -> None:
        from graqle.workflow.mcp_agent import McpActionAgent
        from graqle.plugins.mcp_dev_server import KogniDevServer
        assert McpActionAgent is not None
        assert KogniDevServer is not None
