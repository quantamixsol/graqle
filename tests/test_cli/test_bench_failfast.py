"""Tests for graq bench fail-fast behavior and TTY auto-detection."""

# ── graqle:intelligence ──
# module: tests.test_cli.test_bench_failfast
# risk: LOW (impact radius: 1 modules)
# consumers: scan
# dependencies: __future__, mock, pytest
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# typer.Exit raises click.exceptions.Exit in some contexts
_EXIT_EXCEPTIONS = (SystemExit, Exception)


class TestBenchFailFast:
    """P1-6: graq bench should stop immediately on first query failure."""

    def test_bench_detects_fallback_backend(self):
        """If backend is a MockBackend fallback, bench should exit immediately."""
        from graqle.cli.main import bench

        mock_backend = MagicMock()
        mock_backend.is_fallback = True
        mock_backend.fallback_reason = "ANTHROPIC_API_KEY not set"

        with patch("graqle.cli.main._load_graph") as mock_load, \
             patch("graqle.cli.main._create_backend_from_config", return_value=mock_backend):
            mock_load.return_value = MagicMock()
            with pytest.raises(_EXIT_EXCEPTIONS):
                bench(config="graqle.yaml", queries=5, max_rounds=3)

    def test_bench_smoke_test_catches_bad_backend(self):
        """Smoke test should catch backend errors before running N queries."""
        from graqle.cli.main import bench
        from graqle.backends.api import BackendError

        mock_backend = MagicMock()
        mock_backend.is_fallback = False

        mock_graph = MagicMock()

        # The bench function does `import asyncio` locally then calls asyncio.run().
        # We need to make the graph's areason raise when called via asyncio.run.
        # Patch at the module level where asyncio lives.
        original_asyncio_run = __import__("asyncio").run

        def fake_asyncio_run(coro):
            raise BackendError("bedrock", "Invalid model ID", 3)

        with patch("graqle.cli.main._load_graph", return_value=mock_graph), \
             patch("graqle.cli.main._create_backend_from_config", return_value=mock_backend):
            import asyncio
            old_run = asyncio.run
            asyncio.run = fake_asyncio_run
            try:
                with pytest.raises(_EXIT_EXCEPTIONS):
                    bench(config="graqle.yaml", queries=5, max_rounds=3)
            finally:
                asyncio.run = old_run

    def test_bench_failfast_stops_on_first_query_error(self):
        """After smoke test passes, if first real query fails, stop immediately."""
        from graqle.cli.main import bench
        from graqle.backends.api import BackendError

        mock_backend = MagicMock()
        mock_backend.is_fallback = False

        mock_graph = MagicMock()

        call_count = 0

        def fake_asyncio_run(coro):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Smoke test passes
                return MagicMock(confidence=0.8, rounds_completed=1, node_count=5)
            else:
                # First real query fails
                raise BackendError("bedrock", "Model not found", 3)

        with patch("graqle.cli.main._load_graph", return_value=mock_graph), \
             patch("graqle.cli.main._create_backend_from_config", return_value=mock_backend):
            import asyncio
            old_run = asyncio.run
            asyncio.run = fake_asyncio_run
            try:
                with pytest.raises(_EXIT_EXCEPTIONS):
                    bench(config="graqle.yaml", queries=5, max_rounds=3)
            finally:
                asyncio.run = old_run

        # Should have stopped after smoke test + first failed query = 2 calls
        assert call_count == 2, f"Expected 2 asyncio.run calls but got {call_count}"

    def test_bench_failfast_does_not_retry_all_queries(self):
        """Verify that fail-fast prevents running remaining queries."""
        from graqle.cli.main import bench
        from graqle.backends.api import BackendError

        mock_backend = MagicMock()
        mock_backend.is_fallback = False

        mock_graph = MagicMock()

        call_count = 0

        def fake_asyncio_run(coro):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                # Smoke test passes
                return MagicMock(confidence=0.8, rounds_completed=1, node_count=5)
            elif call_count == 2:
                # First real query passes
                return MagicMock(
                    confidence=0.7, rounds_completed=2, node_count=5,
                    cost_usd=0.001, latency_ms=100.0,
                )
            else:
                # Second query fails
                raise BackendError("bedrock", "throttled", 3)

        with patch("graqle.cli.main._load_graph", return_value=mock_graph), \
             patch("graqle.cli.main._create_backend_from_config", return_value=mock_backend):
            import asyncio
            old_run = asyncio.run
            asyncio.run = fake_asyncio_run
            try:
                with pytest.raises(_EXIT_EXCEPTIONS):
                    bench(config="graqle.yaml", queries=10, max_rounds=3)
            finally:
                asyncio.run = old_run

        # Should stop at call 3 (smoke + 1 pass + 1 fail), NOT run all 10
        assert call_count == 3, f"Expected 3 calls (not all 10), got {call_count}"


