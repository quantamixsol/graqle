"""Tests for JSON graph connector."""

import json
import pytest
from pathlib import Path

from graqle.connectors.json_graph import JSONGraphConnector


@pytest.fixture
def json_graph_file(tmp_path):
    """Create a temp JSON graph file."""
    data = {
        "nodes": {
            "n1": {"label": "Node 1", "type": "Concept",
                   "description": "First node", "properties": {}},
            "n2": {"label": "Node 2", "type": "Concept",
                   "description": "Second node", "properties": {}},
        },
        "edges": {
            "e1": {"source": "n1", "target": "n2", "relationship": "RELATED_TO",
                   "weight": 0.8},
        },
    }
    path = tmp_path / "test_graph.json"
    path.write_text(json.dumps(data))
    return str(path)


def test_json_connector_load(json_graph_file):
    """Load graph from JSON file."""
    conn = JSONGraphConnector(json_graph_file)
    nodes, edges = conn.load()
    assert len(nodes) == 2
    assert len(edges) == 1
    assert "n1" in nodes
    assert nodes["n1"]["label"] == "Node 1"


def test_json_connector_validate(json_graph_file):
    """Validate returns True when file exists."""
    conn = JSONGraphConnector(json_graph_file)
    assert conn.validate() is True


def test_json_connector_validate_missing():
    """Validate returns False for missing file."""
    conn = JSONGraphConnector("/nonexistent/path.json")
    assert conn.validate() is False


def test_json_connector_save(json_graph_file, tmp_path):
    """Save graph to JSON file."""
    conn = JSONGraphConnector(json_graph_file)
    nodes, edges = conn.load()
    out_path = tmp_path / "output.json"
    out_conn = JSONGraphConnector(out_path)
    out_conn.save(nodes, edges)
    data = json.loads(out_path.read_text())
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) == 1


def test_json_connector_load_missing():
    """Load raises FileNotFoundError for missing file."""
    conn = JSONGraphConnector("/nonexistent/path.json")
    with pytest.raises(FileNotFoundError):
        conn.load()
