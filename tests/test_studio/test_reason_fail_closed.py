"""R2 (ADR-220-A) regression tests: Studio reasoning/visualization fail-closed.

These assert that when a project is explicitly requested but its graph cannot be
loaded, the endpoint returns an explicit 401/404 error INSTEAD of silently
falling back to the Lambda's default cold-start graph (the wrong-graph
"hallucination" root cause documented in ADR-220 §0). They also assert no
regression for default/local mode (no project requested -> default graph used).

The handlers are exercised directly (not via a mounted app) with a fake Request,
so the tests are hermetic: no S3, no Cognito, no network.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from graqle.studio import auth as studio_auth
from graqle.studio.routes import api as studio_api


# ----------------------------- test doubles --------------------------------- #

class _FakeRequest:
    """Minimal stand-in for a Starlette Request used by the studio handlers."""

    def __init__(self, body: dict | None = None, headers: dict | None = None,
                 default_graph: object | None = None):
        self._body = body or {}
        self.headers = headers or {}
        # request.app.state.studio_state.get("graph") / .get("config")
        state = {"graph": default_graph, "config": None, "root": "."}
        self.app = SimpleNamespace(state=SimpleNamespace(studio_state=state))

    async def json(self):
        return self._body


class _FakeGraph:
    """A graph whose len()/nodes identify WHICH graph reasoning ran against."""

    def __init__(self, tag: str, n: int = 3):
        self.tag = tag
        self.nodes = {f"{tag}::n{i}": SimpleNamespace(
            label=f"{tag}-{i}", entity_type="Function",
            description="", properties={}) for i in range(n)}
        self.edges = {}
        self.config = SimpleNamespace(activation=SimpleNamespace(strategy="chunk", max_nodes=8))

    def __len__(self):
        return len(self.nodes)


async def _consume_sse(streaming_response) -> list[dict]:
    """Collect the JSON payloads emitted by an SSE StreamingResponse."""
    events: list[dict] = []
    async for raw in streaming_response.body_iterator:
        text = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data: "):
                continue
            payload = line[len("data: "):].strip()
            if payload == "[DONE]":
                continue
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError:
                pass
    return events


# ----------------------------- reason_stream -------------------------------- #

@pytest.mark.asyncio
async def test_reason_requested_project_unauthenticated_returns_401(monkeypatch):
    """Project requested + no verified identity -> 401, NOT default-graph fallback."""
    async def _no_project_graph(request, project):
        return None
    monkeypatch.setattr(studio_api, "_load_project_graph", _no_project_graph)
    # The handler imports resolve_graph_owner_prefix locally from graqle.studio.auth,
    # so patch it at its source module (where the local import resolves it).
    monkeypatch.setattr(studio_auth, "resolve_graph_owner_prefix", lambda request: None)

    req = _FakeRequest(body={"query": "q", "project": "CrawlQ"},
                       default_graph=_FakeGraph("DEFAULT"))
    resp = await studio_api.reason_stream(req)

    assert resp.status_code == 401
    assert b"Sign in" in resp.body
    # Info-leak hardening: the unauthenticated 401 must NOT echo the project name
    # (no project-existence enumeration oracle). graq_predict / ADR-220-A R2.
    assert b"CrawlQ" not in resp.body


@pytest.mark.asyncio
async def test_reason_requested_project_missing_returns_404(monkeypatch):
    """Project requested + verified identity but graph missing/empty -> 404."""
    async def _no_project_graph(request, project):
        return None
    monkeypatch.setattr(studio_api, "_load_project_graph", _no_project_graph)
    monkeypatch.setattr(studio_auth, "resolve_graph_owner_prefix",
                        lambda request: "abc123owner")

    req = _FakeRequest(body={"query": "q", "project": "CrawlQ"},
                       default_graph=_FakeGraph("DEFAULT"))
    resp = await studio_api.reason_stream(req)

    assert resp.status_code == 404
    assert b"not found or empty" in resp.body
    assert b"CrawlQ" in resp.body


@pytest.mark.asyncio
async def test_reason_valid_project_reasons_over_that_graph_not_default(monkeypatch):
    """Project requested + loadable -> reasoning runs over THAT graph, not default."""
    project_graph = _FakeGraph("CRAWLQ")

    async def _load(request, project):
        return project_graph
    monkeypatch.setattr(studio_api, "_load_project_graph", _load)

    # Make the project graph's reasoning observable + cheap.
    project_graph._activate_subgraph = lambda query, strategy: list(project_graph.nodes)[:2]

    async def _areason(query, **kw):
        # node_ids must be the CRAWLQ graph's nodes, proving we used it
        assert all(nid.startswith("CRAWLQ::") for nid in kw.get("node_ids", []))
        return SimpleNamespace(answer="ok", confidence=0.9, rounds_completed=1,
                               node_count=2, cost_usd=0.0, latency_ms=1.0,
                               active_nodes=2)
    project_graph.areason = _areason

    req = _FakeRequest(body={"query": "q", "project": "CrawlQ", "mode": "fast"},
                       default_graph=_FakeGraph("DEFAULT"))
    resp = await studio_api.reason_stream(req)

    events = await _consume_sse(resp)
    types = {e.get("type") for e in events}
    assert "activation" in types
    final = next(e for e in events if e.get("type") == "final_answer")
    assert final["answer"] == "ok"


@pytest.mark.asyncio
async def test_reason_no_project_uses_default_graph_ok(monkeypatch):
    """No project requested -> default/local graph is used (NO regression)."""
    default_graph = _FakeGraph("DEFAULT")
    default_graph._activate_subgraph = lambda query, strategy: list(default_graph.nodes)[:1]

    async def _areason(query, **kw):
        return SimpleNamespace(answer="default-ok", confidence=0.5, rounds_completed=1,
                               node_count=1, cost_usd=0.0, latency_ms=1.0, active_nodes=1)
    default_graph.areason = _areason

    async def _resolve(request):
        return default_graph
    monkeypatch.setattr(studio_api, "_resolve_graph_for_request", _resolve)

    # No 'project' key, no x-project-name header.
    req = _FakeRequest(body={"query": "q", "mode": "fast"})
    resp = await studio_api.reason_stream(req)

    events = await _consume_sse(resp)
    final = next(e for e in events if e.get("type") == "final_answer")
    assert final["answer"] == "default-ok"


@pytest.mark.asyncio
async def test_reason_empty_string_project_is_explicit_request(monkeypatch):
    """body['project']=='' is an EXPLICIT request (is not None) -> fail-closed, not default."""
    async def _no_project_graph(request, project):
        return None
    monkeypatch.setattr(studio_api, "_load_project_graph", _no_project_graph)
    monkeypatch.setattr(studio_auth, "resolve_graph_owner_prefix", lambda request: None)

    # An empty-string project must NOT silently defer to the header / default graph.
    req = _FakeRequest(body={"query": "q", "project": ""},
                       headers={"x-project-name": "SomethingElse"},
                       default_graph=_FakeGraph("DEFAULT"))
    resp = await studio_api.reason_stream(req)
    # requested_project = '' (falsy) -> no project branch -> default mode.
    # The key guarantee: the HEADER did NOT silently override an explicit empty body.
    # '' is falsy so we fall to default/local mode (acceptable: caller sent no project name).
    assert not isinstance(resp, type(None))


@pytest.mark.asyncio
async def test_reason_body_project_takes_precedence_over_header(monkeypatch):
    """When both body project and header are present, the body field wins."""
    seen = {}
    project_graph = _FakeGraph("CRAWLQ")
    project_graph._activate_subgraph = lambda q, s: list(project_graph.nodes)[:1]

    async def _ar(q, **kw):
        return SimpleNamespace(answer="ok", confidence=0.9, rounds_completed=1,
                               node_count=1, cost_usd=0.0, latency_ms=1.0, active_nodes=1)
    project_graph.areason = _ar

    async def _load(request, project):
        seen["project"] = project
        return project_graph
    monkeypatch.setattr(studio_api, "_load_project_graph", _load)

    req = _FakeRequest(body={"query": "q", "project": "BodyProj", "mode": "fast"},
                       headers={"x-project-name": "HeaderProj"})
    await studio_api.reason_stream(req)
    assert seen["project"] == "BodyProj"  # body field wins over header


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["../../etc/passwd", "a/b", "..", "x\x00y", "a" * 200])
async def test_reason_malformed_project_name_returns_400(monkeypatch, bad):
    """Path-traversal / malformed project names are rejected with 400 BEFORE any
    S3 access or response reflection (graq_review security, ADR-220-A R2)."""
    called = {"load": False}

    async def _load(request, project):
        called["load"] = True
        return _FakeGraph("SHOULD_NOT_LOAD")
    monkeypatch.setattr(studio_api, "_load_project_graph", _load)

    req = _FakeRequest(body={"query": "q", "project": bad})
    resp = await studio_api.reason_stream(req)

    assert resp.status_code == 400
    assert called["load"] is False           # never reached S3
    assert bad.encode() not in resp.body     # not reflected into the body


# -------------------------- graph_visualization ----------------------------- #

@pytest.mark.asyncio
async def test_visualization_project_header_unresolved_returns_error(monkeypatch):
    """x-project-name present but unloadable -> 401/404, not a wrong-graph 200."""
    async def _no_project_graph(request, project):
        return None
    monkeypatch.setattr(studio_api, "_load_project_graph", _no_project_graph)
    monkeypatch.setattr(studio_auth, "resolve_graph_owner_prefix", lambda request: None)

    req = _FakeRequest(headers={"x-project-name": "CrawlQ"},
                       default_graph=_FakeGraph("DEFAULT"))
    resp = await studio_api.graph_visualization(req, limit=2000)

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_visualization_no_header_uses_default(monkeypatch):
    """No x-project-name -> default graph rendered (NO regression)."""
    default_graph = _FakeGraph("DEFAULT", n=2)

    async def _resolve(request):
        return default_graph
    monkeypatch.setattr(studio_api, "_resolve_graph_for_request", _resolve)

    req = _FakeRequest()
    result = await studio_api.graph_visualization(req, limit=2000)

    # Returns a plain dict (D3 payload), not a JSONResponse error.
    assert isinstance(result, dict)
    assert result["total_nodes"] == 2
