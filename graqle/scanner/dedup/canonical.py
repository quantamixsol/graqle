"""Canonical ID computation — deterministic node IDs prevent re-scan duplicates.

Every node gets a canonical ID based on its type + source. Re-scanning
produces the same canonical IDs → nodes are updated, not duplicated.
"""

# ── graqle:intelligence ──
# module: graqle.scanner.dedup.canonical
# risk: LOW (impact radius: 2 modules)
# consumers: __init__, test_canonical
# dependencies: __future__, hashlib, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import hashlib
from typing import Any


def compute_canonical_id(node: dict[str, Any]) -> str | None:
    """Compute a deterministic canonical ID for a node.

    Returns ``None`` if the node type is not supported for canonicalization.
    """
    etype = node.get("entity_type", "").upper()
    props = node.get("properties", {})
    label = node.get("label", "")
    nid = node.get("id", "")

    if etype in ("FUNCTION", "CLASS", "MODULE", "PYTHONMODULE", "JAVASCRIPTMODULE"):
        path = props.get("path", props.get("file_path", ""))
        name = label or nid
        if path:
            return _hash(f"code:{path}:{name}")
        return None

    if etype == "ENDPOINT":
        method = props.get("method", "")
        route = props.get("route", "")
        if method and route:
            return _hash(f"api:{method}:{route}")
        return None

    if etype == "CONFIG":
        source = props.get("source", "")
        key = props.get("key", "")
        if source and key:
            return _hash(f"config:{source}:{key}")
        return None

    if etype == "DEPENDENCY":
        manager = props.get("manager", "")
        name = label or nid
        if manager:
            return _hash(f"dep:{manager}:{name}")
        return None

    if etype in ("SECTION", "DECISION", "REQUIREMENT"):
        path = props.get("path", "")
        heading = label or nid
        if path:
            return _hash(f"doc:{path}:{heading}")
        return None

    if etype == "DOCUMENT":
        path = props.get("path", "")
        if path:
            return _hash(f"doc:{path}")
        return None

    if etype == "RESOURCE":
        aws_type = props.get("aws_type", "")
        if aws_type:
            return _hash(f"resource:{aws_type}:{label}")
        return None

    if etype == "SCHEMA":
        return _hash(f"schema:{label}")

    if etype == "TOOL_RULE":
        tool = props.get("tool", "")
        key = props.get("key", props.get("rule", ""))
        if tool:
            return _hash(f"rule:{tool}:{key}")
        return None

    if etype == "SCRIPT":
        manager = props.get("manager", "")
        return _hash(f"script:{manager}:{label}")

    return None


def _hash(key: str) -> str:
    """Produce a short hex hash for canonical ID."""
    return hashlib.sha256(key.encode()).hexdigest()[:16]
