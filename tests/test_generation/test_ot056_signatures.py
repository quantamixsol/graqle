"""
tests/test_generation/test_ot056_signatures.py
OT-056 — Verify graq_generate includes method signatures in LLM context
so the LLM uses exact parameter names instead of abbreviating them.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graqle.plugins.mcp_dev_server import KogniDevServer


# ---------------------------------------------------------------------------
# Mock infrastructure
# ---------------------------------------------------------------------------

def _build_mock_graph_with_signatures() -> MagicMock:
    """Graph with Function nodes that have properties.signature."""
    graph = MagicMock()

    func_node = MagicMock()
    func_node.label = "build_topology"
    func_node.entity_type = "Function"
    func_node.description = "Build governance topology from KG"
    func_node.properties = {
        "signature": "def build_topology(governance_topology: dict, node_filter: str) -> nx.DiGraph",
    }

    class_node = MagicMock()
    class_node.label = "GovernanceEngine"
    class_node.entity_type = "Class"
    class_node.description = "Main governance engine"
    class_node.properties = {
        "signature": "class GovernanceEngine(BaseEngine)",
    }

    module_node = MagicMock()
    module_node.label = "utils"
    module_node.entity_type = "PythonModule"
    module_node.description = "Utility functions"
    module_node.properties = {}

    no_sig_func = MagicMock()
    no_sig_func.label = "helper_func"
    no_sig_func.entity_type = "Function"
    no_sig_func.description = "A helper function"
    no_sig_func.properties = {}  # No signature

    graph.nodes = {
        "build_topology": func_node,
        "GovernanceEngine": class_node,
        "utils": module_node,
        "helper_func": no_sig_func,
    }
    graph.edges = {}
    graph._activate_subgraph = MagicMock(
        return_value=["build_topology", "GovernanceEngine", "utils", "helper_func"]
    )
    graph.config.activation.strategy = "spread"

    _mock_backend = MagicMock()
    _mock_gen_result = MagicMock()
    _mock_gen_result.text = (
        "--- a/gov.py\n+++ b/gov.py\n@@ -1,1 +1,2 @@\n+# added\n"
        "\nSUMMARY: Added comment."
    )
    _mock_gen_result.tokens_used = 100
    _mock_backend.generate = AsyncMock(return_value=_mock_gen_result)
    _mock_backend.cost_per_1k_tokens = 0.003
    graph._get_backend_for_node = MagicMock(return_value=_mock_backend)
    return graph


@pytest.fixture
def server_with_sigs():
    srv = KogniDevServer.__new__(KogniDevServer)
    srv.config_path = "graqle.yaml"
    srv.read_only = False
    srv._graph = _build_mock_graph_with_signatures()
    srv._config = MagicMock()
    srv._graph_file = "graqle.json"
    srv._graph_mtime = 9999999999.0
    return srv


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOT056SignaturesInContext:
    """Verify that Function/Class signatures appear in the LLM prompt."""

    @pytest.mark.asyncio
    async def test_function_signature_in_prompt(self, server_with_sigs) -> None:
        """Backend.generate() call should include the Function signature."""
        with patch("graqle.cloud.credentials.load_credentials") as mock_creds:
            mock_creds.return_value = MagicMock(plan="team")
            with patch.object(server_with_sigs, "_handle_preflight", new=AsyncMock(
                return_value=json.dumps({
                    "risk_level": "low", "warnings": [], "lessons": [],
                    "safety_boundaries": [], "adrs": [],
                })
            )):
                with patch.object(server_with_sigs, "_handle_safety_check", new=AsyncMock(
                    return_value=json.dumps({"overall_risk": "low"})
                )):
                    await server_with_sigs._handle_generate({
                        "description": "add governance check"
                    })

        # Inspect the prompt passed to backend.generate()
        backend = server_with_sigs._graph._get_backend_for_node.return_value
        call_args = backend.generate.call_args
        prompt = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")

        # Should contain the function signature
        assert "governance_topology" in prompt, (
            "LLM prompt must include the full parameter name 'governance_topology' "
            "from the Function node's signature"
        )
        assert "Signature:" in prompt, (
            "LLM prompt must include 'Signature:' label for Function nodes"
        )

    @pytest.mark.asyncio
    async def test_class_signature_in_prompt(self, server_with_sigs) -> None:
        """Backend.generate() call should include the Class signature."""
        with patch("graqle.cloud.credentials.load_credentials") as mock_creds:
            mock_creds.return_value = MagicMock(plan="team")
            with patch.object(server_with_sigs, "_handle_preflight", new=AsyncMock(
                return_value=json.dumps({
                    "risk_level": "low", "warnings": [], "lessons": [],
                    "safety_boundaries": [], "adrs": [],
                })
            )):
                with patch.object(server_with_sigs, "_handle_safety_check", new=AsyncMock(
                    return_value=json.dumps({"overall_risk": "low"})
                )):
                    await server_with_sigs._handle_generate({
                        "description": "add method to GovernanceEngine"
                    })

        backend = server_with_sigs._graph._get_backend_for_node.return_value
        prompt = backend.generate.call_args[0][0]

        assert "GovernanceEngine(BaseEngine)" in prompt

    @pytest.mark.asyncio
    async def test_module_node_no_signature(self, server_with_sigs) -> None:
        """PythonModule nodes should NOT have a Signature: line."""
        with patch("graqle.cloud.credentials.load_credentials") as mock_creds:
            mock_creds.return_value = MagicMock(plan="team")
            with patch.object(server_with_sigs, "_handle_preflight", new=AsyncMock(
                return_value=json.dumps({
                    "risk_level": "low", "warnings": [], "lessons": [],
                    "safety_boundaries": [], "adrs": [],
                })
            )):
                with patch.object(server_with_sigs, "_handle_safety_check", new=AsyncMock(
                    return_value=json.dumps({"overall_risk": "low"})
                )):
                    await server_with_sigs._handle_generate({
                        "description": "modify utils"
                    })

        backend = server_with_sigs._graph._get_backend_for_node.return_value
        prompt = backend.generate.call_args[0][0]

        # Count Signature: lines — should be exactly 2 (func + class), not 3
        sig_count = prompt.count("Signature:")
        assert sig_count >= 1  # At least one Function/Class has a sig
        # The PythonModule "utils" should not have a Signature line
        # Find the utils context line and verify no Signature follows
        lines = prompt.split("\n")
        for i, line in enumerate(lines):
            if "[PythonModule] utils:" in line:
                if i + 1 < len(lines):
                    assert "Signature:" not in lines[i + 1], (
                        "PythonModule nodes must not have a Signature: line"
                    )

    @pytest.mark.asyncio
    async def test_system_prompt_has_exact_names_instruction(self, server_with_sigs) -> None:
        """System prompt must contain the exact-names instruction."""
        with patch("graqle.cloud.credentials.load_credentials") as mock_creds:
            mock_creds.return_value = MagicMock(plan="team")
            with patch.object(server_with_sigs, "_handle_preflight", new=AsyncMock(
                return_value=json.dumps({
                    "risk_level": "low", "warnings": [], "lessons": [],
                    "safety_boundaries": [], "adrs": [],
                })
            )):
                with patch.object(server_with_sigs, "_handle_safety_check", new=AsyncMock(
                    return_value=json.dumps({"overall_risk": "low"})
                )):
                    await server_with_sigs._handle_generate({
                        "description": "add docstring"
                    })

        backend = server_with_sigs._graph._get_backend_for_node.return_value
        prompt = backend.generate.call_args[0][0]

        assert "EXACT parameter names" in prompt, (
            "System prompt must instruct LLM to use exact parameter names"
        )
        assert "never abbreviate" in prompt.lower() or "never rename" in prompt.lower()
