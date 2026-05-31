"""Tests for v0.63.0 L2 — background auto-grow watcher invokes `grow --embed`.

Focused, deterministic tests (no real watchdog/filesystem timing): the
subprocess argv carries --embed (EG_11), disable-env + missing-watchdog
degrade cleanly, stats shape, and the MCP wire-in method (EG_12).

V-CR-V063-WRITE-NATIVE-001: new test file — graq_write S-010 gate; native Write.
"""

# ── graqle:intelligence ──
# module: tests.test_plugins.test_background_grow_v063
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, background_grow, mcp_dev_server
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from graqle.plugins.background_grow import BackgroundGrowWatcher


class TestSubprocessArgv:
    def test_EG11_argv_includes_embed(self, tmp_path):
        """The watcher must shell `grow --embed`, not bare `grow`."""
        w = BackgroundGrowWatcher(tmp_path, python_executable="pyx")
        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            r = MagicMock()
            r.returncode = 0
            r.stdout = "ok"
            r.stderr = ""
            return r

        with patch("graqle.plugins.background_grow.subprocess.run", side_effect=fake_run):
            ok = w._run_grow_subprocess()
        assert ok is True
        assert captured["argv"] == ["pyx", "-m", "graqle.cli.main", "grow", "--embed"]

    def test_nonzero_exit_returns_false(self, tmp_path):
        w = BackgroundGrowWatcher(tmp_path, python_executable="pyx")

        def fake_run(argv, **kwargs):
            r = MagicMock()
            r.returncode = 2
            r.stdout = ""
            r.stderr = "boom"
            return r

        with patch("graqle.plugins.background_grow.subprocess.run", side_effect=fake_run):
            assert w._run_grow_subprocess() is False


class TestDegrade:
    def test_disabled_via_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GRAQLE_DISABLE_BACKGROUND_GROW", "1")
        w = BackgroundGrowWatcher(tmp_path)
        assert w.start() is False

    def test_missing_watchdog(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GRAQLE_DISABLE_BACKGROUND_GROW", raising=False)
        # Simulate watchdog import failure.
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name.startswith("watchdog"):
                raise ImportError("no watchdog")
            return real_import(name, *a, **k)

        with patch("builtins.__import__", side_effect=fake_import):
            w = BackgroundGrowWatcher(tmp_path)
            assert w.start() is False

    def test_stats_shape(self, tmp_path):
        w = BackgroundGrowWatcher(tmp_path)
        s = w.stats
        assert "root" in s and "growths_completed" in s and "alive" in s


class TestMcpWireIn:
    def test_EG12_maybe_start_disabled_env_is_noop(self, monkeypatch):
        """_maybe_start_background_grow respects the disable env and never raises."""
        monkeypatch.setenv("GRAQLE_DISABLE_BACKGROUND_GROW", "1")
        from graqle.plugins.mcp_dev_server import KogniDevServer
        s = KogniDevServer.__new__(KogniDevServer)
        s._bg_grow_watcher = None
        s._graph_file = None
        s._maybe_start_background_grow()
        assert s._bg_grow_watcher is None

    def test_EG12_maybe_start_is_idempotent(self, monkeypatch):
        """Second call is a no-op when a watcher is already set."""
        monkeypatch.delenv("GRAQLE_DISABLE_BACKGROUND_GROW", raising=False)
        from graqle.plugins.mcp_dev_server import KogniDevServer
        s = KogniDevServer.__new__(KogniDevServer)
        sentinel = object()
        s._bg_grow_watcher = sentinel
        s._graph_file = None
        s._maybe_start_background_grow()
        assert s._bg_grow_watcher is sentinel  # untouched

    def test_EG12_wired_in_both_load_paths(self):
        """Both the Neo4j and JSON graph-load paths call the watcher start.

        Guards against the handoff bug where only the Neo4j path was patched.
        """
        import inspect
        from graqle.plugins import mcp_dev_server
        src = inspect.getsource(mcp_dev_server.KogniDevServer._load_graph_impl)
        assert src.count("_maybe_start_background_grow()") >= 2, (
            "expected the watcher to be started on BOTH the neo4j and JSON "
            "load paths"
        )
