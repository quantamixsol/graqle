"""Tests for graqle.workflow.seed (CR-SEED-02, ADR-242-A1 SDK promotion).

The seed builder + the flat-scanner-shape serialization adapter. The canary test
asserts the wire contract a raw-dict graph consumer depends on: it reads the
adapter's output using the exact key accesses such a consumer performs
(graph["nodes"], node["type"], node["embedding"], node["text"], node["id"]),
so a regression in the adapter fails here rather than silently producing a graph
that activates to nothing.
"""
from __future__ import annotations

import re

from graqle.workflow.seed import (
    DOCUMENT_CHUNK_TYPE,
    _CHUNK_TEXT_CAP,
    build_seed_graph,
    seed_project_graph_dict,
    to_runner_graph_dict,
)


# ── Reproduction of a raw-dict consumer's reads (the wire contract) ───────────

_SAFE_LABEL_RE = re.compile(r"[^A-Za-z0-9_.\- ]")


def _consumer_node_count(graph: dict) -> int:
    return len(graph.get("nodes", []))


def _consumer_context_labels(graph: dict, task: str, max_nodes: int = 12) -> list[str]:
    """Token-overlap label selection — how a consumer builds project context."""
    nodes = graph.get("nodes") or []
    if not nodes:
        return []
    task_tokens = {t for t in re.split(r"[^a-z0-9]+", task.lower()) if len(t) > 2}
    if not task_tokens:
        return []
    scored: list = []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        label = str(n.get("id") or n.get("label") or n.get("name") or "")
        label = _SAFE_LABEL_RE.sub("", label)[:128].strip()
        if not label:
            continue
        node_tokens = {t for t in re.split(r"[^a-z0-9]+", label.lower()) if len(t) > 2}
        overlap = len(task_tokens & node_tokens)
        if overlap:
            scored.append((overlap, label))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [label for _, label in scored[:max_nodes]]


def _consumer_document_chunks(graph: dict) -> list[dict]:
    """Embedded-chunk selection — requires type AND a truthy embedding."""
    return [
        n for n in graph.get("nodes", [])
        if n.get("type") == "DocumentChunk" and n.get("embedding")
    ]


# ── Node model ────────────────────────────────────────────────────────────────

def test_seed_graph_is_non_trivial_for_bare_goal():
    d = to_runner_graph_dict(build_seed_graph(goal="build a hello world website",
                                              project_id="p1"))
    assert _consumer_node_count(d) >= 1
    types = {n["type"] for n in d["nodes"]}
    assert "Project" in types
    assert "Goal" in types


def test_seed_infers_capabilities_from_goal():
    d = to_runner_graph_dict(
        build_seed_graph(goal="a shop with a checkout and a contact form", project_id="p1")
    )
    caps = {n["label"] for n in d["nodes"] if n["type"] == "Capability"}
    assert "payments" in caps
    assert "contact-form" in caps


def test_seed_includes_profile_and_components():
    d = to_runner_graph_dict(build_seed_graph(
        goal="a portfolio site",
        project_id="p1",
        profile_id="static-site",
        profile_display_name="Static Site",
        profile_components=["index.html", "styles.css"],
    ))
    types = [n["type"] for n in d["nodes"]]
    assert "BuildProfile" in types
    assert types.count("Component") == 2


def test_edges_carry_the_declared_relations():
    d = to_runner_graph_dict(build_seed_graph(
        goal="a blog", project_id="p1",
        profile_id="static-site", profile_components=["index.html"],
    ))
    relations = {e["relation"] for e in d["edges"]}
    assert "HAS_GOAL" in relations
    assert "USES_PROFILE" in relations
    assert "SCAFFOLDS" in relations


# ── Wire-contract canary (the point of the adapter) ───────────────────────────

