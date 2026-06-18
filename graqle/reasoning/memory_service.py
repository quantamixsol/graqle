"""Sole factory for ReasoningMemory in multi-tenant mode (ADR-225 G1 T7).

This module is a **process-level singleton registry**. Module-level mutable
state (_registry, _registry_locks, _registry_global_lock) is intentional —
the registry caches one ReasoningMemory instance per tenant across the process
lifetime.  Test isolation requires clear_registry() between test cases (see
the autouse fixture pattern in tests/test_reasoning/test_tenant_isolation.py).

Public API
----------
provision(tenant_id, config)
    Idempotent, thread-safe factory.  Returns the cached instance for the given
    tenant, or constructs and caches a new one.  This is the ONLY recommended
    constructor path for multi-tenant deployments.

clear_registry()
    Test-only.  Clears the registry and all per-tenant locks.  Guarded by the
    GRAQLE_TEST_MODE=1 env flag; raises RuntimeError in production.

Error-handling contract
-----------------------
TenantIdError (from validate_tenant_id)
    The caller MUST catch this and return a 4xx-equivalent error.  Never
    swallow silently — it indicates a malformed or malicious tenant identifier.

TenantScopingDisabledError (from ReasoningMemory.__init__)
    Indicates a fatal misconfiguration: a non-DEFAULT tenant_id was requested
    but GRAQLE_TENANT_SCOPING=1 is not set.  Callers MUST re-raise or convert
    this to a startup-time assertion failure; never swallow silently.

On-prem invariant
-----------------
provision(DEFAULT_TENANT, config) is behaviourally identical to direct
construction ReasoningMemory(config) — the instance returned has entry_count
== 0 and all methods behave identically (GRAQLE_TENANT_SCOPING is irrelevant
for DEFAULT_TENANT).

Locking protocol
----------------
* _registry_global_lock  — protects creation of per-tenant Lock objects only
* _registry_locks[tid]   — per-tenant mutex; held during the inner registry
                            check and construction to ensure exactly-once
                            semantics per tenant
* Double-checked locking: the re-check INSIDE the per-tenant lock
  is MANDATORY and must never be removed.  No outer unsynchronized
  fast-path: removed to prevent tenant data-leak under PEP 703.
* Failed construction (any exception) leaves no entry in _registry; the
  per-tenant lock remains in _registry_locks and is safely reusable on retry.
* clear_registry() acquires _registry_global_lock before clearing both dicts to
  prevent data races with concurrent provision() calls.

Future note
-----------
TenantScopingDisabledError is currently imported from graqle.reasoning.memory.
It logically belongs in graqle.core.tenant or graqle.core.errors — move it
there when the core error hierarchy is extended.
"""
from __future__ import annotations

import os
import threading
from typing import Any

from graqle.core.tenant import DEFAULT_TENANT, TenantIdError, validate_tenant_id  # noqa: F401 — re-exported for callers
from graqle.reasoning.memory import ReasoningMemory, TenantScopingDisabledError  # noqa: F401 — re-exported for callers

__all__ = [
    "provision",
    "clear_registry",
    "DEFAULT_TENANT",
    "TenantIdError",
    "TenantScopingDisabledError",
]

# ---------------------------------------------------------------------------
# Module-level singleton registry
# ---------------------------------------------------------------------------

_registry: dict[str, ReasoningMemory] = {}
_registry_locks: dict[str, threading.Lock] = {}
_registry_global_lock: threading.Lock = threading.Lock()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def provision(tenant_id: str, config: dict[str, Any]) -> ReasoningMemory:
    """Return the cached ReasoningMemory for *tenant_id*, creating it if absent.

    Thread-safe via canonical double-checked locking.  Idempotent: repeated
    calls with the same *tenant_id* return the exact same instance (``is``
    identity).

    Parameters
    ----------
    tenant_id:
        Pre-hashed tenant identifier (64-hex sha256, ``team-<slug>``, or
        ``DEFAULT_TENANT``).  validate_tenant_id() is called internally;
        TenantIdError propagates uncaught on malformed input.
    config:
        Plain dict with the five keys required by ReasoningMemory.  Config
        validation is owned by the constructor; a missing key raises ValueError.

    Raises
    ------
    TenantIdError
        Malformed or unsafe tenant_id.  Caller must treat as 4xx.
    TenantScopingDisabledError
        Non-DEFAULT tenant_id requested without GRAQLE_TENANT_SCOPING=1.
        Caller must treat as fatal misconfiguration.
    """
    # Step 1 — validate and normalise.  TenantIdError propagates.
    effective: str = validate_tenant_id(tenant_id)

    # Step 2 — ensure a per-tenant lock exists and snapshot its reference
    # while still holding _registry_global_lock.  This prevents a concurrent
    # clear_registry() from deleting the lock from _registry_locks between
    # the two `with` blocks (which would cause a KeyError on step 3).
    with _registry_global_lock:
        if effective not in _registry_locks:
            _registry_locks[effective] = threading.Lock()
        tenant_lock = _registry_locks[effective]  # snapshot under global lock

    # Step 3 — acquire per-tenant lock via the snapshot reference.
    with tenant_lock:
        # Step 4 — mandatory inner re-check (double-checked locking safety).
        if effective in _registry:
            return _registry[effective]

        # Step 5 — construct.  Any exception propagates; no partial entry written.
        # Shallow copy defends against caller mutating config after provision() returns.
        # Sufficient because all required config values are primitives (str/float/int).
        instance = ReasoningMemory(dict(config), tenant_id=effective)

        # Step 6 — store and return.
        _registry[effective] = instance
        return instance


def clear_registry() -> None:
    """Clear all cached instances and per-tenant locks.

    **Test-only.**  Guarded by GRAQLE_TEST_MODE=1 env flag.
    Raises RuntimeError in production contexts.

    Must be called in test teardown (e.g., via a pytest autouse fixture) to
    prevent cross-test state leakage.
    """
    if os.environ.get("GRAQLE_TEST_MODE", "").lower() not in ("1", "true", "yes"):
        raise RuntimeError(
            "clear_registry() is for test environments only. "
            "Set GRAQLE_TEST_MODE=1 (also accepts 'true' or 'yes')."
        )

    with _registry_global_lock:
        _registry.clear()
        _registry_locks.clear()
