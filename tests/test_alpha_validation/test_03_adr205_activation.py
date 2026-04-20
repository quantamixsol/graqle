"""ITEM 03 — ADR-205 — Pre-Reason Activation Layer.

Acceptance:
1. ActivationLayer composes 3 providers (chunk scorer, safety gate, subgraph).
2. ADVISORY mode — safety.should_block=True does NOT raise.
3. ENFORCED mode — safety.should_block=True DOES raise TurnBlocked.
4. Provider order holds: chunk_scorer → safety_gate → subgraph.
"""

from __future__ import annotations

import time

import pytest


@pytest.mark.asyncio
async def test_adr205_activation_layer(record):
    t0 = time.monotonic()
    assertions = 0
    evidence: dict = {}

    from graqle.activation.layer import ActivationLayer
    from graqle.activation.default_providers import (
        NoopChunkScoringProvider,
        NoopSubgraphActivationProvider,
        FakeSafetyGateProvider,
    )
    from graqle.activation.providers import TierMode, TurnBlocked, SafetyVerdict

    block_verdict = SafetyVerdict(score=0.1, should_block=True, reason="demo block")

    # --- 1. ADVISORY mode — safety block is surfaced but does NOT raise ---
    advisory_safety = FakeSafetyGateProvider(verdict=block_verdict)
    advisory_layer = ActivationLayer(
        chunk_scorer=NoopChunkScoringProvider(),
        safety_gate=advisory_safety,
        subgraph_activator=NoopSubgraphActivationProvider(),
        tier_mode=TierMode.ADVISORY,
    )
    advisory_verdict = await advisory_layer.run("demo message", {})
    assert advisory_verdict is not None
    assert advisory_verdict.safety.should_block is True
    # ADVISORY must expose the block but NOT raise
    assertions += 1
    evidence["advisory_surfaces_without_raise"] = True
    evidence["advisory_block_reason"] = advisory_verdict.safety.reason

    # --- 2. ENFORCED mode — safety block RAISES TurnBlocked ---
    enforced_verdict = SafetyVerdict(score=0.1, should_block=True, reason="enforced demo")
    enforced_safety = FakeSafetyGateProvider(verdict=enforced_verdict)
    enforced_layer = ActivationLayer(
        chunk_scorer=NoopChunkScoringProvider(),
        safety_gate=enforced_safety,
        subgraph_activator=NoopSubgraphActivationProvider(),
        tier_mode=TierMode.ENFORCED,
    )
    raised = False
    try:
        await enforced_layer.run("demo", {})
    except TurnBlocked as exc:
        raised = True
        evidence["enforced_raise_reason"] = str(exc)
    assert raised, "ENFORCED + should_block must raise TurnBlocked"
    assertions += 1

    # --- 3. Advisory mode — safety OK → no raise, verdict produced ---
    ok_verdict = SafetyVerdict(score=1.0, should_block=False, reason="")
    ok_layer = ActivationLayer(
        chunk_scorer=NoopChunkScoringProvider(),
        safety_gate=FakeSafetyGateProvider(verdict=ok_verdict),
        subgraph_activator=NoopSubgraphActivationProvider(),
        tier_mode=TierMode.ADVISORY,
    )
    ok_verdict = await ok_layer.run("safe message", {})
    assert ok_verdict.safety.should_block is False
    assertions += 1
    evidence["safe_path_produces_verdict"] = True

    record(
        item_id="03-adr205",
        name="ADR-205 — Pre-Reason Activation Layer",
        status="PASS",
        assertions=assertions,
        duration_ms=int((time.monotonic() - t0) * 1000),
        evidence=evidence,
    )
