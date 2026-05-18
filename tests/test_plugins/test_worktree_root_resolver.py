"""Unit tests for cr-016 GRAQLE_WORKTREE_ROOT env-var resolution.

Target: graqle.plugins.mcp_dev_server.KogniDevServer._project_root_from_graph_file

These tests pin the 4-layer precedence matrix and the bad-value graceful
fallthrough behaviour. They are the canonical specification of how the
helper must behave — any future refactor that breaks one of these is a
regression and must be reverted.

Precedence order (highest to lowest):
    1. GRAQLE_WORKTREE_ROOT (cr-016)
    2. graph_file parent directory (when filesystem path, not URI)
    3. GRAQLE_SERVE_CWD
    4. Path.cwd()

The conftest.py autouse fixture ``_cr016_env_isolation`` guarantees that
every test starts with GRAQLE_WORKTREE_ROOT / GRAQLE_SERVE_CWD / etc. unset
regardless of CI runner environment or test-ordering pollution.
"""

# ── graqle:intelligence ──
# module: tests.test_plugins.test_worktree_root_resolver
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, os, tempfile, pathlib
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from graqle.plugins.mcp_dev_server import KogniDevServer


# -------------------------------------------------------------------------
# Helper: a minimal KogniDevServer instance whose __init__ doesn't reach
# the graph-loading code paths. The helper method we're testing only reads
# ``self`` for namespacing purposes — it's effectively a static method.
# -------------------------------------------------------------------------


def _server() -> KogniDevServer:
    """Construct a bare KogniDevServer without invoking lazy graph load."""
    return KogniDevServer(config_path="graqle.yaml", read_only=True)


# -------------------------------------------------------------------------
# LAYER 1A — backward-compat cases (env var unset)
# -------------------------------------------------------------------------


class TestBackwardCompatGraphFileUnset:
    """When GRAQLE_WORKTREE_ROOT is unset, every existing precedence layer
    must behave byte-identically to v0.57.4 / pre-cr-016."""

    def test_no_env_no_graph_file_returns_cwd(self, monkeypatch, tmp_path):
        """Case 1: env unset + graph_file=None → Path.cwd()."""
        monkeypatch.chdir(tmp_path)
        result = _server()._project_root_from_graph_file(None)
        assert result == tmp_path.resolve()

    def test_no_env_filesystem_graph_file_returns_parent(self, tmp_path):
        """Case 2: env unset + graph_file is a regular path →
        graph_file.parent.resolve()."""
        graph_json = tmp_path / "graqle.json"
        graph_json.write_text("{}")
        result = _server()._project_root_from_graph_file(str(graph_json))
        assert result == tmp_path.resolve()

    def test_no_env_uri_graph_file_returns_cwd(self, monkeypatch, tmp_path):
        """Case 4: env unset + graph_file is a Neo4j URI → cwd() fallback."""
        monkeypatch.chdir(tmp_path)
        result = _server()._project_root_from_graph_file(
            "neo4j://bolt://localhost:7687"
        )
        assert result == tmp_path.resolve()


class TestBackwardCompatServeCwd:
    """GRAQLE_SERVE_CWD (the pre-existing env var, mid-priority) must continue
    to work exactly as before."""

    def test_serve_cwd_used_when_graph_file_none(self, tmp_path):
        """Case 3: env=SERVE_CWD only + graph_file=None → SERVE_CWD."""
        os.environ["GRAQLE_SERVE_CWD"] = str(tmp_path)
        result = _server()._project_root_from_graph_file(None)
        assert result == tmp_path.resolve()

    def test_serve_cwd_used_when_graph_file_is_uri(self, tmp_path):
        """Case 5: env=SERVE_CWD only + graph_file=URI → SERVE_CWD."""
        os.environ["GRAQLE_SERVE_CWD"] = str(tmp_path)
        result = _server()._project_root_from_graph_file(
            "neo4j://bolt://localhost:7687"
        )
        assert result == tmp_path.resolve()

    def test_graph_file_beats_serve_cwd_when_filesystem(self, tmp_path):
        """When BOTH SERVE_CWD and a filesystem graph_file are provided,
        the graph_file's parent wins (existing precedence)."""
        serve_dir = tmp_path / "serve"
        graph_dir = tmp_path / "graph"
        serve_dir.mkdir()
        graph_dir.mkdir()
        graph_json = graph_dir / "graqle.json"
        graph_json.write_text("{}")
        os.environ["GRAQLE_SERVE_CWD"] = str(serve_dir)
        result = _server()._project_root_from_graph_file(str(graph_json))
        assert result == graph_dir.resolve()


# -------------------------------------------------------------------------
# LAYER 1B — the cr-016 new behaviour (env var set)
# -------------------------------------------------------------------------


