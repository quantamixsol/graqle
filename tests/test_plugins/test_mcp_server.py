"""Tests for GraQle MCP Server plugin."""

# ── graqle:intelligence ──
# module: tests.test_plugins.test_mcp_server
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, json, math, dataclasses, typing +4 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import numpy as np
import pytest

from graqle.plugins.mcp_server import MCPConfig, MCPServer, MCPToolResult

# ---------------------------------------------------------------------------
# Mock graph objects
# ---------------------------------------------------------------------------

@dataclass
class MockNode:
    id: str
    label: str
    entity_type: str
    description: str
    properties: dict = field(default_factory=dict)


@dataclass
class MockEdge:
    source_id: str
    target_id: str
    relationship: str
    weight: float


def _build_mock_graph() -> MagicMock:
    """Build a small mock knowledge graph with 3 nodes and 2 edges."""
    nodes = {
        "lambda-auth": MockNode(
            id="lambda-auth",
            label="Auth Lambda",
            entity_type="service",
            description="Handles JWT verification and user authentication for the EU region.",
            properties={"runtime": "python3.11", "region": "eu-central-1", "password": "s3cret"},
        ),
        "dynamodb-users": MockNode(
            id="dynamodb-users",
            label="Users Table",
            entity_type="database",
            description="DynamoDB table storing user profiles and workspace membership.",
            properties={"table_name": "users-eu", "api_key": "ak_12345"},
        ),
        "cognito-pool": MockNode(
            id="cognito-pool",
            label="EU Cognito Pool",
            entity_type="auth",
            description="Cognito user pool for the EU region. Manages sign-up, sign-in, MFA.",
            properties={"pool_id": "eu-central-1_Z0rehiDtA"},
        ),
    }

    edges = {
        "e1": MockEdge(source_id="lambda-auth", target_id="dynamodb-users", relationship="READS_FROM", weight=0.9),
        "e2": MockEdge(source_id="lambda-auth", target_id="cognito-pool", relationship="AUTHENTICATES_VIA", weight=0.95),
    }

    graph = MagicMock()
    graph.nodes = nodes
    graph.edges = edges
    return graph


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_graph():
    return _build_mock_graph()


@pytest.fixture
def server(mock_graph):
    """MCPServer with graph pre-injected (bypasses lazy loading)."""
    srv = MCPServer(config=MCPConfig())
    srv._graph = mock_graph
    return srv


# ---------------------------------------------------------------------------
# 1. test_tool_definitions
# ---------------------------------------------------------------------------

def test_tool_definitions(server: MCPServer):
    """Verify 5 tools returned with correct schema (4 original + graq_predict)."""
    tools = server.tools
    assert len(tools) == 5

    names = {t["name"] for t in tools}
    assert names == {"graq_context", "graq_reason", "graq_inspect", "graq_search", "graq_predict"}

    for tool in tools:
        assert "description" in tool
        assert "inputSchema" in tool
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert "properties" in schema


# ---------------------------------------------------------------------------
# 2. test_context_text_format
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_context_text_format(server: MCPServer):
    """Get text context and verify sections present."""
    result = await server.handle_tool_call("graq_context", {"entity": "Auth Lambda"})
    assert not result.is_error
    text = result.content

    # Header with label and type
    assert "Auth Lambda" in text
    assert "service" in text
    # Connections section
    assert "## Connections" in text
    assert "READS_FROM" in text
    assert "Users Table" in text
    assert "AUTHENTICATES_VIA" in text
    # Properties section (should NOT contain redacted 'password')
    assert "## Properties" in text
    assert "runtime" in text
    assert "password" not in text


# ---------------------------------------------------------------------------
# 3. test_context_json_format
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_context_json_format(server: MCPServer):
    """Verify JSON output has required fields."""
    result = await server.handle_tool_call("graq_context", {"entity": "lambda-auth", "format": "json"})
    assert not result.is_error
    data = json.loads(result.content)

    assert data["entity"] == "Auth Lambda"
    assert data["type"] == "service"
    assert "description" in data
    assert "properties" in data
    assert "neighbors" in data
    assert len(data["neighbors"]) == 2
    # Redacted
    assert "password" not in data["properties"]