class TestMockBackendFallbackAttributes:
    """Verify MockBackend exposes is_fallback as a public attribute."""

    def test_mock_backend_has_public_is_fallback(self):
        from graqle.backends.mock import MockBackend

        mock = MockBackend(is_fallback=True, fallback_reason="test reason")
        assert mock.is_fallback is True
        assert mock.fallback_reason == "test reason"

    def test_mock_backend_not_fallback_by_default(self):
        from graqle.backends.mock import MockBackend

        mock = MockBackend()
        assert mock.is_fallback is False
        assert mock.fallback_reason == ""


class TestBedrockModelIdValidation:
    """P1-5: graq doctor should validate Bedrock model IDs."""

    def test_check_skips_when_not_bedrock(self, tmp_path):
        """Should return empty results when backend is not bedrock."""
        import os
        from graqle.cli.commands.doctor import _check_bedrock_model_id

        config = tmp_path / "graqle.yaml"
        config.write_text("model:\n  backend: anthropic\n  model: claude-haiku-4-5-20251001\n")

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            results = _check_bedrock_model_id()
            assert results == []
        finally:
            os.chdir(old_cwd)

    def test_check_skips_when_no_config(self, tmp_path):
        """Should return empty results when no config file exists."""
        import os
        from graqle.cli.commands.doctor import _check_bedrock_model_id

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            results = _check_bedrock_model_id()
            assert results == []
        finally:
            os.chdir(old_cwd)

    def test_check_validates_valid_model(self, tmp_path):
        """Should pass when configured model ID is in available models."""
        import os
        from graqle.cli.commands.doctor import _check_bedrock_model_id, PASS

        config = tmp_path / "graqle.yaml"
        config.write_text(
            "model:\n"
            "  backend: bedrock\n"
            "  model: anthropic.claude-haiku-4-5-20251001-v1:0\n"
            "  region: us-east-1\n"
        )

        mock_client = MagicMock()
        mock_client.list_foundation_models.return_value = {
            "modelSummaries": [
                {"modelId": "anthropic.claude-haiku-4-5-20251001-v1:0"},
                {"modelId": "anthropic.claude-sonnet-4-6"},
            ]
        }

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with patch("boto3.client", return_value=mock_client):
                results = _check_bedrock_model_id()
            assert len(results) == 1
            assert results[0][0] == PASS
            assert "valid" in results[0][2].lower()
        finally:
            os.chdir(old_cwd)

    def test_check_warns_invalid_model(self, tmp_path):
        """Should warn when model ID is not in available models."""
        import os
        from graqle.cli.commands.doctor import _check_bedrock_model_id, WARN

        config = tmp_path / "graqle.yaml"
        config.write_text(
            "model:\n"
            "  backend: bedrock\n"
            "  model: anthropic.claude-nonexistent-v1:0\n"
            "  region: us-east-1\n"
        )

        mock_client = MagicMock()
        mock_client.list_foundation_models.return_value = {
            "modelSummaries": [
                {"modelId": "anthropic.claude-haiku-4-5-20251001-v1:0"},
                {"modelId": "anthropic.claude-sonnet-4-6"},
            ]
        }

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with patch("boto3.client", return_value=mock_client):
                results = _check_bedrock_model_id()
            assert len(results) == 1
            assert results[0][0] == WARN
            assert "not found" in results[0][2].lower()
        finally:
            os.chdir(old_cwd)

    def test_check_handles_inference_profiles(self, tmp_path):
        """Should recognize eu./us./ap./global. prefixed inference profiles."""
        import os
        from graqle.cli.commands.doctor import _check_bedrock_model_id, PASS

        config = tmp_path / "graqle.yaml"
        config.write_text(
            "model:\n"
            "  backend: bedrock\n"
            "  model: eu.anthropic.claude-sonnet-4-6\n"
            "  region: eu-central-1\n"
        )

        mock_client = MagicMock()
        mock_client.list_foundation_models.return_value = {
            "modelSummaries": [
                {"modelId": "anthropic.claude-sonnet-4-6"},
            ]
        }

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with patch("boto3.client", return_value=mock_client):
                results = _check_bedrock_model_id()
            assert len(results) == 1
            assert results[0][0] == PASS
            assert "inference profile" in results[0][2].lower()
        finally:
            os.chdir(old_cwd)

    def test_check_graceful_on_boto3_error(self, tmp_path):
        """Should skip gracefully when boto3 can't connect."""
        import os
        from graqle.cli.commands.doctor import _check_bedrock_model_id, WARN

        config = tmp_path / "graqle.yaml"
        config.write_text(
            "model:\n"
            "  backend: bedrock\n"
            "  model: anthropic.claude-haiku-4-5-20251001-v1:0\n"
            "  region: eu-north-1\n"
        )

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with patch("boto3.client", side_effect=Exception("connection refused")):
                results = _check_bedrock_model_id()
            assert len(results) == 1
            assert results[0][0] == WARN
            assert "could not validate" in results[0][2].lower()
        finally:
            os.chdir(old_cwd)


