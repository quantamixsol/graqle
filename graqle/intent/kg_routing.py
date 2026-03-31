"""KG Node-Type Routing — R6 Component 3: Hypothesis validation.

Validates whether knowledge-graph node types predict the correct tool
routing, using mutual information over a contingency table built from
historical correction records.
"""

# ── graqle:intelligence ──
# module: graqle.intent.kg_routing
# risk: LOW (impact radius: 1 module)
# consumers: intent_engine, r6_validation
# dependencies: __future__, collections, logging, math, typing, graqle.intent.types
# constraints: MI threshold 0.15 for routing recommendation
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import math
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from graqle.intent.types import CorrectionRecord

logger = logging.getLogger("graqle.intent.kg_routing")

# ---------------------------------------------------------------------------
# Routing hypotheses: node_type → hypothesized best tool
# ---------------------------------------------------------------------------

ROUTING_HYPOTHESES: Dict[str, str] = {
    "PRODUCT": "graq_reason",
    "ENTITY": "graq_reason",
    "FUNCTION": "graq_impact",
    "METHOD": "graq_impact",
    "DOCUMENT": "graq_context",
    "SECTION": "graq_context",
    "KNOWLEDGE": "graq_reason",
}


# ---------------------------------------------------------------------------
# Mutual information
# ---------------------------------------------------------------------------

def compute_mutual_information(contingency: Dict[str, Dict[str, int]]) -> float:
    """Compute mutual information from a contingency table.

    Standard MI formula:
        MI = Σ_{x,y} p(x,y) * log2( p(x,y) / (p(x) * p(y)) )

    Zero-count cells are safely skipped.

    Parameters
    ----------
    contingency:
        Nested dict ``{row_label: {col_label: count, ...}, ...}``.

    Returns
    -------
    float
        Mutual information in bits (log base 2).
    """
    total = 0
    row_totals: Dict[str, int] = defaultdict(int)
    col_totals: Dict[str, int] = defaultdict(int)

    for row, cols in contingency.items():
        for col, count in cols.items():
            total += count
            row_totals[row] += count
            col_totals[col] += count

    if total == 0:
        return 0.0

    mi = 0.0
    for row, cols in contingency.items():
        for col, count in cols.items():
            if count == 0:
                continue
            p_xy = count / total
            p_x = row_totals[row] / total
            p_y = col_totals[col] / total
            if p_x > 0 and p_y > 0:
                mi += p_xy * math.log2(p_xy / (p_x * p_y))

    return mi


# ---------------------------------------------------------------------------
# Hypothesis validation
# ---------------------------------------------------------------------------

def validate_hypothesis(
    corrections: List[CorrectionRecord],
    min_samples: int = 30,
) -> Dict[str, Any]:
    """Validate KG node-type routing hypotheses against correction data.

    Parameters
    ----------
    corrections:
        Historical correction records with ``activated_node_types``
        and ``corrected_tool`` fields.
    min_samples:
        Minimum number of records required for statistical validity.

    Returns
    -------
    dict
        Validation results including MI score, per-hypothesis precision,
        and a routing recommendation.
    """
    if len(corrections) < min_samples:
        logger.info(
            "Insufficient data for hypothesis validation: %d < %d",
            len(corrections),
            min_samples,
        )
        return {"status": "insufficient_data"}

    # Build contingency table: dominant_node_type × corrected_tool
    contingency: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for record in corrections:
        if not record.activated_node_types:
            continue
        dominant = Counter(record.activated_node_types).most_common(1)[0][0]
        contingency[dominant][record.corrected_tool] += 1

    mi = compute_mutual_information(dict(contingency))
    logger.info("KG routing hypothesis MI=%.4f", mi)

    # Per-hypothesis precision
    hypothesis_precision: Dict[str, Optional[float]] = {}
    for node_type, predicted_tool in ROUTING_HYPOTHESES.items():
        row = contingency.get(node_type, {})
        total = sum(row.values())
        if total > 0:
            correct = row.get(predicted_tool, 0)
            hypothesis_precision[node_type] = round(correct / total, 4)
        else:
            hypothesis_precision[node_type] = None

    supported = mi > 0.15
    return {
        "mutual_information": round(mi, 4),
        "hypothesis_supported": supported,
        "hypothesis_precision": hypothesis_precision,
        "recommendation": (
            "enable_kg_routing" if supported
            else "kg_routing_unreliable_use_rules_only"
        ),
    }