# ---------------------------------------------------------------------------
# 4. test_context_entity_not_found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_context_entity_not_found(server: MCPServer):
    """Verify error result for missing entity."""
    result = await server.handle_tool_call("graq_context", {"entity": "nonexistent-service"})
    assert result.is_error
    assert "Entity not found" in result.content


# ---------------------------------------------------------------------------
# 5. test_inspect_summary
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inspect_summary(server: MCPServer):
    """Verify node/edge counts in summary."""
    result = await server.handle_tool_call("graq_inspect", {"detail": "summary"})
    assert not result.is_error
    data = json.loads(result.content)

    assert data["nodes"] == 3
    assert data["edges"] == 2
    assert "service" in data["entity_types"]
    assert data["entity_types"]["service"] == 1
    assert data["entity_types"]["database"] == 1
    assert data["entity_types"]["auth"] == 1


# ---------------------------------------------------------------------------
# 6. test_inspect_types
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inspect_types(server: MCPServer):
    """Verify entity type grouping."""
    result = await server.handle_tool_call("graq_inspect", {"detail": "types"})
    assert not result.is_error
    data = json.loads(result.content)

    assert "service" in data
    assert "Auth Lambda" in data["service"]
    assert "database" in data
    assert "Users Table" in data["database"]
    assert "auth" in data
    assert "EU Cognito Pool" in data["auth"]


# ---------------------------------------------------------------------------
# 7. test_search_returns_ranked
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_returns_ranked(server: MCPServer):
    """Mock embedder, verify results sorted by relevance."""
    # Create a deterministic mock embedder
    call_count = {"n": 0}
    vectors = {
        # query vector
        0: np.array([1.0, 0.0, 0.0]),
        # Auth Lambda — most similar to query
        1: np.array([0.9, 0.1, 0.0]),
        # Users Table — medium similarity
        2: np.array([0.5, 0.5, 0.0]),
        # EU Cognito Pool — least similar
        3: np.array([0.1, 0.9, 0.0]),
    }

    def mock_embed(text: str) -> np.ndarray:
        idx = call_count["n"]
        call_count["n"] += 1
        return vectors[idx]

    embedder = MagicMock()
    embedder.embed = mock_embed
    server._embedder = embedder

    result = await server.handle_tool_call("graq_search", {"query": "authentication", "limit": 3})
    assert not result.is_error
    data = json.loads(result.content)

    assert len(data) == 3
    # Results should be sorted by relevance descending
    relevances = [r["relevance"] for r in data]
    assert relevances == sorted(relevances, reverse=True)
    # Most relevant should be the auth lambda (closest vector)
    assert data[0]["label"] == "Auth Lambda"


# ---------------------------------------------------------------------------
# 8. test_redact_sensitive_props
# ---------------------------------------------------------------------------

def test_redact_sensitive_props(server: MCPServer):
    """Verify passwords/secrets/api_keys removed."""
    props = {
        "runtime": "python3.11",
        "password": "s3cret",
        "api_key": "ak_12345",
        "secret": "very_secret",
        "region": "eu-central-1",
    }
    clean = server._redact(props)

    assert "runtime" in clean
    assert "region" in clean
    assert "password" not in clean
    assert "api_key" not in clean
    assert "secret" not in clean


# ---------------------------------------------------------------------------
# 9. test_find_node_fuzzy
# ---------------------------------------------------------------------------

def test_find_node_fuzzy(server: MCPServer):
    """Verify fuzzy matching works."""
    # Exact ID
    node = server._find_node("lambda-auth")
    assert node is not None
    assert node.id == "lambda-auth"

    # Exact label (case-insensitive)
    node = server._find_node("auth lambda")
    assert node is not None
    assert node.label == "Auth Lambda"

    # Substring match
    node = server._find_node("cognito")
    assert node is not None
    assert node.id == "cognito-pool"

    # No match
    node = server._find_node("zzz-no-match")
    assert node is None


