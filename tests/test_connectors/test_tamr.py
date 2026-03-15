"""Tests for TAMRConnector — TAMR+ to Graqle pipeline."""

# ── graqle:intelligence ──
# module: tests.test_connectors.test_tamr
# risk: LOW (impact radius: 0 modules)
# dependencies: json, mock, pytest, tamr
# constraints: none
# ── /graqle:intelligence ──

import json

import pytest

from graqle.connectors.tamr import (
    PipelineConfig,
    TAMRConnector,
    TAMRDocument,
    TAMRSubgraph,
)


@pytest.fixture
def sample_tamr_data():
    """Sample TAMR+ output data."""
    return {
        "query": "What are the AI Act requirements?",
        "documents": [
            {
                "doc_id": "doc1",
                "title": "AI Act Article 6",
                "content": "High-risk AI systems shall...",
                "trace_score": 0.9,
                "relevance_score": 0.8,
                "gap_score": 0.3,
                "framework": "EU AI Act",
            },
            {
                "doc_id": "doc2",
                "title": "AI Act Article 9",
                "content": "Risk management system...",
                "trace_score": 0.7,
                "relevance_score": 0.6,
                "gap_score": 0.1,
                "framework": "EU AI Act",
            },
        ],
        "edges": [
            {
                "source": "doc1",
                "target": "doc2",
                "relationship": "CROSS_REF",
                "weight": 0.85,
            }
        ],
        "total_cost": 1.5,
    }


@pytest.fixture
def tamr_json_file(tmp_path, sample_tamr_data):
    """Write sample data to a temp JSON file."""
    path = tmp_path / "tamr_output.json"
    path.write_text(json.dumps(sample_tamr_data))
    return path


def test_load_from_json(tamr_json_file):
    """Load TAMR+ subgraph from JSON file and verify structure."""
    connector = TAMRConnector()
    subgraph = connector.load_from_json(tamr_json_file)

    assert isinstance(subgraph, TAMRSubgraph)
    assert len(subgraph.documents) == 2
    assert len(subgraph.edges) == 1
    assert subgraph.query == "What are the AI Act requirements?"
    assert subgraph.pcst_nodes_selected == 2

    doc1 = subgraph.documents[0]
    assert doc1.doc_id == "doc1"
    assert doc1.title == "AI Act Article 6"
    assert doc1.trace_score == 0.9
    assert doc1.framework == "EU AI Act"


def test_compute_node_prior():
    """Verify weighted TRACE score calculation."""
    config = PipelineConfig(
        trace_weight=0.5,
        relevance_weight=0.3,
        gap_weight=0.2,
    )
    connector = TAMRConnector(config)

    doc = TAMRDocument(
        doc_id="d1",
        title="Test",
        content="",
        trace_score=0.8,
        relevance_score=0.6,
        gap_score=0.4,
    )

    prior = connector.compute_node_prior(doc)
    # 0.5*0.8 + 0.3*0.6 + 0.2*0.4 = 0.4 + 0.18 + 0.08 = 0.66
    assert prior == 0.66


def test_compute_node_prior_clamped():
    """Prior is clamped to [0, 1]."""
    config = PipelineConfig(trace_weight=1.0, relevance_weight=1.0, gap_weight=1.0)
    connector = TAMRConnector(config)

    doc = TAMRDocument(doc_id="d1", title="T", content="",
                       trace_score=1.0, relevance_score=1.0, gap_score=1.0)
    assert connector.compute_node_prior(doc) == 1.0


def test_to_graqle(sample_tamr_data):
    """Convert subgraph to Graqle and verify nodes/edges."""
    connector = TAMRConnector()
    subgraph = connector.load_from_dict(sample_tamr_data)

    graph = connector.to_graqle(subgraph)

    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1
    assert "doc1" in graph.nodes
    assert "doc2" in graph.nodes


def test_trace_priors_injected(sample_tamr_data):
    """Verify activation_prior is injected into node properties."""
    connector = TAMRConnector()
    subgraph = connector.load_from_dict(sample_tamr_data)

    graph = connector.to_graqle(subgraph)

    node1 = graph.nodes["doc1"]
    assert "trace_score" in node1.properties
    assert node1.properties["trace_score"] == 0.9
    assert "activation_prior" in node1.properties
    assert node1.properties["activation_prior"] > 0


def test_load_from_dict(sample_tamr_data):
    """Verify dict parsing matches JSON parsing structure."""
    connector = TAMRConnector()
    subgraph = connector.load_from_dict(sample_tamr_data)

    assert isinstance(subgraph, TAMRSubgraph)
    assert len(subgraph.documents) == 2
    assert subgraph.documents[0].doc_id == "doc1"
    assert subgraph.total_cost == 1.5
    assert subgraph.query == "What are the AI Act requirements?"


@pytest.mark.asyncio
async def test_missing_api_url():
    """retrieve_and_reason raises ValueError without tamr_api_url."""
    connector = TAMRConnector()  # No API URL configured

    with pytest.raises(ValueError, match="tamr_api_url not configured"):
        await connector.retrieve_and_reason("test query")
