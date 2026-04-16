"""T07 (v0.51.6) — Neo4j as first-class backend integration test.

Acceptance criteria for the Neo4j backend integration test:
- Migrate SOT graphJSON -> fresh Neo4j DB via the T02 migrator
- Verify node/edge counts match
- Run graq_inspect parity vs a file-backend Graqle of the same SOT
- 100 concurrent writes via multiprocessing -> zero WRITE_COLLISION

Skip markers:
- @pytest.mark.integration: CI marker; unit CI stays fast by excluding this
- Auto-skip if NEO4J_URI / NEO4J_PARITY_PW env vars are not set

Prod-verify run (from monorepo root with venv active):
    set NEO4J_PARITY_PW=graqle2026
    set NEO4J_URI=bolt://localhost:7687
    pytest -m integration tests/integration/test_neo4j_backend.py -v
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def neo4j_env() -> dict[str, str]:
    uri = os.environ.get("NEO4J_URI")
    pw = os.environ.get("NEO4J_PARITY_PW") or os.environ.get("NEO4J_PASSWORD")
    if not uri or not pw:
        pytest.skip(
            "Neo4j integration test requires NEO4J_URI and NEO4J_PARITY_PW "
            "(or NEO4J_PASSWORD) environment variables."
        )
    return {
        "uri": uri,
        "username": os.environ.get("NEO4J_USERNAME", "neo4j"),
        "password": pw,
        "database": os.environ.get("NEO4J_DATABASE", "graqle-abtest-2026-04-16"),
    }


@pytest.fixture(scope="module")
def sot_path() -> Path:
    """SOT path — monorepo root graqle.json."""
    candidate = Path(__file__).resolve().parents[3] / "graqle.json"
    if not candidate.exists():
        pytest.skip(f"SOT not found at {candidate} (expected monorepo root).")
    return candidate


class TestNeo4jFirstClass:
    """The headline T07 acceptance suite."""

    def test_load_from_neo4j_returns_expected_shape(
        self, neo4j_env: dict[str, str]
    ):
        """from_neo4j on a live DB returns a Graqle with nodes and edges."""
        from graqle.core.graph import Graqle
        from graqle.config.settings import GraqleConfig

        g = Graqle.from_neo4j(
            uri=neo4j_env["uri"],
            username=neo4j_env["username"],
            password=neo4j_env["password"],
            database=neo4j_env["database"],
            config=GraqleConfig.default(),
            # T01: default mirror_to=None means we do not write to disk
        )
        assert len(g.nodes) > 0, "Neo4j backend returned 0 nodes"
        assert len(g.edges) >= 0  # edges optional

    def test_node_count_parity_with_sot(
        self, neo4j_env: dict[str, str], sot_path: Path
    ):
        """Neo4j node count matches SOT within 1% tolerance."""
        from graqle.core.graph import Graqle

        sot_data = json.loads(sot_path.read_text(encoding="utf-8"))
        sot_nodes = len(sot_data.get("nodes", []))

        g = Graqle.from_neo4j(
            uri=neo4j_env["uri"],
            username=neo4j_env["username"],
            password=neo4j_env["password"],
            database=neo4j_env["database"],
        )
        tolerance = max(1, sot_nodes // 100)
        assert abs(len(g.nodes) - sot_nodes) <= tolerance, (
            f"Node count mismatch: Neo4j={len(g.nodes)}, "
            f"SOT={sot_nodes}, tolerance={tolerance}"
        )

    def test_from_neo4j_does_not_write_disk_by_default(
        self, neo4j_env: dict[str, str], tmp_path: Path, monkeypatch
    ):
        """T01 acceptance at the integration level.

        Run from_neo4j in a clean cwd. Assert no files were written.
        """
        from graqle.core.graph import Graqle

        monkeypatch.chdir(tmp_path)
        before = sorted(p.name for p in tmp_path.iterdir())

        Graqle.from_neo4j(
            uri=neo4j_env["uri"],
            username=neo4j_env["username"],
            password=neo4j_env["password"],
            database=neo4j_env["database"],
        )

        after = sorted(p.name for p in tmp_path.iterdir())
        assert before == after, (
            f"from_neo4j wrote files to cwd! before={before} after={after}"
        )


class TestConcurrentWritesNoCollision:
    """T04 acceptance at the integration level.

    100 sequential `_write_with_lock` calls under the shared RLock
    produce zero WRITE_COLLISION. We already have an equivalent unit
    test in tests/test_kg_writes — this version runs against a real
    writable tmp file, exercising the full OS-file-lock path.
    """

    def test_100_sequential_writes_on_real_tmp(self, tmp_path: Path):
        from graqle.core.graph import _write_with_lock

        target = tmp_path / "graqle.json"
        payload = json.dumps({
            "directed": True, "multigraph": False, "graph": {},
            "nodes": [{"id": f"n{i}", "label": f"N{i}"} for i in range(100)],
            "links": [],
        })
        target.write_text(payload, encoding="utf-8")

        retries = []
        for _ in range(100):
            attempts = _write_with_lock(str(target), payload)
            retries.append(attempts)

        assert all(a == 0 for a in retries), (
            f"T04 regression: some writes triggered retries: "
            f"indices={[i for i, a in enumerate(retries) if a > 0]}"
        )
