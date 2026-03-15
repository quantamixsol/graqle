"""Tests for MockBackend."""

# ── graqle:intelligence ──
# module: tests.test_backends.test_mock
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, mock
# constraints: none
# ── /graqle:intelligence ──

import pytest

from graqle.backends.mock import MockBackend


@pytest.mark.asyncio
async def test_mock_default_response():
    backend = MockBackend()
    result = await backend.generate("test prompt")
    assert "Confidence" in result
    assert backend.call_count == 1


@pytest.mark.asyncio
async def test_mock_fixed_response():
    backend = MockBackend(response="Fixed answer")
    result = await backend.generate("any prompt")
    assert result == "Fixed answer"


@pytest.mark.asyncio
async def test_mock_rotating_responses():
    backend = MockBackend(responses=["Answer A", "Answer B"])
    r1 = await backend.generate("q1")
    r2 = await backend.generate("q2")
    r3 = await backend.generate("q3")
    assert r1 == "Answer A"
    assert r2 == "Answer B"
    assert r3 == "Answer A"  # wraps around


def test_mock_properties():
    backend = MockBackend()
    assert backend.name == "mock"
    assert backend.cost_per_1k_tokens == 0.0
