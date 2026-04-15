"""Tests for v0.51.4 P0 KG shrink guard inside ``_write_with_lock``.

These tests cover the lowest-level protection against catastrophic node
loss. The guard sits inside ``graqle.core.graph._write_with_lock`` so
every KG save path (``_save_graph``, ``kg_sync``, ``scan``, ``grow``,
``link``, ``rebuild``, ``json_graph``, ``mcp_dev_server``) picks it up
the next time the write function is imported — no MCP restart needed.

Regression: a ``graq_learn`` path was observed handing the save function
a stub or partially-loaded graph, which silently overwrote the full
on-disk KG. The guard refuses any write that would lose more than 1%
of on-disk nodes.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from graqle.core.graph import _write_with_lock


def _make_graph(n_nodes: int) -> dict:
    return {
        "directed": True,
        "multigraph": False,
        "nodes": [{"id": f"n{i}"} for i in range(n_nodes)],
        "links": [],
    }


def _seed_file(path: str, nodes: int) -> None:
    Path(path).write_text(json.dumps(_make_graph(nodes)), encoding="utf-8")


@pytest.fixture
def kg_file(tmp_path: Path) -> str:
    return str(tmp_path / "graqle.json")


@pytest.fixture(autouse=True)
def _no_allow_shrink_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure GRAQLE_ALLOW_SHRINK is not set from the caller's env."""
    monkeypatch.delenv("GRAQLE_ALLOW_SHRINK", raising=False)


class TestShrinkGuardRefusesCatastrophicLoss:
    """Saves that would destroy most of the graph must be rejected."""

    def test_99_percent_shrink_is_refused(self, kg_file: str) -> None:
        _seed_file(kg_file, 1000)
        with pytest.raises(ValueError, match="KG write REFUSED"):
            _write_with_lock(kg_file, json.dumps(_make_graph(1)))
        on_disk = json.loads(Path(kg_file).read_text(encoding="utf-8"))
        assert len(on_disk["nodes"]) == 1000, "file must be preserved"

    def test_half_size_shrink_is_refused(self, kg_file: str) -> None:
        _seed_file(kg_file, 1000)
        with pytest.raises(ValueError, match="loss=50.0%"):
            _write_with_lock(kg_file, json.dumps(_make_graph(500)))
        assert len(json.loads(Path(kg_file).read_text())["nodes"]) == 1000

    def test_zero_nodes_incoming_refused(self, kg_file: str) -> None:
        _seed_file(kg_file, 1000)
        with pytest.raises(ValueError, match="incoming=0 nodes"):
            _write_with_lock(kg_file, json.dumps(_make_graph(0)))
        assert len(json.loads(Path(kg_file).read_text())["nodes"]) == 1000


class TestShrinkGuardAllowsTinyChurn:
    """Losing at most 1% is acceptable (normal node-replacement churn)."""

    def test_one_percent_shrink_is_allowed(self, kg_file: str) -> None:
        _seed_file(kg_file, 1000)
        _write_with_lock(kg_file, json.dumps(_make_graph(990)))
        assert len(json.loads(Path(kg_file).read_text())["nodes"]) == 990

    def test_lose_exactly_one_node_on_small_graph_allowed(self, kg_file: str) -> None:
        # floor of 1 node loss is always allowed
        _seed_file(kg_file, 100)
        _write_with_lock(kg_file, json.dumps(_make_graph(99)))
        assert len(json.loads(Path(kg_file).read_text())["nodes"]) == 99


class TestShrinkGuardAllowsGrowth:
    """Growing the graph must always pass the guard."""

    def test_growth_passes(self, kg_file: str) -> None:
        _seed_file(kg_file, 1000)
        _write_with_lock(kg_file, json.dumps(_make_graph(1500)))
        assert len(json.loads(Path(kg_file).read_text())["nodes"]) == 1500

    def test_large_growth_passes(self, kg_file: str) -> None:
        _seed_file(kg_file, 50)
        _write_with_lock(kg_file, json.dumps(_make_graph(12000)))
        assert len(json.loads(Path(kg_file).read_text())["nodes"]) == 12000


class TestShrinkGuardOverrideEnvVar:
    """``GRAQLE_ALLOW_SHRINK=1`` must bypass the guard for recovery scenarios."""

    def test_override_allows_catastrophic_shrink(
        self, kg_file: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_file(kg_file, 1000)
        monkeypatch.setenv("GRAQLE_ALLOW_SHRINK", "1")
        _write_with_lock(kg_file, json.dumps(_make_graph(1)))
        assert len(json.loads(Path(kg_file).read_text())["nodes"]) == 1

    def test_override_value_must_be_exactly_one(
        self, kg_file: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Guard reads strict "1" — "true"/"yes" must NOT bypass (principle of
        # least surprise; forces the user to pick the unambiguous value).
        _seed_file(kg_file, 1000)
        monkeypatch.setenv("GRAQLE_ALLOW_SHRINK", "true")
        with pytest.raises(ValueError, match="KG write REFUSED"):
            _write_with_lock(kg_file, json.dumps(_make_graph(1)))


class TestShrinkGuardDoesNotBlockNonGraphWrites:
    """The guard must only engage on JSON payloads that look like a graph."""

    def test_plain_text_write_passes(self, tmp_path: Path) -> None:
        p = str(tmp_path / "notes.txt")
        Path(p).write_text("original content")
        _write_with_lock(p, "new content that is much shorter")
        assert Path(p).read_text() == "new content that is much shorter"

    def test_json_without_nodes_key_passes(self, tmp_path: Path) -> None:
        p = str(tmp_path / "config.json")
        Path(p).write_text(json.dumps({"setting": "old", "values": list(range(100))}))
        _write_with_lock(p, json.dumps({"setting": "new"}))
        assert json.loads(Path(p).read_text())["setting"] == "new"

    def test_small_existing_graph_not_protected(self, kg_file: str) -> None:
        # Guard only engages once on-disk graph has >=50 nodes. Below that
        # threshold the guard is inert so bootstrap / fresh-project writes
        # are never blocked.
        _seed_file(kg_file, 10)
        _write_with_lock(kg_file, json.dumps(_make_graph(1)))
        assert len(json.loads(Path(kg_file).read_text())["nodes"]) == 1


class TestShrinkGuardFailureModes:
    """Guard must never become a footgun itself."""

    def test_corrupt_existing_file_does_not_block_write(
        self, kg_file: str
    ) -> None:
        # If the existing file is corrupt JSON, the guard can't compare
        # counts — it should let the write proceed so recovery is possible.
        Path(kg_file).write_text("{not json{{", encoding="utf-8")
        _write_with_lock(kg_file, json.dumps(_make_graph(5)))
        assert len(json.loads(Path(kg_file).read_text())["nodes"]) == 5

    def test_nonexistent_target_file_is_created(self, tmp_path: Path) -> None:
        # First-time writes (no existing file) must succeed.
        p = str(tmp_path / "new_graph.json")
        _write_with_lock(p, json.dumps(_make_graph(1000)))
        assert Path(p).exists()
        assert len(json.loads(Path(p).read_text())["nodes"]) == 1000
