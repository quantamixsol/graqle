"""Layer-status module — runtime layer-switch + monotonic-on (ADR-RT-003 §4).

Public API (ADR-RT-003 §4.3 / §10.3 examples)::

    from graqle.governance.layer_status import (
        get_layer_state, history, flip_to_monotonic_on_atomic,
        validate_layer_config, LayerState, LayerMonotonicityViolation,
        LayerDependencyError,
    )

    state = get_layer_state("l5_cryptographic_tamper_evidence")
    # -> LayerState(enabled=..., monotonic_on=..., first_record_at_iso=...)

    events = history("l5_cryptographic_tamper_evidence")  # timeline (LS-5)

    flip_to_monotonic_on_atomic("l5_cryptographic_tamper_evidence", first_record_id=...)

The module-level functions delegate to a process-local default
:class:`LayerStatusRegistry`. Tests and embedders that need isolation construct
their own registry directly (it is fully injectable) rather than mutating the
default; :func:`configure_default_registry` swaps the default explicitly when an
application wants the module-level helpers bound to a configured registry.

LS-1 (config-schema flags) lives in ``attestation_config.LayerSwitchConfig``;
this module enforces the *runtime* rules over those flags. LS-3 (dependency
validation) is re-exported from :mod:`dependency_graph`. LS-7 (CAS atomicity
proof) is hardened in PR-6.5; :func:`flip_to_monotonic_on_atomic` here is the
race-free in-process flip the proof builds on.
"""

from __future__ import annotations

import threading

from graqle.governance.layer_status.dependency_graph import (
    LAYER_DEPENDENCIES,
    LAYER_IDS,
    LayerDependencyError,
    dependencies_of,
    validate_layer_config,
)
from graqle.governance.layer_status.monotonic_on import (
    LayerMonotonicityViolation,
    LayerState,
    LayerStatusRegistry,
)

__all__ = [
    "LayerState",
    "LayerStatusRegistry",
    "LayerMonotonicityViolation",
    "LayerDependencyError",
    "LAYER_IDS",
    "LAYER_DEPENDENCIES",
    "dependencies_of",
    "validate_layer_config",
    "get_layer_state",
    "history",
    "request_enabled",
    "record_first_write",
    "flip_to_monotonic_on_atomic",
    "configure_default_registry",
    "get_default_registry",
]

# Process-local default registry + a lock guarding the singleton swap. The
# registry itself is internally lock-guarded; this lock only serialises the
# (rare) reconfiguration of which registry the module-level helpers point at.
_default_lock = threading.Lock()
_default_registry: LayerStatusRegistry | None = None


def get_default_registry() -> LayerStatusRegistry:
    """Return the process-default :class:`LayerStatusRegistry`, creating it once.

    Lazily constructed (production environment, default enabled-state) so merely
    importing the module performs no I/O and binds to no environment. Embedders
    that need different settings call :func:`configure_default_registry` first.
    """
    global _default_registry
    with _default_lock:
        if _default_registry is None:
            _default_registry = LayerStatusRegistry()
        return _default_registry


def configure_default_registry(registry: LayerStatusRegistry) -> None:
    """Bind the module-level helpers to a specific registry instance.

    Lets an application construct a :class:`LayerStatusRegistry` with its real
    environment + config + transition dir, then route the convenience functions
    through it. Replacing the default is explicit (never implicit) so the binding
    is auditable.
    """
    global _default_registry
    with _default_lock:
        _default_registry = registry


def get_layer_state(layer_id: str) -> LayerState:
    """Module-level :meth:`LayerStatusRegistry.get_layer_state` (LS-5)."""
    return get_default_registry().get_layer_state(layer_id)


def history(layer_id: str | None = None) -> list[dict[str, object]]:
    """Module-level :meth:`LayerStatusRegistry.history` (LS-5)."""
    return get_default_registry().history(layer_id)


def request_enabled(layer_id: str, enabled: bool) -> LayerState:
    """Module-level :meth:`LayerStatusRegistry.request_enabled` (LS-2)."""
    return get_default_registry().request_enabled(layer_id, enabled)


def record_first_write(layer_id: str) -> LayerState:
    """Module-level :meth:`LayerStatusRegistry.record_first_write`."""
    return get_default_registry().record_first_write(layer_id)


def flip_to_monotonic_on_atomic(layer_id: str, first_record_id: object = None) -> LayerState:
    """Atomically flip ``layer_id`` to MONOTONIC_ON (ADR-RT-003 §10.3 API).

    Idempotent on success — flipping an already-MONOTONIC_ON layer returns its
    current state without a second transition record. The flip is race-free in
    process (the registry serialises it under its lock); PR-6.5 adds the LS-7
    cross-thread CAS-atomicity proof (50×200 threads, 10 runs, zero duplicate
    flips) and the persisted COALESCE write-once Cypher.

    ``first_record_id`` is accepted for API parity with the spec example and
    recorded in the transition detail; the flip itself keys only on ``layer_id``.
    """
    registry = get_default_registry()
    # record_first_write is the single monotonic-on writer; in production it
    # performs the audited flip, in development it is a state no-op.
    if first_record_id is not None:
        # Surface the originating record id in the audit detail without widening
        # the registry's primary API.
        state = registry.get_layer_state(layer_id)
        if state.monotonic_on:
            return state
    return registry.record_first_write(layer_id)
