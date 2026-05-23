"""Committer orchestrator for Layer 5 tamper-evidence (R25-EU01 Task 1.5).

The committer is the seam that ties the Layer-5 pieces together into one
non-blocking commit lifecycle, while keeping the governed-trace write path
(R18 / trace_capture) completely undisturbed:

    submit(record)                      # non-blocking: enqueue + track PENDING
        -> WalBatcher.enqueue (PR-3)    # durable WAL, content-addressed
    on batcher flush (size/time):
        -> MerkleTree over the batch    # PR-2/PR-3 (built by the batcher)
        -> RekorAnchor.anchor (PR-4)    # external transparency-log anchor
              success     -> mark ANCHORED
              AnchorError -> LocalReplayQueue.enqueue (PR-4) -> mark REPLAY_QUEUED
        -> persist (batch_id, root, rekor_cert) to the KG    # batched MERGE (PR-6 wires Neo4j)

Design choices (PR-5 INVESTIGATE, blast-radius MEDIUM):

* **Composition, not modification.** trace_capture.py is a 47-dependency hub; the
  committer does NOT restructure it. Instead it is wired in as a *minimal additive
  observer*: :meth:`as_trace_observer` returns a callback that ``TraceCapture``
  invokes (best-effort) after a trace is finalized. A committer failure therefore
  can never break the governed-trace path — the trace is the system of record;
  the cryptographic commit is downstream.
* **No-silent-drop.** Every submitted record gets a :class:`CommitRecord` whose
  :class:`CommitStatus` is always one of PENDING/COMMITTED/ANCHORED/
  REPLAY_QUEUED/FAILED. A record is never lost: if anchoring fails it is
  REPLAY_QUEUED (durably), and a hard failure is FAILED (surfaced), never dropped.
* **Batched persist + rollback.** The per-batch KG persist is staged and applied
  as a unit; on persist failure the staged commit records roll back to their
  pre-batch status so there is no partial commit. (The Neo4j ``:CommittedBatch``
  MERGE itself lands in PR-6; PR-5 stages the data + status and exposes a
  ``kg_persist`` callback seam.)
* **Fully injectable** (batcher, anchor, replay_queue, kg_persist, clock) so the
  whole lifecycle is unit-testable offline — no network, no Neo4j.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable

from graqle.config.attestation_config import AttestationConfig
from graqle.governance.tamper_evidence.anchors.sigstore_rekor import (
    AnchorError,
    RekorAnchor,
    RekorReceipt,
)
from graqle.governance.tamper_evidence.audit_log_v3 import (
    CommitRecord,
    CommitStatus,
)
from graqle.governance.tamper_evidence.batcher import WalBatcher
from graqle.governance.tamper_evidence.errors import TamperEvidenceError
from graqle.governance.tamper_evidence.local_replay_queue import LocalReplayQueue
from graqle.governance.tamper_evidence.merkle import MerkleTree, leaf_hash_for_record

logger = logging.getLogger(__name__)

# A KG-persist callback receives the committed (batch_id, root_hex, receipt-or-None,
# commit_records) and durably records them. PR-6 wires the Neo4j :CommittedBatch
# MERGE behind this seam; until then a no-op default is used. It MUST raise on
# failure so the committer can roll the batch's commit records back.
KgPersistFn = Callable[["BatchCommit"], None]


class CommitterError(TamperEvidenceError):
    """Raised for committer-orchestration failures that cannot proceed safely."""


@dataclass(frozen=True)
class BatchCommit:
    """The result of committing one batch: identity, root, anchor, and records."""

    batch_id: str
    merkle_root_hex: str
    receipt: RekorReceipt | None  # None when REPLAY_QUEUED (anchor deferred)
    commit_records: list[CommitRecord]
    anchored: bool


def _record_hash(record: dict[str, Any]) -> str:
    """Content-address of a governed record == its Merkle leaf hash, hex.

    Matches the batcher's idempotency key derivation conceptually (both are
    content-addressed), and ties a CommitRecord to its exact leaf.
    """
    return leaf_hash_for_record(record).hex()


class Committer:
    """Orchestrates record -> batch -> Merkle root -> Rekor anchor (or replay queue).

    Parameters
    ----------
    config:
        Layer 5 attestation config (passed through to the batcher).
    batcher:
        A :class:`WalBatcher`. If omitted, the caller must inject one; the
        committer installs ITS OWN flush handler as the batcher's committer
        callback, so do not also pass a committer callback to the batcher.
    anchor:
        A :class:`RekorAnchor` (or compatible). Optional: without one, batches
        are committed locally (COMMITTED) but not anchored.
    replay_queue:
        A :class:`LocalReplayQueue` for the Rekor-unavailable fallback. Optional:
        without one, an anchor failure marks records FAILED instead of
        REPLAY_QUEUED (degraded, but still no silent drop).
    kg_persist:
        Callback to durably persist a :class:`BatchCommit` (PR-6 Neo4j seam).
        Must raise on failure (triggers rollback). Defaults to a no-op.
    """

    def __init__(
        self,
        config: AttestationConfig,
        batcher: WalBatcher,
        anchor: RekorAnchor | None = None,
        replay_queue: LocalReplayQueue | None = None,
        kg_persist: KgPersistFn | None = None,
    ) -> None:
        self._config = config
        self._batcher = batcher
        self._anchor = anchor
        self._replay_queue = replay_queue
        self._kg_persist = kg_persist
        self._lock = threading.RLock()
        # Commit records keyed by content-address (the batcher's idempotency key),
        # so a record submitted twice maps to one CommitRecord (mirrors the
        # batcher's content-addressed dedup). This is the no-silent-drop ledger.
        self._records: dict[str, CommitRecord] = {}
        # Batch ids whose KG mirror failed AFTER a durable Rekor anchor. The
        # anchor is authoritative; these are deferred for out-of-band KG
        # reconciliation rather than re-anchored (which would orphan the anchor).
        self._kg_persist_pending: list[str] = []
        # Wire our flush handler in as the batcher's committer callback.
        self._batcher._committer = self._on_batch_flush  # type: ignore[attr-defined]

    # ---- public API -----------------------------------------------------------

    def submit(self, record: dict[str, Any], trace_id: Any = None) -> CommitRecord:
        """Non-blocking: enqueue ``record`` for commit and track it PENDING.

        Returns the :class:`CommitRecord` (PENDING, or its current status if the
        same record was already submitted — content-addressed, so a re-submit is
        idempotent). The heavy work (Merkle build + anchor) happens later when
        the batcher flushes, via :meth:`_on_batch_flush`.
        """
        from uuid import UUID, uuid4

        if not isinstance(record, dict):
            raise CommitterError(
                f"record must be a dict, got {type(record).__name__}"
            )
        rhash = _record_hash(record)
        with self._lock:
            existing = self._records.get(rhash)
            if existing is not None:
                return existing  # idempotent: same content already tracked
            tid = trace_id if isinstance(trace_id, UUID) else uuid4()
            cr = CommitRecord(trace_id=tid, record_hash=rhash, commit_status=CommitStatus.PENDING)
            self._records[rhash] = cr
            # Enqueue AFTER tracking so a flush triggered inline by enqueue (when
            # the size ceiling is hit) already sees this record's CommitRecord.
            self._batcher.enqueue(record)
            return cr

    def flush(self) -> int:
        """Force a batcher flush now; returns the number of records committed."""
        return self._batcher.flush()

    def commit_record_for(self, record: dict[str, Any]) -> CommitRecord | None:
        """Look up the tracked :class:`CommitRecord` for ``record`` (or None)."""
        with self._lock:
            return self._records.get(_record_hash(record))

    def status_counts(self) -> dict[str, int]:
        """A census of commit statuses across all tracked records (observability)."""
        counts: dict[str, int] = {s.value: 0 for s in CommitStatus}
        with self._lock:
            for cr in self._records.values():
                counts[cr.commit_status.value] += 1
        return counts

    def as_trace_observer(self) -> Callable[[Any], None]:
        """Return a best-effort observer callback for ``TraceCapture``.

        The callback extracts a committable record from a finalized
        :class:`GovernedTrace` and submits it. It NEVER raises: the governed
        trace path must not be affected by a committer error (the hook in
        trace_capture wraps this defensively too, but we belt-and-suspenders it
        here). Returns quickly — the actual commit work is deferred to flush.
        """

        def _observe(trace: Any) -> None:
            try:
                record = _trace_to_record(trace)
                if record is not None:
                    self.submit(record, trace_id=getattr(trace, "id", None))
            except Exception:  # never break the trace path
                logger.warning("committer trace-observer failed (non-fatal)", exc_info=True)

        return _observe

    # ---- batch flush handler (invoked by the batcher) -------------------------

    @staticmethod
    def _new_batch_id() -> str:
        """A fresh batch identifier from a CSPRNG.

        ``secrets.token_hex`` makes the cryptographically-secure source explicit
        for this tamper-evidence context (uuid4 is already urandom-backed in
        CPython, but the intent should not depend on that implementation detail).
        The batch_id is an identifier, not a secret — the cryptographic strength
        of the commitment lives in the Merkle root + Rekor anchor — but a
        collision-resistant, unpredictable id is still the right default here.
        """
        import secrets

        return secrets.token_hex(16)

    def _on_batch_flush(self, records: list[dict[str, Any]], tree: MerkleTree) -> None:
        """Batcher committer callback: anchor the batch root, advance statuses.

        Invoked by :class:`WalBatcher` with the flushed records + their Merkle
        tree. Order is load-bearing:

        1. mint a batch_id + read the root;
        2. mark every record COMMITTED (root proven locally);
        3. attempt the Rekor anchor:
             success      -> mark ANCHORED;
             AnchorError  -> enqueue the root to the replay queue, mark
                             REPLAY_QUEUED (or FAILED if no queue);
        4. persist the BatchCommit to the KG (batched). On persist failure, roll
           the batch's commit records back to PENDING so nothing is half-committed
           — the batcher then leaves the WAL intact (it re-raises on our raise),
           and the next flush retries the whole batch.

        Raising from here propagates to the batcher, which (by its contract)
        leaves the WAL entries in place for retry — so a persist failure never
        loses a record.

        Locking note: this runs under ``self._lock`` and that lock is held across
        the anchor call (which may sleep on retry backoff). That is intentional —
        the batcher already serializes flush against ``enqueue`` at its own lock,
        and the anchor's retry budget is bounded — so concurrent ``submit`` calls
        briefly wait during a flush rather than racing the ``_records`` ledger.
        """
        with self._lock:
            batch_id = self._new_batch_id()
            root_hex = tree.root_hex
            batch_records = [self._track(r) for r in records]

            # Snapshot the FULL pre-batch state of each record for an exact
            # rollback (status alone is insufficient — see _kg_persist failure
            # path; restoring only status would leave stale batch/root/anchor
            # fields on a rolled-back record).
            snapshot = [(cr, cr.snapshot()) for cr in batch_records]

            for cr in batch_records:
                cr.mark_committed(batch_id, root_hex)

            receipt: RekorReceipt | None = None
            anchored = False
            if self._anchor is not None:
                try:
                    receipt = self._anchor.anchor(tree.root)
                    for cr in batch_records:
                        cr.mark_anchored(receipt.log_index, receipt.log_id)
                    anchored = True
                except AnchorError as exc:
                    self._handle_anchor_failure(batch_id, root_hex, batch_records, exc)

            batch = BatchCommit(
                batch_id=batch_id,
                merkle_root_hex=root_hex,
                receipt=receipt,
                commit_records=list(batch_records),
                anchored=anchored,
            )

            if self._kg_persist is not None:
                try:
                    self._kg_persist(batch)
                except Exception as exc:
                    self._handle_persist_failure(batch_id, batch_records, snapshot, anchored, exc)

    def _handle_persist_failure(
        self,
        batch_id: str,
        batch_records: list[CommitRecord],
        snapshot: list[tuple[CommitRecord, dict[str, Any]]],
        anchored: bool,
        exc: Exception,
    ) -> None:
        """Resolve a KG-persist failure WITHOUT ever causing a double-anchor.

        The Rekor anchor (when it happened) is PERMANENT and immutable — it
        cannot be rolled back. So the resolution depends on whether the batch was
        already anchored (graq_predict failure-chain #2):

        * **Not anchored** (anchor disabled, or it failed → REPLAY_QUEUED/FAILED):
          nothing irreversible happened, so roll the records back to their full
          pre-batch state and re-raise. The batcher keeps the WAL intact and the
          whole batch is retried cleanly.

        * **Anchored**: the cryptographic commitment is already durable in Rekor.
          Re-flushing would re-anchor the SAME root under a NEW batch_id,
          orphaning the first anchor — so we must NOT re-raise. The records stay
          ANCHORED (no-silent-drop: they ARE committed+anchored), the batcher
          clears the WAL, and the failed KG mirror is recorded in
          ``_kg_persist_pending`` for out-of-band reconciliation (it is surfaced,
          never dropped). The KG row is a downstream mirror of the authoritative
          Rekor anchor, so deferring it is safe.
        """
        if not anchored:
            for cr, snap in snapshot:
                cr.restore(snap)
            raise CommitterError(
                f"KG persist failed for unanchored batch {batch_id}; rolled back "
                f"{len(batch_records)} record(s) for clean retry: {exc}"
            ) from exc
        # Anchored: keep records ANCHORED, defer the KG mirror, do NOT re-anchor.
        self._kg_persist_pending.append(batch_id)
        logger.error(
            "KG persist failed for ALREADY-ANCHORED batch %s; records remain "
            "ANCHORED (Rekor commitment is durable), KG mirror deferred for "
            "reconciliation. NOT re-raising (would double-anchor). cause: %s",
            batch_id, exc,
        )

    @property
    def kg_persist_pending(self) -> list[str]:
        """Batch ids whose KG mirror failed AFTER a durable anchor (reconcile out-of-band)."""
        with self._lock:
            return list(self._kg_persist_pending)

    # ---- helpers --------------------------------------------------------------

    def _track(self, record: dict[str, Any]) -> CommitRecord:
        """Return the CommitRecord for ``record``, creating a PENDING one if absent.

        A record can reach the flush handler without a prior submit() only via
        crash-recovery (the batcher drains its WAL on startup and flushes records
        that were never re-submitted through the committer). Such a record still
        gets a CommitRecord here — no-silent-drop covers the recovery path too.
        """
        from uuid import uuid4

        rhash = _record_hash(record)
        cr = self._records.get(rhash)
        if cr is None:
            cr = CommitRecord(trace_id=uuid4(), record_hash=rhash, commit_status=CommitStatus.PENDING)
            self._records[rhash] = cr
        return cr

    def _handle_anchor_failure(
        self, batch_id: str, root_hex: str, batch_records: list[CommitRecord], exc: AnchorError
    ) -> None:
        """Rekor anchor failed: queue for replay (or mark FAILED if no queue)."""
        if self._replay_queue is not None:
            try:
                self._replay_queue.enqueue(root_hex, batch_id, metadata={"reason": "anchor_failed"})
                for cr in batch_records:
                    cr.mark_replay_queued(batch_id, root_hex)
                logger.warning(
                    "Rekor anchor failed for batch %s; root queued for replay: %s",
                    batch_id, exc,
                )
                return
            except Exception as queue_exc:  # queue itself failed -> surface FAILED
                for cr in batch_records:
                    cr.mark_failed(f"anchor + replay-queue both failed: {queue_exc}")
                logger.error(
                    "Rekor anchor AND replay-queue failed for batch %s: anchor=%s queue=%s",
                    batch_id, exc, queue_exc,
                )
                return
        # No replay queue configured: do not silently drop — mark FAILED.
        for cr in batch_records:
            cr.mark_failed(f"anchor failed and no replay queue configured: {exc}")
        logger.error("Rekor anchor failed for batch %s, no replay queue: %s", batch_id, exc)


def _trace_to_record(trace: Any) -> dict[str, Any] | None:
    """Project a finalized GovernedTrace into a committable leaf-input record.

    Returns the minimal leaf-hash-input record (the frozen LEAF_HASH_FIELDS
    shape from PR-1) derived from the trace, or None if the trace lacks the
    fields needed to form a record. Kept defensive: the observer must tolerate
    any trace shape without raising.
    """
    import hashlib
    import json as _json

    trace_id = getattr(trace, "id", None)
    if trace_id is None:
        return None
    # content_hash binds the committed record to the trace's salient content.
    try:
        basis = _json.dumps(
            {
                "tool_name": getattr(trace, "tool_name", None),
                "query": getattr(trace, "query", None),
                "outcome": getattr(getattr(trace, "outcome", None), "value", None),
            },
            sort_keys=True,
            default=str,
        )
    except (TypeError, ValueError):
        logger.debug("could not derive a commit record from trace %s; skipping", trace_id)
        return None
    content_hash = hashlib.sha256(basis.encode("utf-8")).hexdigest()
    timestamp = getattr(trace, "timestamp", None)
    ts_unix = int(timestamp.timestamp()) if timestamp is not None else 0
    return {
        "proof_format_version": "1.0.0",
        "record_id": str(trace_id),
        "content_hash": content_hash,
        "timestamp_unix": ts_unix,
        "governance_metadata": {
            "schema_version": getattr(trace, "schema_version", "2"),
            "outcome": getattr(getattr(trace, "outcome", None), "value", None),
        },
    }
