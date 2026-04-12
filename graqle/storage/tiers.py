"""Read-only storage tier facade.

Invariant: Tier 0 (graqle.json) is the single source of truth for ALL users
regardless of plan; Tier 1A (Neo4j local) and Tier 1B (Neptune hosted) are
opt-in projections, never primary. This module has no network calls, no LLM
calls, no side effects, and is safe to call from doctor.py.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class TierStatus(str, Enum):
    ACTIVE = "active"
    OPT_IN_AVAILABLE = "opt_in_available"
    DISABLED = "disabled"
    NOT_CONFIGURED = "not_configured"


@dataclass(frozen=True)
class TierDescriptor:
    """Descriptor for a storage tier."""

    name: str
    role: str
    status: TierStatus
    detail: str


_NEO4J_DISABLED_VALUES = ("1", "true", "yes", "on")


class StorageTiers:
    def __init__(self, project_dir: Path | None = None):
        self.project_dir = project_dir if project_dir is not None else Path.cwd()

    def tier0(self) -> TierDescriptor:
        graqle_json = self.project_dir / "graqle.json"
        if graqle_json.exists():
            size_bytes = graqle_json.stat().st_size
            detail = f"{graqle_json} exists ({size_bytes} bytes)."
            status = TierStatus.ACTIVE
        else:
            detail = f"{graqle_json} not found; run 'graq scan repo .' to create it."
            status = TierStatus.NOT_CONFIGURED
        return TierDescriptor(
            name="Tier 0 — Local JSON",
            role="primary",
            status=status,
            detail=detail,
        )

    def tier1_neo4j(self) -> TierDescriptor:
        disabled_value = os.getenv("NEO4J_DISABLED", "")
        if disabled_value.lower() in _NEO4J_DISABLED_VALUES:
            detail = "Disabled by NEO4J_DISABLED gate)."
            status = TierStatus.DISABLED
        else:
            detail = "Projection available via Graqle.to_neo4j."
            status = TierStatus.OPT_IN_AVAILABLE
        return TierDescriptor(
            name="Tier 1A — Neo4j (local, opt-in)",
            role="projection",
            status=status,
            detail=detail,
        )

    def tier1_neptune(self) -> TierDescriptor:
        endpoint = os.getenv("NEPTUNE_ENDPOINT", "")
        if endpoint:
            detail = f"Projection available to Neptune endpoint: {endpoint}"
            status = TierStatus.OPT_IN_AVAILABLE
        else:
            detail = "NEPTUNE_ENDPOINT not configured."
            status = TierStatus.NOT_CONFIGURED
        return TierDescriptor(
            name="Tier 1B — Neptune (hosted, opt-in)",
            role="projection",
            status=status,
            detail=detail,
        )

    def all(self) -> list[TierDescriptor]:
        return [self.tier0(), self.tier1_neo4j(), self.tier1_neptune()]

    def invariant_check(self) -> tuple[bool, str]:
        tiers = self.all()
        primary_tiers = [tier for tier in tiers if tier.role == "primary"]
        if len(primary_tiers) != 1:
            return False, "Expected exactly one primary tier."
        if primary_tiers[0].name != "Tier 0 — Local JSON":
            return False, "Primary tier must be named 'Tier 0 — Local JSON'."
        return True, "OK"
