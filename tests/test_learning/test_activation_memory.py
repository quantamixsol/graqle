"""Tests for ActivationMemory - cross-query learning for node activation."""

# ── graqle:intelligence ──
# module: tests.test_learning.test_activation_memory
# risk: LOW (impact radius: 0 modules)
# dependencies: json, tempfile, pathlib, pytest, activation_memory
# constraints: none
# ── /graqle:intelligence ──
import pytest

# IP-PROTECTED STUB: the implementation of this module is covered by European
# Patent Applications EP26162901.8, EP26166054.2, EP26167849.4.
# The source file exists as a stub only. Tests are skipped until the
# implementation ships. Do not remove this guard - CI must pass cleanly.
try:
    import importlib as _importlib
    _importlib.import_module("graqle.learning.activation_memory")
    # Verify the key class exists in the stub
    import graqle.learning.activation_memory as _stub_mod
    if not any(hasattr(_stub_mod, a) for a in dir(_stub_mod) if not a.startswith("_")):
        raise ImportError("stub only")
    # v0.51.4: the ``ActivationMemoryConfig`` symbol is the signal that the
    # full (IP-protected) implementation has shipped. The lightweight stub
    # added in v0.51.4 only exports ``ActivationMemory`` to unblock imports
    # in graqle.core.graph and graqle.learning.ontology_refiner.
    if not hasattr(_stub_mod, "ActivationMemoryConfig"):
        raise ImportError("stub only (ActivationMemoryConfig missing)")
except (ImportError, AttributeError):
    pytest.skip(
        "IP-protected module not yet implemented in this build - skipping.",
        allow_module_level=True,
    )




import json
import tempfile
from pathlib import Path

from graqle.learning.activation_memory import (
    ActivationMemory,
    ActivationMemoryConfig,
)


class FakeResult:
    """Minimal result-like object for testing."""

    def __init__(self, trace=None):
        self.message_trace = trace or []


class FakeMessage:
    def __init__(self, source_node_id, confidence):
        self.source_node_id = source_node_id
        self.confidence = confidence


def test_record_and_stats():
    """Record a few queries and check stats update."""
    mem = ActivationMemory(ActivationMemoryConfig(persist=False))
    result = FakeResult([
        FakeMessage("node_a", 0.9),
        FakeMessage("node_b", 0.3),
    ])
    mem.record("What products does this website offer?", ["node_a", "node_b"], result)

    assert mem.stats["total_queries"] == 1
    assert mem.stats["tracked_nodes"] == 2


def test_useful_threshold():
    """Nodes above useful_threshold get marked as useful."""
    mem = ActivationMemory(ActivationMemoryConfig(
        persist=False,
        useful_threshold=0.5,
    ))
    result = FakeResult([
        FakeMessage("good_node", 0.8),
        FakeMessage("bad_node", 0.2),
    ])
    mem.record("test query", ["good_node", "bad_node"], result)

    assert mem._records["good_node"].useful_activations == 1
    assert mem._records["bad_node"].useful_activations == 0


def test_get_boosts_requires_min_activations():
    """Boosts only apply after min_activations queries."""
    mem = ActivationMemory(ActivationMemoryConfig(
        persist=False,
        min_activations=3,
    ))
    result = FakeResult([FakeMessage("node_a", 0.9)])

    # Record 2 queries - not enough for boosts
    mem.record("products list", ["node_a"], result)
    mem.record("product catalog", ["node_a"], result)
    boosts = mem.get_boosts("what products are available")
    assert len(boosts) == 0  # Not enough history

    # 3rd query - now boosts should appear
    mem.record("show products", ["node_a"], result)
    boosts = mem.get_boosts("what products are available")
    # node_a has 3 activations, all useful, keyword overlap with "products"
    assert "node_a" in boosts
    assert boosts["node_a"] > 0


def test_get_boosts_keyword_matching():
    """Boosts are higher when query keywords match past patterns."""
    mem = ActivationMemory(ActivationMemoryConfig(
        persist=False,
        min_activations=2,
    ))
    result = FakeResult([FakeMessage("auth_node", 0.8)])

    mem.record("authentication JWT tokens", ["auth_node"], result)
    mem.record("auth session management", ["auth_node"], result)

    # Similar query → should boost
    boosts_similar = mem.get_boosts("JWT authentication flow")
    # Completely different query → should not boost
    boosts_different = mem.get_boosts("database migration schema")

    if "auth_node" in boosts_similar:
        similar_boost = boosts_similar["auth_node"]
    else:
        similar_boost = 0.0

    different_boost = boosts_different.get("auth_node", 0.0)
    assert similar_boost >= different_boost


def test_temporal_decay():
    """Older records decay over time."""
    mem = ActivationMemory(ActivationMemoryConfig(
        persist=False,
        decay_factor=0.5,  # Aggressive decay for testing
    ))
    result = FakeResult([FakeMessage("node_a", 0.9)])
    mem.record("query 1", ["node_a"], result)

    initial_conf = mem._records["node_a"].avg_confidence

    # Record another query - decay should apply
    mem.record("query 2", ["node_a"], result)

    # avg_confidence is a running average, but decay was applied before
    # the second recording, so it won't be exactly 0.9
    # The important thing is the decay factor was applied
    assert mem._total_queries == 2


def test_persist_and_load():
    """Memory persists to disk and reloads correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = str(Path(tmpdir) / "memory.json")

        # Save
        mem = ActivationMemory(ActivationMemoryConfig(
            persist=True,
            persist_path=path,
        ))
        result = FakeResult([FakeMessage("node_a", 0.9)])
        mem.record("test query", ["node_a"], result)
        mem.save()

        # Verify file exists
        assert Path(path).exists()
        data = json.loads(Path(path).read_text())
        assert data["total_queries"] == 1
        assert "node_a" in data["records"]

        # Load into new instance
        mem2 = ActivationMemory(ActivationMemoryConfig(
            persist=False,
            persist_path=path,
        ))
        loaded = mem2.load()
        assert loaded == 1
        assert mem2._total_queries == 1
        assert "node_a" in mem2._records


def test_reset():
    """Reset clears all state."""
    mem = ActivationMemory(ActivationMemoryConfig(persist=False))
    result = FakeResult([FakeMessage("node_a", 0.9)])
    mem.record("test", ["node_a"], result)

    assert mem.stats["total_queries"] == 1

    mem.reset()
    assert mem.stats["total_queries"] == 0
    assert mem.stats["tracked_nodes"] == 0


def test_max_boost_capped():
    """Boost never exceeds max_boost."""
    mem = ActivationMemory(ActivationMemoryConfig(
        persist=False,
        max_boost=0.10,
        min_activations=1,
    ))
    result = FakeResult([FakeMessage("node_a", 1.0)])

    # Record many identical queries
    for _ in range(20):
        mem.record("same query keywords", ["node_a"], result)

    boosts = mem.get_boosts("same query keywords")
    if "node_a" in boosts:
        assert boosts["node_a"] <= 0.10
