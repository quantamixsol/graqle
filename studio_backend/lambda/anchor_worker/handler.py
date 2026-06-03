"""SQS-triggered batch anchoring Lambda (BizQ S2, Studio backend).

Dequeues attested records from the anchoring SQS queue, anchors them as one batch
(Merkle root → Sigstore Rekor → ed25519-signed proof bundles), writes each proof
bundle to S3 under ``proofs/{batch_id}/{leaf_hash}.json``, and emits one
``proof_anchored`` meter event per anchored leaf.

Deployment shape: this handler lives OUTSIDE the importable ``graqle`` package
(``studio_backend/``) so it never ships in the public Community wheel — it is
proprietary Studio-backend code. It composes the shipped Layer-5 primitives via
``studio_backend.anchoring.worker.anchor_records`` and signs with the
Secrets-Manager-held ed25519 key via ``studio_backend.anchoring.signer``.

Partial-batch failure (SQS): the handler returns ``batchItemFailures`` so SQS
re-drives ONLY the messages it could not process (eventually to the DLQ),
never re-anchoring already-anchored records. Because all messages in one Lambda
invocation are anchored as ONE Merkle batch, a Rekor failure fails the whole
batch (every message id is returned for redrive) — fail-closed: nothing is
written or billed for an unanchored batch.

Config via env:
* ``ANCHOR_SQS_QUEUE_URL``    — (informational; the trigger provides the records)
* ``ANCHOR_S3_BUCKET``        — proof-bundle bucket (default ``graqle-graphs-eu``)
* ``ANCHOR_S3_PREFIX``        — key prefix (default ``proofs``)
* ``ANCHOR_SIGNING_SECRET_ID``— Secrets Manager id of the ed25519 seed
* ``ANCHOR_SIGNING_KID``      — the signing key id (published to the trust source)
* ``ANCHOR_REGION``           — AWS region (default ``eu-central-1``)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("studio_backend.anchor_worker")
logging.getLogger().setLevel(logging.INFO)

_DEFAULT_BUCKET = "graqle-graphs-eu"
_DEFAULT_PREFIX = "proofs"
_DEFAULT_REGION = "eu-central-1"


def _env(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name)
    return val if val not in (None, "") else default


def _build_dependencies():
    """Build (signer, anchor, s3_client) from env. Lazy so unit tests can inject.

    Imports are local so importing this module for unit testing the pure
    record-parsing helpers does not require boto3/sigstore.
    """
    from studio_backend.anchoring.signer import (
        load_ecdsa_rekor_signer_from_secrets_manager,
        load_signer_from_secrets_manager,
    )
    from graqle.governance.tamper_evidence.anchors.sigstore_rekor import RekorAnchor

    region = _env("ANCHOR_REGION", _DEFAULT_REGION)
    secret_id = _env("ANCHOR_SIGNING_SECRET_ID")
    kid = _env("ANCHOR_SIGNING_KID")
    rekor_secret_id = _env("ANCHOR_REKOR_SIGNING_SECRET_ID")
    if not secret_id or not kid:
        raise RuntimeError(
            "ANCHOR_SIGNING_SECRET_ID and ANCHOR_SIGNING_KID must be set"
        )
    if not rekor_secret_id:
        raise RuntimeError("ANCHOR_REKOR_SIGNING_SECRET_ID (ECDSA key) must be set")
    signer = load_signer_from_secrets_manager(
        secret_id=secret_id, kid=kid, region_name=region
    )
    # Dedicated ECDSA P-256 key for the Rekor hashedrekord (ed25519 unsupported
    # by Rekor hashedrekord — sigstore/rekor#851).
    rekor_signer = load_ecdsa_rekor_signer_from_secrets_manager(
        secret_id=rekor_secret_id, region_name=region
    )
    anchor = RekorAnchor()  # real Sigstore Rekor (needs the sigstore extra + egress)

    import boto3

    s3 = boto3.client("s3", region_name=region)
    return signer, rekor_signer, anchor, s3


def parse_records(event: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Parse an SQS event into ``[(message_id, record), ...]``.

    A message whose body is not a JSON object is dropped from the batch and
    logged (it can never anchor) — it is NOT returned as a failure, because
    re-driving an un-parseable message would loop it to the DLQ pointlessly on
    every retry; logging + dropping surfaces it once. (Malformed-but-redrivable
    is distinct from un-anchorable-garbage.)
    """
    out: list[tuple[str, dict[str, Any]]] = []
    for msg in event.get("Records", []) or []:
        mid = msg.get("messageId", "")
        body = msg.get("body")
        try:
            record = json.loads(body) if isinstance(body, str) else body
        except (json.JSONDecodeError, TypeError):
            logger.warning("dropping un-parseable SQS message %s", mid)
            continue
        if not isinstance(record, dict):
            logger.warning("dropping non-object SQS message %s", mid)
            continue
        out.append((mid, record))
    return out


