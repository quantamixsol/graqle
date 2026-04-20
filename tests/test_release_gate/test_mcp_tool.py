"""G2 — MCP dispatcher-level tests for graq_release_gate tool."""
from __future__ import annotations

import asyncio
import json

import pytest

from graqle.plugins.mcp_dev_server import KogniDevServer, TOOL_DEFINITIONS


@pytest.fixture
def server():
    """Minimal KogniDevServer for dispatcher-level tests (no graph load)."""
    srv = KogniDevServer.__new__(KogniDevServer)
    srv._session_started = True
    srv._plan_active = True
    srv._cg01_bypass = True
    srv._cg02_bypass = True
    srv._cg03_bypass = True
    srv.read_only = False
    srv._config = type("Cfg", (), {"governance": None})()
    return srv


# ── 1. Tool registered in TOOL_DEFINITIONS ────────────────────────────────

def test_release_gate_tool_in_tool_definitions():
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert "graq_release_gate" in names


# ── 2. kogni_ alias present ───────────────────────────────────────────────

def test_release_gate_kogni_alias_present():
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert "kogni_release_gate" in names


# ── 3. Schema parity between graq_ and kogni_ variants ───────────────────

def test_release_gate_schema_parity():
    graq = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_release_gate")
    kogni = next(t for t in TOOL_DEFINITIONS if t["name"] == "kogni_release_gate")
    assert graq["inputSchema"] == kogni["inputSchema"]
    assert graq["description"] == kogni["description"]


# ── 4. Handler rejects missing diff ───────────────────────────────────────

def test_release_gate_handler_rejects_missing_diff(server):
    # Stub adapter dependencies so the handler path doesn't need real providers.
    async def _stub_review(args):
        return json.dumps({"comments": []})
    async def _stub_predict(args):
        return json.dumps({"confidence": 0.99})
    server._handle_review = _stub_review
    server._handle_predict = _stub_predict

    result = asyncio.run(server._handle_release_gate({
        "target": "pypi",
    }))
    data = json.loads(result)
    # Missing diff triggers engine fallback → WARN verdict with invalid_diff
    assert data["verdict"] == "WARN"
    assert "invalid_diff" in data["prediction_reasons"]


# ── 5. Handler rejects invalid target ─────────────────────────────────────

def test_release_gate_handler_rejects_invalid_target(server):
    async def _stub_review(args):
        return json.dumps({"comments": []})
    async def _stub_predict(args):
        return json.dumps({"confidence": 0.99})
    server._handle_review = _stub_review
    server._handle_predict = _stub_predict

    result = asyncio.run(server._handle_release_gate({
        "diff": "diff --git a/x.py b/x.py\n+print()",
        "target": "npm",
    }))
    data = json.loads(result)
    assert data["verdict"] == "WARN"
    assert "invalid_target" in data["prediction_reasons"]


# ── 6. Handler returns valid JSON with all expected fields ───────────────

def test_release_gate_handler_returns_full_verdict_shape(server):
    async def _stub_review(args):
        return json.dumps({
            "verdict": "CLEAR",
            "summary": "ok",
            "comments": [],
        })
    async def _stub_predict(args):
        return json.dumps({
            "risk_score": 0.1,
            "confidence": 0.99,
            "reasons": ["low blast radius"],
        })
    server._handle_review = _stub_review
    server._handle_predict = _stub_predict

    result = asyncio.run(server._handle_release_gate({
        "diff": "diff --git a/x.py b/x.py\n+print()",
        "target": "pypi",
    }))
    data = json.loads(result)
    # All expected fields present
    for field in ("verdict", "target", "blockers", "majors", "minors",
                  "risk_score", "confidence", "review_summary",
                  "prediction_reasons", "timestamp"):
        assert field in data, f"missing field: {field}"
    assert data["verdict"] in ("CLEAR", "WARN", "BLOCK")
    assert data["target"] == "pypi"


# ── 7. Non-dict args returns structured error ────────────────────────────

def test_release_gate_handler_non_dict_args(server):
    result = asyncio.run(server._handle_release_gate(None))
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "INVALID_ARGUMENTS"
