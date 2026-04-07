"""MCP node reclassification — batch pass converting generic Entity/Function nodes to typed MCP nodes.

ADR-128 Phase 3: Reclassification functions are designed to be called via
Graqle.reclassify_batch() which provides atomic copy-on-write execution.
The functions here intentionally mutate the already-copied node dicts in-place.
Pattern-match rules (first-match-wins) with explicit confidence-descending ordering.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("graqle.scanner.reclassify_mcp")

# Reclassification rules — first match wins, ordered by confidence descending.
# Use re.search for substring/keyword rules, re.match only for ^-anchored prefixes.
# NOTE: Confidence values are loaded from private config (TS-2 compliance).
# See: ADR-129, ADR-130 — hardcoded values were flagged as trade secret exposure.

def _load_confidence_values() -> dict[str, float]:
    """Load reclassification confidence values from private config.

    Falls back to opaque defaults if config not found.
    Values are proprietary calibration outputs (TS-2) and must
    NEVER be hardcoded in source files committed to public repos.
    """
    import os
    config_path = os.path.join(
        os.path.dirname(__file__), "..", "..", ".graqle", "reclassify_confidence.json"
    )
    try:
        import json
        with open(config_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Environment variable override
    env_val = os.environ.get("GRAQLE_RECLASSIFY_CONFIDENCE")
    if env_val:
        try:
            import json
            return json.load(env_val) if isinstance(env_val, str) else {}
        except Exception:
            pass

    # Opaque defaults — values intentionally not visible in source
    # Actual calibrated values should be in .graqle/reclassify_confidence.json
    return {
        "MCP_TOOL": 0.9,
        "MCP_TRANSPORT": 0.9,
        "MCP_SERVER": 0.9,
        "MCP_CLIENT": 0.9,
        "MCP_REQUEST": 0.8,
        "MCP_RESPONSE": 0.8,
        "MCP_NOTIFICATION": 0.8,
    }


_CONFIDENCE = _load_confidence_values()

RECLASSIFICATION_RULES: tuple[dict[str, Any], ...] = (
    {
        "pattern": re.compile(r"^graq_|^kogni_", re.IGNORECASE),
        "from_types": ["Entity", "Function"],
        "to_type": "MCP_TOOL",
        "confidence": _CONFIDENCE.get("MCP_TOOL", 0.9),
        "evidence": "name prefix matches TOOL_REGISTRY",
        "match_fn": "match",  # anchored prefix
    },
    {
        "pattern": re.compile(r"\bstdio\b|\bsse\b|\btransport\b", re.IGNORECASE),
        "from_types": ["Entity", "Config"],
        "to_type": "MCP_TRANSPORT",
        "confidence": _CONFIDENCE.get("MCP_TRANSPORT", 0.9),
        "evidence": "name matches transport keywords",
        "match_fn": "search",  # substring with word boundaries
    },
    {
        "pattern": re.compile(r".*[Ss]erver$|mcp_server", re.IGNORECASE),
        "from_types": ["Entity", "Class"],
        "to_type": "MCP_SERVER",
        "confidence": _CONFIDENCE.get("MCP_SERVER", 0.9),
        "evidence": "name matches server pattern",
        "match_fn": "search",
    },
    {
        "pattern": re.compile(r".*[Cc]lient$|mcp_client", re.IGNORECASE),
        "from_types": ["Entity", "Class"],
        "to_type": "MCP_CLIENT",
        "confidence": _CONFIDENCE.get("MCP_CLIENT", 0.9),
        "evidence": "name matches client pattern",
        "match_fn": "search",
    },
    {
        "pattern": re.compile(r"[_.]request$|Request$", re.IGNORECASE),
        "from_types": ["Entity"],
        "to_type": "MCP_REQUEST",
        "confidence": _CONFIDENCE.get("MCP_REQUEST", 0.8),
        "evidence": "name suffix indicates JSON-RPC request",
        "match_fn": "search",
    },
    {
        "pattern": re.compile(r"[_.]response$|Response$", re.IGNORECASE),
        "from_types": ["Entity"],
        "to_type": "MCP_RESPONSE",
        "confidence": _CONFIDENCE.get("MCP_RESPONSE", 0.8),
        "evidence": "name suffix indicates JSON-RPC response",
        "match_fn": "search",
    },
    {
        "pattern": re.compile(r"notification", re.IGNORECASE),
        "from_types": ["Entity"],
        "to_type": "MCP_NOTIFICATION",
        "confidence": _CONFIDENCE.get("MCP_NOTIFICATION", 0.8),
        "evidence": "name contains notification pattern",
        "match_fn": "search",
    },
)

# Enforce confidence-descending ordering at module load (raise, not assert — safe under -O)
if not all(
    RECLASSIFICATION_RULES[i]["confidence"] >= RECLASSIFICATION_RULES[i + 1]["confidence"]
    for i in range(len(RECLASSIFICATION_RULES) - 1)
):
    raise RuntimeError(
        "RECLASSIFICATION_RULES must be ordered by confidence descending. "
        "This invariant is required for first-match semantics."
    )


def _match_rule(node_data: dict[str, Any]) -> dict[str, Any] | None:
    """Find the first matching reclassification rule for a node.

    Returns the matched rule dict, or ``None`` if no rule applies.
    Handles None/missing label safely (returns None, no crash).
    """
    entity_type = node_data.get("entity_type", "")
    label = node_data.get("label") or node_data.get("name") or ""
    if not label:
        return None

    for rule in RECLASSIFICATION_RULES:
        if entity_type not in rule["from_types"]:
            continue
        compiled = rule["pattern"]
        if rule["match_fn"] == "match":
            if compiled.match(label):
                return rule
        else:
            if compiled.search(label):
                return rule
    return None


def make_reclassify_fn() -> tuple[Callable[[dict[str, Any]], None], dict[str, Any]]:
    """Create a reclassification function and stats tracker for use with
    ``Graqle.reclassify_batch()``.

    Returns:
        A ``(reclassify_fn, stats_dict)`` tuple.  The function mutates
        *node_data* dicts in-place; *stats_dict* is populated during
        execution. NOT thread-safe — reclassify_batch() calls it serially.
    """
    stats: dict[str, Any] = {"reclassified": 0, "skipped": 0, "by_type": {}}

    def reclassify_fn(node_data: dict[str, Any]) -> None:
        rule = _match_rule(node_data)
        if rule is None:
            stats["skipped"] += 1
            return

        old_type = node_data.get("entity_type", "")
        new_type: str = rule["to_type"]

        # Skip if already correctly typed
        if old_type == new_type:
            stats["skipped"] += 1
            return

        # Reclassify
        node_data["entity_type"] = new_type
        node_data["domain"] = "mcp"
        node_data["reclassification_confidence"] = rule["confidence"]
        node_data["reclassification_source"] = rule["evidence"]
        node_data["reclassification_from"] = old_type

        stats["reclassified"] += 1
        stats["by_type"][new_type] = stats["by_type"].get(new_type, 0) + 1

        logger.debug(
            "Reclassified %s: %s -> %s (confidence=%.2f)",
            node_data.get("label", "?"),
            old_type,
            new_type,
            rule["confidence"],
        )

    return reclassify_fn, stats
