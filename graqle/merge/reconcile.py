"""R2 Bridge-Edge Reconciliation — ADR-133.

Deduplicates and reconciles bridge edge candidates from
BridgeDetectionReport, resolving conflicts by dedup key,
confidence score, method priority, and cross-language semantics.
"""

# ── graqle:intelligence ──
# module: graqle.merge.reconcile
# risk: LOW (impact radius: 2 modules)
# consumers: merge.pipeline, mcp_dev_server
# dependencies: __future__, dataclasses, logging, graqle.analysis.bridge
# constraints: ADR-133 R2 bridge validation protocol
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from graqle.analysis.bridge import BridgeCandidate, make_dedup_key

logger = logging.getLogger(__name__)

# Method-based source priority — lower value wins on confidence tie.
_METHOD_PRIORITY: dict[str, int] = {
    "exact_name": 0,
    "token_overlap": 1,
}

_DEFAULT_PRIORITY = 99


@dataclass
class ReconciliationReport:
    """Result of bridge-edge reconciliation.

    Attributes:
        accepted: Deduplicated candidates that survived reconciliation.
        merged: Candidates that were merged/deduped (losers).
        stats: Per-method counts of accepted candidates.
    """

    accepted: list[BridgeCandidate] = field(default_factory=list)
    merged: list[BridgeCandidate] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


@runtime_checkable
class _HasCandidates(Protocol):
    candidates: list[BridgeCandidate]


class BridgeReconciler:
    """Deduplicate and reconcile bridge edge candidates.

    Resolution rules (applied per dedup-key bucket):
    1. Pick the candidate with the highest ``confidence``.
    2. On confidence tie, prefer the method with lower
       ``_METHOD_PRIORITY`` (``exact_name`` > ``token_overlap``).
    3. Cross-language conflicts (same target from both Python and JS
       sources) are detected and logged; resolution follows the same
       confidence/method-priority chain. The losing candidate is
       recorded in ``merged``.

    Parameters:
        report: A ``BridgeDetectionReport`` (or any object exposing a
            ``.candidates`` list of :class:`BridgeCandidate`).
    """

    def __init__(self, report: _HasCandidates) -> None:
        self._report = report

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reconcile(self) -> ReconciliationReport:
        """Run deduplication and return a :class:`ReconciliationReport`."""
        if not hasattr(self._report, "candidates"):
            logger.warning(
                "report missing .candidates attribute; returning empty ReconciliationReport",
            )
            return ReconciliationReport()

        candidates: list[BridgeCandidate] = list(self._report.candidates)

        if not candidates:
            logger.debug("reconcile: no candidates to process")
            return ReconciliationReport()

        # 1. Group by dedup key (with error isolation for malformed candidates)
        buckets: dict[str, list[BridgeCandidate]] = {}
        skipped: list[BridgeCandidate] = []
        for cand in candidates:
            try:
                key = make_dedup_key(cand)
            except Exception as exc:
                logger.warning("Skipping malformed candidate %r: %s", cand, exc)
                skipped.append(cand)
                continue
            buckets.setdefault(key, []).append(cand)

        accepted: list[BridgeCandidate] = []
        merged: list[BridgeCandidate] = []

        for key, group in buckets.items():
            # 2. Detect cross-language conflicts for logging
            if len(group) > 1:
                languages: set[str] = {c.language for c in group if c.language}
                if len(languages) > 1:
                    logger.debug(
                        "Cross-language conflict for key=%s languages=%s",
                        key,
                        sorted(languages),
                    )

            # 3. Pick winner: highest confidence, then method priority
            winner = self._pick_winner(group)
            accepted.append(winner)

            winner_idx = group.index(winner)
            for i, cand in enumerate(group):
                if i != winner_idx:
                    merged.append(cand)

        # 4. Build per-method stats
        stats: dict[str, int] = {}
        for c in accepted:
            method = c.method or "unknown"
            stats[method] = stats.get(method, 0) + 1

        logger.info(
            "Reconciliation complete: %d accepted, %d merged from %d total",
            len(accepted),
            len(merged),
            len(candidates),
        )

        return ReconciliationReport(
            accepted=accepted,
            merged=merged,
            stats=stats,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pick_winner(group: list[BridgeCandidate]) -> BridgeCandidate:
        """Select the best candidate from a dedup-key bucket.

        Sorting key ``(-confidence, method_priority)`` so highest
        confidence wins first, then lowest method priority breaks ties.
        """
        if len(group) == 1:
            return group[0]

        return min(
            group,
            key=lambda c: (
                -(c.confidence or 0.0),
                _METHOD_PRIORITY.get(c.method or "", _DEFAULT_PRIORITY),
                c.source_id or "",
            ),
        )
