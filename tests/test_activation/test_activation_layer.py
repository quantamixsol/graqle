"""ADR-205 — ActivationLayer orchestration tests (fakes only, no LLM)."""
from __future__ import annotations

import asyncio
import os

import pytest

from graqle.activation import (
    ActivationLayer,
    ActivationVerdict,
    TierMode,
    TurnBlocked,
    resolve_tier_mode,
)
from graqle.activation.default_providers import (
    FakeChunkScoringProvider,
    FakeSafetyGateProvider,
    FakeSubgraphActivationProvider,
    NoopChunkScoringProvider,
    NoopSafetyGateProvider,
    NoopSubgraphActivationProvider,
)
from graqle.activation.providers import (
    ActivatedSubgraph,
    ChunkScoreResult,
    SafetyVerdict,
)


def _layer(tier, chunks=None, safety=None, subgraph=None):
    return ActivationLayer(
        chunk_scorer=FakeChunkScoringProvider(chunks or ChunkScoreResult()),
        safety_gate=FakeSafetyGateProvider(safety or SafetyVerdict(score=1.0, should_block=False)),
        subgraph_activator=FakeSubgraphActivationProvider(subgraph or ActivatedSubgraph()),
        tier_mode=tier,
    )


# ── 1. ADVISORY + clean verdict → CLEAR, no chip ─────────────────────────

def test_advisory_clean_no_chip():
    layer = _layer(TierMode.ADVISORY)
    v = asyncio.run(layer.run("hello", {}))
    assert not v.is_blocked
    assert v.advisory_chip is None
    assert v.tier_mode is TierMode.ADVISORY


# ── 2. ADVISORY + should_block → NOT blocked, upgrade chip emitted ───────

def test_advisory_blocked_worthy_shows_upgrade_chip():
    layer = _layer(
        TierMode.ADVISORY,
        safety=SafetyVerdict(score=0.2, should_block=True, reason="unsafe"),
    )
    v = asyncio.run(layer.run("hello", {}))
    assert not v.is_blocked
    chip = v.advisory_chip
    assert chip is not None
    assert chip["kind"] == "upgrade_to_enforce"
    assert "graqle.com/pricing" in chip["message"]
    assert chip["drace_score"] == 0.2


# ── 3. ENFORCED + should_block → TurnBlocked raised ──────────────────────

def test_enforced_blocked_worthy_raises():
    layer = _layer(
        TierMode.ENFORCED,
        safety=SafetyVerdict(score=0.2, should_block=True, reason="unsafe"),
    )
    with pytest.raises(TurnBlocked) as exc:
        asyncio.run(layer.run("hello", {}))
    assert exc.value.verdict.is_blocked
    assert exc.value.verdict.block_reason == "unsafe"


# ── 4. ENFORCED + clean verdict → NOT blocked ────────────────────────────

def test_enforced_clean_passes():
    layer = _layer(TierMode.ENFORCED)
    v = asyncio.run(layer.run("hello", {}))
    assert not v.is_blocked


# ── 5. Providers run in correct order (score → evaluate → predict) ───────

def test_providers_called_in_order():
    order = []

    class CS:
        async def score(self, msg, hints):
            order.append("score")
            return ChunkScoreResult(chunks=("a",), scores=(0.8,), summary="s")

    class SG:
        async def evaluate(self, msg, chunks, hints):
            order.append("evaluate")
            return SafetyVerdict(score=1.0, should_block=False)

    class SA:
        async def predict(self, chunks, safety):
            order.append("predict")
            return ActivatedSubgraph(nodes=("x",), confidence=0.9)

    layer = ActivationLayer(CS(), SG(), SA(), tier_mode=TierMode.ADVISORY)
    asyncio.run(layer.run("hi", {}))
    assert order == ["score", "evaluate", "predict"]


# ── 6. Noop providers: full flow still works end-to-end ──────────────────

def test_noop_providers_end_to_end():
    layer = ActivationLayer(
        NoopChunkScoringProvider(),
        NoopSafetyGateProvider(),
        NoopSubgraphActivationProvider(),
        tier_mode=TierMode.ADVISORY,
    )
    v = asyncio.run(layer.run("hello", {}))
    assert not v.is_blocked
    assert v.tier_mode is TierMode.ADVISORY


