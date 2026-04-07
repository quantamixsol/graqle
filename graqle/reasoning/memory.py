"""Governed Epistemic Memory for multi-agent reasoning rounds.

Implements the ReasoningMemory class per ADR-146: provenance-tracked,
clearance-filtered, decay-aware memory with MVCC snapshots and
concurrent merge semantics.
"""
from __future__ import annotations

import copy
import logging
from typing import Any

from graqle.core.memory_types import ProvenanceEntry, TRACEScores
from graqle.core.results import ToolResult
from graqle.core.types import ClearanceLevel

logger = logging.getLogger(__name__)

_MAX_SNAPSHOTS = 10
_SUMMARY_CHAR_CAP = 8000  # ~2000 tokens

_REQUIRED_KEYS = [
    "MEMORY_SUMMARY_MAX_CHARS",
    "MEMORY_MIN_CONFIDENCE",
    "EPISTEMIC_DECAY_LAMBDA",
    "CONTRADICTION_PENALTY",
    "REVERIFICATION_THRESHOLD",
]


class ReasoningMemory:
    """Governed Epistemic Memory — provenance-tracked, decay-aware store.

    Every entry carries a :class:`ProvenanceEntry` with TRACE scores,
    clearance level, and Lamport timestamp.  Supports MVCC snapshots
    for safe rollback during adversarial debate rounds.

    All tuneable thresholds are loaded from the *config* dict at
    construction time (TS-2 compliant — no hard-coded policy values).
    See ADR-146 for design rationale.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        missing = [k for k in _REQUIRED_KEYS if k not in config]
        if missing:
            raise ValueError(
                f"ReasoningMemory requires config keys: {missing}. "
                f"TS-2: these must come from graqle_secrets.yaml, not defaults."
            )
        self._max_chars: int = int(config["MEMORY_SUMMARY_MAX_CHARS"])
        self._min_confidence: float = float(config["MEMORY_MIN_CONFIDENCE"])
        self._decay_lambda: float = float(config["EPISTEMIC_DECAY_LAMBDA"])
        self._contradiction_penalty: float = float(config["CONTRADICTION_PENALTY"])
        self._reverification_threshold: float = float(config["REVERIFICATION_THRESHOLD"])

        self._store: dict[str, ProvenanceEntry] = {}
        self._epochs: list[dict[str, ProvenanceEntry]] = []
        self._logical_clock: int = 0

    @property
    def entry_count(self) -> int:
        """Number of entries currently in the store."""
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

        # Contradiction detection: same node, different agent
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
        )

        self._store[key] = entry
        logger.debug("Stored entry %s (confidence=%.3f)", key, confidence)
        return key

    # ------------------------------------------------------------------
    # 2. decay_all
    # ------------------------------------------------------------------

    def decay_all(self, current_round: int) -> list[str]:
        """Apply epistemic decay to all entries.

        Returns keys whose confidence fell below the re-verification
        threshold.
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
        """All entries sorted by confidence descending."""
        return sorted(
            self._store.values(),
            key=lambda e: e.confidence,
            reverse=True,
        )

    # ------------------------------------------------------------------
    # 5. get_by_agent
    # ------------------------------------------------------------------

    def get_by_agent(self, agent_id: str) -> list[ProvenanceEntry]:
        """All entries from a specific agent."""
        return [
            e for e in self._store.values()
            if e.source_agent_id == agent_id
        ]

    # ------------------------------------------------------------------
    # 6. redundancy_rate
    # ------------------------------------------------------------------

    def redundancy_rate(self, current_round_nodes: set[str]) -> float:
        """Fraction of *current_round_nodes* already activated in prior rounds."""
        if not current_round_nodes:
            return 0.0
        prior_nodes = {entry.node_id for entry in self._store.values()}
        overlap = current_round_nodes & prior_nodes
        return len(overlap) / len(current_round_nodes)

    # ------------------------------------------------------------------
    # 7. snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> int:
        """Create an MVCC snapshot via deep copy.

        Returns the epoch number.  Caps at ``_MAX_SNAPSHOTS``.
        """
        snap = copy.deepcopy(self._store)
        self._epochs.append(snap)

        if len(self._epochs) > _MAX_SNAPSHOTS:
            self._epochs = self._epochs[-_MAX_SNAPSHOTS:]

        epoch = len(self._epochs) - 1
        logger.debug("Snapshot taken — epoch %d", epoch)
        return epoch

    # ------------------------------------------------------------------
    # 8. rollback
    # ------------------------------------------------------------------

    def rollback(self, epoch: int) -> None:
        """Rollback to a previously captured epoch snapshot."""
        if epoch < 0 or epoch >= len(self._epochs):
            raise IndexError(
                f"Epoch {epoch} not found (available: 0–{len(self._epochs) - 1})"
            )
        self._store = copy.deepcopy(self._epochs[epoch])
        logger.info("Rolled back to epoch %d", epoch)

    # ------------------------------------------------------------------
    # 9. merge_concurrent
    # ------------------------------------------------------------------

    def merge_concurrent(
        self,
        scratch_spaces: list[dict[str, ProvenanceEntry]],
    ) -> None:
        """Merge concurrent agent writes into the main store.

        Conflicting keys are resolved by highest TRACE composite score.
        Losers are preserved under ``DISSENT:{key}``.
        """
        for scratch in scratch_spaces:
            for key, entry in scratch.items():
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