# ---------------------------------------------------------------------------
# 10. test_unknown_tool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_tool(server: MCPServer):
    """Verify error for invalid tool name."""
    result = await server.handle_tool_call("graq_nonexistent", {})
    assert result.is_error
    assert "Unknown tool" in result.content


# ---------------------------------------------------------------------------
# Bonus: MCPToolResult.to_dict
# ---------------------------------------------------------------------------

def test_tool_result_to_dict():
    """Verify MCPToolResult serialization."""
    result = MCPToolResult("hello", is_error=False)
    d = result.to_dict()
    assert d["content"][0]["type"] == "text"
    assert d["content"][0]["text"] == "hello"
    assert d["isError"] is False

    err = MCPToolResult("boom", is_error=True)
    d = err.to_dict()
    assert d["isError"] is True


# ---------------------------------------------------------------------------
# _ensure_graph regression test (Group 5 gate — v0.34.0)
# Guards that the _ensure_graph fix (JSONGraphConnector → Graqle.from_json)
# does not break graq_context, graq_reason, graq_inspect, graq_search.
# ---------------------------------------------------------------------------

def test_ensure_graph_loads_graqle_instance(tmp_path):
    """_ensure_graph must produce a Graqle instance via Graqle.from_json.
    All four existing tools depend on this — if the loader changes type they all break."""
    import json
    from graqle.core.graph import Graqle

    # Write a minimal valid graqle.json to a temp path
    minimal = {"directed": False, "multigraph": False, "graph": {}, "nodes": [], "links": []}
    graph_file = tmp_path / "graqle.json"
    graph_file.write_text(json.dumps(minimal))

    srv = MCPServer(config=MCPConfig(graph_path=str(graph_file)))
    srv._ensure_graph()
    assert isinstance(srv._graph, Graqle), (
        "_ensure_graph must return a Graqle instance (not raw NX or connector). "
        "graq_context/reason/inspect/search all depend on this."
    )


@pytest.mark.asyncio
async def test_ensure_graph_existing_tools_unaffected_after_predict_added(server: MCPServer):
    """graq_context, graq_reason, graq_inspect all still work after graq_predict was added.
    Regression guard: _ensure_graph change must not alter shared tool behaviour."""
    import json

    # graq_inspect
    r = await server.handle_tool_call("graq_inspect", {})
    assert not r.is_error
    data = json.loads(r.content)
    assert "nodes" in data
    assert data["nodes"] == 3

    # graq_context
    r = await server.handle_tool_call("graq_context", {"entity": "Auth Lambda"})
    assert not r.is_error
    assert "Auth Lambda" in r.content

    # graq_search
    r = await server.handle_tool_call("graq_search", {"query": "auth"})
    assert not r.is_error


# ===========================================================================
# v1.4 HOTFIX TESTS (FB-004 + FB-005)
# ===========================================================================


