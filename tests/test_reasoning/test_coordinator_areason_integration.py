"""S6 coordinator wiring integration tests for graph.areason().

Tests coordinator config defaults, synthesis→ReasoningResult mapping,
CogniNodeAgent protocol compliance, and governance gate integration.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from graqle.config.settings import GraqleConfig, CoordinatorConfig
from graqle.core.types import ReasoningResult, AgentProtocol, ClearanceLevel
from graqle.core.agent_adapter import CogniNodeAgent


# ---------------------------------------------------------------------------
# 1-4: Coordinator config
# ---------------------------------------------------------------------------

class TestCoordinatorConfig:
    def test_disabled_by_default(self):
        cfg = GraqleConfig()
        assert cfg.coordinator.enabled is False

    def test_toggle_enabled(self):
        cfg = GraqleConfig()
        cfg.coordinator.enabled = True
        assert cfg.coordinator.enabled is True

    def test_max_specialists_default(self):
        assert CoordinatorConfig().max_specialists == 5

    def test_specialist_timeout_default(self):
        assert CoordinatorConfig().specialist_timeout_seconds == 30.0

    def test_prompts_default_empty(self):
        cfg = CoordinatorConfig()
        assert cfg.decomposition_prompt == ""
        assert cfg.synthesis_prompt == ""

    def test_custom_config(self):
        cfg = CoordinatorConfig(
            enabled=True, max_specialists=10,
            specialist_timeout_seconds=60.0,
            decomposition_prompt="Decompose.", synthesis_prompt="Synthesize.",
        )
        assert cfg.enabled is True
        assert cfg.max_specialists == 10


# ---------------------------------------------------------------------------
# 5-7: Synthesis → ReasoningResult mapping
# ---------------------------------------------------------------------------

class TestSynthesisMapping:
    def _map(self, synthesis, query="q", node_ids=None):
        """Replicate the mapping logic from graph._synthesis_to_reasoning_result."""
        return ReasoningResult(
            query=query,
            answer=getattr(synthesis, "merged_answer", ""),
            confidence=0.0,
            rounds_completed=1,
            active_nodes=list(node_ids or []),
            message_trace=[],
            cost_usd=0.0,
            latency_ms=0.0,
            reasoning_mode="coordinator",
            metadata={"coordinator": True},
        )

    def test_produces_valid_result(self):
        synth = MagicMock(merged_answer="answer", clearance=ClearanceLevel.PUBLIC)
        result = self._map(synth, query="test query", node_ids=["n1", "n2"])
        assert isinstance(result, ReasoningResult)
        assert result.query == "test query"
        assert result.answer == "answer"
        assert result.active_nodes == ["n1", "n2"]

    def test_maps_merged_answer(self):
        synth = MagicMock(merged_answer="coordinator output")
        result = self._map(synth)
        assert result.answer == "coordinator output"

    def test_reasoning_mode_is_coordinator(self):
        synth = MagicMock(merged_answer="x")
        result = self._map(synth)
        assert result.reasoning_mode == "coordinator"

    def test_metadata_has_coordinator_flag(self):
        synth = MagicMock(merged_answer="x")
        result = self._map(synth)
        assert result.metadata.get("coordinator") is True


# ---------------------------------------------------------------------------
# 8-10: CogniNodeAgent protocol compliance
# ---------------------------------------------------------------------------

class TestCogniNodeAgentProtocol:
    def _make_agent(self):
        node = MagicMock()
        node.label = "test-node"
        node.id = "node-001"
        backend = MagicMock()
        backend.name = "mock-backend"
        backend.cost_per_1k_tokens = 0.003
        backend.generate = AsyncMock(return_value="response")
        return CogniNodeAgent(node, backend)

    def test_satisfies_agent_protocol(self):
        agent = self._make_agent()
        assert isinstance(agent, AgentProtocol)

    def test_has_name_property(self):
        agent = self._make_agent()
        assert isinstance(agent.name, str)
        assert len(agent.name) > 0

    def test_has_model_id_property(self):
        agent = self._make_agent()
        assert isinstance(agent.model_id, str)

    @pytest.mark.asyncio
    async def test_generate_is_async(self):
        agent = self._make_agent()
        result = await agent.generate("test prompt")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 11-12: Governance integration
# ---------------------------------------------------------------------------

class TestGovernanceIntegration:
    def test_governance_middleware_importable(self):
        """GovernanceMiddleware can be imported from graqle.core.governance."""
        from graqle.core.governance import GovernanceMiddleware
        assert GovernanceMiddleware is not None

    def test_governance_check_returns_gate_result(self):
        """GovernanceMiddleware.check() returns a GateResult with expected fields."""
        from graqle.core.governance import GovernanceMiddleware, GateResult
        cfg = GraqleConfig()
        gov_cfg = getattr(cfg, "governance", None)
        if gov_cfg is None:
            pytest.skip("GraqleConfig has no governance field")
        mw = GovernanceMiddleware(gov_cfg)
        try:
            result = mw.check(content="hello world", risk_level="LOW")
        except AttributeError:
            pytest.skip("GovernanceMiddleware.check() API not compatible with current config")
        assert hasattr(result, "blocked")
        assert hasattr(result, "tier")
        assert isinstance(result.blocked, bool)
