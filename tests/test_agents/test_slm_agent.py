"""Tests for agent abstractions."""

# ── graqle:intelligence ──
# module: tests.test_agents.test_slm_agent
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, base_agent, slm_agent, mock, message +1 more
# constraints: none
# ── /graqle:intelligence ──

import pytest

from graqle.agents.base_agent import BaseAgent
from graqle.agents.slm_agent import SLMAgent
from graqle.backends.mock import MockBackend
from graqle.core.message import Message
from graqle.core.types import ReasoningType


@pytest.mark.asyncio
async def test_slm_agent_basic():
    """SLMAgent generates a response from backend."""
    backend = MockBackend(response="Agent response here")
    agent = SLMAgent(backend)
    result = await agent.reason(
        query="What is GDPR?",
        context=[],
        node_info={"label": "GDPR", "description": "EU data regulation"},
    )
    assert result == "Agent response here"
    assert backend.call_count == 1


@pytest.mark.asyncio
async def test_slm_agent_with_context():
    """SLMAgent includes neighbor messages in prompt."""
    backend = MockBackend(response="Synthesized")
    agent = SLMAgent(backend, system_prompt="You are an EU expert.")
    msg = Message(
        source_node_id="n2",
        target_node_id="n1",
        round=0,
        content="Neighbor insight about AI Act.",
        reasoning_type=ReasoningType.ASSERTION,
        confidence=0.7,
        evidence=["n2"],
    )
    result = await agent.reason(
        query="How do GDPR and AI Act interact?",
        context=[msg],
        node_info={"label": "GDPR", "description": "Data protection"},
    )
    assert result == "Synthesized"
    # Check that the backend received a prompt with context
    assert backend.call_count == 1


@pytest.mark.asyncio
async def test_slm_agent_custom_params():
    """SLMAgent respects custom max_tokens and temperature."""
    backend = MockBackend(response="ok")
    agent = SLMAgent(backend, max_tokens=256, temperature=0.1)
    assert agent.max_tokens == 256
    assert agent.temperature == 0.1
    await agent.reason("q", [], {"label": "X", "description": ""})
    assert backend.call_count == 1


def test_agent_name():
    """Agent name property returns class name."""
    backend = MockBackend()
    agent = SLMAgent(backend)
    assert agent.name == "SLMAgent"


def test_base_agent_is_abstract():
    """Cannot instantiate BaseAgent directly."""
    with pytest.raises(TypeError):
        BaseAgent(MockBackend())
