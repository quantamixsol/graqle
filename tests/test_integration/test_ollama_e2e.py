"""End-to-end tests with real Ollama GPU inference (RTX 5060).

These tests require a running Ollama instance with qwen2.5:0.5b pulled.
They are marked with `pytest.mark.gpu` and skipped if Ollama is unavailable.
"""

# ── graqle:intelligence ──
# module: tests.test_integration.test_ollama_e2e
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, asyncio, pytest, httpx, networkx +3 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import httpx
import networkx as nx
import pytest

from graqle.backends.api import OllamaBackend
from graqle.config.settings import GraqleConfig
from graqle.core.graph import Graqle


def _ollama_available() -> bool:
    """Check if Ollama is running and has qwen2.5:0.5b.

    Uses a short timeout (0.5s) to fail fast when Ollama is not running.
    Result is cached at module level — called once per pytest session, not
    once per test (which was burning 5s × N tests on connection timeouts).
    """
    try:
        resp = httpx.get("http://localhost:11434/api/tags", timeout=0.5)
        if resp.status_code != 200:
            return False
        models = [m["name"] for m in resp.json().get("models", [])]
        return any("qwen2.5" in m for m in models)
    except Exception:
        return False


# Evaluated ONCE at import time (module load), not per-test.
# Short timeout (0.5s) means fast failure when Ollama is not running.
_OLLAMA_AVAILABLE: bool = _ollama_available()

skip_no_ollama = pytest.mark.skipif(
    not _OLLAMA_AVAILABLE,
    reason="Ollama not running or qwen2.5:0.5b not available",
)


@skip_no_ollama
class TestOllamaBackendDirect:
    """Test OllamaBackend directly against real Ollama."""

    @pytest.fixture
    def backend(self):
        return OllamaBackend(model="qwen2.5:0.5b")

    @pytest.mark.asyncio
    async def test_simple_generation(self, backend):
        result = await backend.generate("What is 2+2? Reply with just the number.")
        assert "4" in result

    @pytest.mark.asyncio
    async def test_generation_with_params(self, backend):
        result = await backend.generate(
            "Name one color of the rainbow. One word only.",
            max_tokens=32,
            temperature=0.1,
        )
        assert len(result) > 0
        assert len(result) < 200  # should be short

    @pytest.mark.asyncio
    async def test_backend_name(self, backend):
        assert backend.name == "ollama:qwen2.5:0.5b"

    @pytest.mark.asyncio
    async def test_cost_per_1k_tokens(self, backend):
        assert backend.cost_per_1k_tokens == 0.0001


@skip_no_ollama
class TestGraqleWithOllama:
    """End-to-end: GraQle reasoning with real Ollama GPU backend."""

    @pytest.fixture
    def small_graph(self):
        """Create a small knowledge graph about EU AI Act."""
        G = nx.Graph()
        G.add_node("ai_act", label="EU AI Act", type="Regulation",
                    description="EU regulation on artificial intelligence systems")
        G.add_node("high_risk", label="High-Risk AI", type="Category",
                    description="AI systems classified as high-risk under EU AI Act")
        G.add_node("transparency", label="Transparency", type="Requirement",
                    description="Transparency obligations for AI system providers")
        G.add_edge("ai_act", "high_risk", relationship="DEFINES")
        G.add_edge("ai_act", "transparency", relationship="REQUIRES")
        G.add_edge("high_risk", "transparency", relationship="SUBJECT_TO")

        config = GraqleConfig.default()
        config.orchestration.max_rounds = 2
        return Graqle.from_networkx(G, config=config)

    def test_reason_with_ollama(self, small_graph):
        """Full pipeline: graph.reason() with real GPU inference."""
        backend = OllamaBackend(model="qwen2.5:0.5b")
        small_graph.set_default_backend(backend)

        result = small_graph.reason(
            "What does the EU AI Act require for high-risk AI systems?",
            node_ids=["ai_act", "high_risk", "transparency"],
        )

        assert result.answer is not None
        assert len(result.answer) > 10
        assert result.metadata["convergence_round"] >= 1
        assert result.metadata["total_tokens"] > 0
        assert result.metadata["cumulative_cost_usd"] >= 0

    @pytest.mark.asyncio
    async def test_areason_with_ollama(self, small_graph):
        """Async reasoning with real GPU inference."""
        backend = OllamaBackend(model="qwen2.5:0.5b")
        small_graph.set_default_backend(backend)

        result = await small_graph.areason(
            "Explain transparency requirements.",
            node_ids=["ai_act", "transparency"],
        )

        assert result.answer is not None
        assert len(result.answer) > 5

    @pytest.mark.asyncio
    async def test_multi_node_reasoning(self, small_graph):
        """Test with all 3 nodes activated — full message passing."""
        backend = OllamaBackend(model="qwen2.5:0.5b")
        small_graph.set_default_backend(backend)

        result = await small_graph.areason(
            "What are the key requirements for high-risk AI?",
            node_ids=["ai_act", "high_risk", "transparency"],
        )

        assert result.answer is not None
        assert result.metadata["convergence_round"] >= 1
        # Should have messages from multiple nodes
        assert result.metadata["total_messages"] > 0
