# ──────────────────────────────────────────────────────────────────
# PATENT NOTICE — Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Applications EP26162901.8 and EP26166054.2, owned by
# Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: legal@quantamix.io
# ──────────────────────────────────────────────────────────────────

"""ActivatorRegistry — (backend, ranking) -> activator factory dispatch.

v0.62.3 structural fix (SPEC-v0623-activation-schema.md). Replaces the
if/elif pile inside Graqle._activate_subgraph with an explicit registry
keyed on (backend, ranking) pairs.

The registry is populated eagerly at import time via register_defaults() in
graqle/activation/__init__.py. Runtime registration of additional pairs is
guarded behind GRAQLE_ALLOW_RUNTIME_REGISTER for plugin extensibility.

Thread-safety:
- ``register()`` takes ``_lock`` with a 1s timeout (DoS-bounded).
- ``resolve()`` is lockless: dict read is atomic under the CPython GIL.
- ``register_defaults()`` runs once at module import before any ``resolve()``
  call from another thread can race (Python import lock guarantees this).

Security:
- ``register()`` validates that the factory is callable and that backend/
  ranking strings are ASCII alphanumeric + underscore (injection guard).
- ``MAX_ENTRIES=100`` caps the registry against DoS via unbounded registration.

V-MARKER: V-CR-WRITE-NATIVE-001 — created via native Write because graq_write
S-010 path-resolution bug hits Neo4j-backed sessions where _graph_file is a
URI (not a filesystem path). Logged to capability-gap tracker.
"""

# ── graqle:intelligence ──
# module: graqle.activation.registry
# risk: MEDIUM (new module, single source of truth for activator dispatch)
# consumers: graqle.activation.__init__ (calls register_defaults at import)
# dependencies: __future__, logging, os, re, threading, typing
# constraints: thread-safe register/resolve; runtime register gated by env var
# ── /graqle:activation ──

from __future__ import annotations

import logging
import os
import re
import threading
from typing import Any, Callable, Iterable

logger = logging.getLogger("graqle.activation.registry")

# Identifier validation: ASCII alphanumeric + underscore only. Defends against
# injection attempts where a config-parsed value might contain shell or yaml
# metacharacters. backend/ranking are control-plane identifiers, never data.
_VALID_IDENT = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")


class UnregisteredActivatorError(KeyError):
    """Raised when (backend, ranking) has no registered activator factory.

    Carries the full list of registered pairs in the message so the user sees
    both what they asked for and what was available. Never silent fallback.
    """


