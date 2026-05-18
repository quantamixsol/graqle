"""Regression-pinning tests for cr-016 — byte-for-byte specification of the
EXISTING 4-layer project-root resolution logic in
``KogniDevServer._project_root_from_graph_file``.

These tests intentionally duplicate Layer 1's TestBackwardCompat* coverage
to provide a NAMED, EXPLICIT contract that any future refactor must keep
passing. Layer 1 tests the new env var; this layer tests what was there
BEFORE cr-016 and must stay there AFTER cr-016.

If the helper is ever rewritten (e.g., the deferred cr-016b that refactors
_resolve_file_path to delegate to this helper), every test in this file
must continue to pass — otherwise a regression has been introduced.

Pinned behaviours:
  P1: graph_file=None + no env vars → Path.cwd()
  P2: graph_file=filesystem path + no env vars → graph_file.parent.resolve()
  P3: graph_file=URI + no env vars → Path.cwd() (URI rejected, falls through)
  P4: GRAQLE_SERVE_CWD set + no other → SERVE_CWD wins over Path.cwd()
"""

# ── graqle:intelligence ──
# module: tests.test_plugins.test_worktree_root_regression
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, os, pathlib
# constraints: pin existing v0.57.4 behaviour byte-for-byte
# ── /graqle:intelligence ──

from __future__ import annotations

import os
from pathlib import Path

from graqle.plugins.mcp_dev_server import KogniDevServer


def _server() -> KogniDevServer:
    return KogniDevServer(read_only=True)


class TestPreCR016BehaviourPinned:
    """These four tests freeze the v0.57.4 / pre-cr-016 contract. The cr-016
    helper must NEVER change any of these answers — only the new env var
    layer is allowed to override them, and ONLY when the env var is set."""

    def test_P1_no_env_no_graph_file_returns_cwd(self, monkeypatch, tmp_path):
        """P1 (pinned): with no env vars and graph_file=None, the helper
        returns Path.cwd().resolve() exactly. This was the v0.57.4 behaviour
        and must remain forever (until we issue a documented breaking
        change in a major version)."""
        monkeypatch.chdir(tmp_path)
        # Belt-and-braces: explicitly confirm env is clean
        assert os.environ.get("GRAQLE_WORKTREE_ROOT") is None
        assert os.environ.get("GRAQLE_SERVE_CWD") is None

        actual = _server()._project_root_from_graph_file(None)
        expected = tmp_path.resolve()
        assert actual == expected, (
            f"REGRESSION: P1 contract violated. With no env vars and "
            f"graph_file=None, the helper must return Path.cwd().resolve(). "
            f"Expected {expected!r}, got {actual!r}."
        )

    def test_P2_no_env_filesystem_graph_file_returns_parent(self, tmp_path):
        """P2 (pinned): with no env vars and graph_file as a filesystem
        path, the helper returns the path's parent (resolved)."""
        graph_dir = tmp_path / "the_graph_dir"
        graph_dir.mkdir()
        graph_json = graph_dir / "graqle.json"
        graph_json.write_text("{}")

        assert os.environ.get("GRAQLE_WORKTREE_ROOT") is None
        assert os.environ.get("GRAQLE_SERVE_CWD") is None

        actual = _server()._project_root_from_graph_file(str(graph_json))
        expected = graph_dir.resolve()
        assert actual == expected, (
            f"REGRESSION: P2 contract violated. With graph_file as a "
            f"filesystem path and no env vars, the helper must return "
            f"graph_file.parent.resolve(). Expected {expected!r}, got "
            f"{actual!r}."
        )

    def test_P3_no_env_uri_graph_file_returns_cwd(self, monkeypatch, tmp_path):
        """P3 (pinned): with no env vars and graph_file containing '://'
        (a URI scheme like neo4j://, bolt://, http://), the helper must
        reject the URI and fall through to Path.cwd()."""
        monkeypatch.chdir(tmp_path)
        assert os.environ.get("GRAQLE_WORKTREE_ROOT") is None
        assert os.environ.get("GRAQLE_SERVE_CWD") is None

        # Test all URI schemes the codebase might encounter
        for uri in [
            "neo4j://bolt://localhost:7687",
            "bolt://localhost:7687",
            "https://example.com/graph.json",
            "s3://bucket/key/graph.json",
        ]:
            actual = _server()._project_root_from_graph_file(uri)
            expected = tmp_path.resolve()
            assert actual == expected, (
                f"REGRESSION: P3 contract violated for URI {uri!r}. "
                f"URIs must be rejected and the helper must fall through "
                f"to Path.cwd(). Expected {expected!r}, got {actual!r}."
            )

    def test_P4_serve_cwd_wins_over_path_cwd(self, monkeypatch, tmp_path):
        """P4 (pinned): when GRAQLE_SERVE_CWD is set AND graph_file is
        unsuitable (None or URI), SERVE_CWD wins over Path.cwd()."""
        serve_dir = tmp_path / "serve_cwd_dir"
        serve_dir.mkdir()
        other_dir = tmp_path / "actual_cwd_dir"
        other_dir.mkdir()
        monkeypatch.chdir(other_dir)

        assert os.environ.get("GRAQLE_WORKTREE_ROOT") is None
        os.environ["GRAQLE_SERVE_CWD"] = str(serve_dir)

        # Sub-case (a): graph_file=None → SERVE_CWD, not cwd
        actual = _server()._project_root_from_graph_file(None)
        expected = serve_dir.resolve()
        assert actual == expected, (
            f"REGRESSION: P4(a) contract violated. With graph_file=None "
            f"and SERVE_CWD set, the helper must return SERVE_CWD. "
            f"Expected {expected!r}, got {actual!r}."
        )

        # Sub-case (b): graph_file=URI → SERVE_CWD, not cwd
        actual = _server()._project_root_from_graph_file("neo4j://localhost")
        assert actual == expected, (
            f"REGRESSION: P4(b) contract violated. With graph_file=URI "
            f"and SERVE_CWD set, the helper must return SERVE_CWD. "
            f"Expected {expected!r}, got {actual!r}."
        )


class TestPreCR016PrecedenceContract:
    """Pin the ORDER of the 4 layers: graph_file (filesystem) > SERVE_CWD >
    cwd. The cr-016 addition (GRAQLE_WORKTREE_ROOT > everything) does NOT
    re-order any of these — it only adds a new top-priority layer."""

    def test_filesystem_graph_file_beats_serve_cwd(
        self, monkeypatch, tmp_path
    ):
        """When BOTH a filesystem graph_file AND GRAQLE_SERVE_CWD are
        provided, the graph_file's parent wins (it's earlier in precedence
        than SERVE_CWD)."""
        graph_dir = tmp_path / "graph_dir"
        graph_dir.mkdir()
        graph_json = graph_dir / "graqle.json"
        graph_json.write_text("{}")
        serve_dir = tmp_path / "serve_dir"
        serve_dir.mkdir()

        assert os.environ.get("GRAQLE_WORKTREE_ROOT") is None
        os.environ["GRAQLE_SERVE_CWD"] = str(serve_dir)

        actual = _server()._project_root_from_graph_file(str(graph_json))
        expected = graph_dir.resolve()
        assert actual == expected, (
            f"REGRESSION: precedence contract violated. graph_file's "
            f"parent must win over SERVE_CWD. Expected {expected!r}, "
            f"got {actual!r}."
        )
        # Anti-assertion: explicitly NOT SERVE_CWD
        assert actual != serve_dir.resolve(), (
            "REGRESSION: SERVE_CWD overrode the filesystem graph_file "
            "parent. Precedence order broken."
        )