def s3_key(prefix: str, batch_id: str, leaf_hash: str) -> str:
    """Build the S3 key for one proof bundle: ``{prefix}/{batch_id}/{leaf_hash}.json``."""
    return f"{prefix.rstrip('/')}/{batch_id}/{leaf_hash}.json"


def lambda_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """SQS batch entrypoint. Returns ``{"batchItemFailures": [...]}``.

    All records in the event are anchored as ONE Merkle batch. On a fail-closed
    anchor error, every message id is returned for redrive (nothing written/billed).
    """
    from uuid import uuid4

    from studio_backend.anchoring.worker import AnchorWorkerError, anchor_records
    from graqle.metering.committer_hook import make_meter_observer

    parsed = parse_records(event)
    if not parsed:
        return {"batchItemFailures": []}

    message_ids = [mid for mid, _ in parsed]
    records = [rec for _, rec in parsed]

    bucket = _env("ANCHOR_S3_BUCKET", _DEFAULT_BUCKET)
    prefix = _env("ANCHOR_S3_PREFIX", _DEFAULT_PREFIX)
    batch_id = uuid4().hex

    try:
        signer, rekor_signer, anchor, s3 = _build_dependencies()
    except Exception:
        # Cannot build the signer/anchor → fail the WHOLE batch for redrive
        # (do not silently drop; a config/secret outage must be retried).
        logger.exception("failed to build anchoring dependencies")
        return {"batchItemFailures": [{"itemIdentifier": m} for m in message_ids]}

    # Stub meter for Phase 3 (LocalNullMeter via make_meter_observer with no sink).
    # Phase 4 swaps in StudioMeter + a DynamoDB-backed MeterDedupeStore.
    meter_observer = make_meter_observer(edition="studio")

    try:
        result = anchor_records(
            records,
            signer=signer,
            rekor_signer=rekor_signer,
            anchor=anchor,
            batch_id=batch_id,
            meter_observer=meter_observer,
            edition="studio",
        )
    except AnchorWorkerError:
        # Fail-closed: the batch did not anchor → redrive every message, write
        # nothing, bill nothing.
        logger.exception("batch %s failed to anchor (fail-closed)", batch_id)
        return {"batchItemFailures": [{"itemIdentifier": m} for m in message_ids]}

    # Persist each proof bundle to S3. A per-bundle write failure fails ONLY that
    # message (its proof IS anchored in Rekor and durable; we just couldn't store
    # the bundle yet — redrive will re-anchor into a NEW batch, which is safe:
    # the dedupe store [Phase 4] keys on leaf_hash so it bills exactly once).
    failures: list[dict[str, str]] = []
    for mid, bundle in zip(message_ids, result.bundles):
        leaf_hash = bundle["leaf"]["leaf_hash"]
        key = s3_key(prefix, batch_id, leaf_hash)
        try:
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=json.dumps(bundle, sort_keys=True).encode("utf-8"),
                ContentType="application/json",
            )
        except Exception:
            logger.exception("failed to write proof bundle %s to s3://%s/%s", mid, bucket, key)
            failures.append({"itemIdentifier": mid})

    logger.info(
        "anchored batch %s: %d bundles, root=%s, rekor_log_index=%s, s3_failures=%d",
        batch_id, len(result.bundles), result.merkle_root, result.rekor_log_index, len(failures),
    )
    return {"batchItemFailures": failures}


handler = lambda_handler


__all__ = ["parse_records", "s3_key", "lambda_handler", "handler"]
