"""Cross-language MCP resolution — TypeScript callTool() → Python _handle_*().

Resolves MCP call sites discovered by JSAnalyzer to handler functions found
by PythonAnalyzer, creating ``CALLS_VIA_MCP`` edges in the knowledge graph.

Invoked as ``discover_mcp_links()`` in the scan pipeline after
``_resolve_imports``.

ADR-131: Cross-language MCP resolution algorithm.
ADR-130 / TS-2: Confidence values loaded from private config, never hardcoded.
"""

# ── graqle:intelligence ──
# module: graqle.scanner.mcp_linker
# risk: HIGH (impact radius: scanner pipeline, KG edge integrity)
# consumers: scanner.pipeline, scanner.graph_builder, test_mcp_linker
# dependencies: __future__, dataclasses, json, logging, pathlib, typing
# constraints: ADR-131, ADR-130/TS-2 (no hardcoded confidence values)
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, Sequence, runtime_checkable

logger = logging.getLogger("graqle.scanner.mcp_linker")

# ---------------------------------------------------------------------------
# Confidence config (ADR-130 / TS-2 compliant — NO hardcoded values)
# ---------------------------------------------------------------------------

_CONFIDENCE_CONFIG_PATH = Path(".graqle") / "mcp_linker_confidence.json"

# Opaque defaults — actual tuned values MUST live in the config file.
# Sentinel defaults (None) — fail-fast when config is missing.
# B1 fix: 0.0 defaults silently caused R2 to reject ALL edges at >=0.75 gate.
_DEFAULT_CONFIDENCE: dict[str, float | None] = {
    "direct_match": None,
    "prefix_strip": None,
    "alias_strip": None,
    "registry_fallback": None,
}

_confidence_cache: dict[str, float] | None = None


def _load_confidence_config(
    config_path: Path | None = None,
) -> dict[str, float]:
    """Load confidence values from private config file.

    Falls back to opaque defaults if the file is missing or malformed.
    No hardcoded confidence values are used — all come from config (TS-2).
    """
    global _confidence_cache  # noqa: PLW0603

    if _confidence_cache is not None and config_path is None:
        return _confidence_cache

    path = config_path or _CONFIDENCE_CONFIG_PATH
    conf = dict(_DEFAULT_CONFIDENCE)

    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in _DEFAULT_CONFIDENCE:
                    if key in data and isinstance(data[key], (int, float)):
                        conf[key] = float(data[key])
            logger.debug("Loaded MCP linker confidence config from %s", path)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        logger.warning(
            "Failed to load MCP linker confidence config (%s): %s — using defaults",
            path,
            exc,
        )

    # B1 fix: warn when confidence values are unconfigured (None sentinel)
    if any(v is None for v in conf.values()):
        logger.warning(
            "MCP linker confidence config missing or incomplete at %s. "
            "Edges will have confidence=None and may be rejected by "
            "downstream gates. Create the config per ADR-130/TS-2.",
            path,
        )

    if config_path is None:
        _confidence_cache = conf
    return conf


def reset_confidence_cache() -> None:
    """Reset the cached confidence config (for testing)."""
    global _confidence_cache  # noqa: PLW0603
    _confidence_cache = None


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossLangEdge:
    """A resolved cross-language ``CALLS_VIA_MCP`` edge."""

    source: Any  # MCPCallSite
    target: Any  # MCPHandler
    tool_name: str
    bare_name: str
    alias_chain: tuple[str, ...] = ()
    transport: str = "mcp"
    resolution_path: str = ""
    confidence: float = 0.0


@dataclass(frozen=True)
class UnresolvedEdge:
    """An MCP call site that could not be resolved to a handler."""

    source: Any  # MCPCallSite
    reason: str  # "UNRESOLVED_DYNAMIC" | "UNRESOLVED_MISSING_HANDLER"
    hint: str = ""


# ---------------------------------------------------------------------------
# Alias map builder
# ---------------------------------------------------------------------------

_GRAQ_PREFIX = "graq_"
_KOGNI_PREFIX = "kogni_"
_KNOWN_PREFIXES = (_GRAQ_PREFIX, _KOGNI_PREFIX)


