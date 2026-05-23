"""Neo4j KG-persist seam for Layer 5 committed batches (R25-EU01 Task 1.6, PR-6).

PR-5 left a seam in the committer: ``Committer(kg_persist=...)`` takes a callback
``Callable[[BatchCommit], None]`` that durably records a committed batch and MUST
raise on failure (so the committer can roll the batch's commit records back). PR-5
shipped a no-op default; PR-6 wires the real thing here.

:class:`Neo4jBatchPersister` is that callback, as a callable class:

    persister = Neo4jBatchPersister(connector)   # connector is a Neo4jConnector
    committer = Committer(config, batcher, anchor, replay_queue, kg_persist=persister)

On first call it ensures the ``:CommittedBatch`` schema exists (idempotent), then
for each batch it MERGEs the batch node and links its records — in one transaction
via :meth:`Neo4jConnector.persist_committed_batch`. The connector is fully
injectable, so this is unit-testable offline with a fake/mock driver (no live
Neo4j) — that is how PR-6 reaches realistic 100% coverage.

Design notes:

* **Composition, not modification** (lesson 20260405T220446): the committer is
  not touched; this is wired purely through the ``kg_persist`` parameter PR-5
  already exposed. The :class:`BatchCommit` → ``:CommittedBatch`` property mapping
  lives here, isolated from both the committer orchestration and the raw Cypher.
* **Raise-on-failure is the contract.** :meth:`__call__` lets any persist error
  propagate as :class:`KgPersistError` so the committer's rollback engages. It
  never swallows — a swallowed persist failure would be a silent KG/Rekor
  divergence, the exact class of bug §8 guards against.
* **Write-once mapping.** Only the immutable commitment fields of a
  :class:`BatchCommit` are mapped; the connector's MERGE + ``ON CREATE SET`` make
  the node write-once on ``batch_id``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from graqle.governance.tamper_evidence.errors import TamperEvidenceError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from graqle.connectors.neo4j import Neo4jConnector
    from graqle.governance.tamper_evidence.committer import BatchCommit

logger = logging.getLogger(__name__)


class KgPersistError(TamperEvidenceError):
    """Raised when a committed batch cannot be persisted to the KG.

    The committer treats any exception from its ``kg_persist`` callback as a
    persist failure and rolls the batch's commit records back (when the batch was
    not yet anchored). Wrapping driver errors in this type makes the failure mode
    explicit and keeps the tamper-evidence error hierarchy uniform.
    """


def batch_commit_to_props(batch: "BatchCommit") -> dict[str, Any]:
    """Project a :class:`BatchCommit` into the ``:CommittedBatch`` property map.

    Maps only the immutable commitment fields (ADR-RT-003 §8.1 example node):
    identity (``batch_id``), the Merkle ``root_hex``, the batch ``size``, the
    commit timestamp, the Rekor anchor identifiers (when anchored), the anchor
    backend, and the proof-format version. ``batch_quarter`` is intentionally
    omitted here and derived by the connector from ``committed_at_iso`` so the
    partition rule lives in exactly one place.

    Anchor fields are included only when the batch was anchored — a
    replay-queued (anchor-deferred) batch has no ``rekor_log_index`` yet, and we
    must not write a null/placeholder that a later reconciliation would have to
    distinguish from a real anchor.
    """
    records = batch.commit_records
    # committed_at_iso: prefer a record's COMMITTED timestamp (all records in a
    # batch share it); fall back to None (connector buckets it as "unknown").
    committed_at_iso: str | None = None
    for cr in records:
        if cr.committed_at_iso is not None:
            committed_at_iso = cr.committed_at_iso
            break

    props: dict[str, Any] = {
        "batch_id": batch.batch_id,
        "root_hex": batch.merkle_root_hex,
        "size": len(records),
        "committed_at_iso": committed_at_iso,
        "anchor_backend": "sigstore_rekor",
        "proof_format_version": "1.0.0",
    }
    if batch.anchored and batch.receipt is not None:
        receipt = batch.receipt
        props["rekor_log_index"] = receipt.log_index
        props["rekor_log_id"] = receipt.log_id
        # Carry the Rekor inclusion cert + signed tree head so the persisted
        # batch node is a self-contained mirror of the anchor (matches the
        # ADR-RT-003 §8.1 example node). getattr-guarded so a receipt shape
        # without these optional fields still persists the core anchor ids.
        cert = getattr(receipt, "inclusion_cert", None)
        if cert is not None:
            props["rekor_inclusion_cert_b64"] = cert
        sth = getattr(receipt, "signed_tree_head", None)
        if sth is not None:
            props["rekor_signed_tree_head_b64"] = sth
    return props


class Neo4jBatchPersister:
    """The PR-5 ``kg_persist`` callback, backed by a :class:`Neo4jConnector`.

    Parameters
    ----------
    connector:
        A :class:`graqle.connectors.neo4j.Neo4jConnector` (or any object exposing
        ``create_committed_batch_schema()`` and
        ``persist_committed_batch(props, record_hashes)``). Injectable so tests
        pass a fake/mock and never touch a live database.
    ensure_schema:
        If ``True`` (default), the ``:CommittedBatch`` schema is created
        idempotently on the first persist. Set ``False`` when the schema is
        managed out-of-band (e.g. by a migration step) to skip the per-process
        ensure.
    """

    def __init__(self, connector: "Neo4jConnector", ensure_schema: bool = True) -> None:
        self._connector = connector
        self._ensure_schema = ensure_schema
        self._schema_ready = False

    def __call__(self, batch: "BatchCommit") -> None:
        """Persist ``batch`` to the KG; raise :class:`KgPersistError` on failure.

        Ensures the schema once (if configured), maps the batch to properties,
        and delegates the single-transaction MERGE to the connector. Any
        underlying error is re-raised as :class:`KgPersistError` so the
        committer's rollback path engages — the failure is never swallowed.
        """
        try:
            if self._ensure_schema and not self._schema_ready:
                self._connector.create_committed_batch_schema()
                self._schema_ready = True
            props = batch_commit_to_props(batch)
            record_hashes = [cr.record_hash for cr in batch.commit_records]
            self._connector.persist_committed_batch(props, record_hashes)
        except KgPersistError:
            # Log the typed failure for the compliance audit trail before
            # re-raising — the committer also logs, but recording it here means
            # the failure is captured even if the committer's handling changes.
            logger.error("KG persist failed for batch %s (typed)", batch.batch_id, exc_info=True)
            raise
        except Exception as exc:  # noqa: BLE001 - wrap-and-propagate by design
            logger.error("KG persist failed for batch %s", batch.batch_id, exc_info=True)
            raise KgPersistError(
                f"failed to persist :CommittedBatch {batch.batch_id} to the KG: {exc}"
            ) from exc

    def backfill_count(self) -> int:
        """Report how many governed records still await a v058_legacy backfill.

        Thin pass-through to :meth:`Neo4jConnector.count_uncommitted_records` so
        a bootstrap/health check can confirm the one-time legacy backfill drained
        to zero. Wrapped so a transient query error is surfaced (not swallowed)
        but typed consistently with the rest of this seam.
        """
        try:
            return self._connector.count_uncommitted_records()
        except Exception as exc:  # noqa: BLE001 - wrap-and-propagate by design
            raise KgPersistError(f"failed to count uncommitted records: {exc}") from exc