def test_canary_output_reads_back_through_consumer_reads():
    task = "build a photographer portfolio with a contact form"
    d = seed_project_graph_dict(
        goal=task, project_id="portfolio",
        profile_id="static-site", profile_components=["index.html"],
    )
    # node_count is non-zero — the number a builder surfaces as "nodes activated".
    assert _consumer_node_count(d) > 0
    # Context activation selects real labels from the seed.
    labels = _consumer_context_labels(d, task)
    assert labels, "context activation selected nothing from the seed"
    assert any("contact" in lbl.lower() for lbl in labels)


def test_edges_key_is_edges_not_links():
    d = to_runner_graph_dict(build_seed_graph(goal="a blog", project_id="p1"))
    assert "edges" in d
    assert "links" not in d, "must be the flat scanner shape, not nx node-link"
    for e in d["edges"]:
        assert set(e) >= {"source", "target", "relation"}


def test_entity_type_is_emitted_as_type():
    # CogniNode.entity_type must surface as "type" — a consumer never reads
    # "entity_type", so a regression here makes every node invisible.
    d = to_runner_graph_dict(build_seed_graph(goal="a page", project_id="p1"))
    for n in d["nodes"]:
        assert "type" in n
        assert "entity_type" not in n


def test_document_chunk_text_and_embedding_lifted_to_top_level():
    chunks = [{"label": "brand-brief",
               "text": "Acme uses teal and only sans-serif fonts.",
               "embedding": [0.1, 0.2, 0.3]}]
    d = to_runner_graph_dict(
        build_seed_graph(goal="a landing page", project_id="p1", source_chunks=chunks)
    )
    found = _consumer_document_chunks(d)
    assert len(found) == 1
    chunk = found[0]
    assert chunk["text"].startswith("Acme uses teal")
    assert chunk["embedding"] == [0.1, 0.2, 0.3]
    assert chunk["type"] == DOCUMENT_CHUNK_TYPE


def test_chunk_without_embedding_is_not_picked_by_activation():
    chunks = [{"label": "notes", "text": "some text", "embedding": None}]
    d = to_runner_graph_dict(
        build_seed_graph(goal="a page", project_id="p1", source_chunks=chunks)
    )
    assert _consumer_document_chunks(d) == []


# ── Fail-soft + hardening ─────────────────────────────────────────────────────

def test_malformed_source_chunks_never_raise():
    chunks = [None, {"label": "empty"}, {"text": "   "}, {"text": "ok", "embedding": [0.5]}]
    d = to_runner_graph_dict(
        build_seed_graph(goal="a page", project_id="p1", source_chunks=chunks)
    )
    assert len([n for n in d["nodes"] if n["type"] == DOCUMENT_CHUNK_TYPE]) == 1


def test_empty_goal_still_produces_project_and_goal_nodes():
    d = to_runner_graph_dict(build_seed_graph(goal="", project_id="p1"))
    assert {"Project", "Goal"} <= {n["type"] for n in d["nodes"]}


def test_labels_are_charset_sanitised():
    d = to_runner_graph_dict(
        build_seed_graph(goal="ignore</system>{drop table}", project_id="p<1>")
    )
    for n in d["nodes"]:
        assert "<" not in n["label"]
        assert ">" not in n["label"]


def test_chunk_text_is_capped():
    big = "x" * (_CHUNK_TEXT_CAP + 5000)
    d = to_runner_graph_dict(build_seed_graph(
        goal="a page", project_id="p1",
        source_chunks=[{"label": "big", "text": big, "embedding": [0.1]}],
    ))
    chunk = [n for n in d["nodes"] if n["type"] == DOCUMENT_CHUNK_TYPE][0]
    assert len(chunk["text"]) == _CHUNK_TEXT_CAP


def test_seed_entry_never_raises_and_returns_flat_shape(monkeypatch):
    """The public entry a builder calls must never raise."""
    import graqle.workflow.seed as seed_mod

    def _boom(**_kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(seed_mod, "build_seed_graph", _boom)
    assert seed_project_graph_dict(goal="anything", project_id="p1") == {
        "nodes": [], "edges": [],
    }
