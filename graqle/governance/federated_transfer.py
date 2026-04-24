# ------------------------------------------------------------------
# PATENT NOTICE -- Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Applications EP26162901.8, EP26166054.2, EP26167849.4 (composite),
# owned by Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: support@quantamixsolutions.com
# ------------------------------------------------------------------

"""Privacy-Preserving Federated Transfer Engine (R21 ADR-204).

Orchestrates the full cross-org pattern transfer pipeline:
    1. Find candidate source patterns from the registry
    2. Compute similarity against the target org's context
    3. Gate on sim(A, B) >= threshold
    4. Verify privacy pre-adaptation
    5. Adapt patterns to target org mapping tables
    6. Verify privacy post-adaptation
    7. Record auditable transfer log

Privacy invariant: zero raw data crosses the org boundary.

Network effect: V(N) = O(N^2) -- value grows quadratically with org count.

TS-2 Gate: Transfer decision logic is core IP.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from graqle.governance.adaptation import (
    AdaptationError,
    AdaptationResult,
    TargetOrgContext,
    adapt_pattern,
)
from graqle.governance.pattern_abstractor import AbstractPattern, verify_privacy
from graqle.governance.pattern_registry import PatternRegistry
from graqle.governance.similarity import (
    DEFAULT_TRANSFER_THRESHOLD,
    SimilarityScore,
    SimilarityWeights,
    compute_similarity,
)

logger = logging.getLogger("graqle.governance.federated_transfer")

_DEFAULT_AUDIT_DIR = ".graqle/transfers"


class TransferRecord(BaseModel):
    """Audit log entry for a single transfer attempt."""

    model_config = ConfigDict(extra="forbid")

    transfer_id: str = Field(default_factory=lambda: f"xfer-{uuid4().hex[:12]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_pattern_id: str
    source_org_hash: str
    target_org_hash: str
    similarity_total: float
    similarity_domain: float
    similarity_stack: float
    similarity_governance: float
    threshold: float
    gated: bool  # True = passed similarity gate
    adapted: bool  # True = adaptation succeeded
    privacy_verified_pre: bool
    privacy_verified_post: bool
    adapted_pattern_id: str | None = None
    unmapped_gates: list[str] = Field(default_factory=list)
    unmapped_clearances: list[str] = Field(default_factory=list)
    error: str | None = None


class TransferResult(BaseModel):
    """Full result of a transfer attempt."""

    model_config = ConfigDict(extra="forbid")

    record: TransferRecord
    adapted_pattern: AbstractPattern | None = None


class PrivacyViolation(Exception):
    """Raised when a privacy verification fails during transfer."""


class FederatedTransferEngine:
    """Orchestrates privacy-preserving cross-org pattern transfer.

    Usage::

        engine = FederatedTransferEngine(registry=PatternRegistry())
        results = await engine.transfer(
            target_pattern=my_org_pattern,
            target_context=my_target_context,
            trace_class="reasoning",
            threshold=0.6,
        )
        # results: list of TransferResult, one per successful transfer
    """

    def __init__(
        self,
        registry: PatternRegistry | None = None,
        audit_dir: str | Path | None = None,
    ) -> None:
        self._registry = registry or PatternRegistry()
        if audit_dir is None:
            audit_dir = _DEFAULT_AUDIT_DIR
        self._audit_dir = Path(audit_dir)
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        self._transfer_count = 0

    @property
    def transfer_count(self) -> int:
        return self._transfer_count

    @property
    def audit_dir(self) -> Path:
        return self._audit_dir

    async def transfer(
        self,
        target_pattern: AbstractPattern,
        target_context: TargetOrgContext,
        trace_class: str | None = None,
        threshold: float = DEFAULT_TRANSFER_THRESHOLD,
        weights: SimilarityWeights | None = None,
        max_sources: int = 20,
    ) -> list[TransferResult]:
        """Find candidate source patterns and transfer those that qualify.

        Parameters
        ----------
        target_pattern:
            Abstract pattern representing the target org's own governance fingerprint.
            Used for similarity matching and origin exclusion.
        target_context:
            Target org mapping tables (gate/clearance/tool).
        trace_class:
            Optional filter for candidate source patterns.
        threshold:
            Minimum total similarity for transfer to proceed.
        weights:
            Override default similarity weights.
        max_sources:
            Maximum candidate sources to evaluate.

        Returns
        -------
        List of TransferResult — one per candidate (including gated-out).
        Only results with adapted=True have adapted_pattern populated.
        """
        effective_class = trace_class or target_pattern.trace_class
        candidates = self._registry.find_matches(
            trace_class=effective_class,
            exclude_org_hash=target_context.org_hash,
            limit=max_sources,
        )

        results: list[TransferResult] = []
        for source in candidates:
            result = await self._transfer_one(
                source=source,
                target_pattern=target_pattern,
                target_context=target_context,
                threshold=threshold,
                weights=weights,
            )
            results.append(result)
            self._transfer_count += 1

        return results

    async def _transfer_one(
        self,
        source: AbstractPattern,
        target_pattern: AbstractPattern,
        target_context: TargetOrgContext,
        threshold: float,
        weights: SimilarityWeights | None,
    ) -> TransferResult:
        """Transfer a single source pattern through the full pipeline."""
        score = compute_similarity(source, target_pattern, weights=weights, threshold=threshold)

        # Pre-adaptation privacy check
        pre_ok = verify_privacy(source)

        record = TransferRecord(
            source_pattern_id=source.pattern_id,
            source_org_hash=source.source_org_hash,
            target_org_hash=target_context.org_hash,
            similarity_total=score.total,
            similarity_domain=score.domain,
            similarity_stack=score.stack,
            similarity_governance=score.governance,
            threshold=threshold,
            gated=score.meets_threshold,
            adapted=False,
            privacy_verified_pre=pre_ok,
            privacy_verified_post=False,
        )

        # Gate: similarity threshold
        if not score.meets_threshold:
            record.error = f"below_threshold: {score.total:.3f} < {threshold}"
            await self._write_audit(record)
            return TransferResult(record=record)

        # Gate: pre-adaptation privacy
        if not pre_ok:
            record.error = "pre_privacy_verification_failed"
            await self._write_audit(record)
            return TransferResult(record=record)

        # Adapt
        try:
            adaptation = adapt_pattern(source, target_context)
        except AdaptationError as e:
            record.error = f"adaptation_failed: {str(e)[:200]}"
            record.unmapped_gates = []  # adaptation error keeps details internal
            await self._write_audit(record)
            return TransferResult(record=record)

        # Post-adaptation privacy (already verified inside adapt_pattern, re-verify)
        post_ok = verify_privacy(adaptation.adapted_pattern)
        record.privacy_verified_post = post_ok
        record.unmapped_gates = adaptation.unmapped_gates
        record.unmapped_clearances = adaptation.unmapped_clearances

        if not post_ok:
            record.error = "post_privacy_verification_failed"
            await self._write_audit(record)
            return TransferResult(record=record)

        record.adapted = True
        record.adapted_pattern_id = adaptation.adapted_pattern.pattern_id

        await self._write_audit(record)
        return TransferResult(record=record, adapted_pattern=adaptation.adapted_pattern)

    async def _write_audit(self, record: TransferRecord) -> None:
        """Append an audit record. Hash-only, no raw payload content."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        file_path = self._audit_dir / f"{today}.jsonl"
        line = json.dumps(record.model_dump(mode="json"), default=str) + "\n"

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._sync_append, file_path, line)

    @staticmethod
    def _sync_append(file_path: Path, line: str) -> None:
        fd = os.open(str(file_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)

    def read_audit(
        self,
        date: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Read transfer audit entries for a given date (default: today)."""
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        file_path = self._audit_dir / f"{date}.jsonl"
        if not file_path.exists():
            return []
        records: list[dict[str, Any]] = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records[-limit:][::-1]
