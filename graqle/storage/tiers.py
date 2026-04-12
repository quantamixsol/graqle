"""Read-only storage tier facade with runtime enforcement.

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

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


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


class StorageTierInvariantError(RuntimeError):
    """Raised when the storage tier invariant is violated at runtime."""


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
            name="Tier 0 \u2014 Local JSON",
            role="primary",
            status=status,
            detail=detail,
        )

    def _read_backends_yaml(self) -> dict:
        """Read backends: section from graqle.yaml, or empty dict on failure."""
        if yaml is None:
            return {}
        yaml_path = self.project_dir / "graqle.yaml"
        if not yaml_path.exists():
            return {}
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            return data.get("backends", {})
        except Exception:
            return {}

    def tier1_neo4j(self) -> TierDescriptor:
        disabled_value = os.getenv("NEO4J_DISABLED", "")
        if disabled_value.lower() in _NEO4J_DISABLED_VALUES:
            detail = "Disabled by NEO4J_DISABLED environment variable."
            status = TierStatus.DISABLED
        else:
            # Phase 3: check backends.neo4j.enabled in graqle.yaml
            backends = self._read_backends_yaml()
            neo4j_cfg = backends.get("neo4j", {})
            if neo4j_cfg.get("enabled", False):
                uri = neo4j_cfg.get("uri", "bolt://localhost:7687")
                detail = f"Enabled via backends.neo4j (uri={uri})."
                status = TierStatus.ACTIVE
            else:
                detail = "Projection available via Graqle.to_neo4j."
                status = TierStatus.OPT_IN_AVAILABLE
        return TierDescriptor(
            name="Tier 1A \u2014 Neo4j (local, opt-in)",
            role="projection",
            status=status,
            detail=detail,
        )

    def tier1_neptune(self) -> TierDescriptor:
        # Phase 3: check backends.neptune.enabled in graqle.yaml first
        backends = self._read_backends_yaml()
        neptune_cfg = backends.get("neptune", {})
        if neptune_cfg.get("enabled", False):
            endpoint = neptune_cfg.get("endpoint", os.getenv("NEPTUNE_ENDPOINT", ""))
            detail = f"Enabled via backends.neptune (endpoint={endpoint})."
            status = TierStatus.ACTIVE
        else:
            endpoint = os.getenv("NEPTUNE_ENDPOINT", "")
            if endpoint:
                detail = f"Projection available to Neptune endpoint: {endpoint}"
                status = TierStatus.OPT_IN_AVAILABLE
            else:
                detail = "NEPTUNE_ENDPOINT not configured."
                status = TierStatus.NOT_CONFIGURED
        return TierDescriptor(
            name="Tier 1B \u2014 Neptune (hosted, opt-in)",
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
        if primary_tiers[0].name != "Tier 0 \u2014 Local JSON":
            return False, "Primary tier must be named 'Tier 0 \u2014 Local JSON'."
        return True, "OK"

    def effective_primary(self) -> TierDescriptor:
        """Return effective runtime primary tier, accounting for graqle.yaml override.

        If graqle.yaml sets graph.connector to neo4j or neptune, this returns
        a TierDescriptor with DISABLED status and a MISMATCH detail — surfacing
        the contradiction between declared primary (always Tier 0) and runtime
        behavior (loads from the configured connector first).
        """
        if yaml is None:
            return self.tier0()
        yaml_path = self.project_dir / "graqle.yaml"
        if not yaml_path.exists():
            return self.tier0()
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except Exception:
            return self.tier0()
        connector = str((data.get("graph") or {}).get("connector", "networkx")).lower()
        if connector in ("neo4j", "neptune"):
            return TierDescriptor(
                name="Tier 0 \u2014 Local JSON",
                role="primary",
                status=TierStatus.DISABLED,
                detail=(
                    f"MISMATCH: graqle.yaml graph.connector={connector} overrides "
                    f"Tier 0. Runtime loads from {connector} first."
                ),
            )
        return self.tier0()

    def has_override(self) -> bool:
        """Returns True if graqle.yaml graph.connector overrides Tier 0."""
        return self.effective_primary().status != self.tier0().status

    def enforce(self, strict: bool = False) -> tuple[bool, str]:
        """Enforce the storage tier invariant.

        Checks: (1) invariant_check passes, (2) Tier 0 is ACTIVE,
        (3) no graph.connector override in graqle.yaml.

        Returns (True, 'OK') on success. On failure: raises
        StorageTierInvariantError if strict=True, else returns (False, reason).
        """
        ok, reason = self.invariant_check()
        if not ok:
            if strict:
                raise StorageTierInvariantError(reason)
            return False, reason
        t0 = self.tier0()
        if t0.status != TierStatus.ACTIVE:
            reason = f"Tier 0 graqle.json is not active: {t0.detail}"
            if strict:
                raise StorageTierInvariantError(reason)
            return False, reason
        if self.has_override():
            reason = self.effective_primary().detail
            if strict:
                raise StorageTierInvariantError(reason)
            return False, reason
        return True, "OK"
