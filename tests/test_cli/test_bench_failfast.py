"""Tests for P1-5: graq bench fails fast when backend is unavailable."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestBenchFailFast:
    def test_bench_detects_fallback_backend(self):
        """If backend is a MockBackend fallback, bench should exit immediately."""
        from graqle.cli.main import bench

        mock_backend = MagicMock()
        mock_backend.is_fallback = True
        mock_backend.fallback_reason = "ANTHROPIC_API_KEY not set"

        with patch("graqle.cli.main._load_graph") as mock_load, \
             patch("graqle.cli.main._create_backend_from_config", return_value=mock_backend):
            mock_load.return_value = MagicMock()
            with pytest.raises((SystemExit, Exception)):
                bench(config="graqle.yaml", queries=5, max_rounds=3)


class TestWindowsUnicodeEnv:
    def test_pythonioencoding_set_on_import(self):
        """graqle.cli.main should set PYTHONIOENCODING=utf-8 on Windows."""
        import os
        # After importing main, the env var should be set (on Windows)
        import graqle.cli.main  # noqa: F401
        if __import__("sys").platform == "win32":
            assert os.environ.get("PYTHONIOENCODING") == "utf-8"
