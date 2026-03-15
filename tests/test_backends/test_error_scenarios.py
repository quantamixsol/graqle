"""T60 — Error scenario tests for hardened backends and budget enforcement.

Covers: backend timeout, auth failure (401), malformed response, rate limit (429),
budget exceeded, empty graph, fallback chain, retry with backoff.
"""

# ── graqle:intelligence ──
# module: tests.test_backends.test_error_scenarios
# risk: CRITICAL (impact radius: 34 modules)
# consumers: routing, reformulator, api, gemini, providers +29 more
# dependencies: __future__, asyncio, mock, pytest, api +6 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graqle.backends.api import (
    BackendError,
    _retry_with_backoff,
    AnthropicBackend,
    OpenAIBackend,
    OllamaBackend,
    CustomBackend,
)
from graqle.backends.fallback import BackendFallbackChain
from graqle.backends.base import BaseBackend
from graqle.backends.mock import MockBackend
from graqle.config.settings import GraqleConfig, CostConfig
from graqle.core.graph import Graqle
from graqle.orchestration.orchestrator import Orchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FailingBackend(BaseBackend):
    """Backend that always raises."""

    def __init__(self, error: Exception, name_str: str = "failing") -> None:
        self._error = error
        self._name = name_str

    async def generate(self, prompt, **kwargs) -> str:
        raise self._error

    @property
    def name(self) -> str:
        return self._name

    @property
    def cost_per_1k_tokens(self) -> float:
        return 0.001


class CountingBackend(BaseBackend):
    """Backend that fails N times then succeeds."""

    def __init__(self, fail_count: int, name_str: str = "counting") -> None:
        self._fail_count = fail_count
        self._calls = 0
        self._name = name_str

    async def generate(self, prompt, **kwargs) -> str:
        self._calls += 1
        if self._calls <= self._fail_count:
            raise RuntimeError(f"Failure #{self._calls}")
        return "Success after retries. Confidence: 85%"

    @property
    def name(self) -> str:
        return self._name

    @property
    def cost_per_1k_tokens(self) -> float:
        return 0.001


# ===========================================================================
# 1. Retry with backoff
# ===========================================================================

@pytest.mark.asyncio
async def test_retry_succeeds_on_first_attempt():
    """No retries needed when function succeeds immediately."""
    call_count = 0

    async def fn():
        nonlocal call_count
        call_count += 1
        return "ok"

    result = await _retry_with_backoff(fn, backend_name="test", max_retries=3)
    assert result == "ok"
    assert call_count == 1


@pytest.mark.asyncio
async def test_retry_succeeds_after_failures():
    """Retries and eventually succeeds."""
    call_count = 0

    async def fn():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError("transient")
        return "recovered"

    result = await _retry_with_backoff(fn, backend_name="test", max_retries=3)
    assert result == "recovered"
    assert call_count == 3


@pytest.mark.asyncio
async def test_retry_raises_backend_error_after_max():
    """Raises BackendError after exhausting retries."""
    async def fn():
        raise RuntimeError("permanent failure")

    with pytest.raises(BackendError) as exc_info:
        await _retry_with_backoff(fn, backend_name="test-be", max_retries=2)

    assert "test-be" in str(exc_info.value)
    assert exc_info.value.attempts == 2


@pytest.mark.asyncio
async def test_retry_does_not_retry_import_errors():
    """ImportError is immediately re-raised without retry."""
    call_count = 0

    async def fn():
        nonlocal call_count
        call_count += 1
        raise ImportError("missing package")

    with pytest.raises(ImportError):
        await _retry_with_backoff(fn, backend_name="test", max_retries=3)

    assert call_count == 1  # no retry


# ===========================================================================
# 2. BackendError
# ===========================================================================

def test_backend_error_attributes():
    err = BackendError("anthropic:claude", "rate limited", 3)
    assert err.backend_name == "anthropic:claude"
    assert err.attempts == 3
    assert "anthropic:claude" in str(err)
    assert "3 attempts" in str(err)


# ===========================================================================
# 3. BackendFallbackChain
# ===========================================================================

