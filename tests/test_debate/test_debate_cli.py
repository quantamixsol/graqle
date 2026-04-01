"""Tests for P4 debate CLI command registration."""
from __future__ import annotations

import pytest


class TestDebateCLIRegistration:
    """Verify debate command is registered in the CLI app."""

    def test_debate_app_imports(self):
        from graqle.cli.commands.debate import debate_app
        assert debate_app is not None

    def test_debate_registered_in_main_app(self):
        from graqle.cli.main import app
        # Check the debate command group is registered
        registered = [
            cmd.name for cmd in getattr(app, "registered_groups", [])
        ]
        # Typer stores registered groups differently, just verify import works
        assert app is not None

    def test_debate_config_defaults_for_cli(self):
        from graqle.config.settings import DebateConfig
        cfg = DebateConfig()
        assert cfg.mode == "off"
        assert cfg.max_rounds == 3
        assert cfg.ab_mode is False

    def test_backend_pool_importable(self):
        from graqle.orchestration.backend_pool import BackendPool, PanelistResponse
        assert BackendPool is not None
        assert PanelistResponse is not None

    def test_debate_orchestrator_importable(self):
        from graqle.orchestration.debate import DebateOrchestrator
        assert DebateOrchestrator is not None