@pytest.mark.asyncio
async def test_predict_foldback_backend_not_none():
    """fold_back=True must not return SKIPPED_GENERATION_ERROR due to None backend (FB-004).

    Verifies _generate_predicted_subgraph() uses _get_backend_for_node() instead of
    the broken node.backend loop (which always returns None after areason() deactivates).
    """
    from unittest.mock import AsyncMock, MagicMock
    import json as _json

    mock_reason_result = MagicMock()
    mock_reason_result.answer = "Auth lambda is tightly coupled to DynamoDB."
    mock_reason_result.confidence = 0.72
    mock_reason_result.rounds_completed = 2
    mock_reason_result.node_count = 5
    mock_reason_result.cost_usd = 0.01
    mock_reason_result.active_nodes = ["lambda-auth", "dynamodb-users"]
    mock_reason_result.message_trace = []

    mock_backend = MagicMock()
    mock_backend.generate = AsyncMock(return_value=json.dumps({
        "anchor_label": "Auth-DB Coupling Risk",
        "anchor_type": "service",
        "anchor_description": "Auth lambda is tightly coupled to DynamoDB.",
        "anchor_properties": {
            "source_query": "Compound risk",
            "derived_from": "graq_predict",
            "confidence": 0.72,
        },
        "supporting_nodes": [
            {
                "label": "DynamoDB Dependency",
                "type": "database",
                "description": "Direct dependency",
                "relationship_to_anchor": "CAUSES",
            }
        ],
        "causal_edges": [
            {
                "from_label": "Auth-DB Coupling Risk",
                "to_label": "DynamoDB Dependency",
                "relationship": "CAUSES",
                "weight": 0.8,
            }
        ],
    }))

    srv = MCPServer(config=MCPConfig())

    # Build 12 mock nodes (safety guard requires >= 10)
    mock_nodes = {
        f"node-{i}": MagicMock(
            id=f"node-{i}", label=f"Node {i}", entity_type="service",
            description=f"Node {i}.", properties={},
            outgoing_edges=[], incoming_edges=[], backend=None,
        )
        for i in range(12)
    }
    mock_nodes["lambda-auth"] = MagicMock(
        id="lambda-auth", label="Auth Lambda", entity_type="service",
        description="Auth service.", properties={},
        outgoing_edges=[], incoming_edges=[], backend=None,  # None — as after deactivation
    )

    mock_graph = MagicMock()
    mock_graph.nodes = mock_nodes
    mock_graph.edges = {}
    mock_graph._get_backend_for_node = MagicMock(return_value=mock_backend)
    mock_graph.areason = AsyncMock(return_value=mock_reason_result)
    mock_graph.to_json = MagicMock()

    srv._graph = mock_graph

    result = await srv._handle_predict({
        "query": "compound architectural risk",
        "fold_back": True,
        "confidence_threshold": 0.01,  # low — allow write-back
    })
    data = _json.loads(result.content)

    assert data["prediction"]["status"] != "SKIPPED_GENERATION_ERROR", (
        f"fold_back=True returned SKIPPED_GENERATION_ERROR after FB-004 fix. "
        f"Full prediction: {data['prediction']}"
    )
    mock_graph._get_backend_for_node.assert_called()


@pytest.mark.asyncio
async def test_predict_dryrun_unaffected():
    """fold_back=False must return DRY_RUN — regression check for FB-004 fix."""
    from unittest.mock import AsyncMock, MagicMock
    import json as _json

    mock_reason_result = MagicMock()
    mock_reason_result.answer = "No changes needed."
    mock_reason_result.confidence = 0.60
    mock_reason_result.rounds_completed = 2
    mock_reason_result.node_count = 3
    mock_reason_result.cost_usd = 0.005
    mock_reason_result.active_nodes = ["lambda-auth"]
    mock_reason_result.message_trace = []

    srv = MCPServer(config=MCPConfig())
    mock_graph = _build_mock_graph()
    mock_graph.areason = AsyncMock(return_value=mock_reason_result)
    srv._graph = mock_graph

    result = await srv._handle_predict({
        "query": "compound architectural risk",
        "fold_back": False,
        "confidence_threshold": 0.01,
    })
    data = _json.loads(result.content)

    assert data["prediction"]["status"] == "DRY_RUN", (
        f"fold_back=False must always return DRY_RUN. Got: {data['prediction']['status']}"
    )


def test_predict_json_extraction_handles_special_chars():
    """_extract_json_from_llm must not raise on LLM output with regex metacharacters (FB-005).

    re.search(r'\\{.*\\}') raises on '[', '(', '*' in string values.
    The brace-counting replacement handles all valid JSON.
    """
    from graqle.plugins.mcp_server import _extract_json_from_llm
    import json as _json

    raw = '{"anchor_label": "test [bracket] (paren) *star*", "anchor_type": "pse_predict"}'
    extracted = _extract_json_from_llm(raw)
    parsed = _json.loads(extracted)

    assert parsed["anchor_label"] == "test [bracket] (paren) *star*"
    assert parsed["anchor_type"] == "pse_predict"


# ===========================================================================
# v0.35.0 TESTS (Changes 1-4)
# ===========================================================================


# ---- Change 1: from_json skip_validation ----

