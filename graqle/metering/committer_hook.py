"""Count point 2 (Layer-5 batch path): meter each anchored leaf (WS-B B1).

The Layer-5 ``Committer`` anchors a *batch* of governed records to Rekor in one
call; each leaf in that batch is one hosted proof and therefore one billable
``proof_anchored`` event. This path bypasses the runtime ``AttestationSink``
entirely, so metering only count point 1 would silently under-bill every
batch-anchored proof (the spec's revenue-leak finding).

This module provides :func:`make_meter_observer` — a factory that returns a
**best-effort, never-raise** callback matching the ``Committer``'s additive
``meter_observer`` seam (mirroring the shipped ``as_trace_observer`` discipline:
a metering fault must never break the anchoring/governed path). The ``Committer``
invokes it **only on the ANCHORED transition**, once per anchored leaf, passing
that leaf's ``record_hash`` (the Merkle ``leaf_hash`` hex — the SAME idempotency
key used on count point 1, so a proof that somehow flows through both paths bills
exactly once when the two paths share a :class:`MeterDedupeStore`).

The free/paid line is honoured structurally: the observer fires on
``anchored=True`` only. A purely-local commit (no anchor configured, or anchor
failed → REPLAY_QUEUED/FAILED) never reaches this callback, so local work emits
zero billable events.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from graqle.metering.dedupe import MeterDedupeStore
from graqle.metering.events import MeterEvent, MeterSink
from graqle.metering.sinks import LocalNullMeter

__all__ = ["make_meter_observer"]

logger = logging.getLogger(__name__)

# The observer is called once per anchored leaf with (record_hash, context).
MeterObserver = Callable[[str, dict[str, Any]], None]


def make_meter_observer(
    meter: MeterSink | None = None,
    dedupe: MeterDedupeStore | None = None,
    *,
    edition: str = "community",
) -> MeterObserver:
    """Build a never-raise ``meter_observer`` for the ``Committer`` anchor path.

    Parameters
    ----------
    meter:
        Where billable events go (defaults to :class:`LocalNullMeter` — Community
        meters nothing). The Studio-backend passes its ``StudioMeter``.
    dedupe:
        The exactly-once gate. Pass the SAME :class:`MeterDedupeStore` instance as
        count point 1 to get cross-path exactly-once; omit for per-call emission
        without dedupe.
    edition:
        Edition stamped onto emitted events. Defaults to ``"community"``.

    Returns
    -------
    A callable ``observer(record_hash, context)`` that the ``Committer`` invokes
    once per anchored leaf. It NEVER raises: any metering fault is swallowed and
    logged so the anchoring path's success/failure semantics are unchanged.
    ``context`` carries non-billing batch metadata (e.g. ``batch_id``,
    ``rekor_log_index``) for the meter API's audit trail.
    """
    sink: MeterSink = meter if meter is not None else LocalNullMeter()

    def _observe(record_hash: str, context: dict[str, Any] | None = None) -> None:
        try:
            if not isinstance(record_hash, str) or not record_hash:
                return  # nothing to bill without a leaf hash
            if dedupe is not None and not dedupe.mark_if_new(record_hash):
                return  # already billed (other path / retry) — exactly-once
            event = MeterEvent(
                idempotency_key=record_hash,
                edition=edition,
                metadata=dict(context) if isinstance(context, dict) else {},
            )
            sink.record(event)
        except Exception:  # never break the anchoring path
            logger.warning("metering failed on committer anchor path (non-fatal)", exc_info=True)

    return _observe