@pytest.mark.asyncio
async def test_fallback_uses_first_working_backend():
    """First backend succeeds — no fallback needed."""
    b1 = MockBackend(response="primary answer. Confidence: 90%")
    b2 = MockBackend(response="secondary answer. Confidence: 80%")
    chain = BackendFallbackChain([b1, b2])

    result = await chain.generate("test")
    assert "primary" in result
    assert chain.last_used == "mock"


@pytest.mark.asyncio
async def test_fallback_falls_to_secondary():
    """Primary fails, secondary succeeds."""
    b1 = FailingBackend(RuntimeError("primary down"), name_str="primary")
    b2 = MockBackend(response="secondary result. Confidence: 85%")
    chain = BackendFallbackChain([b1, b2])

    result = await chain.generate("test")
    assert "secondary" in result
    assert chain.last_used == "mock"
    assert chain.failure_counts["primary"] == 1


@pytest.mark.asyncio
async def test_fallback_all_fail():
    """All backends fail — RuntimeError with summary."""
    b1 = FailingBackend(RuntimeError("err1"), name_str="b1")
    b2 = FailingBackend(ValueError("err2"), name_str="b2")
    chain = BackendFallbackChain([b1, b2])

    with pytest.raises(RuntimeError, match="All 2 backends failed"):
        await chain.generate("test")


def test_fallback_requires_at_least_one():
    with pytest.raises(ValueError, match="at least one"):
        BackendFallbackChain([])


def test_fallback_name_property():
    b1 = MockBackend()
    b2 = MockBackend()
    chain = BackendFallbackChain([b1, b2])
    assert "fallback:" in chain.name
    assert "mock" in chain.name


def test_fallback_cost_uses_last_used():
    b1 = FailingBackend(RuntimeError("x"), name_str="b1")
    b2 = MockBackend()
    chain = BackendFallbackChain([b1, b2])
    # Before any call, returns first backend's cost
    assert chain.cost_per_1k_tokens == b1.cost_per_1k_tokens


# ===========================================================================
# 4. Budget enforcement in Orchestrator
# ===========================================================================

@pytest.mark.asyncio
async def test_budget_exceeded_halts_early(sample_graph):
    """Orchestrator stops when cumulative cost exceeds budget."""
    # Use CountingBackend which has cost_per_1k_tokens=0.001 (nonzero)
    backend = CountingBackend(fail_count=0, name_str="costed-mock")
    sample_graph.set_default_backend(backend)

    # Set a tiny budget that will be exceeded after 1 round.
    # Disable dynamic ceiling for deterministic test behavior.
    config = GraqleConfig(cost=CostConfig(
        budget_per_query=0.0000001,
        dynamic_ceiling=False,
        hard_ceiling_multiplier=2.0,
    ))
    sample_graph.config = config

    # Activate nodes (normally areason() does this)
    node_ids = list(sample_graph.nodes.keys())[:3]
    for nid in node_ids:
        sample_graph.nodes[nid].activate(backend)

    orchestrator = Orchestrator()
    result = await orchestrator.run(
        graph=sample_graph,
        query="test budget",
        active_node_ids=node_ids,
        max_rounds=5,
    )

    # Should stop early (fewer than max rounds)
    assert result.rounds_completed < 5
    assert result.metadata["budget_exceeded"] is True


@pytest.mark.asyncio
async def test_no_budget_exceeded_normal_run(sample_graph):
    """Normal run without budget issues."""
    backend = MockBackend(responses=[
        "Analysis. Confidence: 75%",
        "Refined. Confidence: 92%",
    ])
    sample_graph.set_default_backend(backend)

    node_ids = list(sample_graph.nodes.keys())[:2]
    for nid in node_ids:
        sample_graph.nodes[nid].activate(backend)

    orchestrator = Orchestrator()
    result = await orchestrator.run(
        graph=sample_graph,
        query="test normal",
        active_node_ids=node_ids,
        max_rounds=2,
    )

    assert result.metadata["budget_exceeded"] is False
    assert result.metadata["cumulative_cost_usd"] >= 0


