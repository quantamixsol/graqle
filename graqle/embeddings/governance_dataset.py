"""R23 GSEFT: governance contrastive dataset builder (ADR-206).

Builds (anchor, positive, negative) triplets from the KG for contrastive training.
Dataset construction deferred: requires curated governance node labels (R24).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Deferred training marker
# ---------------------------------------------------------------------------
# GSEFT_TRAINING_DEFERRED: dataset curation milestone not yet reached (R24).
# When R24 completes, replace this constant with actual dataset loading logic.
GSEFT_TRAINING_DEFERRED = True


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
