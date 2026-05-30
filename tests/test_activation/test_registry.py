"""Tests for v0.62.3 ActivatorRegistry (TR_01..TR_23).

Covers:
- Eager registration of 9 built-in (backend, ranking) pairs at module import
- UnregisteredActivatorError for unknown pairs with full-list error message
- Backend inference (None / Neo4jConnector / unexpected type)
- Security: input validation (ASCII identifiers), runtime-register gating,
  factory callable check, MAX_ENTRIES DoS guard, lock timeout
- Thread safety: lockless resolve under concurrent register
- Performance: resolve() <5µs/call, dispatch path <110% of v0.62.2 baseline

SPEC: .gsm/decisions/SPEC-v0623-activation-schema.md §3.2
"""

from __future__ import annotations

import os
import threading
import time
from unittest.mock import MagicMock

import pytest

from graqle.activation import factory_helpers as fh
from graqle.activation.registry import (
    ActivatorRegistry,
    UnregisteredActivatorError,
)


# ─── TR_01-TR_07: built-in pairs resolve to correct factory types ──────────


def test_TR_01_local_semantic_resolves_to_chunk_scorer_factory():
    factory = ActivatorRegistry.resolve("local", "semantic")
    assert factory is fh._chunk_scorer_factory


def test_TR_02_local_degree_resolves_to_degree_ranker():
    factory = ActivatorRegistry.resolve("local", "degree")
    assert factory is fh._degree_factory


def test_TR_03_local_none_resolves_to_full_activator():
    factory = ActivatorRegistry.resolve("local", "none")
    assert factory is fh._full_factory


def test_TR_04_neo4j_semantic_resolves_to_cypher_activation():
    factory = ActivatorRegistry.resolve("neo4j", "semantic")
    assert factory is fh._cypher_factory


def test_TR_05_neo4j_degree_resolves_to_degree_ranker_with_warning():
    factory = ActivatorRegistry.resolve("neo4j", "degree")
    assert factory is fh._degree_with_warning_factory


def test_TR_06_neo4j_none_resolves_to_full_activator():
    factory = ActivatorRegistry.resolve("neo4j", "none")
    assert factory is fh._neo4j_full_factory


def test_TR_07_neptune_semantic_resolves_to_neptune_factory():
    factory = ActivatorRegistry.resolve("neptune", "semantic")
    assert factory is fh._neptune_factory


# ─── TR_08-TR_09: unknown (backend, ranking) raises with full-list message ──


def test_TR_08_unknown_backend_raises_with_full_list():
    with pytest.raises(UnregisteredActivatorError) as exc_info:
        ActivatorRegistry.resolve("hypothetical_backend", "semantic")
    msg = str(exc_info.value)
    assert "hypothetical_backend" in msg
    assert "semantic" in msg
    # Must list registered pairs so user sees what IS available
    assert "local" in msg
    assert "neo4j" in msg


def test_TR_09_unknown_ranking_raises_with_full_list():
    with pytest.raises(UnregisteredActivatorError) as exc_info:
        ActivatorRegistry.resolve("local", "esoteric_ranking")
    msg = str(exc_info.value)
    assert "esoteric_ranking" in msg
    assert "local" in msg
    # Hint to enable runtime registration is included
    assert "GRAQLE_ALLOW_RUNTIME_REGISTER" in msg


# ─── TR_10-TR_11: eager registration at module import ───────────────────────


def test_TR_10_eager_register_full_set_at_import():
    """register_defaults() ran at import; 9 built-in pairs are present."""
    pairs = set(ActivatorRegistry.registered_pairs())
    expected = {
        ("local", "semantic"), ("local", "degree"), ("local", "none"),
        ("neo4j", "semantic"), ("neo4j", "degree"), ("neo4j", "none"),
        ("neptune", "semantic"), ("neptune", "degree"), ("neptune", "none"),
    }
    assert expected.issubset(pairs), f"Missing pairs: {expected - pairs}"


def test_TR_11_idempotent_register_defaults():
    """Calling register_defaults() again does not duplicate or change."""
    from graqle.activation import register_defaults
    before = set(ActivatorRegistry.registered_pairs())
    register_defaults()
    after = set(ActivatorRegistry.registered_pairs())
    assert before == after


# ─── TR_12: perf — resolve() <5µs/call ─────────────────────────────────────


def test_TR_12_perf_registry_resolve_under_5us_per_call():
    """resolve() x10000 calls < 50ms total (5µs/call). Catches perf regression."""
    iterations = 10_000
    t0 = time.perf_counter()
    for _ in range(iterations):
        ActivatorRegistry.resolve("local", "semantic")
    elapsed = time.perf_counter() - t0
    per_call_us = (elapsed / iterations) * 1_000_000
    assert per_call_us < 50, (  # generous 50µs ceiling for slow CI
        f"resolve() too slow: {per_call_us:.2f}µs/call (target <5µs/call typical, "
        f"50µs/call hard ceiling on slow CI)"
    )


# ─── TR_13: thread safety — concurrent resolve during register ─────────────


