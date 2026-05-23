"""Audit-log v3: commit-status sidecar over the v2 governed trace (R25-EU01 PR-5).

The v2 audit record is :class:`graqle.governance.trace_schema.GovernedTrace` —
the system of record for every governed tool call (schema_version ``"2"`` since
cr-017). That model is ``ConfigDict(extra="forbid")``: its field set is frozen,
and adding Layer-5 commit fields directly to it would be a breaking schema change
touching every reader.

Audit-log **v3** therefore composes ALONGSIDE v2 rather than mutating it: a
:class:`CommitRecord` is a *sidecar* that references a trace by id and carries
only the cryptographic-commit lifecycle — which batch the trace's record landed
in, when it was committed, and (crucially) its :class:`CommitStatus`. The trace
stays exactly as v2 wrote it; v3 is a separate, joinable record.

**No-silent-drop invariant.** :class:`CommitStatus` makes the fate of every
submitted record explicit and total — a record is always in exactly one of:

    PENDING        enqueued to the batcher, not yet flushed
    COMMITTED      in a flushed batch with a Merkle root (root proven locally)
    ANCHORED       the batch root is anchored in Rekor (externally proven)
    REPLAY_QUEUED  Rekor was unreachable; root durably queued for later anchor
    FAILED         a terminal, surfaced failure (operator must act)

There is no "unknown" / "lost" state: a record that leaves ``submit()`` is
tracked to one of these, and the committer never silently discards one (the
AC-9 lineage from PR-4's replay queue).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID


class CommitStatus(str, Enum):
    """The total, explicit set of commit-lifecycle states (no-silent-drop).

    Ordered loosely by progression: PENDING -> COMMITTED -> ANCHORED is the
    happy path; REPLAY_QUEUED is the Rekor-unavailable branch (still progressing
    toward ANCHORED on a later drain); FAILED is terminal and operator-surfaced.
    """

    PENDING = "pending"
    COMMITTED = "committed"
    ANCHORED = "anchored"
    REPLAY_QUEUED = "replay_queued"
    FAILED = "failed"


# Terminal states: no further automatic transition is expected from these.
# COMMITTED and REPLAY_QUEUED are NON-terminal (a later anchor/drain advances
# them to ANCHORED). PENDING is non-terminal (a flush advances it).
_TERMINAL = frozenset({CommitStatus.ANCHORED, CommitStatus.FAILED})


@dataclass
class CommitRecord:
    """An audit-log v3 sidecar binding a governed trace to its commit lifecycle.

    Joinable to the v2 :class:`GovernedTrace` via ``trace_id``. Carries only the
    Layer-5 commit fields, so the v2 record is never mutated.

    Attributes
    ----------
    trace_id:
        The ``id`` of the :class:`GovernedTrace` this commit pertains to.
    record_hash:
        SHA-256 (hex) content-address of the governed record that entered the
        batch — the batcher's idempotency key, so a CommitRecord is joinable to
        the exact leaf as well as the trace.
    commit_status:
        The current :class:`CommitStatus`. Starts at PENDING.
    batch_id:
        The batch this record was committed in (set at COMMITTED).
    merkle_root_hex:
        The batch's Merkle root, lowercase hex (set at COMMITTED).
    rekor_log_index / rekor_log_id:
        Rekor inclusion-cert identifiers (set at ANCHORED).
    committed_at_iso / anchored_at_iso:
        UTC ISO-8601 timestamps for the COMMITTED / ANCHORED transitions.
    error:
        Failure detail (set at FAILED).
    schema_version:
        The audit-log generation. ``"3"`` for these sidecar records.
    """

    trace_id: UUID
    record_hash: str
    commit_status: CommitStatus = CommitStatus.PENDING
    batch_id: str | None = None
    merkle_root_hex: str | None = None
    rekor_log_index: int | None = None
    rekor_log_id: str | None = None
    committed_at_iso: str | None = None
    anchored_at_iso: str | None = None
    error: str | None = None
    schema_version: str = "3"

    # -- transitions (each is explicit; none drops the record) --------------

    def mark_committed(self, batch_id: str, merkle_root_hex: str) -> None:
        """PENDING -> COMMITTED: the record's batch was flushed with a root."""
        self.commit_status = CommitStatus.COMMITTED
        self.batch_id = batch_id
        self.merkle_root_hex = merkle_root_hex
        self.committed_at_iso = _utc_now_iso()

    def mark_anchored(self, rekor_log_index: int, rekor_log_id: str) -> None:
        """COMMITTED -> ANCHORED: the batch root is in Rekor (externally proven)."""
        self.commit_status = CommitStatus.ANCHORED
        self.rekor_log_index = rekor_log_index
        self.rekor_log_id = rekor_log_id
        self.anchored_at_iso = _utc_now_iso()

    def mark_replay_queued(self, batch_id: str, merkle_root_hex: str) -> None:
        """-> REPLAY_QUEUED: Rekor unreachable; root durably queued for later.

        Sets the batch identity too (the record IS committed locally with a
        root; only the external anchor is deferred), so a later drain can
        advance it to ANCHORED.
        """
        self.commit_status = CommitStatus.REPLAY_QUEUED
        self.batch_id = batch_id
        self.merkle_root_hex = merkle_root_hex
        if self.committed_at_iso is None:
            self.committed_at_iso = _utc_now_iso()

    def mark_failed(self, error: str) -> None:
        """-> FAILED: a terminal, surfaced failure (operator must act)."""
        self.commit_status = CommitStatus.FAILED
        self.error = error[:1000]

    @property
    def is_terminal(self) -> bool:
        """True if no further automatic transition is expected (ANCHORED/FAILED)."""
        return self.commit_status in _TERMINAL

    def snapshot(self) -> dict[str, Any]:
        """Capture the FULL mutable state for an exact rollback.

        Returns every commit-lifecycle field (not just status), so a failed batch
        can be restored byte-for-byte to its pre-batch state — restoring only the
        status would leave stale ``batch_id`` / root / anchor fields on a
        rolled-back record (a real inconsistency caught in PR-5 review).
        """
        return {
            "commit_status": self.commit_status,
            "batch_id": self.batch_id,
            "merkle_root_hex": self.merkle_root_hex,
            "rekor_log_index": self.rekor_log_index,
            "rekor_log_id": self.rekor_log_id,
            "committed_at_iso": self.committed_at_iso,
            "anchored_at_iso": self.anchored_at_iso,
            "error": self.error,
        }

    def restore(self, snap: dict[str, Any]) -> None:
        """Restore the full mutable state captured by :meth:`snapshot`."""
        self.commit_status = snap["commit_status"]
        self.batch_id = snap["batch_id"]
        self.merkle_root_hex = snap["merkle_root_hex"]
        self.rekor_log_index = snap["rekor_log_index"]
        self.rekor_log_id = snap["rekor_log_id"]
        self.committed_at_iso = snap["committed_at_iso"]
        self.anchored_at_iso = snap["anchored_at_iso"]
        self.error = snap["error"]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for the append-only audit store / KG."""
        return {
            "schema_version": self.schema_version,
            "trace_id": str(self.trace_id),
            "record_hash": self.record_hash,
            "commit_status": self.commit_status.value,
            "batch_id": self.batch_id,
            "merkle_root_hex": self.merkle_root_hex,
            "rekor_log_index": self.rekor_log_index,
            "rekor_log_id": self.rekor_log_id,
            "committed_at_iso": self.committed_at_iso,
            "anchored_at_iso": self.anchored_at_iso,
            "error": self.error,
        }


def _utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string with a trailing Z."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
