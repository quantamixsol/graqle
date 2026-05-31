"""Tests for v0.63.0 `graq grow` end-to-end auto-grow: --embed / --backend.

Covers backend resolution, the embed flag surface, degrade-quiet behaviour,
the Neo4j write path (mocked), R-SEC-1 on the Neo4j embed_fn, and the
graqle.json-shape-unchanged guard.

V-CR-V063-WRITE-NATIVE-001: new test file in graqle-sdk/ — graq_write/generate
hit S-010 "path escapes project root"; native Write fallback per SENTINEL-v0623.
"""

# ── graqle:intelligence ──
# module: tests.test_cli.test_grow_embed
# risk: LOW (impact radius: 0 modules)
# dependencies: json, pytest, typer, grow
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import typer
from typer.testing import CliRunner

from graqle.cli.commands import grow as grow_mod
from graqle.cli.commands.grow import (
    _chunks_for_nodes,
    _make_redacting_embed_fn,
    _resolve_backend,
)

runner = CliRunner()


# ────────────────────────── _resolve_backend ──────────────────────────
class TestResolveBackend:
    def test_EG06_bogus_rejected(self):
        with pytest.raises(typer.BadParameter):
            _resolve_backend("bogus", "x.yaml")

    def test_explicit_local(self):
        assert _resolve_backend("local", "x.yaml") == "local"

    def test_explicit_neo4j(self):
        assert _resolve_backend("neo4j", "x.yaml") == "neo4j"

    def test_EG05_auto_no_config_is_local(self, tmp_path):
        assert _resolve_backend("auto", str(tmp_path / "missing.yaml")) == "local"

    def test_EG04_auto_neo4j_connector(self, tmp_path):
        cfg = tmp_path / "graqle.yaml"
        cfg.write_text("graph:\n  connector: neo4j\n", encoding="utf-8")
        assert _resolve_backend("auto", str(cfg)) == "neo4j"

    def test_auto_local_connector(self, tmp_path):
        cfg = tmp_path / "graqle.yaml"
        cfg.write_text("graph:\n  connector: networkx\n", encoding="utf-8")
        assert _resolve_backend("auto", str(cfg)) == "local"


# ────────────────────────── _chunks_for_nodes ─────────────────────────
class TestChunksForNodes:
    def test_with_explicit_chunks(self):
        nodes = {"a.py": {"id": "a.py", "properties": {"chunks": [
            {"text": "def a(): pass", "type": "function"},
        ]}}}
        out = _chunks_for_nodes(nodes, {"a.py"})
        assert out["a.py"][0]["text"] == "def a(): pass"

    def test_desc_fallback_when_no_chunks(self):
        nodes = {"d": {"id": "d", "description": "Directory: d", "properties": {}}}
        out = _chunks_for_nodes(nodes, {"d"})
        assert out["d"] == [{"text": "Directory: d", "type": "description"}]

    def test_missing_node_skipped(self):
        out = _chunks_for_nodes({}, {"ghost"})
        assert out == {}


# ───────────────────── R-SEC-1 on the Neo4j embed_fn ───────────────────
class TestRedactingEmbedFn:
    def test_EG10_neo4j_embed_fn_redacts_secret(self, monkeypatch):
        """The Neo4j path's embed_fn must never pass a raw SECRET to the engine."""
        seen: list[str] = []

        class _Eng:
            def embed(self, text):
                seen.append(text)
                import numpy as np
                return np.array([0.1, 0.2, 0.3])

        monkeypatch.setattr(
            "graqle.activation.embeddings.EmbeddingEngine", lambda *a, **k: _Eng()
        )
        fn = _make_redacting_embed_fn()
        secret = "AWS_SECRET_ACCESS_KEY=" + "B" * 40
        vec = fn(f"token = '{secret}'")
        assert isinstance(vec, list)  # .tolist() applied
        assert all(secret not in t for t in seen), "raw secret reached engine"


