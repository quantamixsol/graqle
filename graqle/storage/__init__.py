"""Storage tier facade for the GraQle SDK. Tier 0 (graqle.json on disk) is the single source of truth for ALL users regardless of plan. Tier 1A (Neo4j local, opt-in) and Tier 1B (Neptune hosted, opt-in) are projections/replicas of Tier 0, never primary. This package provides a read-only facade for inspecting which tiers are active."""

from graqle.storage.tiers import (
    StorageTiers,
    TierDescriptor,
    TierStatus,
)

__all__ = ['StorageTiers', 'TierDescriptor', 'TierStatus']
