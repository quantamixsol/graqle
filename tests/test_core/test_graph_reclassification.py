"""
tests/test_core/test_graph_reclassification.py
Phase 3 (ADR-128) — Copy-on-write atomic reclassification tests.
Guards against split-brain graph risk (pse-pred-6099a446b482, 94% confidence).
"""
from __future__ import annotations

import networkx as nx
import pytest

from graqle.core.graph import Graqle
from graqle.config.settings import GraqleConfig


def _make_test_graph(node_specs: dict[str, dict], edges: list[tuple[str, str]]) -> Graqle:
    """Create a minimal Graqle instance with given nodes and edges."""
    G = nx.DiGraph()
    for nid, attrs in node_specs.items():
        G.add_node(nid, **attrs)
    for u, v in edges:
        G.add_edge(u, v, edge_type="CALLS")
    config = GraqleConfig.default()
    return Graqle.from_networkx(G, config=config)


class TestReclassifyBatchAtomicity:
    def test_successful_swap_updates_all_nodes(self) -> None:
        """Happy path: all nodes reclassified atomically."""
        graph = _make_test_graph(
            {"a": {"entity_type": "Entity", "label": "graq_reason", "description": "test"},
             "b": {"entity_type": "Entity", "label": "graq_inspect", "description": "test"}},
            [("a", "b")],
        )

        def reclassify(node_data):
            if node_data.get("label", "").startswith("graq_"):
                node_data["entity_type"] = "MCP_TOOL"

        stats = graph.reclassify_batch(reclassify)
        assert stats["reclassified"] == 2
        assert graph.nodes["a"].entity_type == "MCP_TOOL"
        assert graph.nodes["b"].entity_type == "MCP_TOOL"

    def test_partial_failure_preserves_original(self) -> None:
        """Crash at node N → live graph has zero mutations."""
        graph = _make_test_graph(
            {"a": {"entity_type": "Entity", "label": "good", "description": "test"},
             "b": {"entity_type": "Entity", "label": "bad", "description": "test"}},
            [("a", "b")],
        )

        def reclassify(node_data):
            if node_data.get("label") == "bad":
                raise ValueError("Intentional failure")
            node_data["entity_type"] = "MCP_TOOL"

        with pytest.raises(RuntimeError, match="1 node\\(s\\) failed"):
            graph.reclassify_batch(reclassify)

        # Original graph untouched
        assert graph.nodes["a"].entity_type == "Entity"
        assert graph.nodes["b"].entity_type == "Entity"

    def test_skipped_count_for_unchanged_nodes(self) -> None:
        """Nodes where entity_type doesn't change count as skipped."""
        graph = _make_test_graph(
            {"a": {"entity_type": "Entity", "label": "graq_reason", "description": "test"},
             "b": {"entity_type": "Function", "label": "some_function", "description": "test"}},
            [],
        )

        def reclassify(node_data):
            if node_data.get("label", "").startswith("graq_"):
                node_data["entity_type"] = "MCP_TOOL"

        stats = graph.reclassify_batch(reclassify)
        assert stats["reclassified"] == 1
        assert stats["skipped"] == 1
        assert stats["by_type"] == {"MCP_TOOL": 1}

    def test_cache_invalidation_after_swap(self) -> None:
        """_activator and _nx_graph are None post-swap."""
        graph = _make_test_graph(
            {"a": {"entity_type": "Entity", "label": "test", "description": "test"}},
            [],
        )
        # Pre-set caches to non-None
        graph._activator = "cached_value"
        graph._nx_graph = "cached_graph"

        graph.reclassify_batch(lambda nd: None)

        assert graph._activator is None
        assert graph._nx_graph is None

    def test_empty_graph_returns_zero_stats(self) -> None:
        """Empty graph reclassifies without error."""
        graph = Graqle(nodes={}, edges={})
        stats = graph.reclassify_batch(lambda nd: None)
        assert stats == {"reclassified": 0, "skipped": 0, "failed": 0, "by_type": {}}

    def test_reclassification_adds_properties(self) -> None:
        """Reclassification metadata is written to node.properties."""
        graph = _make_test_graph(
            {"a": {"entity_type": "Entity", "label": "graq_reason", "description": "test"}},
            [],
        )

        def reclassify(node_data):
            node_data["entity_type"] = "MCP_TOOL"
            node_data["domain"] = "mcp"
            node_data["reclassification_from"] = "Entity"
            node_data["reclassification_confidence"] = 0.95
            node_data["reclassification_source"] = "name prefix"

        graph.reclassify_batch(reclassify)
        node = graph.nodes["a"]
        assert node.entity_type == "MCP_TOOL"
        assert node.properties.get("domain") == "mcp"
        assert node.properties.get("reclassification_from") == "Entity"
        assert node.properties.get("reclassification_confidence") == 0.95