class TestWorktreeRootHighestPriority:
    """When GRAQLE_WORKTREE_ROOT is set to a valid directory, it MUST win
    over every other source (the cr-016 contract)."""

    def test_worktree_root_beats_cwd(self, monkeypatch, tmp_path):
        """Case 6: WORKTREE_ROOT set, graph_file=None → WORKTREE_ROOT
        (not cwd)."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        monkeypatch.chdir(tmp_path)  # cwd is the parent, distinct from worktree
        os.environ["GRAQLE_WORKTREE_ROOT"] = str(worktree)
        result = _server()._project_root_from_graph_file(None)
        assert result == worktree.resolve()

    def test_worktree_root_beats_filesystem_graph_file(self, tmp_path):
        """Case 7: WORKTREE_ROOT set, graph_file is filesystem path →
        WORKTREE_ROOT (not graph_file's parent)."""
        worktree = tmp_path / "worktree"
        graph_dir = tmp_path / "graph"
        worktree.mkdir()
        graph_dir.mkdir()
        graph_json = graph_dir / "graqle.json"
        graph_json.write_text("{}")
        os.environ["GRAQLE_WORKTREE_ROOT"] = str(worktree)
        result = _server()._project_root_from_graph_file(str(graph_json))
        assert result == worktree.resolve()
        # explicit anti-assertion: NOT the graph_file's parent
        assert result != graph_dir.resolve()

    def test_worktree_root_beats_serve_cwd(self, tmp_path):
        """Case 8: WORKTREE_ROOT + SERVE_CWD both set, graph_file=None →
        WORKTREE_ROOT (not SERVE_CWD)."""
        worktree = tmp_path / "worktree"
        serve = tmp_path / "serve"
        worktree.mkdir()
        serve.mkdir()
        os.environ["GRAQLE_WORKTREE_ROOT"] = str(worktree)
        os.environ["GRAQLE_SERVE_CWD"] = str(serve)
        result = _server()._project_root_from_graph_file(None)
        assert result == worktree.resolve()
        assert result != serve.resolve()

    def test_worktree_root_beats_uri_graph_file(self, tmp_path):
        """Case 9: WORKTREE_ROOT set, graph_file is Neo4j URI →
        WORKTREE_ROOT (not the URI-fallthrough chain)."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        os.environ["GRAQLE_WORKTREE_ROOT"] = str(worktree)
        result = _server()._project_root_from_graph_file(
            "neo4j://bolt://localhost:7687"
        )
        assert result == worktree.resolve()

    def test_worktree_root_full_precedence_stack(self, tmp_path):
        """Maximum-evidence precedence test: WORKTREE_ROOT + SERVE_CWD +
        filesystem graph_file all set simultaneously. WORKTREE_ROOT wins."""
        worktree = tmp_path / "worktree"
        serve = tmp_path / "serve"
        graph_dir = tmp_path / "graph"
        for d in (worktree, serve, graph_dir):
            d.mkdir()
        graph_json = graph_dir / "graqle.json"
        graph_json.write_text("{}")
        os.environ["GRAQLE_WORKTREE_ROOT"] = str(worktree)
        os.environ["GRAQLE_SERVE_CWD"] = str(serve)
        result = _server()._project_root_from_graph_file(str(graph_json))
        assert result == worktree.resolve()


# -------------------------------------------------------------------------
# LAYER 1C — bad-value graceful fallthrough
# -------------------------------------------------------------------------


class TestWorktreeRootBadValue:
    """Malformed or unusable GRAQLE_WORKTREE_ROOT values must NOT crash. The
    helper logs a warning and falls through to the next precedence layer."""

    def test_nonexistent_path_falls_through_to_cwd(
        self, monkeypatch, tmp_path, caplog
    ):
        """Case 10: WORKTREE_ROOT points to a non-existent directory →
        warning logged + cwd() used."""
        monkeypatch.chdir(tmp_path)
        bogus = tmp_path / "does" / "not" / "exist"
        os.environ["GRAQLE_WORKTREE_ROOT"] = str(bogus)
        with caplog.at_level("WARNING"):
            result = _server()._project_root_from_graph_file(None)
        assert result == tmp_path.resolve()
        assert any(
            "GRAQLE_WORKTREE_ROOT" in record.message
            and "not a directory" in record.message
            for record in caplog.records
        )

    def test_empty_string_treated_as_unset(self, monkeypatch, tmp_path, caplog):
        """Case 11: WORKTREE_ROOT='' (empty) → treated as unset, no warning,
        cwd() used (the bool check ``if worktree_root:`` filters out empty)."""
        monkeypatch.chdir(tmp_path)
        os.environ["GRAQLE_WORKTREE_ROOT"] = ""
        with caplog.at_level("WARNING"):
            result = _server()._project_root_from_graph_file(None)
        assert result == tmp_path.resolve()
        # Critical assertion: NO warning emitted for empty string
        assert not any(
            "GRAQLE_WORKTREE_ROOT" in record.message
            for record in caplog.records
        )

    def test_file_not_directory_falls_through(
        self, monkeypatch, tmp_path, caplog
    ):
        """Case 12: WORKTREE_ROOT points to a regular file, not a dir →
        warning + fall through."""
        monkeypatch.chdir(tmp_path)
        a_file = tmp_path / "not_a_dir.txt"
        a_file.write_text("hello")
        os.environ["GRAQLE_WORKTREE_ROOT"] = str(a_file)
        with caplog.at_level("WARNING"):
            result = _server()._project_root_from_graph_file(None)
        assert result == tmp_path.resolve()
        assert any(
            "GRAQLE_WORKTREE_ROOT" in record.message
            and "not a directory" in record.message
            for record in caplog.records
        )

    def test_serve_cwd_used_when_worktree_root_invalid(
        self, monkeypatch, tmp_path, caplog
    ):
        """Defensive precedence: if WORKTREE_ROOT is invalid, fall-through
        must still respect SERVE_CWD (not jump straight to cwd)."""
        monkeypatch.chdir(tmp_path)
        bogus = tmp_path / "does" / "not" / "exist"
        serve = tmp_path / "serve"
        serve.mkdir()
        os.environ["GRAQLE_WORKTREE_ROOT"] = str(bogus)
        os.environ["GRAQLE_SERVE_CWD"] = str(serve)
        with caplog.at_level("WARNING"):
            result = _server()._project_root_from_graph_file(None)
        # WORKTREE_ROOT invalid → fall through → graph_file=None → SERVE_CWD wins
        assert result == serve.resolve()
        # Verify the warning was still emitted
        assert any(
            "GRAQLE_WORKTREE_ROOT" in record.message
            for record in caplog.records
        )


# -------------------------------------------------------------------------
# LAYER 1D — path-resolution behaviour (canonical / relative)
# -------------------------------------------------------------------------


class TestWorktreeRootPathBehaviour:
    """The helper applies Path.resolve() to the env value, which canonicalises
    .., symlinks, and relative paths. Pin these behaviours."""

    def test_path_with_dotdot_canonicalised(self, monkeypatch, tmp_path):
        """Case 13: WORKTREE_ROOT contains a .. component → Path.resolve()
        produces the canonical path."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        # Build a path that traverses up and back down to the same dir
        with_dotdot = str(tmp_path / "worktree" / ".." / "worktree")
        os.environ["GRAQLE_WORKTREE_ROOT"] = with_dotdot
        result = _server()._project_root_from_graph_file(None)
        assert result == worktree.resolve()

    def test_relative_path_resolved_against_cwd(self, monkeypatch, tmp_path):
        """Case 14: WORKTREE_ROOT is a relative path → resolved against
        current cwd at call time."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        monkeypatch.chdir(tmp_path)
        # Pass a relative path; resolve() should compose it with cwd
        os.environ["GRAQLE_WORKTREE_ROOT"] = "worktree"
        result = _server()._project_root_from_graph_file(None)
        assert result == worktree.resolve()


# -------------------------------------------------------------------------
# LAYER 1E — test-isolation defence
# -------------------------------------------------------------------------


class TestEnvIsolation:
    """Verify that the conftest autouse fixture works — each test must start
    with all 3 cr-016 env vars unset, regardless of CI runner state."""

    def test_baseline_env_is_clean(self, monkeypatch, tmp_path):
        """Case 15: with no manipulation, all 3 env vars are absent and
        the helper returns the pure cwd() fallback. This test would fail
        if the conftest fixture leaked state from a prior test."""
        monkeypatch.chdir(tmp_path)
        assert os.environ.get("GRAQLE_WORKTREE_ROOT") is None
        assert os.environ.get("GRAQLE_SERVE_CWD") is None
        result = _server()._project_root_from_graph_file(None)
        assert result == tmp_path.resolve()

    def test_env_restored_after_test(self):
        """The conftest restores original env values on teardown. After
        this test sets WORKTREE_ROOT, a subsequent test (run by pytest)
        must see it unset again. We can't directly test the teardown from
        within this test, but we can document the contract via assertion
        that no env var is *intentionally* leaked from this test body."""
        os.environ["GRAQLE_WORKTREE_ROOT"] = "/some/path"
        # If this leaks, the conftest fixture is broken.
        # The cleanup is handled by the autouse fixture's finally block.
