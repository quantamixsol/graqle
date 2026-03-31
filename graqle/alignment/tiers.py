"""R10 Embedding Space Alignment — five-tier classification."""

# ── graqle:intelligence ──
# module: graqle.alignment.tiers
# risk: LOW (impact radius: 2 modules)
# consumers: alignment.measurement, alignment.pipeline
# dependencies: __future__, typing
# constraints: threshold values are classification ranges, not proprietary calibration
# ── /graqle:intelligence ──

from __future__ import annotations

from typing import Any, Dict


# ---------------------------------------------------------------------------
# Alignment tier definitions
# ---------------------------------------------------------------------------

ALIGNMENT_TIERS: Dict[str, Dict[str, Any]] = {
    "GREEN": {
        "range": (0.85, 1.00),
        "label": "Well-Aligned",
        "action": "No correction needed. Cross-KG activation scores are directly comparable.",
        "description": (
            "Embeddings occupy similar regions despite language differences. "
            "The model captures functional equivalence through description text."
        ),
    },
    "BLUE": {
        "range": (0.70, 0.85),
        "label": "Acceptably Aligned",
        "action": "Monitor. Apply correction if federated activation shows ranking anomalies.",
        "description": (
            "Embeddings are close enough for most queries. Edge cases may surface "
            "where cross-KG ranking disagrees with ground truth."
        ),
    },
    "YELLOW": {
        "range": (0.55, 0.70),
        "label": "Misaligned — Correction Recommended",
        "action": "Run diagnostic protocol. Apply lightest sufficient correction.",
        "description": (
            "Embeddings diverge enough to cause false negatives in cross-KG activation. "
            "Federated queries will miss relevant nodes from the distant KG."
        ),
    },
    "RED": {
        "range": (0.40, 0.55),
        "label": "Severely Misaligned",
        "action": "Correction required before enabling federated activation.",
        "description": (
            "Embeddings are in substantially different regions. Cross-KG scores are "
            "not comparable. Federated merge will produce misleading rankings."
        ),
    },
    "GRAY": {
        "range": (0.00, 0.40),
        "label": "Unrelated / Broken",
        "action": "Investigate. Likely a bug in description generation or embedding pipeline.",
        "description": (
            "Embeddings are nearly orthogonal. Either the descriptions are wrong, "
            "the embeddings are from different models, or the edge is a false positive."
        ),
    },
}


def classify_alignment_tier(cosine_sim: float) -> str:
    """Classify a cosine similarity score into an alignment tier.

    Returns the tier name (GREEN, BLUE, YELLOW, RED, or GRAY).
    Falls back to GRAY for negative cosine similarity values.
    """
    for tier_name, tier_info in ALIGNMENT_TIERS.items():
        low, high = tier_info["range"]
        if low <= cosine_sim <= high:
            return tier_name
    return "GRAY"
