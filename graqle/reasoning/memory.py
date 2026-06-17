"""Governed Epistemic Memory for multi-agent reasoning rounds.

Implements the ReasoningMemory class per provenance-tracked,
clearance-filtered, decay-aware memory with MVCC snapshots and
concurrent merge semantics.

Multi-tenant design (ADR-225, G1 T2):
  Each ReasoningMemory instance is bound to a single tenant at construction
  time.  self._store is a property returning the current tenant's slice of
  self._tenants — isolation by construction, not by filtering discipline.
  On-prem (DEFAULT_TENANT) behaviour is byte-for-byte identical to v0.74.
"""
from __future__ import annotations

import copy
import logging
import os
from typing import Any

from graqle.core.memory_types import ProvenanceEntry, TRACEScores
from graqle.core.results import ToolResult
from graqle.core.tenant import DEFAULT_TENANT, TenantIdError, is_default_tenant, validate_tenant_id
from graqle.core.types import ClearanceLevel

logger = logging.getLogger(__name__)

_MAX_SNAPSHOTS = 10
_SUMMARY_CHAR_CAP = 8000  # ~2000 tokens

# Read once at import time — never per-instance.  Prevents a mid-process
# os.environ mutation from bypassing the tenant-scoping guard on new instances.
# ADR-225: this import-time read is intentional security-by-design; do NOT
# change to a per-call os.environ lookup (that reintroduces a TOCTOU bypass).
_SCOPING_ON: bool = os.environ.get("GRAQLE_TENANT_SCOPING", "").lower() in ("1", "true", "yes")

_REQUIRED_KEYS = [
    "MEMORY_SUMMARY_MAX_CHARS",
    "MEMORY_MIN_CONFIDENCE",
    "EPISTEMIC_DECAY_LAMBDA",
    "CONTRADICTION_PENALTY",
    "REVERIFICATION_THRESHOLD",
]


class TenantScopingDisabledError(ValueError):
    """Raised when a non-DEFAULT tenant_id is used but GRAQLE_TENANT_SCOPING is OFF."""


class TenantMismatchError(ValueError):
    """Raised when a scratch-space entry belongs to a different tenant."""