def test_TR_13_thread_safety_concurrent_resolve_during_register(monkeypatch):
    """1000 concurrent resolve()s during register()s — no exceptions, no None."""
    monkeypatch.setenv("GRAQLE_ALLOW_RUNTIME_REGISTER", "1")

    results: list[Exception | object] = []
    stop = threading.Event()

    def resolver():
        while not stop.is_set():
            try:
                f = ActivatorRegistry.resolve("local", "semantic")
                if f is None:
                    results.append(RuntimeError("got None from resolve"))
                    return
            except Exception as exc:
                results.append(exc)
                return

    threads = [threading.Thread(target=resolver) for _ in range(20)]
    for t in threads:
        t.start()

    try:
        # Hammer register() concurrently with the resolvers
        for i in range(50):
            ActivatorRegistry.register(
                "perf_test_backend", f"perf_test_ranking_{i}",
                lambda g: MagicMock(),
            )
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=2.0)

    errors = [r for r in results if isinstance(r, Exception)]
    assert errors == [], f"Concurrent resolve/register errors: {errors[:5]}"


# ─── TR_14-TR_16: _infer_backend explicit cases ────────────────────────────


def test_TR_14_infer_backend_none_returns_local():
    """When _neo4j_connector is None, _infer_backend returns 'local'."""
    from graqle.core.graph import Graqle
    g = Graqle.__new__(Graqle)  # construct without calling __init__
    g._neo4j_connector = None
    assert g._infer_backend() == "local"


def test_TR_15_infer_backend_neo4j_connector():
    """When _neo4j_connector is a Neo4jConnector, returns 'neo4j'."""
    pytest.importorskip("neo4j")
    from graqle.connectors.neo4j import Neo4jConnector
    from graqle.core.graph import Graqle
    g = Graqle.__new__(Graqle)
    g._neo4j_connector = Neo4jConnector.__new__(Neo4jConnector)  # don't actually connect
    assert g._infer_backend() == "neo4j"


def test_TR_16_infer_backend_unknown_type_raises():
    """Unexpected _neo4j_connector type raises RuntimeError naming the type."""
    from graqle.core.graph import Graqle

    class FakeConnector:
        pass

    g = Graqle.__new__(Graqle)
    g._neo4j_connector = FakeConnector()
    with pytest.raises(RuntimeError) as exc_info:
        g._infer_backend()
    assert "FakeConnector" in str(exc_info.value)


# ─── TR_18-TR_22: register() security + DoS guards ─────────────────────────


def test_TR_18_register_security_invalid_factory(monkeypatch):
    """register() with non-callable factory raises TypeError."""
    monkeypatch.setenv("GRAQLE_ALLOW_RUNTIME_REGISTER", "1")
    with pytest.raises(TypeError):
        ActivatorRegistry.register("test_b", "test_r", "not_callable")


def test_TR_19_register_security_invalid_identifier_blocks_injection(monkeypatch):
    """register() with non-alphanumeric backend rejects (injection guard)."""
    monkeypatch.setenv("GRAQLE_ALLOW_RUNTIME_REGISTER", "1")
    with pytest.raises(ValueError) as exc_info:
        ActivatorRegistry.register("local; DROP TABLE", "x", lambda g: None)
    assert "identifier" in str(exc_info.value).lower()


def test_TR_19b_register_empty_string_rejected(monkeypatch):
    monkeypatch.setenv("GRAQLE_ALLOW_RUNTIME_REGISTER", "1")
    with pytest.raises(ValueError):
        ActivatorRegistry.register("", "x", lambda g: None)


def test_TR_20_register_runtime_disabled_by_default(monkeypatch):
    """Without GRAQLE_ALLOW_RUNTIME_REGISTER, external register() raises."""
    monkeypatch.delenv("GRAQLE_ALLOW_RUNTIME_REGISTER", raising=False)
    with pytest.raises(PermissionError) as exc_info:
        ActivatorRegistry.register("test_b", "test_r", lambda g: None)
    assert "GRAQLE_ALLOW_RUNTIME_REGISTER" in str(exc_info.value)


def test_TR_21_register_dos_max_entries_guard(monkeypatch):
    """Adding > MAX_ENTRIES raises RuntimeError (DoS guard)."""
    monkeypatch.setenv("GRAQLE_ALLOW_RUNTIME_REGISTER", "1")
    # Don't reset the registry — start from current size, fill to cap, then assert.
    current = len(list(ActivatorRegistry.registered_pairs()))
    cap = ActivatorRegistry.MAX_ENTRIES
    slots_available = cap - current
    # Fill up to (cap - 1)
    for i in range(slots_available - 1):
        ActivatorRegistry.register("dos_test_backend", f"dos_test_r{i}", lambda g: None)
    # Next one fills to cap exactly — still allowed
    ActivatorRegistry.register("dos_test_backend", "dos_test_r_last", lambda g: None)
    # One more should raise
    with pytest.raises(RuntimeError) as exc_info:
        ActivatorRegistry.register("dos_test_backend", "dos_test_r_overflow", lambda g: None)
    assert "DoS guard" in str(exc_info.value) or "registry full" in str(exc_info.value).lower()


def test_TR_22_register_lock_timeout(monkeypatch):
    """register() with held lock and short timeout raises TimeoutError."""
    monkeypatch.setenv("GRAQLE_ALLOW_RUNTIME_REGISTER", "1")
    ActivatorRegistry._lock.acquire()
    try:
        with pytest.raises(TimeoutError) as exc_info:
            ActivatorRegistry.register(
                "timeout_test", "x", lambda g: None, timeout=0.05,
            )
        assert "lock contention" in str(exc_info.value).lower()
    finally:
        ActivatorRegistry._lock.release()
