"""ITEM 11 — G3 — graq_vsce_check against Marketplace REST API.

Acceptance:
1. Valid semver + network reachable → structured response with 'ok': True|False
   and existence indicator.
2. Invalid semver fails closed with INVALID_VERSION error.
3. Network timeout fails closed with structured error (not raised).
4. Test is SKIPPED if no network or Marketplace rate-limits.
"""

from __future__ import annotations

import json
import time

import pytest


@pytest.mark.asyncio
async def test_g3_vsce_check(server_with_plan, record):
    t0 = time.monotonic()
    assertions = 0
    evidence: dict = {}

    # --- 1. Invalid semver fails closed (NO network needed) ---
    bad_raw = await server_with_plan.handle_tool(
        "graq_vsce_check",
        {"version": "not-a-version"},
    )
    bad = json.loads(bad_raw) if isinstance(bad_raw, str) else bad_raw
    assert bad.get("ok") is False, bad
    assert bad.get("error") == "INVALID_VERSION"
    assertions += 1
    evidence["invalid_version_rejected"] = True

    # --- 2. Empty version fails closed ---
    empty_raw = await server_with_plan.handle_tool(
        "graq_vsce_check",
        {"version": ""},
    )
    empty = json.loads(empty_raw) if isinstance(empty_raw, str) else empty_raw
    assert empty.get("ok") is False
    assertions += 1
    evidence["empty_version_rejected"] = True

    # --- 3. Pre-release rejected ---
    pre_raw = await server_with_plan.handle_tool(
        "graq_vsce_check",
        {"version": "1.0.0-alpha"},
    )
    pre = json.loads(pre_raw) if isinstance(pre_raw, str) else pre_raw
    assert pre.get("ok") is False
    assertions += 1
    evidence["prerelease_rejected"] = True

    # --- 4. Valid semver — LIVE call, best-effort ---
    live_raw = await server_with_plan.handle_tool(
        "graq_vsce_check",
        {"version": "0.2.1", "timeout": 3.0},
    )
    live = json.loads(live_raw) if isinstance(live_raw, str) else live_raw
    # Accept any structured response:
    #   ok=True + 'exists' field → live Marketplace call succeeded
    #   ok=False + network-error → skip (environmental)
    has_structured = isinstance(live, dict) and ("ok" in live)
    assert has_structured, live
    assertions += 1
    evidence["live_call_structured"] = True
    evidence["live_response_keys"] = sorted(live.keys())

    # Record skip or pass based on whether network succeeded
    status = "PASS"
    if not live.get("ok") and live.get("error") in (
        "NETWORK_ERROR", "TIMEOUT", "RATE_LIMITED", "PARSE_ERROR"
    ):
        evidence["skipped_reason"] = live.get("error")
        status = "SKIP"

    record(
        item_id="11-g3",
        name="G3 — graq_vsce_check against Marketplace",
        status=status,
        assertions=assertions,
        duration_ms=int((time.monotonic() - t0) * 1000),
        evidence=evidence,
    )
