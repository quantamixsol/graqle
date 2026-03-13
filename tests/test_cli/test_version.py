"""Tests for P2-8: graq --version flag."""

from __future__ import annotations

from typer.testing import CliRunner

from graqle.cli.main import app

runner = CliRunner()


class TestVersionFlag:
    def test_version_flag(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "graq " in result.output
        # Should contain a semver-like version string
        parts = result.output.strip().split(" ", 1)
        assert len(parts) == 2
        assert parts[0] == "graq"
        # Version should have at least major.minor.patch
        version_parts = parts[1].split(".")
        assert len(version_parts) >= 2

    def test_version_flag_matches_package(self):
        from graqle.__version__ import __version__
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_version_command_still_works(self):
        """The existing 'graq version' subcommand should still work."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "Graqle v" in result.output
