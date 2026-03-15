"""End-to-end integration tests for Graqle."""

# ── graqle:intelligence ──
# module: tests.test_integration.test_end_to_end
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, networkx, graqle, mock, settings
# constraints: none
# ── /graqle:intelligence ──

import networkx as nx
import pytest

from graqle import Graqle
from graqle.backends.mock import MockBackend
from graqle.config.settings import GraqleConfig


@pytest.mark.asyncio
async def test_full_reasoning_pipeline():
    """Test the complete reasoning pipeline: graph → activate → reason → result."""
    # Build a 6-node graph
    G = nx.Graph()
    G.add_node("gdpr", label="GDPR", type="Regulation",
               description="EU data protection regulation")
    G.add_node("ai_act", label="AI Act", type="Regulation",
               description="EU AI regulation framework")
    G.add_node("art22", label="GDPR Art 22", type="Article",
               description="Automated decision-making rights")
    G.add_node("art6", label="AI Act Art 6", type="Article",
               description="High-risk AI classification")
    G.add_node("consent", label="Consent", type="Concept",
               description="Legal basis for processing")
    G.add_node("transparency", label="Transparency", type="Concept",
               description="AI system transparency requirements")

    G.add_edge("gdpr", "art22", relationship="CONTAINS")
    G.add_edge("ai_act", "art6", relationship="CONTAINS")
    G.add_edge("art22", "art6", relationship="CONFLICTS_WITH")
    G.add_edge("gdpr", "consent", relationship="DEFINES")
    G.add_edge("ai_act", "transparency", relationship="REQUIRES")
    G.add_edge("consent", "transparency", relationship="RELATED_TO")

    # Build Graqle
    graph = Graqle.from_networkx(G)
    assert len(graph) == 6

    # Assign mock backend
    backend = MockBackend(responses=[
        "GDPR Art 22 requires human oversight for automated decisions. Confidence: 85%",
        "AI Act Art 6 classifies decision AI as high-risk. Confidence: 78%",
        "Conflict detected between GDPR opt-out and AI Act operation. Confidence: 90%",
    ])
    graph.set_default_backend(backend)

    # Run reasoning
    result = await graph.areason(
        "How do GDPR and AI Act conflict on automated decisions?",
        max_rounds=3,
        strategy="full",
    )

    # Verify result
    assert result.answer  # non-empty
    assert result.confidence > 0
    assert result.rounds_completed >= 1
    assert result.node_count == 6
    assert result.cost_usd >= 0
    assert result.latency_ms >= 0
    assert len(result.message_trace) > 0


@pytest.mark.asyncio
async def test_per_node_backend_assignment():
    """Test that different nodes can use different backends."""
    G = nx.Graph()
    G.add_node("hub", label="Hub Node", type="Hub", description="Central hub")
    G.add_node("leaf1", label="Leaf 1", type="Leaf", description="Peripheral node")
    G.add_node("leaf2", label="Leaf 2", type="Leaf", description="Peripheral node")
    G.add_edge("hub", "leaf1", relationship="CONTAINS")
    G.add_edge("hub", "leaf2", relationship="CONTAINS")

    graph = Graqle.from_networkx(G)

    hub_backend = MockBackend(response="Hub reasoning with smart model. Confidence: 95%")
    leaf_backend = MockBackend(response="Leaf reasoning with cheap model. Confidence: 70%")

    from graqle.core.types import NodeConfig
    graph.configure_nodes({
        "hub": NodeConfig(backend=hub_backend),
        "leaf*": NodeConfig(backend=leaf_backend),
        "*": NodeConfig(backend=leaf_backend),
    })

    result = await graph.areason("test query", strategy="full", max_rounds=2)
    assert result.answer
    assert hub_backend.call_count > 0
    assert leaf_backend.call_count > 0


def test_config_from_yaml(tmp_path):
    """Test YAML config loading."""
    config_content = """
model:
  backend: local
  model: Qwen/Qwen2.5-0.5B-Instruct

graph:
  connector: networkx

orchestration:
  max_rounds: 3
  convergence_threshold: 0.9

domain: regulatory
"""
    config_file = tmp_path / "graqle.yaml"
    config_file.write_text(config_content)

    cfg = GraqleConfig.from_yaml(str(config_file))
    assert cfg.model.model == "Qwen/Qwen2.5-0.5B-Instruct"
    assert cfg.orchestration.max_rounds == 3
    assert cfg.domain == "regulatory"


def test_imports():
    """Test that all public imports work."""
    from graqle import (
        Graqle,
    )
    from graqle.backends import MockBackend
    from graqle.orchestration import Orchestrator

    # All imports successful
    assert Graqle is not None
    assert MockBackend is not None
    assert Orchestrator is not None
