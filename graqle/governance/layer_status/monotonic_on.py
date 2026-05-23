"""Monotonic-on layer-status registry (ADR-RT-003 §2.2 / §8.3; LS-2, LS-4, LS-6).

This module operationalises the EU AI Act Article 12 invariant **"once you start
recording, you do not stop recording"** as a runtime rule on the five governance
layers L1..L5.

Semantics differ by environment (LS-2):

* **development** — layers freely toggle on/off; transitions are logged but never
  gate further operations.
* **production** — a layer toggles on/off only *before* the first governed record
  is written under it. The first write flips the layer to ``MONOTONIC_ON``; from
  then on any attempt to set ``enabled: false`` for that layer raises
  :class:`LayerMonotonicityViolation`. **There is no override** (LS-6): no method
  here clears ``monotonic_on`` — to leave the state a deployment must be
  re-instantiated from scratch.

Every monotonic-on transition AND every refused disable attempt is itself a
governed record (LS-4). To capture that audit trail WITHOUT recursing back into
the trace-capture machinery (§8.3) — TraceCapture invokes the committer observer,
which would re-enter here and self-trigger — these records are written by
:func:`_write_layer_transition_audit_record` straight to a dedicated append-only
sidecar (``layer_transitions/``) flagged ``_internal_transition: true``. That
sidecar is a different physical store from the governed-trace store, so the
transition record can never loop back through TraceCapture.

The registry is process-local and lock-guarded. :func:`flip_to_monotonic_on`
here is the single writer of the ``monotonic_on`` flag; PR-6.5 hardens the flip
with a compare-and-set atomicity proof (LS-7) — the lock here already makes the
in-process flip race-free; PR-6.5 adds the cross-thread zero-duplicate guarantee
test and the COALESCE write-once Cypher for the persisted flag.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from graqle.governance.layer_status.dependency_graph import LAYER_IDS
from graqle.governance.tamper_evidence.errors import TamperEvidenceError

logger = logging.getLogger(__name__)

__all__ = [
    "LayerState",
    "LayerMonotonicityViolation",
    "LayerStatusRegistry",
]

# Sidecar dir for §8.3 transition audit records. Sibling of the governed-trace
# store but a SEPARATE physical store (recursion prevention).
_DEFAULT_TRANSITION_DIR = Path.home() / ".graqle" / "layer_transitions"


class LayerMonotonicityViolation(TamperEvidenceError):
    """Raised when production code attempts to disable a ``MONOTONIC_ON`` layer.

    The attempted disable is itself audited (LS-4) before this is raised, so the
    audit trail records the attempt even though it is refused.
    """

    def __init__(self, layer_id: str) -> None:
        self.layer_id = layer_id
        super().__init__(
            f"layer {layer_id!r} is MONOTONIC_ON and cannot be disabled: once a "
            f"governed record is written under a layer in production, that layer "
            f"stays on (ADR-RT-003 §2.2; EU AI Act Art. 12). There is no override."
        )


@dataclass
class LayerState:
    """Runtime status of one governance layer.

    Attributes
    ----------
    layer_id:
        Canonical layer id (one of :data:`LAYER_IDS`).
    enabled:
        The current enabled flag.
    monotonic_on:
        ``True`` once a governed record has been written under this layer in a
        production environment. Never cleared (LS-6).
    first_record_at_iso:
        UTC ISO-8601 timestamp of the first governed record under this layer
        (the moment ``monotonic_on`` flipped), or ``None`` if it has not.
    """

    layer_id: str
    enabled: bool
    monotonic_on: bool = False
    first_record_at_iso: str | None = None


@dataclass
class _Transition:
    """One recorded layer-status transition (for the queryable history, LS-5)."""

    layer_id: str
    event: str  # "monotonic_on" | "disable_refused" | "enabled" | "disabled"
    at_iso: str
    environment: str
    detail: dict[str, object] = field(default_factory=dict)


def _utc_now_iso() -> str:
    """Current UTC time as ISO-8601 with a trailing ``Z`` (matches audit_log_v3)."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_layer_transition_audit_record(
    record: dict[str, object], transition_dir: Path
) -> None:
    """Append a transition audit record to the sidecar store (§8.3 bypass).

    Written synchronously with ``fsync`` durability — mirroring
    ``TraceStore._sync_append`` — straight to a dedicated ``layer_transitions/``
    JSONL, NOT through ``TraceCapture``. Routing a layer transition through
    TraceCapture would re-enter the committer observer and self-trigger another
    transition check (infinite recursion); writing here breaks that loop while
    still preserving the Article 12 audit trail (LS-4).

    The record always carries ``_internal_transition: true`` so downstream
    consumers can distinguish an internal layer-status event from an ordinary
    governed trace.
    """
    record = {**record, "_internal_transition": True}
    transition_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    file_path = transition_dir / f"{today}.jsonl"
    line = json.dumps(record, default=str) + "\n"
    fd = os.open(str(file_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


class LayerStatusRegistry:
    """Process-local registry of per-layer enabled / monotonic-on state.

    Parameters
    ----------
    environment:
        ``"production"`` or ``"development"`` — gates monotonic-on enforcement
        (§2.2). Unknown values are treated as production (fail-safe: enforce the
        stricter rule rather than silently allowing disables).
    enabled:
        Initial enabled-state map (layer id -> bool). Defaults to all layers
        enabled except L5, mirroring the v0.59.0 config default.
    transition_dir:
        Directory for the §8.3 transition audit sidecar. Injectable for tests so
        no writes touch the real ``~/.graqle`` store.
    """

    def __init__(
        self,
        environment: str = "production",
        enabled: dict[str, bool] | None = None,
        transition_dir: str | Path | None = None,
    ) -> None:
        self._environment = environment
        self._transition_dir = Path(transition_dir) if transition_dir is not None else _DEFAULT_TRANSITION_DIR
        self._lock = threading.RLock()
        if enabled is None:
            enabled = {lid: (lid != "l5_cryptographic_tamper_evidence") for lid in LAYER_IDS}
        self._states: dict[str, LayerState] = {
            lid: LayerState(layer_id=lid, enabled=bool(enabled.get(lid, False)))
            for lid in LAYER_IDS
        }
        self._history: list[_Transition] = []

    @property
    def is_production(self) -> bool:
        """True unless the environment is exactly ``"development"`` (fail-safe)."""
        return self._environment != "development"

    def _require_known_layer(self, layer_id: str) -> None:
        """Reject an unknown layer id at the public boundary with a clear error.

        Still a :class:`KeyError` (the documented contract), but the message
        names the canonical layer ids so a typo is actionable rather than an
        opaque dict miss.
        """
        if layer_id not in self._states:
            raise KeyError(
                f"unknown layer id {layer_id!r}; valid ids: {', '.join(LAYER_IDS)}"
            )

    def get_layer_state(self, layer_id: str) -> LayerState:
        """Return the current :class:`LayerState` for ``layer_id`` (LS-5).

        Raises :class:`KeyError` for an unknown layer id.
        """
        with self._lock:
            self._require_known_layer(layer_id)
            state = self._states[layer_id]
            # Return a copy so callers cannot mutate registry state directly.
            return LayerState(
                layer_id=state.layer_id,
                enabled=state.enabled,
                monotonic_on=state.monotonic_on,
                first_record_at_iso=state.first_record_at_iso,
            )

    def history(self, layer_id: str | None = None) -> list[dict[str, object]]:
        """Return the transition timeline (LS-5).

        With ``layer_id`` set, only that layer's transitions are returned;
        otherwise all transitions across all layers, in chronological order.
        Each entry is a plain dict (``layer_id, event, at_iso, environment,
        detail``) so it serialises directly.
        """
        with self._lock:
            return [
                {
                    "layer_id": t.layer_id,
                    "event": t.event,
                    "at_iso": t.at_iso,
                    "environment": t.environment,
                    "detail": dict(t.detail),
                }
                for t in self._history
                if layer_id is None or t.layer_id == layer_id
            ]

    def record_first_write(self, layer_id: str) -> LayerState:
        """Register that a governed record was written under ``layer_id``.

        In production, the FIRST such write flips the layer to ``MONOTONIC_ON``
        (idempotent: subsequent writes are no-ops). In development this is a
        no-op on state (monotonic-on does not apply) but is still logged. Returns
        the (copied) post-call :class:`LayerState`.
        """
        with self._lock:
            self._require_known_layer(layer_id)
            state = self._states[layer_id]
            if not self.is_production:
                return self.get_layer_state(layer_id)
            if state.monotonic_on:
                return self.get_layer_state(layer_id)  # already flipped
            self._flip_to_monotonic_on_locked(layer_id)
            return self.get_layer_state(layer_id)

    def _flip_to_monotonic_on_locked(self, layer_id: str) -> None:
        """Flip ``layer_id`` to MONOTONIC_ON + audit it (caller holds the lock).

        The single writer of the ``monotonic_on`` flag (LS-6: nothing else sets
        it, and nothing ever clears it). Records an LS-4 transition audit record
        via the §8.3 sidecar.
        """
        now = _utc_now_iso()
        state = self._states[layer_id]
        state.monotonic_on = True
        state.enabled = True  # a layer that just recorded is, by definition, on
        state.first_record_at_iso = now
        self._append_transition(layer_id, "monotonic_on", now, {"first_record_at_iso": now})
        logger.info("Layer %s flipped to MONOTONIC_ON at %s (production)", layer_id, now)

    def request_enabled(self, layer_id: str, enabled: bool) -> LayerState:
        """Apply an enabled-state change request, enforcing monotonic-on (LS-2).

        * Enabling a layer is always allowed.
        * Disabling a layer is allowed in development, and in production only if
          the layer is NOT yet ``MONOTONIC_ON``.
        * Disabling a ``MONOTONIC_ON`` layer in production audits the refused
          attempt (LS-4) then raises :class:`LayerMonotonicityViolation` (LS-2).

        Returns the (copied) post-call :class:`LayerState` on success.
        """
        with self._lock:
            self._require_known_layer(layer_id)
            state = self._states[layer_id]
            now = _utc_now_iso()
            if enabled:
                if not state.enabled:
                    state.enabled = True
                    self._append_transition(layer_id, "enabled", now, {})
                return self.get_layer_state(layer_id)
            # enabled is False -> a disable request.
            if self.is_production and state.monotonic_on:
                # Audit the refused attempt BEFORE raising (LS-4): the attempt is
                # itself part of the Article 12 trail.
                self._append_transition(
                    layer_id, "disable_refused", now, {"reason": "monotonic_on"}
                )
                logger.warning(
                    "Refused disable of MONOTONIC_ON layer %s (production)", layer_id
                )
                raise LayerMonotonicityViolation(layer_id)
            if state.enabled:
                state.enabled = False
                self._append_transition(layer_id, "disabled", now, {})
            return self.get_layer_state(layer_id)

    def _append_transition(
        self, layer_id: str, event: str, at_iso: str, detail: dict[str, object]
    ) -> None:
        """Record a transition in-memory (LS-5) and to the §8.3 sidecar (LS-4)."""
        self._history.append(
            _Transition(
                layer_id=layer_id,
                event=event,
                at_iso=at_iso,
                environment=self._environment,
                detail=dict(detail),
            )
        )
        _write_layer_transition_audit_record(
            {
                "layer_id": layer_id,
                "event": event,
                "at_iso": at_iso,
                "environment": self._environment,
                "detail": detail,
            },
            self._transition_dir,
        )
