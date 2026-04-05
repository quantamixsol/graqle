"""Tests for HFCI-018: tool_hints routing protocol in MCP responses.

Verifies that handle_tool injects tool_hints into every response,
guiding AI callers through the mandatory protocol sequence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graqle.plugins.mcp_dev_server import KogniDevServer


# ---------------------------------------------------------------------------
# Mock objects
# ---------------------------------------------------------------------------

@dataclass
class MockNode:
    id: str
    label: str
    entity_type: str
    description: str
    properties: dict = field(default_factory=dict)
    degree: int = 2
    status: str = "ACTIVE"


@dataclass
class MockStats:
    total_nodes: int = 3
    total_edges: int = 2
    avg_degree: float = 1.33
    density: float = 0.67
    connected_components: int = 1
    hub_nodes: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def server():
    """KogniDevServer with graph pre-injected."""
    srv = KogniDevServer.__new__(KogniDevServer)
    srv.config_path = "graqle.yaml"
    srv.read_only = False
    srv._graph = MagicMock()
    srv._graph.nodes = {
        "auth": MockNode(
            id="auth", label="Auth", entity_type="service",
            description="Auth service",
        ),
    }
    srv._graph.edges = {}
    srv._graph.stats = MockStats()
    srv._config = None
    srv._graph_file = "graqle.json"
    srv._graph_mtime = 9999999999.0
    return srv


# ---------------------------------------------------------------------------
# TestToolHintsMap — static map correctness
# ---------------------------------------------------------------------------

class TestToolHintsMap:
    def test_protocol_sequence_completeness(self):
        """Every mandatory protocol tool has a hints entry."""
        protocol_tools = [
            "graq_inspect", "graq_context", "graq_impact",
            "graq_preflight", "graq_reason", "graq_generate",
        ]
        for tool in protocol_tools:
            assert tool in KogniDevServer._TOOL_HINTS, f"Missing: {tool}"

    def test_sequence_chain_is_linear(self):
        """Each protocol tool hints to the next tool in sequence."""
        expected_chain = [
            ("graq_inspect", "graq_context"),
            ("graq_context", "graq_impact"),
            ("graq_impact", "graq_preflight"),
            ("graq_preflight", "graq_reason"),
            ("graq_reason", "graq_generate"),
            ("graq_generate", "graq_review"),
        ]
        for source, target in expected_chain:
            hints = KogniDevServer._TOOL_HINTS[source]
            assert len(hints) == 1, f"{source} should have exactly 1 hint"
            assert hints[0]["tool"] == target, f"{source} should hint to {target}"

    def test_terminal_tools_have_empty_hints(self):
        """Terminal tools have no next-step hints."""
        assert KogniDevServer._TOOL_HINTS["graq_review"] == []
        assert KogniDevServer._TOOL_HINTS["graq_write"] == []

    def test_all_hints_have_tool_and_reason(self):
        """Every hint has both 'tool' and 'reason' keys."""
        for tool_name, hints in KogniDevServer._TOOL_HINTS.items():
            for hint in hints:
                assert "tool" in hint, f"Missing 'tool' in {tool_name} hint"
                assert "reason" in hint, f"Missing 'reason' in {tool_name} hint"


# ---------------------------------------------------------------------------
# TestInjectToolHints — injection function
# ---------------------------------------------------------------------------

class TestInjectToolHints:
    def test_existing_fields_preserved(self, server):
        """Original response fields survive injection."""
        original = json.dumps({"analysis": "deep", "score": 42})
        result = json.loads(server._inject_tool_hints("graq_inspect", original))
        assert result["analysis"] == "deep"
        assert result["score"] == 42
        assert "tool_hints" in result

    def test_hints_injected_for_protocol_tool(self, server):
        """Protocol tools get their next-step hints."""
        original = json.dumps({"data": "ok"})
        result = json.loads(server._inject_tool_hints("graq_inspect", original))
        assert len(result["tool_hints"]) == 1
        assert result["tool_hints"][0]["tool"] == "graq_context"

    def test_error_response_gets_retry_plus_sequence(self, server):
        """Error responses prepend a retry hint using original tool name."""
        original = json.dumps({"error": "file not found"})
        result = json.loads(server._inject_tool_hints("graq_inspect", original))
        assert result["error"] == "file not found"
        # First hint = retry self (original name), second = next in sequence
        assert result["tool_hints"][0]["tool"] == "graq_inspect"
        assert result["tool_hints"][1]["tool"] == "graq_context"

    def test_kogni_error_retry_uses_original_name(self, server):
        """kogni_* error retry hint preserves original kogni_* name."""
        original = json.dumps({"error": "some error"})
        result = json.loads(server._inject_tool_hints("kogni_inspect", original))
        # Retry uses original name, not normalized
        assert result["tool_hints"][0]["tool"] == "kogni_inspect"
        # Sequence uses graq_* (the canonical hint target)
        assert result["tool_hints"][1]["tool"] == "graq_context"

    def test_kogni_alias_maps_to_graq(self, server):
        """kogni_* aliases get the same hints as graq_* tools."""
        original = json.dumps({"data": "ok"})
        result = json.loads(server._inject_tool_hints("kogni_inspect", original))
        assert result["tool_hints"][0]["tool"] == "graq_context"

    def test_unknown_tool_gets_empty_hints(self, server):
        """Tools not in the map get an empty hints list."""
        original = json.dumps({"data": "ok"})
        result = json.loads(server._inject_tool_hints("graq_unknown", original))
        assert result["tool_hints"] == []

    def test_non_dict_json_passes_through(self, server):
        """Non-dict JSON (arrays, primitives) passes through unchanged."""
        original = json.dumps([1, 2, 3])
        assert server._inject_tool_hints("graq_inspect", original) == original

    def test_malformed_json_passes_through(self, server):
        """Malformed JSON passes through unchanged."""
        original = "not json at all"
        assert server._inject_tool_hints("graq_inspect", original) == original

    def test_read_hints_to_inspect(self, server):
        """graq_read hints to graq_inspect."""
        original = json.dumps({"content": "file data"})
        result = json.loads(server._inject_tool_hints("graq_read", original))
        assert result["tool_hints"][0]["tool"] == "graq_inspect"

    def test_write_has_empty_hints(self, server):
        """graq_write is terminal — no hints."""
        original = json.dumps({"written": True})
        result = json.loads(server._inject_tool_hints("graq_write", original))
        assert result["tool_hints"] == []

    def test_edit_hints_to_review(self, server):
        """graq_edit hints to graq_review."""
        original = json.dumps({"edited": True})
        result = json.loads(server._inject_tool_hints("graq_edit", original))
        assert result["tool_hints"][0]["tool"] == "graq_review"


# ---------------------------------------------------------------------------
# TestHandleToolIntegration — verify hints appear in real tool calls
# ---------------------------------------------------------------------------

class TestHandleToolIntegration:
    @pytest.mark.asyncio
    async def test_inspect_response_has_hints(self, server):
        """A real graq_inspect call includes tool_hints."""
        result = await server.handle_tool("graq_inspect", {"stats": True})
        data = json.loads(result)
        assert "tool_hints" in data
        assert data["tool_hints"][0]["tool"] == "graq_context"

    @pytest.mark.asyncio
    async def test_context_response_has_hints(self, server):
        """A real graq_context call includes tool_hints."""
        with patch.object(server, "_read_active_branch", return_value=None):
            result = await server.handle_tool(
                "graq_context", {"task": "test auth"},
            )
        data = json.loads(result)
        assert "tool_hints" in data
        assert data["tool_hints"][0]["tool"] == "graq_impact"

    @pytest.mark.asyncio
    async def test_error_response_has_retry_hint(self, server):
        """Error responses include retry hint."""
        result = await server.handle_tool("graq_context", {})  # missing 'task'
        data = json.loads(result)
        assert "error" in data
        assert data["tool_hints"][0]["tool"] == "graq_context"  # retry
        assert data["tool_hints"][1]["tool"] == "graq_impact"  # sequence

    @pytest.mark.asyncio
    async def test_unknown_tool_error_has_hints(self, server):
        """Unknown tool error still gets hints (empty list)."""
        result = await server.handle_tool("graq_nonexistent", {})
        data = json.loads(result)
        assert "error" in data
        assert "tool_hints" in data

    @pytest.mark.asyncio
    async def test_kogni_alias_has_hints(self, server):
        """kogni_inspect gets same hints as graq_inspect."""
        result = await server.handle_tool("kogni_inspect", {"stats": True})
        data = json.loads(result)
        assert "tool_hints" in data
        assert data["tool_hints"][0]["tool"] == "graq_context"


# ---------------------------------------------------------------------------
# TestFullChain — end-to-end protocol sequence validation
# ---------------------------------------------------------------------------

class TestFullChain:
    def test_full_chain_hints_form_dag(self, server):
        """Following hints from inspect reaches generate then review."""
        tools_in_order = [
            "graq_inspect", "graq_context", "graq_impact",
            "graq_preflight", "graq_reason", "graq_generate", "graq_review",
        ]
        for i, tool in enumerate(tools_in_order[:-1]):
            original = json.dumps({"step": i})
            result = json.loads(server._inject_tool_hints(tool, original))
            assert result["tool_hints"][0]["tool"] == tools_in_order[i + 1]
