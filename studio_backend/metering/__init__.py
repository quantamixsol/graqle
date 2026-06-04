"""BizQ S2 hosted metering (Phase 4) — proprietary Studio backend.

Turns hosted anchoring into the billable ``proof_anchored`` unit:

* :class:`DynamoDbDedupeStore` — the DISTRIBUTED exactly-once gate keyed on the
  proof ``leaf_hash`` (a DynamoDB conditional-put). The Community
  ``MeterDedupeStore`` is WAL-on-local-disk — correct for one process, useless
  across many concurrent Lambda invocations (each has its own ``/tmp``). This is
  the cloud analogue; it drops into the SAME ``make_meter_observer(dedupe=...)``
  seam (it exposes ``mark_if_new(leaf_hash) -> bool``).
* :class:`StudioMeter` — the ``MeterSink`` (``record(event)``) that records the
  billable event to a DynamoDB usage table aggregated per
  ``(tenant_id, edition, YYYY-MM)`` and enforces the configurable free monthly
  allowance (default 1,000 anchors) → overage. Best-effort + never-raise on the
  anchoring path (a metering fault must not break a durable, already-anchored
  proof).

Lives OUTSIDE the importable ``graqle`` package (under ``studio_backend/``), so it
never ships in the public Community wheel — proprietary Studio-backend code.
Composes the shipped ``graqle.metering`` interfaces (``MeterSink``,
``MeterEvent``, ``make_meter_observer``); it does not modify them.
"""
