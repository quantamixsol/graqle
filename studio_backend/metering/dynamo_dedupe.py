"""Distributed exactly-once billing dedupe — DynamoDB conditional-put (Phase 4).

The Community :class:`graqle.metering.dedupe.MeterDedupeStore` is a local WAL on
disk: correct for ONE process, but the hosted anchoring worker runs as many
concurrent Lambda invocations, each with its own ephemeral ``/tmp``. Two
invocations anchoring the same proof (a retry, or a redrive that re-batches the
same record) would each see an empty local store and bill twice.

This is the cloud analogue: a DynamoDB table keyed on the proof ``leaf_hash``.
``mark_if_new`` does a conditional ``put_item`` with
``attribute_not_exists(leaf_hash)`` — DynamoDB's strongly-consistent
conditional write is the cross-invocation mutex. The FIRST writer of a key wins
(returns ``True`` → the caller bills once); every later writer gets a
``ConditionalCheckFailedException`` (returns ``False`` → no-op). Exactly-once
billing across the whole distributed worker fleet.

It exposes the SAME ``mark_if_new(key) -> bool`` surface as the Community store,
so it drops straight into ``graqle.metering.make_meter_observer(dedupe=...)`` with
no change to the count-point wiring.

Key = leaf_hash (a 64-char lowercase SHA-256 hex), validated before it becomes a
table key (defence-in-depth, mirrors the Community store).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("studio_backend.metering.dynamo_dedupe")

_KEY_LEN = 64
_HEX_DIGITS = frozenset("0123456789abcdef")


class DedupeError(Exception):
    """Raised when a dedupe operation cannot proceed safely (not a duplicate)."""


def _is_valid_key(key: object) -> bool:
    """True iff ``key`` is a well-formed 64-char lowercase SHA-256 hex leaf_hash."""
    return isinstance(key, str) and len(key) == _KEY_LEN and not (set(key) - _HEX_DIGITS)


class DynamoDbDedupeStore:
    """DynamoDB-backed exactly-once gate keyed on the proof ``leaf_hash``.

    Parameters
    ----------
    table_name:
        The DynamoDB table. Schema: partition key ``leaf_hash`` (S). Optionally a
        ``ttl`` numeric attribute with a table TTL so old ledger rows self-expire
        (the proof is permanent in Rekor/S3; the dedupe row only needs to outlive
        the redrive/retry window — a few days is plenty).
    client:
        An injectable boto3 ``dynamodb`` client (testable without AWS). Created
        lazily in production.
    region_name:
        Region for the lazily-created client. Defaults to ``eu-central-1``.
    ttl_seconds:
        If set, each new row is stamped with ``ttl = now + ttl_seconds`` (the
        caller passes ``now`` so this stays deterministic/testable). Default
        ``None`` = no expiry.
    """

    def __init__(
        self,
        table_name: str,
        *,
        client: Any = None,
        region_name: str = "eu-central-1",
        ttl_seconds: int | None = None,
    ) -> None:
        if not isinstance(table_name, str) or not table_name:
            raise DedupeError("table_name must be a non-empty string")
        self._table_name = table_name
        self._client = client
        self._region_name = region_name
        self._ttl_seconds = ttl_seconds

    def _ddb(self) -> Any:
        if self._client is None:  # pragma: no cover - real AWS only
            import boto3

            self._client = boto3.client("dynamodb", region_name=self._region_name)
        return self._client

    def mark_if_new(self, key: str, *, now_epoch: int | None = None) -> bool:
        """Atomically record ``key`` and report whether it was new (first writer).

        Returns ``True`` exactly once per ``key`` across the whole fleet (the
        caller then bills), ``False`` on every later call for the same key. A
        malformed key is rejected with :class:`DedupeError` rather than treated as
        new — a non-leaf_hash key is an upstream bug, not a billable event.

        On any *other* DynamoDB error (throttle, outage), this RAISES — the caller
        (``make_meter_observer``) swallows it best-effort, so a dedupe outage means
        the meter simply does not fire for that proof (a rare under-bill), never a
        double-bill and never a broken anchoring path.
        """
        if not _is_valid_key(key):
            raise DedupeError(
                f"refusing to dedupe on a malformed key (expected {_KEY_LEN}-char "
                "lowercase hex leaf_hash)"
            )

        item: dict[str, Any] = {"leaf_hash": {"S": key}}
        if self._ttl_seconds is not None:
            base = now_epoch if now_epoch is not None else _utc_epoch()
            item["ttl"] = {"N": str(int(base) + int(self._ttl_seconds))}

        client = self._ddb()
        try:
            client.put_item(
                TableName=self._table_name,
                Item=item,
                ConditionExpression="attribute_not_exists(leaf_hash)",
            )
            return True
        except Exception as exc:
            # The conditional-check failure is the EXPECTED "already billed" path.
            # Detect it by the exception's class name so we don't hard-depend on
            # botocore's exception classes in unit tests (fakes raise a stand-in).
            if _is_conditional_check_failed(exc):
                return False
            # Any other error (throttle/outage) is surfaced — fail-safe upstream.
            raise


def _is_conditional_check_failed(exc: Exception) -> bool:
    """True iff ``exc`` is DynamoDB's ConditionalCheckFailedException.

    Matched by class name (botocore generates these dynamically) and, as a
    fallback, by the error code in a ``ClientError``-style ``response`` dict.
    """
    if type(exc).__name__ == "ConditionalCheckFailedException":
        return True
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        return code == "ConditionalCheckFailedException"
    return False


def _utc_epoch() -> int:  # pragma: no cover - thin clock wrapper
    from datetime import datetime, timezone

    return int(datetime.now(timezone.utc).timestamp())


__all__ = ["DedupeError", "DynamoDbDedupeStore"]