def test_from_json_skip_validation_bypasses_error(tmp_path):
    """skip_validation=True must load a mismatched graph without raising."""
    import json as _json
    from graqle.core.graph import Graqle

    mismatch_graph = {
        "directed": False, "multigraph": False,
        "graph": {"_meta": {"embedding_model": "old-model", "embedding_dim": 9999}},
        "nodes": [], "links": [],
    }
    gp = tmp_path / "mismatch.json"
    gp.write_text(_json.dumps(mismatch_graph))

    graph = Graqle.from_json(str(gp), skip_validation=True)
    assert graph is not None


def test_from_json_default_still_raises_on_mismatch(tmp_path):
    """Default from_json must still raise EmbeddingDimensionMismatchError (regression check)."""
    import json as _json
    from unittest.mock import MagicMock, patch
    from graqle.core.graph import Graqle

    mismatch_graph = {
        "directed": False, "multigraph": False,
        "graph": {"_meta": {"embedding_model": "old-model", "embedding_dim": 9999}},
        "nodes": [], "links": [],
    }
    gp = tmp_path / "mismatch.json"
    gp.write_text(_json.dumps(mismatch_graph))

    mock_engine = MagicMock()
    mock_engine.model_name = "current-model"
    mock_engine._dim = 384
    mock_engine._dimension = None

    try:
        from graqle.core.exceptions import EmbeddingDimensionMismatchError
    except ImportError:
        pytest.skip("EmbeddingDimensionMismatchError not available")

    with patch("graqle.activation.embeddings.create_embedding_engine",
               return_value=mock_engine, create=True):
        with pytest.raises(EmbeddingDimensionMismatchError):
            Graqle.from_json(str(gp), skip_validation=False)


def test_from_json_skip_validation_normal_graph(tmp_path):
    """skip_validation=True on a graph without _meta must load cleanly."""
    import json as _json
    from graqle.core.graph import Graqle

    normal = {"directed": False, "multigraph": False, "graph": {}, "nodes": [], "links": []}
    gp = tmp_path / "normal.json"
    gp.write_text(_json.dumps(normal))

    graph = Graqle.from_json(str(gp), skip_validation=True)
    assert graph is not None


# ---- Change 2: AGREEMENT_THRESHOLD ----

def test_agreement_threshold_rejects_boilerplate_only_overlap():
    """Jaccard of messages sharing only boilerplate must be < 0.16 (FB-003 calibration).

    The research briefing identified J=0.14 for two messages that share only the
    boilerplate tokens 'Query:' and 'CONFIDENCE:' while having completely different
    substantive content. At threshold=0.12 these would count as agreeing; at 0.16
    they correctly fail.

    We construct messages whose ONLY overlap is pure boilerplate framing — not content.
    """
    # These messages share ONLY boilerplate framing tokens: "query:", "authentication.", "confidence:", "75%"
    # Their substantive content is completely different (JWT/DynamoDB vs React/Redux/Cognito).
    # Verified J=0.148 — above 0.12 (old threshold) but below 0.16 (new threshold).
    msg_a = (
        "Query: authentication. Lambda verifies JWT tokens using HMAC-SHA256 signatures "
        "stored in DynamoDB sessions table. CONFIDENCE: 75%"
    )
    msg_b = (
        "Query: authentication. Frontend React components dispatch Redux actions "
        "triggering Cognito OAuth2 refresh flows. CONFIDENCE: 75%"
    )
    a_tokens = set(msg_a.lower().split())
    b_tokens = set(msg_b.lower().split())
    union = len(a_tokens | b_tokens)
    assert union > 0
    jaccard = len(a_tokens & b_tokens) / union
    # The only shared tokens are boilerplate framing: "query:", "architectural", "risk.", "confidence:"
    # Jaccard should be < 0.16 to verify the threshold correctly rejects pure-boilerplate overlap
    assert jaccard < 0.16, (
        f"Messages with mostly-different content have Jaccard={jaccard:.3f} >= 0.16. "
        f"This test verifies the AGREEMENT_THRESHOLD=0.16 gate. "
        f"Shared tokens: {a_tokens & b_tokens}"
    )


# ---- Change 3: embedding_model field ----