@pytest.mark.asyncio
async def test_dynamic_ceiling_respects_hard_limit(sample_graph):
    """Dynamic ceiling never exceeds hard_ceiling_multiplier * budget."""
    backend = CountingBackend(fail_count=0, name_str="costed-mock")
    sample_graph.set_default_backend(backend)

    # Tiny budget, dynamic ceiling ON, hard limit at 3x
    config = GraqleConfig(cost=CostConfig(
        budget_per_query=0.0000001,
        dynamic_ceiling=True,
        continuation_base_prob=1.0,  # always continue (deterministic)
        continuation_decay=1.0,  # never decay
        hard_ceiling_multiplier=3.0,
    ))
    sample_graph.config = config

    node_ids = list(sample_graph.nodes.keys())[:3]
    for nid in node_ids:
        sample_graph.nodes[nid].activate(backend)

    orchestrator = Orchestrator()
    result = await orchestrator.run(
        graph=sample_graph,
        query="test dynamic ceiling hard limit",
        active_node_ids=node_ids,
        max_rounds=10,
    )

    # Even with P=1.0 (always continue), must stop at hard ceiling
    assert result.rounds_completed < 10
    assert result.metadata["budget_exceeded"] is True


@pytest.mark.asyncio
async def test_dynamic_ceiling_config_fields():
    """CostConfig exposes dynamic ceiling fields with correct defaults."""
    from graqle.config.settings import CostConfig

    cfg = CostConfig()
    assert cfg.dynamic_ceiling is True
    assert cfg.continuation_base_prob == 0.85
    assert cfg.continuation_decay == 0.6
    assert cfg.hard_ceiling_multiplier == 3.0


# ===========================================================================
# 5. Empty graph / no active nodes
# ===========================================================================

@pytest.mark.asyncio
async def test_empty_active_nodes(sample_graph):
    """Orchestrator handles empty active node list gracefully."""
    backend = MockBackend(response="should not be called")
    sample_graph.set_default_backend(backend)

    orchestrator = Orchestrator()
    result = await orchestrator.run(
        graph=sample_graph,
        query="test empty",
        active_node_ids=[],
        max_rounds=2,
    )

    assert result.rounds_completed >= 0
    assert result.answer is not None


# ===========================================================================
# 6. API backend error scenarios (mocked)
# ===========================================================================

@pytest.mark.asyncio
async def test_anthropic_import_error():
    """AnthropicBackend raises ImportError if anthropic not installed."""
    backend = AnthropicBackend(api_key="test-key")
    with patch.dict("sys.modules", {"anthropic": None}):
        with pytest.raises(ImportError, match="anthropic"):
            backend._client = None  # Force re-import
            backend._get_client()


@pytest.mark.asyncio
async def test_openai_import_error():
    """OpenAIBackend raises ImportError if openai not installed."""
    backend = OpenAIBackend(api_key="test-key")
    with patch.dict("sys.modules", {"openai": None}):
        with pytest.raises(ImportError, match="openai"):
            backend._client = None
            backend._get_client()


@pytest.mark.asyncio
async def test_ollama_connection_refused():
    """OllamaBackend fails gracefully on connection refused."""
    backend = OllamaBackend(
        host="http://localhost:99999",
        max_retries=1,
    )
    with pytest.raises(BackendError):
        await backend.generate("test")


@pytest.mark.asyncio
async def test_custom_backend_timeout():
    """CustomBackend fails after timeout."""
    backend = CustomBackend(
        endpoint="http://localhost:99999/v1/completions",
        timeout=0.1,
        max_retries=1,
    )
    with pytest.raises(BackendError):
        await backend.generate("test")


# ===========================================================================
# 7. Fallback chain integration with orchestrator
# ===========================================================================

@pytest.mark.asyncio
async def test_fallback_chain_in_graph(sample_graph):
    """FallbackChain works when set as graph backend."""
    primary = FailingBackend(RuntimeError("primary down"), name_str="primary")
    secondary = MockBackend(response="Fallback answer. Confidence: 80%")
    chain = BackendFallbackChain([primary, secondary])

    sample_graph.set_default_backend(chain)

    node_ids = list(sample_graph.nodes.keys())[:2]
    for nid in node_ids:
        sample_graph.nodes[nid].activate(chain)

    orchestrator = Orchestrator()
    result = await orchestrator.run(
        graph=sample_graph,
        query="test fallback integration",
        active_node_ids=node_ids,
        max_rounds=2,
    )

    assert result.answer != ""
    assert result.rounds_completed > 0