class TestReclassifyMcpModule:
    def test_reclassify_graq_tools_to_mcp_tool(self) -> None:
        """Pattern match correctness for graq_* prefix."""
        from graqle.scanner.reclassify_mcp import _match_rule

        node = {"entity_type": "Entity", "label": "graq_reason"}
        rule = _match_rule(node)
        assert rule is not None
        assert rule["to_type"] == "MCP_TOOL"

    def test_reclassify_kogni_tools_to_mcp_tool(self) -> None:
        from graqle.scanner.reclassify_mcp import _match_rule

        node = {"entity_type": "Function", "label": "kogni_reason"}
        rule = _match_rule(node)
        assert rule is not None
        assert rule["to_type"] == "MCP_TOOL"

    def test_reclassify_first_match_wins(self) -> None:
        from graqle.scanner.reclassify_mcp import _match_rule

        # "graq_transport" matches graq_ (MCP_TOOL, 0.95) AND transport (0.90)
        # First match should win: MCP_TOOL
        node = {"entity_type": "Entity", "label": "graq_transport"}
        rule = _match_rule(node)
        assert rule is not None
        assert rule["to_type"] == "MCP_TOOL"

    def test_reclassify_skips_already_typed_nodes(self) -> None:
        from graqle.scanner.reclassify_mcp import make_reclassify_fn

        fn, stats = make_reclassify_fn()
        node = {"entity_type": "MCP_TOOL", "label": "graq_reason"}
        fn(node)
        assert stats["skipped"] == 1
        assert stats["reclassified"] == 0

    def test_reclassify_no_match_skips(self) -> None:
        from graqle.scanner.reclassify_mcp import make_reclassify_fn

        fn, stats = make_reclassify_fn()
        node = {"entity_type": "Entity", "label": "some_random_entity"}
        fn(node)
        assert stats["skipped"] == 1

    def test_reclassify_preserves_existing_properties(self) -> None:
        from graqle.scanner.reclassify_mcp import make_reclassify_fn

        fn, stats = make_reclassify_fn()
        node = {"entity_type": "Entity", "label": "graq_reason", "existing_prop": "keep_me"}
        fn(node)
        assert node["entity_type"] == "MCP_TOOL"
        assert node["existing_prop"] == "keep_me"
        assert node["reclassification_from"] == "Entity"

    def test_reclassify_server_pattern(self) -> None:
        from graqle.scanner.reclassify_mcp import _match_rule

        node = {"entity_type": "Class", "label": "McpServer"}
        rule = _match_rule(node)
        assert rule is not None
        assert rule["to_type"] == "MCP_SERVER"

    def test_reclassify_transport_pattern(self) -> None:
        from graqle.scanner.reclassify_mcp import _match_rule

        node = {"entity_type": "Entity", "label": "stdio"}
        rule = _match_rule(node)
        assert rule is not None
        assert rule["to_type"] == "MCP_TRANSPORT"

    def test_make_reclassify_fn_stats_tracking(self) -> None:
        from graqle.scanner.reclassify_mcp import make_reclassify_fn

        fn, stats = make_reclassify_fn()
        fn({"entity_type": "Entity", "label": "graq_reason"})
        fn({"entity_type": "Entity", "label": "graq_inspect"})
        fn({"entity_type": "Entity", "label": "some_other"})

        assert stats["reclassified"] == 2
        assert stats["skipped"] == 1
        assert stats["by_type"] == {"MCP_TOOL": 2}
