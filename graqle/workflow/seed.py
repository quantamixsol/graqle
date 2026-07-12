"""Seed a project knowledge graph from a build goal, profile, and source docs.

A builder that generates a project from a natural-language goal starts with no
graph: there is no codebase to scan yet, so activation has nothing to activate
and every build cold-starts. This module produces the missing *seed* graph — a
small but real project graph built from the inputs available before the first
line of code exists:

* the user's **goal**,
* the **build profile** (which scaffolded components it implies),
* any attached **source documents** (already chunked and embedded upstream).

The seed is written to the project's graph file, so the *next* build loads a
non-empty graph and its context activation has real nodes to select from. Fold
build results back into the same graph after each build and the project's
knowledge compounds instead of resetting.

This is pure composition of the core graph API — it constructs no graph
structures of its own:

* :class:`graqle.core.graph.Graqle` (container)
* ``Graqle.add_node_simple`` / ``add_edge_simple`` (typed nodes/edges)
* ``Graqle.auto_connect`` (semantic edge discovery)

Serialization
-------------
:func:`to_runner_graph_dict` emits the **flat scanner shape** —
``{"nodes": [{"id","label","type","text","embedding",...}], "edges": [...]}`` —
which is what a graph consumer reading raw dict keys expects (the same shape a
repository scan produces). Note this is deliberately **not** the NetworkX
node-link shape that :meth:`Graqle.to_json` emits (``{"nodes", "links"}`` with
``entity_type`` rather than ``type``). Consumers that read the file as a raw
dict — rather than via :meth:`Graqle.from_json`, which normalizes both — need
the flat shape, so this adapter is the single serialization choke point.

Example
-------
>>> graph_dict = seed_project_graph_dict(
...     goal="a photographer portfolio with a contact form",
...     profile_id="static-site",
...     profile_components=["index.html"],
...     project_id="portfolio",
... )
>>> graph_dict["nodes"][0]["type"]
'Project'
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "build_seed_graph",
    "seed_project_graph_dict",
    "to_runner_graph_dict",
]

# Node type used for attached document chunks. Consumers filter on this exact
# string when selecting embedded context, so it is part of the wire contract.
DOCUMENT_CHUNK_TYPE = "DocumentChunk"

# Node labels flow into generation prompts as project context. They are
# attacker-influenceable data (a goal is user input), so restrict them to a safe
# identifier charset and cap the length at the source — defence in depth on top
# of whatever fencing the consumer applies.
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.\- ]")

# Size guard for chunk text held in the seed graph. This is NOT a sanitiser:
# chunk text reaches a prompt only through the caller's own untrusted-text
# fencing, which is the single source of truth for that concern. This cap only
# stops a pathological chunk from bloating the graph file.
_CHUNK_TEXT_CAP = 20_000


def _safe(text: str, limit: int = 128) -> str:
    """Restrict to a safe identifier charset and cap length. Never raises."""
    return _SAFE_ID_RE.sub("", str(text or ""))[:limit].strip()


def _infer_capabilities(goal: str, max_caps: int = 6) -> list[str]:
    """Infer capability names from the goal by keyword match (no LLM, no cost).

    Deliberately conservative: a curated intent->capability map. Anything
    unmatched contributes nothing, so noise never invents a capability. Returns
    a de-duplicated, order-stable list.
    """
    g = goal.lower()
    catalogue: list[tuple[tuple[str, ...], str]] = [
        (("login", "sign in", "sign-in", "auth", "account"), "authentication"),
        (("sign up", "signup", "register", "registration"), "user-registration"),
        (("contact", "get in touch", "enquiry", "inquiry"), "contact-form"),
        (("cart", "checkout", "payment", "stripe", "buy", "shop", "store", "commerce"), "payments"),
        (("blog", "post", "article", "cms", "content"), "content-management"),
        (("dashboard", "chart", "graph", "analytics", "metric"), "analytics-dashboard"),
        (("search", "filter", "query"), "search"),
        (("upload", "file", "attachment", "document"), "file-upload"),
        (("api", "endpoint", "rest", "backend"), "api"),
        (("map", "location", "geo"), "maps"),
        (("gallery", "portfolio", "photo", "image"), "media-gallery"),
        (("booking", "appointment", "reservation", "schedule", "calendar"), "booking"),
    ]
    caps: list[str] = []
    for keywords, cap in catalogue:
        if any(k in g for k in keywords) and cap not in caps:
            caps.append(cap)
        if len(caps) >= max_caps:
            break
    return caps


def build_seed_graph(
    *,
    goal: str,
    profile_id: str | None = None,
    profile_display_name: str | None = None,
    profile_components: list[str] | None = None,
    project_id: str = "",
    tenant_hash: str = "",
    source_chunks: list[dict] | None = None,
    created_at: str = "",
) -> Any:
    """Compose a seed :class:`~graqle.core.graph.Graqle` from pre-build inputs.

    Node model::

        Project . Goal . BuildProfile . Capability . Component . DocumentChunk

    Edges::

        Project -HAS_GOAL->      Goal
        Goal    -TARGETS->       Capability
        Project -USES_PROFILE->  BuildProfile
        BuildProfile -SCAFFOLDS-> Component
        Project -HAS_CONTEXT->   DocumentChunk

    Parameters
    ----------
    goal:
        The user's build request. Becomes the ``Goal`` node and drives
        capability inference.
    profile_id, profile_display_name, profile_components:
        Optional build-profile identity and the components it scaffolds.
    project_id, tenant_hash, created_at:
        Project identity metadata carried on the ``Project`` node.
    source_chunks:
        Optional ``[{"label", "text", "embedding"}]`` — already-chunked source
        documents. Added verbatim as ``DocumentChunk`` nodes (embeddings
        preserved) so a later build's embedding activation can rank them. This
        function does not chunk or embed; pass already-prepared chunks.

    Returns
    -------
    Graqle
        Serialize with :func:`to_runner_graph_dict`.

    Notes
    -----
    Per-chunk parsing and ``auto_connect`` are guarded: a malformed chunk or an
    embedding-backend failure degrades the seed, never raises.
    """
    from graqle.core.graph import Graqle

    g = Graqle()
    new_ids: list[str] = []

    project_node_id = f"project::{_safe(project_id) or 'new'}"
    g.add_node_simple(
        project_node_id,
        label=_safe(project_id) or "new-project",
        entity_type="Project",
        description="project root",
        properties={"tenant_hash": tenant_hash, "created_at": created_at},
    )
    new_ids.append(project_node_id)

    goal_id = "goal::0"
    g.add_node_simple(
        goal_id,
        label=_safe(goal, limit=80) or "build-goal",
        entity_type="Goal",
        description=str(goal or "")[:2048],
        properties={"created_at": created_at},
    )
    g.add_edge_simple(project_node_id, goal_id, relation="HAS_GOAL")
    new_ids.append(goal_id)

    if profile_id:
        profile_node_id = f"profile::{_safe(profile_id)}"
        g.add_node_simple(
            profile_node_id,
            label=_safe(profile_display_name or profile_id, limit=80),
            entity_type="BuildProfile",
            description=f"build profile {profile_id}",
            properties={"profile_id": _safe(profile_id)},
        )
        g.add_edge_simple(project_node_id, profile_node_id, relation="USES_PROFILE")
        new_ids.append(profile_node_id)

        for comp in (profile_components or []):
            comp_label = _safe(comp, limit=80)
            if not comp_label:
                continue
            comp_id = f"component::{comp_label}"
            g.add_node_simple(
                comp_id,
                label=comp_label,
                entity_type="Component",
                description=f"scaffolded component {comp_label}",
                properties={"layer": "generated"},
            )
            g.add_edge_simple(profile_node_id, comp_id, relation="SCAFFOLDS")
            new_ids.append(comp_id)

    for cap in _infer_capabilities(goal):
        cap_id = f"capability::{cap}"
        g.add_node_simple(
            cap_id,
            label=cap,
            entity_type="Capability",
            description=f"capability inferred from goal: {cap}",
            properties={"status": "active", "source": "inferred"},
        )
        g.add_edge_simple(goal_id, cap_id, relation="TARGETS")
        new_ids.append(cap_id)

    for i, chunk in enumerate(source_chunks or []):
        if not isinstance(chunk, dict):
            continue
        text = str(chunk.get("text") or "")[:_CHUNK_TEXT_CAP]
        if not text.strip():
            continue
        chunk_id = f"chunk::{i}"
        g.add_node_simple(
            chunk_id,
            label=_safe(chunk.get("label") or f"chunk-{i}", limit=64),
            entity_type=DOCUMENT_CHUNK_TYPE,
            description="attached source document chunk",
            properties={"text": text, "embedding": chunk.get("embedding")},
        )
        g.add_edge_simple(project_node_id, chunk_id, relation="HAS_CONTEXT")
        new_ids.append(chunk_id)

    # Semantic auto-connect over the new nodes. Best-effort: the seed is valid
    # without discovered edges, so a backend failure never blocks the caller.
    try:
        g.auto_connect(new_ids)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("seed: auto_connect skipped (%s)", type(exc).__name__)

    return g


def to_runner_graph_dict(graph: Any) -> dict:
    """Serialize a :class:`~graqle.core.graph.Graqle` to the flat scanner shape.

    The single serialization choke point for consumers that read a graph file as
    a raw dict (``graph["nodes"]``, ``node["type"]``, ``node["embedding"]``)
    rather than through :meth:`Graqle.from_json`.

    Mapping:

    ==================  ===================
    ``CogniNode``       emitted key
    ==================  ===================
    ``id``              ``id``
    ``label``           ``label``
    ``entity_type``     ``type``
    ``description``     ``description``
    ``properties.text``       ``text``       (lifted to top level)
    ``properties.embedding``  ``embedding``  (lifted to top level)
    remaining props     ``properties``
    ==================  ===================

    Edges are emitted under ``"edges"`` (never ``"links"``) as
    ``{"source", "target", "relation"}``.

    ``text`` and ``embedding`` are lifted out of ``properties`` because that is
    where a raw-dict consumer reads them; leaving them nested makes document
    chunks invisible to context activation.
    """
    nodes_out: list[dict] = []
    for node in graph.nodes.values():
        props = dict(getattr(node, "properties", {}) or {})
        node_dict: dict[str, Any] = {
            "id": node.id,
            "label": getattr(node, "label", node.id),
            "type": getattr(node, "entity_type", "CONCEPT"),
            "description": getattr(node, "description", ""),
        }
        if "text" in props:
            node_dict["text"] = props["text"]
        if props.get("embedding") is not None:
            node_dict["embedding"] = props["embedding"]
        extra = {k: v for k, v in props.items() if k not in ("text", "embedding")}
        if extra:
            node_dict["properties"] = extra
        nodes_out.append(node_dict)

    edges_out: list[dict] = []
    for edge in graph.edges.values():
        edges_out.append({
            "source": edge.source_id,
            "target": edge.target_id,
            "relation": getattr(edge, "relationship", "RELATES_TO"),
        })

    return {"nodes": nodes_out, "edges": edges_out}


def seed_project_graph_dict(
    *,
    goal: str,
    profile_id: str | None = None,
    profile_display_name: str | None = None,
    profile_components: list[str] | None = None,
    project_id: str = "",
    tenant_hash: str = "",
    source_chunks: list[dict] | None = None,
    created_at: str = "",
) -> dict:
    """Build the seed graph and return it in the flat scanner shape.

    The one-call entry point for a builder: compose the seed, serialize it, and
    hand back a dict ready to persist as the project's graph file.

    **Guaranteed non-raising.** On any internal failure it returns the empty
    shape ``{"nodes": [], "edges": []}`` — identical to what a consumer falls
    back to when no graph file exists — so a seed failure can never abort a
    build. Callers should persist only when ``nodes`` is non-empty, so a
    degraded seed is never written over a good graph.
    """
    try:
        g = build_seed_graph(
            goal=goal,
            profile_id=profile_id,
            profile_display_name=profile_display_name,
            profile_components=profile_components,
            project_id=project_id,
            tenant_hash=tenant_hash,
            source_chunks=source_chunks,
            created_at=created_at,
        )
        return to_runner_graph_dict(g)
    except Exception as exc:  # pragma: no cover - defensive top-level guard
        logger.warning("seed: seed_project_graph_dict failed (%s)", type(exc).__name__)
        return {"nodes": [], "edges": []}
