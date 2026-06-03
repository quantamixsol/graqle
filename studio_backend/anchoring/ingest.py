"""Hosted-anchoring ingress (BizQ S2): AttestationSink → SQS.

The customer-facing entry to hosted anchoring. A customer's ``GovernedRuntime``
is configured with a :class:`SqsAttestationSink` instead of the local
``DurableJsonlSink``; every ``attest()`` then enqueues the record to the
anchoring SQS queue, where the batch worker Lambda picks it up. Swapping the sink
is the only change needed to move from "durable local trail" to "publicly
anchored" — exactly the seam the runtime's ``AttestationSink`` Protocol was
designed for (see ``graqle.governance.runtime.runtime.AttestationSink``).

The sink satisfies the Protocol's contract precisely: ``write(record)`` durably
records the record (here: hands it to SQS, which is durable) and **MUST raise on
failure** — a record we could not enqueue is a record that will not be anchored,
so the caller must learn about it rather than silently lose a proof.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("studio_backend.anchoring.ingest")


class IngestError(Exception):
    """Raised when an attested record cannot be enqueued for anchoring."""


class SqsAttestationSink:
    """An ``AttestationSink`` that enqueues attested records to SQS for anchoring.

    Parameters
    ----------
    queue_url:
        The anchoring SQS queue URL.
    client:
        An injectable boto3 ``sqs`` client (so this is testable without AWS). In
        production it is created lazily on first use.
    region_name:
        Region for the lazily-created client. Defaults to ``eu-central-1``.

    Notes
    -----
    Structurally a duck-typed ``AttestationSink`` (one method ``write``); we keep
    it import-light (no ``graqle.server`` import) so it can run inside the
    customer runtime or a thin ingress Lambda.
    """

    def __init__(
        self,
        queue_url: str,
        *,
        tenant_id: str | None = None,
        client: Any = None,
        region_name: str = "eu-central-1",
    ) -> None:
        if not isinstance(queue_url, str) or not queue_url:
            raise IngestError("queue_url must be a non-empty string")
        # The billing tenant for proofs enqueued through THIS sink. The ingress
        # constructs one sink per authenticated request (the Studio API key →
        # account), so the tenant is known here and stamped onto each record for
        # the meter (StudioMeter bills per (tenant_id, edition, month)).
        if tenant_id is not None and (not isinstance(tenant_id, str) or not tenant_id):
            raise IngestError("tenant_id, when given, must be a non-empty string")
        self._tenant_id = tenant_id
        self._queue_url = queue_url
        self._client = client
        self._region_name = region_name

    def _sqs(self) -> Any:
        if self._client is None:  # pragma: no cover - real AWS only
            import boto3

            self._client = boto3.client("sqs", region_name=self._region_name)
        return self._client

    def write(self, record: dict[str, Any]) -> None:
        """Enqueue one attested record for hosted anchoring. MUST raise on failure.

        The record MUST carry ``proof_format_version`` (the leaf/canon contract);
        we validate shape here so a malformed record is rejected at the ingress,
        not deep in the batch worker.
        """
        if not isinstance(record, dict):
            raise IngestError(f"record must be a dict, got {type(record).__name__}")
        if not record.get("proof_format_version"):
            raise IngestError(
                "record is missing 'proof_format_version' (required by the "
                "leaf/canon contract); refusing to enqueue an un-anchorable record"
            )
        # Stamp the billing tenant onto the enqueued record (the worker reads it
        # into the meter). A tenant_id already on the record is NOT overwritten —
        # only add ours when the caller hasn't set one. Copy so we never mutate
        # the caller's dict.
        if self._tenant_id is not None and not record.get("tenant_id"):
            record = {**record, "tenant_id": self._tenant_id}
        try:
            body = json.dumps(record, sort_keys=True, default=str)
        except (TypeError, ValueError) as exc:
            raise IngestError(f"record is not JSON-serialisable: {exc}") from exc

        try:
            self._sqs().send_message(QueueUrl=self._queue_url, MessageBody=body)
        except Exception as exc:  # surface — a dropped record is an un-anchored proof
            raise IngestError(f"failed to enqueue record for anchoring: {exc}") from exc


__all__ = ["IngestError", "SqsAttestationSink"]
