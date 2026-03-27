"""
tests/test_generation/test_graq_generate.py
T1.3 — Tests for _handle_generate() and graq_generate tool registration.
10 tests.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS, KogniDevServer


# ---------------------------------------------------------------------------
# Minimal mock graph + ReasoningResult stand-in
# ---------------------------------------------------------------------------

@dataclass
class _MockReasoningResult:
    answer: str = "--- a/foo.py\n+++ b/foo.py\n@@ -1,1 +1,2 @@\n+# added\n\nSUMMARY: Added comment."
    confidence: float = 0.85
    rounds_completed: int = 1
    active_nodes: list = field(default_factory=lambda: ["SyncEngine", "sync_module"])
    cost_usd: float = 0.001
    latency_ms: float = 500.0
    backend_status: str = "ok"
    backend_error: str | None = None
    reasoning_mode: str = "full"

    @property
    def node_count(self) -> int:
        return len(self.active_nodes)


def _build_mock_graph() -> MagicMock:
    graph = MagicMock()
    graph.nodes = {
        "SyncEngine": MagicMock(label="SyncEngine", entity_type="Class", description="Cloud sync"),
    }
    graph.edges = {}
    graph.areason = AsyncMock(return_value=_MockReasoningResult())
    return graph


@pytest.fixture
def server():
    srv = KogniDevServer.__new__(KogniDevServer)
    srv.config_path = "graqle.yaml"
    srv.read_only = False
    srv._graph = _build_mock_graph()
    srv._config = MagicMock()
    srv._graph_file = "graqle.json"
    srv._graph_mtime = 9999999999.0
    return srv


# ---------------------------------------------------------------------------
# Tool registration tests (T1.4)
# ---------------------------------------------------------------------------

class TestGraqGenerateToolDefinition:
    def test_graq_generate_in_tool_definitions(self) -> None:
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "graq_generate" in names

    def test_kogni_generate_in_tool_definitions(self) -> None:
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "kogni_generate" in names

    def test_graq_generate_has_description_param(self) -> None:
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_generate")
        props = tool["inputSchema"]["properties"]
        assert "description" in props

    def test_graq_generate_description_required(self) -> None:
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_generate")
        assert "description" in tool["inputSchema"]["required"]

    def test_graq_generate_has_dry_run_param(self) -> None:
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_generate")
        assert "dry_run" in tool["inputSchema"]["properties"]


# ---------------------------------------------------------------------------
# Handler behaviour tests (T1.3)
# ---------------------------------------------------------------------------

class TestHandleGenerate:
    @pytest.mark.asyncio
    async def test_missing_description_returns_error(self, server) -> None:
        result = json.loads(await server._handle_generate({}))
        assert "error" in result
        assert "description" in result["error"].lower() or "required" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_returns_patches_list(self, server) -> None:
        with patch("graqle.cloud.credentials.load_credentials") as mock_creds:
            mock_creds.return_value = MagicMock(plan="team")
            with patch.object(server, "_handle_preflight", new=AsyncMock(return_value=json.dumps({
                "risk_level": "low", "warnings": [], "lessons": [], "safety_boundaries": [], "adrs": []
            }))):
                with patch.object(server, "_handle_safety_check", new=AsyncMock(return_value=json.dumps({
                    "overall_risk": "low"
                }))):
                    result = json.loads(await server._handle_generate({
                        "description": "add a docstring to SyncEngine"
                    }))
        assert "patches" in result
        assert isinstance(result["patches"], list)

    @pytest.mark.asyncio
    async def test_result_has_confidence(self, server) -> None:
        with patch("graqle.cloud.credentials.load_credentials") as mock_creds:
            mock_creds.return_value = MagicMock(plan="team")
            with patch.object(server, "_handle_preflight", new=AsyncMock(return_value=json.dumps({
                "risk_level": "low", "warnings": [], "lessons": [], "safety_boundaries": [], "adrs": []
            }))):
                with patch.object(server, "_handle_safety_check", new=AsyncMock(return_value=json.dumps({
                    "overall_risk": "low"
                }))):
                    result = json.loads(await server._handle_generate({
                        "description": "add docstring"
                    }))
        assert "confidence" in result
        assert 0.0 <= result["confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_dry_run_true_by_default(self, server) -> None:
        with patch("graqle.cloud.credentials.load_credentials") as mock_creds:
            mock_creds.return_value = MagicMock(plan="enterprise")
            with patch.object(server, "_handle_preflight", new=AsyncMock(return_value=json.dumps({
                "risk_level": "low", "warnings": [], "lessons": [], "safety_boundaries": [], "adrs": []
            }))):
                with patch.object(server, "_handle_safety_check", new=AsyncMock(return_value=json.dumps({
                    "overall_risk": "low"
                }))):
                    result = json.loads(await server._handle_generate({
                        "description": "add docstring"
                    }))
        assert result.get("dry_run") is True

    @pytest.mark.asyncio
    async def test_free_plan_blocked(self, server) -> None:
        with patch("graqle.cloud.credentials.load_credentials") as mock_creds:
            mock_creds.return_value = MagicMock(plan="free")
            result = json.loads(await server._handle_generate({
                "description": "add docstring"
            }))
        assert result.get("error") == "PLAN_GATE"
        assert "team" in result.get("message", "").lower()
