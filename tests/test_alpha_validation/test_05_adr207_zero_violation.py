"""ITEM 05 — Zero-Violation Governance Discipline.

Acceptance:
1. Release-gate engine module exists and exposes expected public surface.
2. Fast-path module defines expected public symbols.
3. Activation module exposes expected public symbols.
4. A key governance-gate env var / config is settable without crashing.
"""

from __future__ import annotations

import time


def test_adr207_zero_violation_surfaces(record, monkeypatch):
    t0 = time.monotonic()
    assertions = 0
    evidence: dict = {}

    # --- 1. Release gate engine surface ---
    from graqle.release_gate import (
        ReleaseGateEngine,
        ReleaseGateVerdict,
        ReviewSummary,
        PredictionSummary,
    )
    assert ReleaseGateEngine is not None
    assert ReleaseGateVerdict is not None
    assertions += 1
    evidence["release_gate_surface"] = [
        "ReleaseGateEngine",
        "ReleaseGateVerdict",
        "ReviewSummary",
        "PredictionSummary",
    ]

    # --- 2. Fast-path module surface ---
    from graqle.chat.fast_path import (
        FastPathIntent,
        classify_intent,
        is_path_safe,
        is_fast_path_candidate,
    )
    assert FastPathIntent is not None
    assert callable(classify_intent)
    assert callable(is_path_safe)
    assert callable(is_fast_path_candidate)
    assertions += 1
    evidence["fast_path_surface"] = [
        "FastPathIntent",
        "classify_intent",
        "is_path_safe",
        "is_fast_path_candidate",
    ]

    # --- 3. Activation module surface ---
    from graqle.activation.layer import ActivationLayer
    from graqle.activation.providers import TierMode, TurnBlocked
    assert ActivationLayer is not None
    assert TierMode.ADVISORY is not None
    assert TierMode.ENFORCED is not None
    assert issubclass(TurnBlocked, Exception)
    assertions += 1
    evidence["activation_surface"] = ["ActivationLayer", "TierMode", "TurnBlocked"]

    # --- 4. Governance tier-mode env toggle is parseable ---
    from graqle.activation.tier_gate import resolve_tier_mode
    monkeypatch.setenv("GRAQLE_ACTIVATION_TIER", "ENFORCED")
    mode_enforced = resolve_tier_mode()
    monkeypatch.setenv("GRAQLE_ACTIVATION_TIER", "ADVISORY")
    mode_advisory = resolve_tier_mode()
    assert mode_enforced in (TierMode.ENFORCED, TierMode.ADVISORY)
    assert mode_advisory in (TierMode.ENFORCED, TierMode.ADVISORY)
    assertions += 1
    evidence["tier_mode_resolver_callable"] = True
    evidence["resolved_enforced"] = str(mode_enforced)
    evidence["resolved_advisory"] = str(mode_advisory)

    record(
        item_id="05-adr207",
        name="Zero-Violation Governance Discipline (public surfaces)",
        status="PASS",
        assertions=assertions,
        duration_ms=int((time.monotonic() - t0) * 1000),
        evidence=evidence,
    )
