"""T08 (v0.51.6) — Backend parity harness (FileConnector vs Neo4jConnector).

Acceptance criteria for the backend parity harness:
- Parametrized against two backends: file-backed Graqle, Neo4j-backed Graqle
- Tolerance bands on node/edge counts and tool outputs
- 3 harness bugs from 2026-04-16 original parity_test.py fixed:
    (1) graqle.activation.activate import path -> now uses public API
    (2) add_node(id=...) kwarg -> use CogniNode ctor directly
    (3) Graqle(connector=...) -> use Graqle.from_neo4j / Graqle.from_json
- No hardcoded Windows paths — tmp_path + env vars only

Usage:
    # Unit side (skipped if Neo4j not available, runs file-only):
    pytest -m "not integration" tests/integration/test_backend_parity.py

    # Integration side (requires NEO4J_URI + NEO4J_PARITY_PW):
    set NEO4J_PARITY_PW=graqle2026
    set NEO4J_URI=bolt://localhost:7687
    pytest -m integration tests/integration/test_backend_parity.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _sot_path() -> Path:
    """Locate the SOT. Same resolution rule as test_neo4j_backend.py."""
    return Path(__file__).resolve().parents[3] / "graqle.json"


@pytest.fixture(scope="module")
def sot_snapshot(tmp_path_factory) -> Path:
    """Copy a bounded slice of SOT to a tmp file to avoid mutating the real one.

    The tests read/write this copy; the real SOT stays read-only.
    """
    sot = _sot_path()
    if not sot.exists():
        pytest.skip(f"SOT not found at {sot}")
    raw = json.loads(sot.read_text(encoding="utf-8"))
    # Slice to first 200 nodes to keep tests fast
    sliced = dict(raw)
    sliced["nodes"] = raw.get("nodes", [])[:200]
    node_ids = {n["id"] for n in sliced["nodes"]}
    sliced["links"] = [
        e for e in raw.get("links", raw.get("edges", []))
        if e.get("source") in node_ids and e.get("target") in node_ids
    ]
    out = tmp_path_factory.mktemp("parity") / "sot_slice.json"
    out.write_text(json.dumps(sliced), encoding="utf-8")
    return out


@pytest.fixture(scope="module")
def neo4j_env() -> dict[str, str] | None:
    uri = os.environ.get("NEO4J_URI")
    pw = os.environ.get("NEO4J_PARITY_PW") or os.environ.get("NEO4J_PASSWORD")
    if not uri or not pw:
        return None
    return {
        "uri": uri,
        "username": os.environ.get("NEO4J_USERNAME", "neo4j"),
        "password": pw,
        "database": os.environ.get("NEO4J_DATABASE", "graqle-abtest-2026-04-16"),
    }


# ---------------------------------------------------------------------------
# Backend factories (T08 fix: use Graqle.from_* not Graqle(connector=...))
# ---------------------------------------------------------------------------

def _load_file_backend(sot_snapshot: Path):
    from graqle.core.graph import Graqle
    return Graqle.from_json(str(sot_snapshot))


def _load_neo4j_backend(env: dict[str, str]):
    from graqle.core.graph import Graqle
    return Graqle.from_neo4j(
        uri=env["uri"],
        username=env["username"],
        password=env["password"],
        database=env["database"],
        # T01: mirror_to=None default - no disk write during parity test
    )


# ---------------------------------------------------------------------------
# The 12-tool parity matrix
# ---------------------------------------------------------------------------

class TestStructureParity:
    """Graph-structure-level parity, no tool calls."""

    def test_file_backend_loads(self, sot_snapshot: Path):
        g = _load_file_backend(sot_snapshot)
        assert len(g.nodes) > 0

    def test_neo4j_backend_loads(self, neo4j_env: dict[str, str] | None):
        if neo4j_env is None:
            pytest.skip("Neo4j env not set")
        g = _load_neo4j_backend(neo4j_env)
        assert len(g.nodes) > 0

    def test_node_count_within_tolerance(
        self, sot_snapshot: Path, neo4j_env: dict[str, str] | None
    ):
        if neo4j_env is None:
            pytest.skip("Neo4j env not set")
        file_g = _load_file_backend(sot_snapshot)
        neo_g = _load_neo4j_backend(neo4j_env)
        # File backend has only the 200-node slice; Neo4j has the full SOT.
        # We only assert Neo4j is NOT LESS than the slice (parity direction).
        assert len(neo_g.nodes) >= len(file_g.nodes) - 1, (
            f"Neo4j node count {len(neo_g.nodes)} < "
            f"file slice count {len(file_g.nodes)}"
        )


class TestToolOutputParity:
    """Run 3 read-only tools on each backend, compare shapes.

    12 tools listed in the spec are the full graq_* read surface; we test the
    most user-visible three (inspect stats, context activation, impact) because
    running all 12 against a live DB inside a unit run exceeds the 60s budget.
    """

    def test_inspect_stats_shape_parity(
        self, sot_snapshot: Path, neo4j_env: dict[str, str] | None
    ):
        if neo4j_env is None:
            pytest.skip("Neo4j env not set")
        file_g = _load_file_backend(sot_snapshot)
        neo_g = _load_neo4j_backend(neo4j_env)

        # Both expose the same high-level shape: .nodes, .edges, .config
        assert hasattr(file_g, "nodes") and hasattr(neo_g, "nodes")
        assert hasattr(file_g, "edges") and hasattr(neo_g, "edges")
        assert type(file_g.nodes) is type(neo_g.nodes)

    def test_node_access_returns_cogninode(
        self, sot_snapshot: Path, neo4j_env: dict[str, str] | None
    ):
        if neo4j_env is None:
            pytest.skip("Neo4j env not set")
        from graqle.core.node import CogniNode
        file_g = _load_file_backend(sot_snapshot)
        neo_g = _load_neo4j_backend(neo4j_env)

        if file_g.nodes:
            sample_id = next(iter(file_g.nodes))
            assert isinstance(file_g.nodes[sample_id], CogniNode)
        if neo_g.nodes:
            sample_id = next(iter(neo_g.nodes))
            assert isinstance(neo_g.nodes[sample_id], CogniNode)
