"""StudioMeter — the hosted ``MeterSink`` that records billable anchors (Phase 4).

Implements ``graqle.metering.events.MeterSink`` (``record(event) -> None``). The
exactly-once dedupe (:class:`DynamoDbDedupeStore`) runs BEFORE this sink, so every
``record`` call is a genuinely-new billable ``proof_anchored`` event.

What it does per call:

1. Resolve the billing tenant from ``event.metadata["tenant_id"]`` (threaded
   from the ingress where the Studio API key is known). A missing tenant_id is
   attributed to a configurable fallback (``"unknown"``) and logged — we never
   *drop* a billable event for lack of attribution (that would under-bill); it is
   recorded against the fallback for reconciliation.
2. Atomically increment the tenant's monthly counter in a DynamoDB usage table,
   keyed ``(tenant_id#edition#YYYY-MM)`` — DynamoDB ``ADD`` returns the new total,
   so we learn this anchor's position in the month in one round-trip.
3. Classify the anchor: within the configurable free allowance (default 1,000) →
   ``"included"``; beyond it → ``"overage"``. The classification + running total
   are written so the dashboard / invoicing read it; pricing the overage is the
   billing system's job, not the meter's.

NEVER raises on the anchoring path: the proof is already durably anchored in Rekor
+ S3 before this runs, so a metering fault must not break it. The wiring
(``make_meter_observer``) already wraps this best-effort; we ALSO guard here so a
DynamoDB blip degrades to "this one anchor not counted yet" (a rare under-bill),
never an exception into the worker.
"""

from __future__ import annotations

import logging
from typing import Any

from graqle.metering.events import MeterEvent

logger = logging.getLogger("studio_backend.metering.studio_meter")

DEFAULT_FREE_ALLOWANCE = 1_000
_UNKNOWN_TENANT = "unknown"

USAGE_INCLUDED = "included"
USAGE_OVERAGE = "overage"


class StudioMeter:
    """A ``MeterSink`` that records billable anchors to a DynamoDB usage table.

    Parameters
    ----------
    usage_table:
        DynamoDB table name. Schema: partition key ``usage_key`` (S) =
        ``"{tenant_id}#{edition}#{YYYY-MM}"``; a numeric ``count`` attribute is
        ``ADD``-incremented per billable anchor.
    free_allowance:
        Free anchors per tenant per month before overage. Default 1,000
        (configurable per the locked decision).
    client:
        Injectable boto3 ``dynamodb`` client (testable without AWS).
    region_name:
        Region for the lazily-created client. Defaults to ``eu-central-1``.
    """

    def __init__(
        self,
        usage_table: str,
        *,
        free_allowance: int = DEFAULT_FREE_ALLOWANCE,
        client: Any = None,
        region_name: str = "eu-central-1",
    ) -> None:
        if not isinstance(usage_table, str) or not usage_table:
            raise ValueError("usage_table must be a non-empty string")
        if not isinstance(free_allowance, int) or free_allowance < 0:
            raise ValueError("free_allowance must be a non-negative int")
        self._usage_table = usage_table
        self._free_allowance = free_allowance
        self._client = client
        self._region_name = region_name

    def _ddb(self) -> Any:
        if self._client is None:  # pragma: no cover - real AWS only
            import boto3

            self._client = boto3.client("dynamodb", region_name=self._region_name)
        return self._client

    def record(self, event: MeterEvent) -> None:
        """Record one billable ``proof_anchored`` event. Side-effects only.

        Best-effort + never-raise: a metering fault degrades to "not counted yet"
        for this one anchor, never an exception into the (already-successful)
        anchoring path.
        """
        try:
            self._record(event)
        except Exception:  # never break the anchoring path
            logger.warning(
                "StudioMeter.record failed (non-fatal; anchor already durable)",
                exc_info=True,
            )

    def _record(self, event: MeterEvent) -> None:
        tenant_id = self._tenant_of(event)
        edition = self._safe_segment(event.edition, "edition")
        period = self._period_of(event)
        usage_key = f"{tenant_id}#{edition}#{period}"

        # Atomic increment; ADD returns the post-increment total in one trip.
        resp = self._ddb().update_item(
            TableName=self._usage_table,
            Key={"usage_key": {"S": usage_key}},
            UpdateExpression="ADD #c :one",
            ExpressionAttributeNames={"#c": "count"},
            ExpressionAttributeValues={":one": {"N": "1"}},
            ReturnValues="UPDATED_NEW",
        )
        new_total = int(resp.get("Attributes", {}).get("count", {}).get("N", "0"))
        classification = (
            USAGE_INCLUDED if new_total <= self._free_allowance else USAGE_OVERAGE
        )
        logger.info(
            "metered proof_anchored: tenant=%s edition=%s period=%s total=%d/%d -> %s leaf=%s",
            tenant_id,
            event.edition,
            period,
            new_total,
            self._free_allowance,
            classification,
            event.idempotency_key[:12],
        )

    def _tenant_of(self, event: MeterEvent) -> str:
        """Billing tenant from event.metadata['tenant_id'] (fallback to unknown).

        Sanitised so a crafted tenant_id cannot alias another tenant's monthly
        usage bucket: the usage_key is ``tenant#edition#period``, so a ``#`` in
        the tenant id would collide buckets. We strip the delimiter rather than
        reject (never drop a billable event); a tenant id reduced to empty by
        sanitising falls back to ``unknown`` for reconciliation.
        """
        tid = event.metadata.get("tenant_id") if isinstance(event.metadata, dict) else None
        if isinstance(tid, str) and tid.strip():
            safe = self._safe_segment(tid, "tenant_id")
            if safe:
                return safe
        logger.warning(
            "billable anchor with no usable tenant_id — attributing to %r for "
            "reconciliation (leaf=%s)",
            _UNKNOWN_TENANT,
            event.idempotency_key[:12],
        )
        return _UNKNOWN_TENANT

    @staticmethod
    def _safe_segment(value: object, what: str) -> str:
        """Make ``value`` safe to use as a ``#``-delimited usage_key segment.

        Removes the ``#`` delimiter (and surrounding whitespace) so no input can
        alias another segment. Returns "" for non-str/empty, which the caller
        handles (tenant → unknown; edition → "" is acceptable, the tenant+period
        still disambiguate).
        """
        if not isinstance(value, str):
            return ""
        return value.strip().replace("#", "")

    @staticmethod
    def _period_of(event: MeterEvent) -> str:
        """Billing period ``YYYY-MM`` from the event's UTC timestamp.

        The event carries an ISO-8601 ``ts`` (set at the anchoring moment). We
        take the first 7 chars (``YYYY-MM``) — robust to any offset suffix and
        avoids re-parsing. Falls back to ``"unknown"`` for a malformed ts (never
        drops the event).
        """
        ts = getattr(event, "ts", "")
        if isinstance(ts, str) and len(ts) >= 7 and ts[4] == "-" and ts[:4].isdigit():
            return ts[:7]
        return "unknown"


__all__ = [
    "StudioMeter",
    "DEFAULT_FREE_ALLOWANCE",
    "USAGE_INCLUDED",
    "USAGE_OVERAGE",
]