class ActivatorRegistry:
    """(backend, ranking) -> activator factory. Single source of truth.

    Built-in pairs registered eagerly by graqle.activation.register_defaults():
        (local,   semantic) -> ChunkScorer
        (local,   degree)   -> DegreeRanker
        (local,   none)     -> FullActivator
        (neo4j,   semantic) -> CypherActivation
        (neo4j,   degree)   -> DegreeRanker + WARNING (ignores vector index)
        (neo4j,   none)     -> Neo4jFullActivator
        (neptune, semantic) -> NeptuneActivator (stub if NeptuneConnector unavailable)
        (neptune, degree)   -> DegreeRanker + WARNING
        (neptune, none)     -> NeptuneFullActivator (stub)

    Third-party plugin extensibility:
        Set environment variable ``GRAQLE_ALLOW_RUNTIME_REGISTER=1`` then call
        ``ActivatorRegistry.register(backend, ranking, factory)`` from plugin
        code at import time.
    """

    MAX_ENTRIES: int = 100
    _registry: dict[tuple[str, str], Callable[[Any], Any]] = {}
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def _runtime_register_allowed(cls) -> bool:
        """Re-read env var on every call so tests can toggle it without restart."""
        return os.environ.get("GRAQLE_ALLOW_RUNTIME_REGISTER", "0") == "1"

    @classmethod
    def register(
        cls,
        backend: str,
        ranking: str,
        factory: Callable[[Any], Any],
        *,
        _builtin: bool = False,
        timeout: float = 1.0,
    ) -> None:
        """Register a ``(backend, ranking) -> factory`` pair.

        Args:
            backend: Backend identifier (local | neo4j | neptune | ...).
                Must be ASCII alphanumeric + underscore.
            ranking: Ranking identifier (semantic | degree | none | ...).
                Must be ASCII alphanumeric + underscore.
            factory: Callable ``(graph) -> Activator`` that returns an
                activator instance bound to the given Graqle instance.
            _builtin: Internal flag set by ``register_defaults()``. External
                callers MUST leave this False; they need
                ``GRAQLE_ALLOW_RUNTIME_REGISTER=1``.
            timeout: Max seconds to wait for the lock. Prevents indefinite
                DoS via lock contention. Default 1s.

        Raises:
            PermissionError: External caller without env var.
            TypeError: factory is not callable.
            ValueError: backend or ranking is not a valid identifier, or is empty.
            TimeoutError: Lock contention exceeded ``timeout``.
            RuntimeError: Registry full (>= MAX_ENTRIES).
        """
        if not _builtin and not cls._runtime_register_allowed():
            raise PermissionError(
                "ActivatorRegistry.register: runtime registration is disabled. "
                "Set GRAQLE_ALLOW_RUNTIME_REGISTER=1 to enable plugin extensibility. "
                "Built-in (backend, ranking) pairs register automatically at "
                "graqle.activation import time."
            )

        if not callable(factory):
            raise TypeError(
                f"ActivatorRegistry.register: factory must be callable, "
                f"got {type(factory).__name__}"
            )

        for name, val in [("backend", backend), ("ranking", ranking)]:
            if not isinstance(val, str) or not val:
                raise ValueError(
                    f"ActivatorRegistry.register: {name} must be a non-empty "
                    f"string, got {val!r}"
                )
            if not _VALID_IDENT.match(val):
                raise ValueError(
                    f"ActivatorRegistry.register: {name}={val!r} is not a valid "
                    f"identifier. Must match [a-zA-Z][a-zA-Z0-9_]* (ASCII only). "
                    f"This is an injection guard against config-parsed values."
                )

        acquired = cls._lock.acquire(timeout=timeout)
        if not acquired:
            raise TimeoutError(
                f"ActivatorRegistry.register: lock contention exceeded {timeout}s. "
                f"This indicates DoS or deadlock — investigate concurrent register() "
                f"callers."
            )
        try:
            if len(cls._registry) >= cls.MAX_ENTRIES:
                raise RuntimeError(
                    f"ActivatorRegistry: registry full ({cls.MAX_ENTRIES} entries). "
                    f"This is a DoS guard. If you legitimately need more entries, "
                    f"file an issue."
                )
            cls._registry[(backend, ranking)] = factory
            logger.debug(
                "ActivatorRegistry: registered (%s, %s) -> %s",
                backend, ranking, getattr(factory, "__qualname__", repr(factory)),
            )
        finally:
            cls._lock.release()

    @classmethod
    def resolve(cls, backend: str, ranking: str) -> Callable[[Any], Any]:
        """Look up the factory for ``(backend, ranking)``.

        Lockless read: ``dict.__getitem__`` is atomic under the CPython GIL,
        so the read path stays fast even under heavy concurrent registration.

        Raises:
            UnregisteredActivatorError: No factory registered for the pair.
                The error message contains the full list of registered pairs.
        """
        key = (backend, ranking)
        if key not in cls._registry:
            registered = sorted(cls._registry.keys())
            raise UnregisteredActivatorError(
                f"No activator registered for (backend={backend!r}, "
                f"ranking={ranking!r}). Registered pairs: {registered}. "
                f"If you intended a new combination, register it with "
                f"ActivatorRegistry.register(backend, ranking, factory_callable) "
                f"(requires GRAQLE_ALLOW_RUNTIME_REGISTER=1)."
            )
        return cls._registry[key]

    @classmethod
    def registered_pairs(cls) -> Iterable[tuple[str, str]]:
        """Return all currently-registered ``(backend, ranking)`` pairs.

        Snapshot — safe to iterate even if another thread is registering.
        """
        return tuple(cls._registry.keys())

    @classmethod
    def _reset_for_tests(cls) -> None:
        """TESTS ONLY: clear the registry. NEVER call from production code."""
        with cls._lock:
            cls._registry.clear()
