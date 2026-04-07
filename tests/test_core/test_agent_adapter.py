"""Tests for CogniNodeAgent in graqle/core/agent_adapter.py."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock

from graqle.core.types import ClearanceLevel
from graqle.core.agent_adapter import CogniNodeAgent


def _make_node(*, node_id="node-abc", label="TestNode", capability_tags=("tag_a",)):
    node = MagicMock()
    node.id = node_id
    node.label = label
    node.capability_tags = capability_tags
    return node


def _make_backend(*, name="mock-backend", generate_return="Hello"):
    backend = MagicMock()
    backend.name = name
    backend.cost_per_1k_tokens = 0.003
    backend.generate = AsyncMock(return_value=generate_return)
    return backend


class TestConstructorValidation:
    def test_rejects_none_node(self):
        with pytest.raises(ValueError, match="node"):
            CogniNodeAgent(None, _make_backend())

    def test_rejects_none_backend(self):
        with pytest.raises(ValueError, match="backend"):
            CogniNodeAgent(_make_node(), None)

    def test_accepts_valid_inputs(self):
        agent = CogniNodeAgent(_make_node(), _make_backend())
        assert agent is not None


class TestNameProperty:
    def test_returns_label(self):
        agent = CogniNodeAgent(_make_node(label="MyAgent"), _make_backend())
        assert agent.name == "MyAgent"

    def test_falls_back_to_id_when_label_falsy(self):
        node = _make_node(node_id="fallback-id", label="")
        agent = CogniNodeAgent(node, _make_backend())
        assert agent.name == "fallback-id"

    def test_falls_back_to_id_when_label_none(self):
        node = _make_node(node_id="fallback-id")
        node.label = None
        agent = CogniNodeAgent(node, _make_backend())
        assert agent.name == "fallback-id"


class TestModelId:
    def test_returns_backend_name(self):
        agent = CogniNodeAgent(_make_node(), _make_backend(name="claude-sonnet"))
        assert agent.model_id == "claude-sonnet"


class TestGenerate:
    @pytest.mark.asyncio
    async def test_delegates_to_backend(self):
        backend = _make_backend(generate_return="delegated")
        agent = CogniNodeAgent(_make_node(), backend)
        result = await agent.generate("Hello?")
        assert result == "delegated"
        backend.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_none_return(self):
        backend = _make_backend()
        backend.generate = AsyncMock(return_value=None)
        agent = CogniNodeAgent(_make_node(), backend)
        result = await agent.generate("prompt")
        assert result == ""

    @pytest.mark.asyncio
    async def test_handles_object_with_text_attr(self):
        result_obj = MagicMock()
        result_obj.text = "from text attr"
        backend = _make_backend()
        backend.generate = AsyncMock(return_value=result_obj)
        agent = CogniNodeAgent(_make_node(), backend)
        result = await agent.generate("prompt")
        assert result == "from text attr"


class TestClearanceLevel:
    def test_defaults_to_public(self):
        agent = CogniNodeAgent(_make_node(), _make_backend())
        assert agent.clearance_level == ClearanceLevel.PUBLIC

    def test_custom_clearance(self):
        agent = CogniNodeAgent(
            _make_node(), _make_backend(),
            clearance_level=ClearanceLevel.CONFIDENTIAL,
        )
        assert agent.clearance_level == ClearanceLevel.CONFIDENTIAL


class TestCapabilityTags:
    def test_from_node(self):
        agent = CogniNodeAgent(
            _make_node(capability_tags=("nlp", "code")), _make_backend()
        )
        assert agent.capability_tags == ("nlp", "code")

    def test_empty_default(self):
        node = _make_node()
        del node.capability_tags
        agent = CogniNodeAgent(node, _make_backend())
        assert agent.capability_tags == ()


class TestId:
    def test_from_node_id(self):
        agent = CogniNodeAgent(_make_node(node_id="xyz-123"), _make_backend())
        assert agent.id == "xyz-123"


class TestCostPer1kTokens:
    def test_returns_backend_cost(self):
        agent = CogniNodeAgent(_make_node(), _make_backend())
        assert agent.cost_per_1k_tokens == pytest.approx(0.003)

    def test_returns_zero_on_invalid(self):
        backend = _make_backend()
        backend.cost_per_1k_tokens = "not-a-number"
        agent = CogniNodeAgent(_make_node(), backend)
        assert agent.cost_per_1k_tokens == 0.0

    def test_returns_zero_when_missing(self):
        backend = _make_backend()
        del backend.cost_per_1k_tokens
        agent = CogniNodeAgent(_make_node(), backend)
        assert agent.cost_per_1k_tokens == 0.0
