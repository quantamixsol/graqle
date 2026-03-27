"""
tests/test_generation/test_graq_edit.py
T2.2 — Tests for _handle_edit() and graq_edit tool registration.
10 tests.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS, KogniDevServer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@dataclass
class _MockReasoningResult:
    answer: str = "--- a/foo.py\n+++ b/foo.py\n@@ -1,1 +1,2 @@\n+# added\n\nSUMMARY: Added comment."
    confidence: float = 0.80
    rounds_completed: int = 1
    active_nodes: list = field(default_factory=lambda: ["SyncEngine"])
    cost_usd: float = 0.001
    latency_ms: float = 400.0
    backend_status: str = "ok"
    backend_error: str | None = None
    reasoning_mode: str = "full"

    @property
    def node_count(self) -> int:
        return len(self.active_nodes)


SAMPLE_DIFF = """\
--- a/sample.py
+++ b/sample.py
@@ -1,2 +1,3 @@
 def hello():
+    \"\"\"Say hello.\"\"\"
     return "hi"
"""

SAMPLE_ORIGINAL = 'def hello():\n    return "hi"\n'


@pytest.fixture
def server():
    graph = MagicMock()
    graph.nodes = {"SyncEngine": MagicMock(label="SyncEngine", entity_type="Class", description="sync")}
    graph.edges = {}
    graph.areason = AsyncMock(return_value=_MockReasoningResult())
    srv = KogniDevServer.__new__(KogniDevServer)
    srv.config_path = "graqle.yaml"
    srv.read_only = False
    srv._graph = graph
    srv._config = MagicMock()
    srv._graph_file = "graqle.json"
    srv._graph_mtime = 9999999999.0
    return srv


@pytest.fixture
def tmp_py_file(tmp_path: Path) -> Path:
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_ORIGINAL, encoding="utf-8")
    return f


# ---------------------------------------------------------------------------
# Tool registration tests (T2.3)
# ---------------------------------------------------------------------------

class TestGraqEditToolDefinition:
    def test_graq_edit_in_tool_definitions(self) -> None:
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "graq_edit" in names

    def test_kogni_edit_in_tool_definitions(self) -> None:
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "kogni_edit" in names

    def test_graq_edit_file_path_required(self) -> None:
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_edit")
        assert "file_path" in tool["inputSchema"]["required"]

    def test_graq_edit_has_dry_run_param(self) -> None:
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_edit")
        assert "dry_run" in tool["inputSchema"]["properties"]


# ---------------------------------------------------------------------------
# Handler behaviour tests (T2.2)
# ---------------------------------------------------------------------------

class TestHandleEdit:
    @pytest.mark.asyncio
    async def test_missing_file_path_returns_error(self, server) -> None:
        result = json.loads(await server._handle_edit({}))
        assert "error" in result
        assert "file_path" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_missing_description_and_diff_returns_error(self, server) -> None:
        result = json.loads(await server._handle_edit({"file_path": "foo.py"}))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_free_plan_blocked(self, server) -> None:
        with patch("graqle.cloud.credentials.load_credentials") as mock_creds:
            mock_creds.return_value = MagicMock(plan="free")
            result = json.loads(await server._handle_edit({
                "file_path": "foo.py", "diff": SAMPLE_DIFF
            }))
        assert result.get("error") == "PLAN_GATE"

    @pytest.mark.asyncio
    async def test_dry_run_true_by_default(self, server, tmp_py_file: Path) -> None:
        with patch("graqle.cloud.credentials.load_credentials") as mock_creds:
            mock_creds.return_value = MagicMock(plan="team")
            with patch.object(server, "_handle_preflight", new=AsyncMock(return_value=json.dumps({
                "risk_level": "low", "warnings": [], "lessons": [], "safety_boundaries": [], "adrs": []
            }))):
                result = json.loads(await server._handle_edit({
                    "file_path": str(tmp_py_file),
                    "diff": SAMPLE_DIFF,
                    # dry_run not specified — should default to True
                }))
        assert result.get("dry_run") is True
        # File must NOT be modified
        assert tmp_py_file.read_text() == SAMPLE_ORIGINAL

    @pytest.mark.asyncio
    async def test_dry_run_does_not_write_file(self, server, tmp_py_file: Path) -> None:
        with patch("graqle.cloud.credentials.load_credentials") as mock_creds:
            mock_creds.return_value = MagicMock(plan="enterprise")
            with patch.object(server, "_handle_preflight", new=AsyncMock(return_value=json.dumps({
                "risk_level": "low", "warnings": [], "lessons": [], "safety_boundaries": [], "adrs": []
            }))):
                await server._handle_edit({
                    "file_path": str(tmp_py_file),
                    "diff": SAMPLE_DIFF,
                    "dry_run": True,
                })
        assert tmp_py_file.read_text() == SAMPLE_ORIGINAL

    @pytest.mark.asyncio
    async def test_result_has_success_field(self, server, tmp_py_file: Path) -> None:
        with patch("graqle.cloud.credentials.load_credentials") as mock_creds:
            mock_creds.return_value = MagicMock(plan="team")
            with patch.object(server, "_handle_preflight", new=AsyncMock(return_value=json.dumps({
                "risk_level": "low", "warnings": [], "lessons": [], "safety_boundaries": [], "adrs": []
            }))):
                result = json.loads(await server._handle_edit({
                    "file_path": str(tmp_py_file),
                    "diff": SAMPLE_DIFF,
                    "dry_run": True,
                }))
        assert "success" in result