# ── 7. Verdict serializes to JSON-safe dict ──────────────────────────────

def test_verdict_to_dict_shape():
    layer = _layer(TierMode.ADVISORY)
    v = asyncio.run(layer.run("hi", {}))
    d = v.to_dict()
    assert d["tier_mode"] == "ADVISORY"
    assert "chunks" in d
    assert "safety" in d
    assert "subgraph" in d
    assert d["is_blocked"] is False


# ── 8. Tier gate: default is ADVISORY (Free) ─────────────────────────────

def test_tier_default_advisory(monkeypatch):
    monkeypatch.delenv("GRAQLE_LICENSE_TIER", raising=False)
    monkeypatch.delenv("GRAQLE_LICENSE_KEY", raising=False)
    assert resolve_tier_mode() is TierMode.ADVISORY


# ── 9. Tier gate: env tier=pro → ENFORCED ────────────────────────────────

def test_tier_env_pro(monkeypatch):
    monkeypatch.setenv("GRAQLE_LICENSE_TIER", "pro")
    assert resolve_tier_mode() is TierMode.ENFORCED


# ── 10. Tier gate: env tier=enterprise → ENFORCED ────────────────────────

def test_tier_env_enterprise(monkeypatch):
    monkeypatch.setenv("GRAQLE_LICENSE_TIER", "enterprise")
    assert resolve_tier_mode() is TierMode.ENFORCED


# ── 11. Tier gate: license key presence → ENFORCED ───────────────────────

def test_tier_license_key_enforced(monkeypatch):
    monkeypatch.delenv("GRAQLE_LICENSE_TIER", raising=False)
    monkeypatch.setenv("GRAQLE_LICENSE_KEY", "abc123")
    assert resolve_tier_mode() is TierMode.ENFORCED


# ── 12. Tier gate: unknown tier string → ADVISORY (fail-safe) ────────────

def test_tier_unknown_string_fallback(monkeypatch):
    monkeypatch.setenv("GRAQLE_LICENSE_TIER", "mystery")
    monkeypatch.delenv("GRAQLE_LICENSE_KEY", raising=False)
    assert resolve_tier_mode() is TierMode.ADVISORY


# ── 13. Provider exception: layer does NOT catch — providers own fallback ─

def test_provider_exception_propagates():
    # Real providers fail open internally; fakes propagate exceptions.
    # This test asserts the LAYER is transparent to exceptions so callers
    # (ChatAgentLoop) can fail-open via their own try/except.
    class BrokenCS:
        async def score(self, msg, hints):
            raise RuntimeError("simulated provider failure")

    layer = ActivationLayer(
        BrokenCS(),
        FakeSafetyGateProvider(),
        FakeSubgraphActivationProvider(),
        tier_mode=TierMode.ADVISORY,
    )
    with pytest.raises(RuntimeError):
        asyncio.run(layer.run("hi", {}))


# ── 14. Real providers (wrappers) load without error ─────────────────────

def test_real_providers_import_and_construct():
    # This confirms the wrappers import and can be constructed.
    # They may fail to wire to actual KG/DRACE in a test env, but that's
    # handled by the _load_*() lazy pattern; construction must always work.
    from graqle.activation.real_providers import (
        RealChunkScoringProvider,
        RealSafetyGateProvider,
        RealSubgraphActivationProvider,
    )
    assert RealChunkScoringProvider() is not None
    assert RealSafetyGateProvider() is not None
    assert RealSubgraphActivationProvider() is not None


# ── 15. default_activation_layer: factory always returns a usable layer ──

def test_default_factory_always_returns_layer(monkeypatch):
    # Even when all real providers might fail to load, factory returns a
    # valid ActivationLayer (may be backed by Noop providers).
    monkeypatch.delenv("GRAQLE_LICENSE_KEY", raising=False)
    monkeypatch.delenv("GRAQLE_LICENSE_TIER", raising=False)
    from graqle.activation import default_activation_layer
    layer = default_activation_layer()
    assert isinstance(layer, ActivationLayer)
    # Should be runnable end-to-end without raising
    v = asyncio.run(layer.run("test msg", {}))
    assert isinstance(v, ActivationVerdict)


