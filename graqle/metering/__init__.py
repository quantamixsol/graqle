"""GraQle metering (WS-B): the billable-unit meter for hosted proof anchoring.

Open-core boundary
------------------
This package ships in the Apache-2.0 ``graqle`` **Community** build. It defines:

* the billable unit — :class:`MeterEvent` (``unit="proof_anchored"``);
* the sink interface — :class:`MeterSink` (the seam the proprietary
  Studio-backend's ``StudioMeter`` binds to in Session-2);
* the Community sink — :class:`LocalNullMeter` (a no-op: **local work is free**);
* the exactly-once dedupe store — :class:`MeterDedupeStore` (WAL-backed,
  keyed on the proof ``leaf_hash``);
* the two count points that record *intent to bill* without modifying any
  governed/anchoring internals (composition, never modification):
    - :class:`MeteredAttestationSink` — wraps the runtime ``AttestationSink``;
    - :func:`make_meter_observer` — a never-raise callback for the Layer-5
      ``Committer`` anchor path.

The free/paid line (ADR §3.3): **local = free, hosted = metered.** A billable
event is recorded only at the moment a proof becomes hosted/anchored, deduped to
exactly-once across both paths and retries on the proof's ``leaf_hash``.
"""

from __future__ import annotations

from graqle.metering.committer_hook import make_meter_observer
from graqle.metering.dedupe import MeterDedupeError, MeterDedupeStore
from graqle.metering.events import PROOF_ANCHORED, MeterEvent, MeterSink
from graqle.metering.sinks import LocalNullMeter, MeteredAttestationSink

__all__ = [
    "PROOF_ANCHORED",
    "MeterEvent",
    "MeterSink",
    "LocalNullMeter",
    "MeteredAttestationSink",
    "MeterDedupeStore",
    "MeterDedupeError",
    "make_meter_observer",
]
