"""Community meter sinks + the runtime-path count point (WS-B B1).

Two pieces ship in Community:

* :class:`LocalNullMeter` — the default :class:`~graqle.metering.events.MeterSink`.
  A no-op: local work is free (ADR §3.3). It exists so the wiring is always
  present and identical in shape to the hosted build — the Studio-backend swaps
  in ``StudioMeter`` (Session-2) with no call-site change.
* :class:`MeteredAttestationSink` — **count point 1** (the runtime path). A thin
  decorator that wraps *any* ``graqle.governance.runtime.AttestationSink``,
  reads the proof's ``leaf_hash_hex`` off the record, runs the exactly-once
  dedupe gate, and (on a genuinely-new proof) records one :class:`MeterEvent` —
  *then* delegates the actual durable write to the wrapped sink. Composition,
  not modification: ``GovernedRuntime.attest`` is untouched; you opt in by
  constructing the runtime with ``GovernedRuntime(sink=MeteredAttestationSink(...))``.

Count point 2 (the Layer-5 batch path) lives in
:mod:`graqle.metering.committer_hook`.

The billable moment on this path is the attested write itself, which only
carries a ``leaf_hash_hex`` when it represents a real governed decision; a record
without one is passed straight through unmetered (defensive — never bill a
malformed/partial record).
"""

from __future__ import annotations

import logging
from typing import Any

from graqle.metering.dedupe import MeterDedupeStore
from graqle.metering.events import MeterEvent, MeterSink

__all__ = ["LocalNullMeter", "MeteredAttestationSink"]

logger = logging.getLogger(__name__)


class LocalNullMeter:
    """The Community no-op meter sink: local work is free, so it bills nothing.

    Implements :class:`~graqle.metering.events.MeterSink`. Kept as a real class
    (not ``None``) so every count point always has a sink to call and the wiring
    is identical between Community and the hosted build.
    """

    def record(self, event: MeterEvent) -> None:  # noqa: D401 - protocol impl
        """No-op. Community does not meter local work."""
        return None


class MeteredAttestationSink:
    """Count point 1 (runtime path): meter an attested write, then delegate it.

    Wraps any ``AttestationSink`` (``DurableJsonlSink``, ``InMemorySink``, or the
    R2 hosted anchoring sink). On each :meth:`write`:

    1. extract the proof's ``leaf_hash_hex`` from the record (the idempotency
       key — computed by ``GovernedRuntime.attest`` before it calls the sink);
    2. **meter best-effort** — run the exactly-once dedupe gate and, only on a
       genuinely-new proof, hand one :class:`MeterEvent` to the configured
       :class:`MeterSink`. Any metering error is swallowed and logged: metering
       must never break or block the durable attestation path;
    3. **always** delegate the write to the wrapped sink (the system of record).

    Parameters
    ----------
    inner:
        The wrapped ``AttestationSink`` whose ``write`` does the durable record.
    meter:
        Where billable events go (defaults to :class:`LocalNullMeter`).
    dedupe:
        The exactly-once gate. Shared with count point 2 so a proof that flows
        through both paths bills once. Optional: if omitted, the meter still
        fires but without cross-call dedupe — pass a shared
        :class:`MeterDedupeStore` for real exactly-once.
    edition:
        Edition stamped onto emitted events. Defaults to ``"community"``.
    """

    def __init__(
        self,
        inner: Any,
        meter: MeterSink | None = None,
        dedupe: MeterDedupeStore | None = None,
        *,
        edition: str = "community",
    ) -> None:
        if inner is None or not hasattr(inner, "write"):
            raise ValueError("inner must be an AttestationSink (an object with a write method)")
        self._inner = inner
        self._meter: MeterSink = meter if meter is not None else LocalNullMeter()
        self._dedupe = dedupe
        self._edition = edition

    def write(self, record: dict[str, Any]) -> None:
        """Meter the attested record (best-effort), then durably write it."""
        # Step 1+2: meter intent. Wrapped so a metering fault can NEVER stop the
        # durable write — the attestation is the system of record; billing is
        # downstream and must not gate it.
        try:
            self._meter_record(record)
        except Exception:  # never break the attestation path
            logger.warning("metering failed on runtime attest path (non-fatal)", exc_info=True)
        # Step 3: the durable write always happens.
        self._inner.write(record)

    def _meter_record(self, record: dict[str, Any]) -> None:
        """Emit one billable event for ``record`` if it is a new anchored proof."""
        key = record.get("leaf_hash_hex") if isinstance(record, dict) else None
        if not isinstance(key, str) or not key:
            # No leaf hash => not a meterable governed proof. Pass through.
            return
        if self._dedupe is not None and not self._dedupe.mark_if_new(key):
            return  # already billed (retry / other path) — exactly-once
        event = MeterEvent(
            idempotency_key=key,
            edition=self._edition,
            metadata={
                k: record[k]
                for k in ("record_id", "domain", "policy_id")
                if isinstance(record, dict) and k in record
            },
        )
        self._meter.record(event)