class ReasoningMemory:
    """Governed Epistemic Memory — provenance-tracked, decay-aware store.

    Every entry carries a :class:`ProvenanceEntry` with TRACE scores,
    clearance level, and Lamport timestamp.  Supports MVCC snapshots
    for safe rollback during adversarial debate rounds.

    All tuneable thresholds are loaded from the *config* dict at
    construction time (internal-pattern-B compliant — no hard-coded policy values).

    Multi-tenant isolation (ADR-225 G1):
      Pass *tenant_id* (pre-hashed: 64-char sha256 hex, ``team-<slug>``, or
      omit for on-prem ``DEFAULT_TENANT``).  The instance sees only its own
      tenant's entries.  Requires ``GRAQLE_TENANT_SCOPING=1`` env var for
      any non-DEFAULT tenant (fail-closed misconfig guard).
    """

    def __init__(self, config: dict[str, Any], tenant_id: str | None = None) -> None:
        missing = [k for k in _REQUIRED_KEYS if k not in config]
        if missing:
            raise ValueError(
                f"ReasoningMemory requires config keys: {missing}. "
                f"internal-pattern-B: these must come from graqle_secrets.yaml, not defaults."
            )
        self._max_chars: int = int(config["MEMORY_SUMMARY_MAX_CHARS"])
        self._min_confidence: float = float(config["MEMORY_MIN_CONFIDENCE"])
        self._decay_lambda: float = float(config["EPISTEMIC_DECAY_LAMBDA"])
        self._contradiction_penalty: float = float(config["CONTRADICTION_PENALTY"])
        self._reverification_threshold: float = float(config["REVERIFICATION_THRESHOLD"])

        # --- Tenant binding (ADR-225 G1 T2) ---
        # Step 1: validate — TenantIdError propagates uncaught (never swallowed).
        # Callers must pass raw, un-normalized input; validate_tenant_id() owns
        # the full normalization pipeline.
        raw = tenant_id if tenant_id is not None else DEFAULT_TENANT
        effective = validate_tenant_id(raw)

        # Step 2: scoping flag check — uses module-level constant, not os.environ.
        if not is_default_tenant(effective) and not _SCOPING_ON:
            raise TenantScopingDisabledError(
                "tenant_id != DEFAULT_TENANT requires GRAQLE_TENANT_SCOPING=1"
            )

        # Step 3: assign after both checks pass.
        self._tenant_id: str = effective
        self._tenants: dict[str, dict[str, ProvenanceEntry]] = {}
        self._epochs_by_tenant: dict[str, list[dict[str, ProvenanceEntry]]] = {}
        self._logical_clock: int = 0

    @property
    def _store(self) -> dict[str, ProvenanceEntry]:
        """Current tenant's entry dict — the ONLY path to tenant data.

        Never cache or memoize this property; rollback() writes directly to
        self._tenants[self._tenant_id] and relies on this property re-fetching.
        """
        assert self._tenant_id is not None, "invariant: _tenant_id must be set before _store access"
        return self._tenants.setdefault(self._tenant_id, {})

    @property
    def _epochs(self) -> list[dict[str, ProvenanceEntry]]:
        """Backward-compat alias: current tenant's epoch list (read-only view).

        Preserves the on-prem invariant — existing tests that read mem._epochs
        continue to work unmodified.  Do NOT mutate the returned list directly;
        use snapshot() / rollback() instead.
        """
        return self._epochs_by_tenant.setdefault(self._tenant_id, [])

    @property
    def entry_count(self) -> int:
        """Number of entries currently in the store (scoped to this tenant)."""
        return len(self._store)

    # ------------------------------------------------------------------
    # 1. store
    # ------------------------------------------------------------------

    def store(
        self,
        round_num: int,
        node_id: str,
        result: ToolResult,
        confidence: float,
        source_agent_id: str,
        trace_scores: TRACEScores | None = None,
    ) -> str:
        """Persist a reasoning result with full provenance.

        Key format: ``'{agent_id}:{round}/{node_id}'``.
        Inherits clearance from *result*.  Detects contradictions when
        a different agent already stored evidence for the same node.

        Returns the storage key.
        """
        self._logical_clock += 1
        key = f"{source_agent_id}:{round_num}/{node_id}"

        clearance = getattr(result, "clearance", ClearanceLevel.PUBLIC)

        # Contradiction detection: same node, different agent (tenant-scoped)
        for existing in self._store.values():
            if (
                existing.node_id == node_id
                and existing.source_agent_id != source_agent_id
            ):
                existing.contradiction_count += 1
                logger.info(
                    "Contradiction detected for node %s between %s and %s",
                    node_id,
                    source_agent_id,
                    existing.source_agent_id,
                )

        entry = ProvenanceEntry(
            value=result.data,
            confidence=confidence,
            confidence_initial=confidence,
            source_agent_id=source_agent_id,
            round_stored=round_num,
            round_verified=round_num,
            node_id=node_id,
            clearance=clearance,
            trace_scores=trace_scores or TRACEScores(),
            tenant_id=self._tenant_id,
        )

        self._store[key] = entry
        logger.debug("Stored entry %s (confidence=%.3f)", key, confidence)
        return key

    # ------------------------------------------------------------------
    # 2. decay_all
    # ------------------------------------------------------------------

    def decay_all(self, current_round: int) -> list[str]:
        """Apply epistemic decay to all entries for the bound tenant.

        Returns keys whose confidence fell below the re-verification
        threshold.

        Note: this method is scoped to the bound tenant only.  Background
        jobs that must decay ALL tenants must iterate self._tenants.keys()
        and call decay_all() on a per-tenant instance (T8 tests cover this).
        """
        needs_reverification: list[str] = []

        for key, entry in self._store.items():
            entry.decay(
                current_round,
                self._decay_lambda,
                self._contradiction_penalty,
            )
            if entry.needs_reverification(self._reverification_threshold):
                needs_reverification.append(key)

        return needs_reverification

    # ------------------------------------------------------------------
    # 3. get_summary
    # ------------------------------------------------------------------

    def get_summary(
        self,
        viewer_clearance: ClearanceLevel,
        current_round: int,
    ) -> str:
        """Return a Markdown digest of memory, filtered by clearance.

        Applies decay first.  Entries above the viewer's clearance are
        **redacted** (not hidden) so the viewer knows they exist.
        Capped at ~2000 tokens (~8000 chars).  Sorted by confidence
        descending; highest-confidence entries appear first.
        """
        self.decay_all(current_round)

        entries = sorted(
            self._store.values(),
            key=lambda e: e.confidence,
            reverse=True,
        )

        lines: list[str] = ["## Prior Findings (from earlier rounds)\n"]
        char_count = len(lines[0])

        for entry in entries:
            if entry.confidence < self._min_confidence:
                continue

            viewed = entry.redacted_for(viewer_clearance)
            value_text = str(viewed.value)[:self._max_chars]

            line = (
                f"- [{viewed.source_agent_id} R{viewed.round_stored}] "
                f"(conf={viewed.confidence:.2f}, "
                f"TRACE={viewed.trace_scores.trace_score:.2f}): "
                f"{value_text}\n"
            )
            if char_count + len(line) > _SUMMARY_CHAR_CAP:
                lines.append("- ... (truncated — more findings available)\n")
                break
            lines.append(line)
            char_count += len(line)

        return "".join(lines)

    # ------------------------------------------------------------------
    # 4. get_weighted
    # ------------------------------------------------------------------

    def get_weighted(self) -> list[ProvenanceEntry]:
        """All entries sorted by confidence descending (tenant-scoped)."""
        return sorted(
            self._store.values(),
            key=lambda e: e.confidence,
            reverse=True,
        )

    # ------------------------------------------------------------------
    # 5. get_by_agent
    # ------------------------------------------------------------------

    def get_by_agent(self, agent_id: str) -> list[ProvenanceEntry]:
        """All entries from a specific agent (tenant-scoped)."""
        return [
            e for e in self._store.values()
            if e.source_agent_id == agent_id
        ]

    # ------------------------------------------------------------------
    # 6. redundancy_rate
    # ------------------------------------------------------------------

    def redundancy_rate(self, current_round_nodes: set[str]) -> float:
        """Fraction of *current_round_nodes* already activated in prior rounds (tenant-scoped)."""
        if not current_round_nodes:
            return 0.0
        prior_nodes = {entry.node_id for entry in self._store.values()}
        overlap = current_round_nodes & prior_nodes
        return len(overlap) / len(current_round_nodes)

    # ------------------------------------------------------------------
    # 7. snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> int:
        """Create an MVCC snapshot of the current tenant's slice via deep copy.

        Returns the epoch number.  Caps at ``_MAX_SNAPSHOTS`` per tenant.

        Concurrency note: NOT thread-safe across concurrent merge_concurrent()
        calls on the same instance.  Callers requiring snapshot + concurrent
        merge must hold an external lock.
        """
        snap = copy.deepcopy(self._store)
        tenant_epochs = self._epochs_by_tenant.setdefault(self._tenant_id, [])
        tenant_epochs.append(snap)

        if len(tenant_epochs) > _MAX_SNAPSHOTS:
            self._epochs_by_tenant[self._tenant_id] = tenant_epochs[-_MAX_SNAPSHOTS:]

        # self._tenant_id is post-validate_tenant_id normalized value (never raw caller input)
        epoch = len(self._epochs_by_tenant[self._tenant_id]) - 1
        logger.debug("Snapshot taken — epoch %d", epoch)
        return epoch

    # ------------------------------------------------------------------
    # 8. rollback
    # ------------------------------------------------------------------

    def rollback(self, epoch: int) -> None:
        """Rollback the current tenant's slice to a previously captured epoch.

        Only restores the bound tenant's data — does NOT replace self._tenants
        wholesale (that would restore other tenants' data from a stale snapshot).

        Raises IndexError for out-of-range epoch (including negative indices).
        Raises IndexError if no snapshot has been taken for this tenant yet.
        """
        tenant_epochs = self._epochs_by_tenant.get(self._tenant_id)
        if not tenant_epochs:
            raise IndexError(
                f"Epoch {epoch} not found — no snapshots recorded for this tenant"
            )
        if epoch < 0 or epoch >= len(tenant_epochs):
            raise IndexError(
                f"Epoch {epoch} not found (available: 0–{len(tenant_epochs) - 1})"
            )
        restored = copy.deepcopy(tenant_epochs[epoch])
        # Post-restore integrity check: every entry must belong to this tenant.
        for entry in restored.values():
            if entry.tenant_id != self._tenant_id:
                raise TenantMismatchError(
                    "rollback aborted — cross-tenant data detected in epoch"
                )
        self._tenants[self._tenant_id] = restored
        logger.info("Rolled back to epoch %d", epoch)

    # ------------------------------------------------------------------
    # 9. merge_concurrent
    # ------------------------------------------------------------------

    def merge_concurrent(
        self,
        scratch_spaces: list[dict[str, ProvenanceEntry]],
    ) -> None:
        """Merge concurrent agent writes into the current tenant's store.

        Conflicting keys are resolved by highest TRACE composite score.
        Losers are preserved under ``DISSENT:{key}``.

        Every entry in every scratch space must carry a tenant_id matching
        self._tenant_id (canonicalized).  Raises TenantMismatchError on any
        mismatch — never silently merges foreign-tenant data.
        """
        for scratch in scratch_spaces:
            for key, entry in scratch.items():
                # Tenant-identity guard: validate + canonicalize before compare.
                if not hasattr(entry, "tenant_id") or entry.tenant_id is None:
                    raise TenantMismatchError(
                        f"scratch entry {key!r} missing tenant_id — possible privilege escalation"
                    )
                try:
                    canonical = validate_tenant_id(entry.tenant_id)
                except TenantIdError as exc:
                    raise TenantMismatchError(
                        f"scratch entry {key!r} has invalid tenant_id"
                    ) from exc
                if canonical != self._tenant_id:
                    raise TenantMismatchError(
                        f"scratch entry {key!r} belongs to a different tenant"
                    )

                if key not in self._store:
                    self._store[key] = entry
                    continue

                existing = self._store[key]

                new_score = entry.trace_scores.trace_score
                existing_score = existing.trace_scores.trace_score

                if new_score > existing_score:
                    self._store[f"DISSENT:{key}"] = existing
                    self._store[key] = entry
                    logger.debug("Merge conflict on %s — new entry wins", key)
                else:
                    self._store[f"DISSENT:{key}"] = entry
                    logger.debug("Merge conflict on %s — existing entry wins", key)