# ───────────────────── grow_command CLI surface ───────────────────────
class TestGrowSurface:
    def test_help_exposes_embed_and_backend(self):
        """The flags must be on the command. Assert against the registered
        params, NOT the rendered Rich --help text: Rich wraps + ANSI-colours
        the help in CI's narrow terminal, splitting '--embed' across a box
        border so a substring match on result.output is flaky (passed locally,
        failed in CI). The param signature is the source of truth.
        """
        import inspect

        from graqle.cli.commands.grow import grow_command

        params = inspect.signature(grow_command).parameters
        assert "embed" in params, "grow_command must expose an `embed` option"
        assert "backend" in params, "grow_command must expose a `backend` option"
        # The param defaults are typer OptionInfo objects; the real default
        # value is on .default of the OptionInfo.
        embed_default = getattr(params["embed"].default, "default", params["embed"].default)
        backend_default = getattr(params["backend"].default, "default", params["backend"].default)
        assert embed_default is True   # --embed on by default
        assert backend_default == "auto"

    def test_help_renders_without_error(self):
        from graqle.cli.main import app
        result = runner.invoke(app, ["grow", "--help"])
        assert result.exit_code == 0


# ───────────── grow_command integration (local, monkeypatched) ─────────
def _seed_graph_json(tmp_path):
    gj = tmp_path / "graqle.json"
    gj.write_text(json.dumps({
        "directed": True, "multigraph": False, "graph": {},
        "nodes": [{"id": "old.py", "label": "old", "type": "PythonModule",
                   "description": "old module"}],
        "links": [],
    }), encoding="utf-8")
    return gj


class TestGrowIntegration:
    def _run(self, monkeypatch, tmp_path, embed=True, backend="local",
             new_nodes=None):
        monkeypatch.chdir(tmp_path)
        _seed_graph_json(tmp_path)
        new_nodes = new_nodes if new_nodes is not None else [
            {"id": "new.py", "label": "new", "type": "PythonModule",
             "description": "new module"}
        ]
        # Force the incremental scan to return our new node, skip git/ingest.
        monkeypatch.setattr(grow_mod, "_get_changed_files", lambda: ["new.py"])
        monkeypatch.setattr(grow_mod, "_incremental_scan",
                            lambda root, changed: (new_nodes, []))
        embed_calls = {"local": 0, "neo4j": 0}
        monkeypatch.setattr(grow_mod, "_embed_local",
                            lambda *a, **k: embed_calls.__setitem__("local", embed_calls["local"] + 1))
        monkeypatch.setattr(grow_mod, "_write_neo4j",
                            lambda *a, **k: embed_calls.__setitem__("neo4j", embed_calls["neo4j"] + 1))
        grow_mod.grow_command(quiet=True, full=False, config="graqle.yaml",
                              embed=embed, backend=backend)
        return embed_calls

    def test_EG01_embed_local_calls_embed(self, monkeypatch, tmp_path):
        calls = self._run(monkeypatch, tmp_path, embed=True, backend="local")
        assert calls["local"] == 1
        assert calls["neo4j"] == 0

    def test_EG02_no_embed_skips_embed(self, monkeypatch, tmp_path):
        calls = self._run(monkeypatch, tmp_path, embed=False, backend="local")
        assert calls["local"] == 0

    def test_EG03_backend_neo4j_calls_write_neo4j(self, monkeypatch, tmp_path):
        calls = self._run(monkeypatch, tmp_path, embed=True, backend="neo4j")
        assert calls["neo4j"] == 1
        # local embed still runs (graqle.json is the local mirror)
        assert calls["local"] == 1

    def test_EG15_graqle_json_shape_unchanged(self, monkeypatch, tmp_path):
        """The node/link serialization must stay v0.62.x-shaped (embed is sidecar)."""
        self._run(monkeypatch, tmp_path, embed=True, backend="local")
        data = json.loads((tmp_path / "graqle.json").read_text(encoding="utf-8"))
        assert "nodes" in data and "links" in data
        ids = {n["id"] for n in data["nodes"]}
        assert "old.py" in ids and "new.py" in ids
        # every node still a plain dict with the canonical keys, no embedding blob
        for n in data["nodes"]:
            assert isinstance(n, dict)
            assert "embedding" not in n
