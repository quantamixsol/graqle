"""CG-19 Routing Gate — handler-level capability filter on graq_route.

This is a DOGFOOD regression suite: covers the pre-impl review findings
(spoofability framing, strict enum validation, structural validation,
null-guards, and back-compat) with asserts on the full response shape.

Scope reminder: CG-19 is ADVISORY-ONLY at the server boundary. The client
owns real permission enforcement; the tool arg only helps the router
recommend tools the client can actually call. This is documented both in
the tool description and in the handler docstring; tests verify the
structured error envelope for malformed input but deliberately do NOT
assert any security property on available_tools itself.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from graqle.plugins.mcp_dev_server import KogniDevServer


@pytest.fixture
def server(tmp_path, monkeypatch) -> KogniDevServer:
    """Fresh KogniDevServer with minimal config.

    We only exercise _handle_route which has no hard KG dependency — it
    calls graqle.runtime.router.route_question() which is a pure function.
    """
    s = KogniDevServer(config_path=None)
    # Ensure gate checks don't interfere — CG-19 is a handler-level concern
    # independent of CG-01/CG-02 session/plan gates.
    s._session_started = True
    return s


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if not asyncio.iscoroutine(coro) else asyncio.run(coro)


# ─── Back-compat guard (CG-19 absent → byte-identical pre-CG-19 payload) ──

def test_back_compat_when_neither_arg_provided(server):
    """Without available_tools or permission_tier, response shape is unchanged."""
    raw = asyncio.run(server._handle_route({"question": "what depends on the config loader?"}))
    payload = json.loads(raw)
    # Legacy fields present
    assert "category" in payload
    assert "graqle_priority" in payload
    assert "recommendation" in payload
    assert "graqle_tools" in payload
    assert "external_tools" in payload
    assert "confidence" in payload
    assert "reasoning" in payload
    # CG-19 fields ABSENT on back-compat path
    assert "cg19_applied" not in payload
    assert "permission_tier" not in payload
    assert "filtered_tools" not in payload


def test_back_compat_back_compat_reasoning_has_no_cg19_annotation(server):
    raw = asyncio.run(server._handle_route({"question": "impact of removing the retry wrapper"}))
    payload = json.loads(raw)
    assert "CG-19" not in payload["reasoning"]


# ─── Required-field validation ───────────────────────────────────────────

def test_missing_question_returns_structured_error(server):
    raw = asyncio.run(server._handle_route({}))
    payload = json.loads(raw)
    assert "error" in payload
    assert "question" in payload["error"].lower()


def test_empty_question_returns_structured_error(server):
    raw = asyncio.run(server._handle_route({"question": ""}))
    payload = json.loads(raw)
    assert "error" in payload


def test_whitespace_only_question_returns_structured_error(server):
    raw = asyncio.run(server._handle_route({"question": "   \n\t  "}))
    payload = json.loads(raw)
    assert "error" in payload


def test_non_string_question_returns_structured_error(server):
    raw = asyncio.run(server._handle_route({"question": 42}))
    payload = json.loads(raw)
    assert "error" in payload


# ─── CG-19 input validation (malformed available_tools / permission_tier) ─

def test_available_tools_non_list_rejected(server):
    raw = asyncio.run(server._handle_route({
        "question": "architecture of X",
        "available_tools": "graq_context",  # str, not list
    }))
    payload = json.loads(raw)
    assert "error" in payload
    assert "CG-19" in payload["error"]
    assert "list" in payload["error"].lower()


def test_available_tools_non_string_items_rejected(server):
    raw = asyncio.run(server._handle_route({
        "question": "architecture of X",
        "available_tools": ["graq_context", 42],
    }))
    payload = json.loads(raw)
    assert "error" in payload
    assert "CG-19" in payload["error"]


def test_permission_tier_invalid_value_rejected(server):
    raw = asyncio.run(server._handle_route({
        "question": "architecture of X",
        "available_tools": ["graq_context"],
        "permission_tier": "STRICT",  # not ADVISORY/ENFORCED
    }))
    payload = json.loads(raw)
    assert "error" in payload
    assert "CG-19" in payload["error"]
    assert "ADVISORY" in payload["error"] or "ENFORCED" in payload["error"]
    assert payload["received"] == "STRICT"


def test_permission_tier_unknown_does_not_silently_default(server):
    """Pre-impl review MAJOR: unknown tier must NOT silently fall back to ADVISORY."""
    raw = asyncio.run(server._handle_route({
        "question": "architecture of X",
        "available_tools": ["graq_context"],
        "permission_tier": "admin",
    }))
    payload = json.loads(raw)
    assert "error" in payload


# ─── ADVISORY tier behavior ─────────────────────────────────────────────

def test_advisory_preserves_original_recommendation(server):
    """ADVISORY keeps full recommendation, only adds filtered_tools + annotation."""
    raw = asyncio.run(server._handle_route({
        "question": "what calls the config loader?",
        "available_tools": ["graq_inspect"],  # router typically recommends graq_context + graq_reason
        "permission_tier": "ADVISORY",
    }))
    payload = json.loads(raw)
    assert payload["cg19_applied"] is True
    assert payload["permission_tier"] == "ADVISORY"
    # graqle_tools must NOT be mutated in ADVISORY mode
    assert isinstance(payload["graqle_tools"], list)
    assert len(payload["graqle_tools"]) > 0  # original recommendation preserved
    # filtered_tools must be surfaced separately if the filter excluded anything
    if payload.get("filtered_tools"):
        assert "CG-19 ADVISORY" in payload["reasoning"]


def test_advisory_without_filter_difference_no_annotation(server):
    """When available_tools is a superset, no filtered_tools key, no annotation."""
    raw = asyncio.run(server._handle_route({
        "question": "what calls the config loader?",
        "available_tools": [
            "graq_context", "graq_reason", "graq_inspect", "graq_impact",
            "graq_preflight", "graq_lessons", "graq_runtime", "graq_bash",
            "graq_read", "graq_grep",
        ],
        "permission_tier": "ADVISORY",
    }))
    payload = json.loads(raw)
    assert payload["cg19_applied"] is True
    assert "filtered_tools" not in payload  # nothing was filtered


# ─── ENFORCED tier behavior ─────────────────────────────────────────────

def test_enforced_hard_filters_graqle_tools(server):
    """ENFORCED replaces graqle_tools with the allowed subset."""
    raw = asyncio.run(server._handle_route({
        "question": "what calls the config loader?",
        "available_tools": ["graq_context"],  # narrow to one
        "permission_tier": "ENFORCED",
    }))
    payload = json.loads(raw)
    assert payload["cg19_applied"] is True
    assert payload["permission_tier"] == "ENFORCED"
    # graqle_tools is the intersection — every entry must be in available_tools
    for t in payload["graqle_tools"]:
        assert t == "graq_context"


def test_enforced_empty_intersection_downgrades(server):
    """ENFORCED with no matching tools downgrades recommendation."""
    raw = asyncio.run(server._handle_route({
        "question": "what calls the config loader?",
        "available_tools": ["some_tool_that_is_not_in_any_category"],
        "permission_tier": "ENFORCED",
    }))
    payload = json.loads(raw)
    assert payload["cg19_applied"] is True
    assert payload["graqle_tools"] == []
    # Recommendation must be downgraded safely
    assert payload["recommendation"] in ("external_only", "blocked")
    assert "CG-19 ENFORCED" in payload["reasoning"]


# ─── Null-guard / defensive behavior ────────────────────────────────────

def test_available_tools_empty_list_enforced_yields_blocked_or_external(server):
    """Empty allowlist in ENFORCED mode must not crash; must downgrade."""
    raw = asyncio.run(server._handle_route({
        "question": "what calls the config loader?",
        "available_tools": [],
        "permission_tier": "ENFORCED",
    }))
    payload = json.loads(raw)
    assert payload["cg19_applied"] is True
    assert payload["graqle_tools"] == []
    assert payload["recommendation"] in ("external_only", "blocked")


def test_available_tools_with_empty_strings_filtered_out(server):
    """Empty-string entries in available_tools are dropped before set-ops."""
    raw = asyncio.run(server._handle_route({
        "question": "what calls the config loader?",
        "available_tools": ["", "graq_context", ""],
        "permission_tier": "ENFORCED",
    }))
    payload = json.loads(raw)
    # Should not crash; empty strings are normalized out but graq_context still passes
    assert payload["cg19_applied"] is True


# ─── Permission_tier without available_tools is a no-op filter ──────────

def test_tier_without_available_tools_is_backcompat(server):
    """permission_tier alone (no available_tools) → filter does not run."""
    raw = asyncio.run(server._handle_route({
        "question": "architecture of X",
        "permission_tier": "ENFORCED",
    }))
    payload = json.loads(raw)
    # Back-compat path: no cg19_applied key
    assert "cg19_applied" not in payload