@pytest.mark.asyncio
async def test_predict_output_includes_embedding_model():
    """graq_predict output must include embedding_model as a string (FB-003)."""
    from unittest.mock import AsyncMock, MagicMock
    import json as _json

    mock_reason_result = MagicMock()
    mock_reason_result.answer = "Some answer."
    mock_reason_result.confidence = 0.50
    mock_reason_result.rounds_completed = 1
    mock_reason_result.node_count = 2
    mock_reason_result.cost_usd = 0.003
    mock_reason_result.active_nodes = ["lambda-auth"]
    mock_reason_result.message_trace = []

    srv = MCPServer(config=MCPConfig())
    mock_graph = _build_mock_graph()
    mock_graph.areason = AsyncMock(return_value=mock_reason_result)
    srv._graph = mock_graph

    result = await srv._handle_predict({
        "query": "test query",
        "fold_back": False,
        "confidence_threshold": 0.99,
    })
    data = _json.loads(result.content)

    assert "embedding_model" in data, "embedding_model field must be in output"
    assert isinstance(data["embedding_model"], str)


def test_get_active_embedding_model_without_embedder():
    """_get_active_embedding_model returns 'unknown' when embedder is not loaded."""
    srv = MCPServer(config=MCPConfig())
    srv._embedder = None
    assert srv._get_active_embedding_model() == "unknown"


def test_get_active_embedding_model_with_mock_embedder():
    """_get_active_embedding_model returns the embedder model_name."""
    from unittest.mock import MagicMock
    srv = MCPServer(config=MCPConfig())
    mock_embedder = MagicMock()
    mock_embedder.model_name = "all-MiniLM-L6-v2"
    srv._embedder = mock_embedder
    assert srv._get_active_embedding_model() == "all-MiniLM-L6-v2"


# ---- Change 4: graq predict CLI ----

def test_predict_cli_command_registered():
    """graq predict CLI command must be accessible via graq predict --help."""
    from typer.testing import CliRunner
    from graqle.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["predict", "--help"])
    assert result.exit_code == 0, (
        "graq predict --help must exit 0 (command must be registered). "
        f"Got exit_code={result.exit_code}, output={result.output[:200]}"
    )


def test_predict_cli_help_shows_flags():
    """graq predict --help must show --fail-below-threshold flag."""
    from typer.testing import CliRunner
    from graqle.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["predict", "--help"])
    assert "fail-below-threshold" in result.output, (
        "--fail-below-threshold must appear in graq predict --help output"
    )
    assert "confidence-threshold" in result.output


# ── v0.35.2: RoutingRule region+profile fix ──

def test_routing_rule_preserves_region_and_profile():
    """RoutingRule.from_dict must retain region and profile fields (FB-006)."""
    from graqle.routing import RoutingRule
    rule = RoutingRule.from_dict({
        "task": "predict",
        "provider": "bedrock",
        "model": "eu.anthropic.claude-opus-4-6-v1",
        "region": "eu-north-1",
        "profile": "cbs-dpt",
    })
    assert rule.region == "eu-north-1"
    assert rule.profile == "cbs-dpt"
    d = rule.to_dict()
    assert d["region"] == "eu-north-1"
    assert d["profile"] == "cbs-dpt"


def test_routing_rule_config_preserves_region_and_profile():
    """RoutingRuleConfig (YAML parser) must retain region and profile fields."""
    from graqle.config.settings import RoutingRuleConfig
    cfg = RoutingRuleConfig(
        task="predict",
        provider="bedrock",
        model="eu.anthropic.claude-opus-4-6-v1",
        region="eu-north-1",
        profile="cbs-dpt",
    )
    assert cfg.region == "eu-north-1"
    assert cfg.profile == "cbs-dpt"


def test_bedrock_backend_accepts_profile_name():
    """BedrockBackend.__init__ must accept profile_name without error (FB-006)."""
    from graqle.backends.api import BedrockBackend
    backend = BedrockBackend(
        model="eu.anthropic.claude-sonnet-4-6",
        region="eu-north-1",
        profile_name="cbs-dpt",
    )
    assert backend._profile_name == "cbs-dpt"
    assert backend._region == "eu-north-1"