def build_alias_map(
    handlers: Sequence[Any] | None = None,
    *,
    registry_bindings: dict[str, str] | None = None,
    extra_aliases: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build ``kogni_*`` → ``graq_*`` alias map dynamically.

    For every handler with ``bare_name`` X, registers
    ``kogni_X`` → ``graq_X`` so legacy TS clients resolve correctly.
    Registry bindings and extra aliases are merged on top.
    """
    alias_map: dict[str, str] = {}

    if handlers:
        for h in handlers:
            bare = getattr(h, "bare_name", None) or getattr(h, "tool_name", None)
            if bare:
                alias_map[f"{_KOGNI_PREFIX}{bare}"] = f"{_GRAQ_PREFIX}{bare}"

    if registry_bindings:
        for registered_name in registry_bindings:
            if registered_name.startswith(_KOGNI_PREFIX):
                suffix = registered_name[len(_KOGNI_PREFIX):]
                alias_map[registered_name] = f"{_GRAQ_PREFIX}{suffix}"

    if extra_aliases:
        alias_map.update(extra_aliases)

    return alias_map


# ---------------------------------------------------------------------------
# Core resolution algorithm
# ---------------------------------------------------------------------------


def _strip_prefix(name: str) -> str:
    """Strip known prefixes (``graq_``, ``kogni_``) to obtain bare tool name."""
    for prefix in _KNOWN_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def resolve_cross_language(
    call_sites: Sequence[Any],
    handlers: Sequence[Any],
    registry_bindings: dict[str, str] | None = None,
    alias_map: dict[str, str] | None = None,
    *,
    confidence_config: dict[str, float] | None = None,
) -> tuple[list[CrossLangEdge], list[UnresolvedEdge]]:
    """Resolve TS ``callTool()`` sites to Python ``_handle_*()`` handlers.

    Resolution priority cascade (ADR-131):
      a. Direct bare-name match: callTool('reason') → _handle_reason
      b. Prefix-strip: callTool('graq_reason') → strip → _handle_reason
      c. Alias + strip: callTool('kogni_reason') → graq_reason → _handle_reason
      d. TOOL_REGISTRY fallback: registered_name → handler function
      e. UNRESOLVED

    Returns ``(resolved_edges, unresolved_warnings)``.
    """
    conf = confidence_config or _load_confidence_config()
    if alias_map is None:
        alias_map = build_alias_map(handlers, registry_bindings=registry_bindings)

    # Index handlers by bare_name for O(1) lookup
    handler_by_bare: dict[str, Any] = {}
    for h in handlers:
        bare = getattr(h, "bare_name", None)
        if bare:
            handler_by_bare[bare] = h

    # Build registry lookup: registered_name → handler bare_name
    registry_lookup: dict[str, str] = {}
    if registry_bindings:
        for reg_name, handler_ref in registry_bindings.items():
            bare = handler_ref
            if bare.startswith("_handle_"):
                bare = bare[len("_handle_"):]
            registry_lookup[reg_name] = bare

    resolved: list[CrossLangEdge] = []
    unresolved: list[UnresolvedEdge] = []

    for site in call_sites:
        tool = site.tool_name
        edge: CrossLangEdge | None = None

        # Guard: dynamic call sites are inherently unresolvable
        if getattr(site, "is_dynamic", False):
            unresolved.append(UnresolvedEdge(
                source=site,
                reason="UNRESOLVED_DYNAMIC",
                hint=f"Dynamic tool name: {tool}",
            ))
            continue

        # (a) Direct bare-name match
        if tool in handler_by_bare:
            edge = CrossLangEdge(
                source=site,
                target=handler_by_bare[tool],
                tool_name=tool,
                bare_name=tool,
                resolution_path="direct_match",
                confidence=conf.get("direct_match"),
            )

        # (b) Prefix-strip: graq_reason → reason
        if edge is None and tool.startswith(_GRAQ_PREFIX):
            bare = tool[len(_GRAQ_PREFIX):]
            if bare in handler_by_bare:
                edge = CrossLangEdge(
                    source=site,
                    target=handler_by_bare[bare],
                    tool_name=tool,
                    bare_name=bare,
                    alias_chain=(tool, bare),
                    resolution_path="prefix_strip",
                    confidence=conf.get("prefix_strip"),
                )

        # (c) Alias + strip: kogni_reason → graq_reason → reason
        if edge is None and tool in alias_map:
            graq_name = alias_map[tool]
            bare = _strip_prefix(graq_name)
            if bare in handler_by_bare:
                edge = CrossLangEdge(
                    source=site,
                    target=handler_by_bare[bare],
                    tool_name=tool,
                    bare_name=bare,
                    alias_chain=(tool, graq_name, bare),
                    resolution_path="alias_strip",
                    confidence=conf.get("alias_strip"),
                )

        # (d) TOOL_REGISTRY fallback
        if edge is None and tool in registry_lookup:
            bare = registry_lookup[tool]
            if bare in handler_by_bare:
                edge = CrossLangEdge(
                    source=site,
                    target=handler_by_bare[bare],
                    tool_name=tool,
                    bare_name=bare,
                    alias_chain=(tool, bare),
                    resolution_path="registry_fallback",
                    confidence=conf.get("registry_fallback"),
                )

        # (e) Collect result — B1 fix: reject edges with unconfigured confidence
        if edge is not None:
            if edge.confidence is None:
                unresolved.append(UnresolvedEdge(
                    source=site,
                    reason="UNCONFIGURED_CONFIDENCE",
                    hint=f"Confidence for {edge.resolution_path} is None — config missing",
                ))
            else:
                resolved.append(edge)
        else:
            unresolved.append(UnresolvedEdge(
                source=site,
                reason="UNRESOLVED_MISSING_HANDLER",
                hint=f"No handler found for tool: {tool}",
            ))

    return resolved, unresolved


# ---------------------------------------------------------------------------
# Knowledge-graph edge emission
# ---------------------------------------------------------------------------


def emit_kg_edges(
    resolved: Sequence[CrossLangEdge],
    unresolved: Sequence[UnresolvedEdge],
    graph: Any,
) -> dict[str, int]:
    """Create ``CALLS_VIA_MCP`` edges in the knowledge graph.

    Validates target node existence before creating each edge to prevent
    dangling references (Gate 4 referential integrity).  Logs warnings
    for all unresolved edges.

    Returns a stats dict with counts of created and skipped edges.
    """
    created = 0
    skipped = 0

    for edge in resolved:
        target_id = getattr(edge.target, "node_id", None)
        source_id = getattr(edge.source, "node_id", None)

        # Gate 4: validate target node exists before creating edge
        has_node = getattr(graph, "has_node", None)
        if has_node and target_id and not has_node(target_id):
            logger.warning(
                "Skipping CALLS_VIA_MCP edge: target node %s does not exist "
                "(tool=%s, resolution=%s)",
                target_id,
                edge.tool_name,
                edge.resolution_path,
            )
            skipped += 1
            continue

        if has_node and source_id and not has_node(source_id):
            logger.warning(
                "Skipping CALLS_VIA_MCP edge: source node %s does not exist "
                "(tool=%s)",
                source_id,
                edge.tool_name,
            )
            skipped += 1
            continue

        # Create the edge in the graph
        add_edge = getattr(graph, "add_edge", None)
        if add_edge and source_id and target_id:
            add_edge(
                source_id,
                target_id,
                edge_type="CALLS_VIA_MCP",
                properties={
                    "tool_name": edge.tool_name,
                    "bare_name": edge.bare_name,
                    "alias_chain": list(edge.alias_chain),
                    "transport": edge.transport,
                    "protocol": "MCP",
                    "resolution_path": edge.resolution_path,
                    "confidence": edge.confidence,
                },
            )
            created += 1
            logger.debug(
                "Created CALLS_VIA_MCP edge: %s -> %s (tool=%s, path=%s)",
                source_id, target_id, edge.tool_name, edge.resolution_path,
            )
        else:
            skipped += 1

    # Log unresolved edges as warnings
    for u in unresolved:
        logger.warning(
            "Unresolved MCP call: %s (reason=%s, hint=%s)",
            getattr(u.source, "file_path", "?"),
            u.reason,
            u.hint,
        )

    return {"created": created, "skipped": skipped, "unresolved": len(unresolved)}


# ---------------------------------------------------------------------------
# Main entry point (called from scan pipeline)
# ---------------------------------------------------------------------------


def discover_mcp_links(
    graph: Any,
    ts_call_sites: Sequence[Any],
    py_handlers: Sequence[Any],
    registry_bindings: dict[str, str] | None = None,
) -> dict[str, int]:
    """Discover and create cross-language MCP edges.

    Main entry point called from the scan pipeline after ``_resolve_imports``.
    Orchestrates: build alias map → resolve → emit edges.

    Returns stats dict with created/skipped/unresolved counts.
    """
    alias_map = build_alias_map(py_handlers, registry_bindings=registry_bindings)
    resolved, unresolved = resolve_cross_language(
        ts_call_sites, py_handlers, registry_bindings, alias_map,
    )
    stats = emit_kg_edges(resolved, unresolved, graph)

    logger.info(
        "MCP cross-language linking: %d created, %d skipped, %d unresolved",
        stats["created"], stats["skipped"], stats["unresolved"],
    )

    return stats