# ── CR-LIC-03b (ADR-245) — tier-trust security invariants ────────────────────
# resolve_tier_mode resolves the governance MODE only; it must NEVER confer a paid
# entitlement, and a VERIFIED paid licence must win over an unverified env/config hint.

def test_verified_paid_licence_wins_over_env(monkeypatch):
    """A real verified PRO licence resolves ENFORCED even if the env says 'free'."""
    from types import SimpleNamespace

    import graqle.activation.tier_gate as tg
    from graqle.licensing.manager import LicenseTier

    monkeypatch.setenv("GRAQLE_LICENSE_TIER", "free")  # unverified hint says free
    fake_mgr = SimpleNamespace(current_tier=LicenseTier.PRO)  # verified = PRO
    monkeypatch.setattr(
        "graqle.licensing.manager._get_manager", lambda: fake_mgr
    )
    assert tg.resolve_tier_mode() is TierMode.ENFORCED


def test_env_tier_confers_mode_not_entitlement(monkeypatch):
    """GRAQLE_LICENSE_TIER=enterprise (unverified) yields ENFORCED *mode* only — it
    does not touch manager.current_tier, which stays FREE (the real entitlement)."""
    from types import SimpleNamespace

    import graqle.activation.tier_gate as tg
    from graqle.licensing.manager import LicenseTier

    monkeypatch.setenv("GRAQLE_LICENSE_TIER", "enterprise")  # unverified
    fake_mgr = SimpleNamespace(current_tier=LicenseTier.FREE)  # verified stays FREE
    monkeypatch.setattr(
        "graqle.licensing.manager._get_manager", lambda: fake_mgr
    )
    # Mode is ENFORCED (stricter governance — grants nothing)...
    assert tg.resolve_tier_mode() is TierMode.ENFORCED
    # ...but the ENTITLEMENT (what paid features consult) is unchanged: still FREE.
    assert fake_mgr.current_tier is LicenseTier.FREE


def test_verified_free_still_advisory_without_hints(monkeypatch):
    """No env/config hints + verified FREE → ADVISORY (no false enforcement)."""
    from types import SimpleNamespace

    import graqle.activation.tier_gate as tg
    from graqle.licensing.manager import LicenseTier

    monkeypatch.delenv("GRAQLE_LICENSE_TIER", raising=False)
    monkeypatch.delenv("GRAQLE_LICENSE_KEY", raising=False)
    fake_mgr = SimpleNamespace(current_tier=LicenseTier.FREE)
    monkeypatch.setattr(
        "graqle.licensing.manager._get_manager", lambda: fake_mgr
    )
    assert tg.resolve_tier_mode() is TierMode.ADVISORY


def test_manager_error_falls_through_safely(monkeypatch):
    """If the verified-tier lookup raises, resolve_tier_mode must not crash — it falls
    through to the mode-only hints (fail-safe), never blocking mode detection."""
    import graqle.activation.tier_gate as tg

    def _boom():
        raise RuntimeError("licence subsystem unavailable")

    monkeypatch.setattr("graqle.licensing.manager._get_manager", _boom)
    monkeypatch.delenv("GRAQLE_LICENSE_TIER", raising=False)
    monkeypatch.delenv("GRAQLE_LICENSE_KEY", raising=False)
    # No hints + manager error → default ADVISORY (fail-safe, least-strict).
    assert tg.resolve_tier_mode() is TierMode.ADVISORY


def test_no_import_cycle_tier_gate_and_manager():
    """CR-LIC-03b MINOR: tier_gate lazy-imports manager to avoid a cycle. Importing
    both in either order must not deadlock or ImportError (guards the cycle boundary)."""
    import importlib

    importlib.import_module("graqle.activation.tier_gate")
    importlib.import_module("graqle.licensing.manager")
    # Reverse order too.
    importlib.reload(importlib.import_module("graqle.licensing.manager"))
    importlib.reload(importlib.import_module("graqle.activation.tier_gate"))