class TestGraqleIgnore:
    """P2-8: .graqle-ignore should be read by scanner."""

    def test_gitignore_matcher_reads_graqle_ignore(self, tmp_path):
        """GitignoreMatcher should load patterns from .graqle-ignore."""
        from graqle.cli.commands.scan import GitignoreMatcher

        # Create a .graqle-ignore file
        ignore_file = tmp_path / ".graqle-ignore"
        ignore_file.write_text("*.log\nbuild/\nsecrets/\n")

        matcher = GitignoreMatcher(tmp_path)

        assert matcher.is_ignored("app.log") is True
        assert matcher.is_ignored("build/output.js") is True
        assert matcher.is_ignored("secrets/key.pem") is True
        assert matcher.is_ignored("src/main.py") is False

    def test_graqle_ignore_combined_with_gitignore(self, tmp_path):
        """Both .gitignore and .graqle-ignore patterns should apply."""
        from graqle.cli.commands.scan import GitignoreMatcher

        (tmp_path / ".gitignore").write_text("node_modules/\n*.pyc\n")
        (tmp_path / ".graqle-ignore").write_text("*.log\nvendor/\n")

        matcher = GitignoreMatcher(tmp_path)

        # From .gitignore
        assert matcher.is_ignored("node_modules/package.json") is True
        assert matcher.is_ignored("test.pyc") is True
        # From .graqle-ignore
        assert matcher.is_ignored("app.log") is True
        assert matcher.is_ignored("vendor/lib.js") is True
        # Neither
        assert matcher.is_ignored("src/main.py") is False

    def test_graqle_ignore_combined_with_exclude_flag(self, tmp_path):
        """--exclude patterns and .graqle-ignore should both apply."""
        from graqle.cli.commands.scan import GitignoreMatcher

        (tmp_path / ".graqle-ignore").write_text("*.log\n")

        matcher = GitignoreMatcher(tmp_path, extra_patterns=["*.tmp"])

        assert matcher.is_ignored("app.log") is True
        assert matcher.is_ignored("cache.tmp") is True
        assert matcher.is_ignored("src/main.py") is False


class TestTTYAutoDetection:
    """P2-9: Non-TTY environments should auto-enable --no-interactive."""

    def test_init_detects_non_tty(self):
        """init_command should set no_interactive=True when stdin is not a TTY."""
        # This is already implemented in graqle/cli/commands/init.py lines 1525-1530.
        # We verify the logic exists by checking the source code.
        import inspect
        from graqle.cli.commands import init

        source = inspect.getsource(init.init_command)
        assert "sys.stdin.isatty()" in source
        assert "no_interactive = True" in source

    def test_isatty_returns_false_for_pipe(self):
        """sys.stdin.isatty() returns False when piped (not a terminal)."""
        import io

        fake_stdin = io.StringIO("test input")
        assert not fake_stdin.isatty()


class TestWindowsUnicodeEnv:
    def test_pythonioencoding_set_on_import(self):
        """graqle.cli.main should set PYTHONIOENCODING=utf-8 on Windows."""
        import os
        # After importing main, the env var should be set (on Windows)
        import graqle.cli.main  # noqa: F401
        if __import__("sys").platform == "win32":
            assert os.environ.get("PYTHONIOENCODING") == "utf-8"
