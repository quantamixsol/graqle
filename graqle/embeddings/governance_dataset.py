"""R23 GSEFT: governance contrastive dataset builder (ADR-206).

Builds (anchor, positive, negative) triplets from the KG for contrastive training.
Dataset construction deferred: requires curated governance node labels (R24).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Deferred training marker
# ---------------------------------------------------------------------------
# B3 fix: env-injectable so R24 can flip without a code change.
# Default True (deferred) unless GRAQLE_GSEFT_TRAINING_ENABLED=1 is set.
GSEFT_TRAINING_DEFERRED: bool = os.environ.get("GRAQLE_GSEFT_TRAINING_ENABLED", "0") != "1"


@dataclass
class GovernanceTriplet:
    anchor: str
    positive: str
    negative: str
    anchor_node_id: str = ""
    label: str = ""


class GovernanceDataset:
    """Contrastive triplet dataset for governance embedding fine-tuning.

    Usage::

        ds = GovernanceDataset.from_kg(kg_nodes)
        for triplet in ds.iter_triplets():
            ...
    """

    def __init__(self, triplets: list[GovernanceTriplet]) -> None:
        self._triplets = triplets

    @classmethod
    def from_kg(cls, kg_nodes: list[dict[str, Any]]) -> GovernanceDataset:
        """Build triplets from KG node list.

        Deferred until R24: returns empty dataset with a runtime warning.
        """
        if GSEFT_TRAINING_DEFERRED:
            import warnings
            warnings.warn(
                "GovernanceDataset.from_kg: GSEFT training deferred (R24 milestone). "
                "Returning empty dataset.",
                stacklevel=2,
            )
            return cls([])
        # R24 implementation placeholder — replace with actual triplet mining
        raise NotImplementedError("GovernanceDataset.from_kg not yet implemented (R24)")

    def __len__(self) -> int:
        return len(self._triplets)

    def iter_triplets(self) -> Iterator[GovernanceTriplet]:
        yield from self._triplets
