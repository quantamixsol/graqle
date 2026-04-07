"""S10: End-to-end hardening tests for the coordinator pipeline.

Tests exercise CoordinatorConfig defaults, YAML loading, and
ReasoningResult field mapping.
"""
from __future__ import annotations

import pytest
from graqle.config.settings import CoordinatorConfig, GraqleConfig
from graqle.core.types import ReasoningResult


class TestCoordinatorConfigDefaults:
    """CoordinatorConfig has correct defaults."""

    def test_enabled_false_by_default(self):
        cfg = CoordinatorConfig()
        assert cfg.enabled is False

    def test_max_specialists_default(self):
        cfg = CoordinatorConfig()
        assert cfg.max_specialists == 5

    def test_specialist_timeout_default(self):
        cfg = CoordinatorConfig()
        assert cfg.specialist_timeout_seconds == 30.0

    def test_prompts_default_empty(self):
        cfg = CoordinatorConfig()
        assert cfg.decomposition_prompt == ""
        assert cfg.synthesis_prompt == ""


class TestCoordinatorConfigFromDict:
    """CoordinatorConfig loads from YAML-style dict."""

    def test_all_fields_load(self):
        cfg = CoordinatorConfig(
            enabled=True,
            max_specialists=8,
            specialist_timeout_seconds=60.0,
            decomposition_prompt="Decompose this.",
            synthesis_prompt="Synthesize this.",
        )
        assert cfg.enabled is True
        assert cfg.max_specialists == 8
        assert cfg.specialist_timeout_seconds == 60.0
        assert cfg.decomposition_prompt == "Decompose this."
        assert cfg.synthesis_prompt == "Synthesize this."

    def test_partial_override(self):
        cfg = CoordinatorConfig(enabled=True, max_specialists=10)
        assert cfg.enabled is True
        assert cfg.max_specialists == 10
        assert cfg.specialist_timeout_seconds == 30.0  # default


class TestGraqleConfigHasCoordinator:
    """GraqleConfig includes coordinator field."""

    def test_coordinator_field_exists(self):
        cfg = GraqleConfig()
        assert hasattr(cfg, "coordinator")
        assert isinstance(cfg.coordinator, CoordinatorConfig)

    def test_coordinator_disabled_by_default(self):
        cfg = GraqleConfig()
        assert cfg.coordinator.enabled is False

    def test_coordinator_can_be_enabled(self):
        cfg = GraqleConfig()
        cfg.coordinator.enabled = True
        assert cfg.coordinator.enabled is True


class TestReasoningResultFields:
    """ReasoningResult has all required fields for coordinator results."""

    def test_all_required_fields(self):
        result = ReasoningResult(
            query="test query",
            answer="test answer",
            confidence=0.85,
            rounds_completed=1,
            active_nodes=["node_a", "node_b"],
            message_trace=[],
            cost_usd=0.002,
            latency_ms=150.0,
        )
        assert result.query == "test query"
        assert result.answer == "test answer"
        assert 0.0 <= result.confidence <= 1.0
        assert result.rounds_completed >= 1
        assert isinstance(result.active_nodes, list)
        assert result.cost_usd >= 0.0
        assert result.latency_ms >= 0.0

    def test_reasoning_mode_field(self):
        result = ReasoningResult(
            query="q", answer="a", confidence=0.5,
            rounds_completed=1, active_nodes=[], message_trace=[],
            cost_usd=0.0, latency_ms=0.0,
            reasoning_mode="coordinator",
        )
        assert result.reasoning_mode == "coordinator"

    def test_metadata_dict(self):
        result = ReasoningResult(
            query="q", answer="a", confidence=0.5,
            rounds_completed=1, active_nodes=[], message_trace=[],
            cost_usd=0.0, latency_ms=0.0,
            metadata={"coordinator": True, "clearance": "PUBLIC"},
        )
        assert result.metadata["coordinator"] is True
        assert result.metadata["clearance"] == "PUBLIC"

    def test_confidence_zero_warns(self):
        """confidence=0.0 is valid but triggers a warning."""
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ReasoningResult(
                query="q", answer="a", confidence=0.0,
                rounds_completed=1, active_nodes=[], message_trace=[],
                cost_usd=0.0, latency_ms=0.0,
            )
            assert any("0.0" in str(warning.message) for warning in w)

    def test_confidence_none_raises(self):
        """confidence=None must raise ValueError."""
        with pytest.raises(ValueError, match="confidence"):
            ReasoningResult(
                query="q", answer="a", confidence=None,
                rounds_completed=1, active_nodes=[], message_trace=[],
                cost_usd=0.0, latency_ms=0.0,
            )
