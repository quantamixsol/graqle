"""Contradiction detection — find conflicting information across sources.

When merging finds conflicting data, flag it:
- Numeric mismatch: config says 3600, doc says "30 minutes"
- Boolean mismatch: code has strict=True, config has strict=false
- Semantic conflict: ADR says "JWT", onboarding doc says "session auth"

This is one of the highest-value features — finding stale docs nobody
knew were wrong.
"""

# ── graqle:intelligence ──
# module: graqle.scanner.dedup.contradictions
# risk: LOW (impact radius: 1 modules)
# consumers: test_contradictions
# dependencies: __future__, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from typing import Any


def detect_contradictions(
    nodes: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Scan nodes for cross-source contradictions.

    Looks for nodes that share a label/key but have different values
    across different source types.

    Returns a list of contradiction dicts.
    """
    contradictions: list[dict[str, Any]] = []

    # Group nodes by normalised label
    label_groups: dict[str, list[dict]] = {}
    for nid, node in nodes.items():
        label = node.get("label", "").lower().strip()
        if not label or len(label) < 3:
            continue
        label_groups.setdefault(label, []).append(node)

    for label, group in label_groups.items():
        if len(group) < 2:
            continue

        # Check for value mismatches in properties
        for i, node_a in enumerate(group):
            for node_b in group[i + 1:]:
                type_a = _source_type(node_a)
                type_b = _source_type(node_b)
                if type_a == type_b:
                    continue

                # Compare shared property keys
                props_a = node_a.get("properties", {})
                props_b = node_b.get("properties", {})

                for key in set(props_a) & set(props_b):
                    if key in ("source", "path", "merge_sources", "merge_method",
                               "merge_confidence", "classification_confidence",
                               "classification_reason"):
                        continue

                    val_a = props_a[key]
                    val_b = props_b[key]

                    if val_a == val_b:
                        continue

                    # Numeric mismatch
                    if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
                        if val_a != val_b:
                            contradictions.append({
                                "type": "numeric_mismatch",
                                "label": label,
                                "key": key,
                                "value_a": val_a,
                                "value_b": val_b,
                                "source_a": f"{node_a.get('id', '')} ({type_a})",
                                "source_b": f"{node_b.get('id', '')} ({type_b})",
                            })

                    # Boolean mismatch
                    elif isinstance(val_a, bool) and isinstance(val_b, bool):
                        contradictions.append({
                            "type": "boolean_mismatch",
                            "label": label,
                            "key": key,
                            "value_a": val_a,
                            "value_b": val_b,
                            "source_a": f"{node_a.get('id', '')} ({type_a})",
                            "source_b": f"{node_b.get('id', '')} ({type_b})",
                        })

                    # String mismatch (only if both are short strings)
                    elif (isinstance(val_a, str) and isinstance(val_b, str)
                          and len(val_a) < 100 and len(val_b) < 100
                          and val_a.lower() != val_b.lower()):
                        contradictions.append({
                            "type": "value_mismatch",
                            "label": label,
                            "key": key,
                            "value_a": val_a,
                            "value_b": val_b,
                            "source_a": f"{node_a.get('id', '')} ({type_a})",
                            "source_b": f"{node_b.get('id', '')} ({type_b})",
                        })

    return contradictions


def _source_type(node: dict) -> str:
    """Classify source type of a node."""
    etype = node.get("entity_type", "").upper()
    props = node.get("properties", {})
    source = props.get("source", "")

    if etype in ("FUNCTION", "CLASS", "MODULE", "PYTHONMODULE"):
        return "code"
    if etype == "ENDPOINT":
        return "api_spec"
    if etype in ("DEPENDENCY", "SCRIPT", "CONFIG", "TOOL_RULE", "RESOURCE"):
        return "json_config"
    if etype == "KNOWLEDGE" or "graq_learn" in source:
        return "user_knowledge"
    if etype in ("DOCUMENT", "SECTION"):
        return "document"
    return "unknown"
