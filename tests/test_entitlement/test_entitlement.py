"""Tests for edition/feature entitlement gating (WS-D D2) — all failure points.

100% statement + branch coverage of graqle/entitlement.py, incl. the
defence-in-depth invariant (forced GRAQLE_EDITION without a licence does NOT
unlock) and the Community-never-gated guard.
"""

from __future__ import annotations

import asyncio

import pytest

import graqle.edition as E
import graqle.entitlement as ENT
from graqle.entitlement import (
    Edition,
    EntitlementError,
    requires_edition,
    requires_feature,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("GRAQLE_EDITION", raising=False)
    E.reset_edition_cache()
    yield
    E.reset_edition_cache()


def _force_tier(monkeypatch, tier_name: str):
    """Force the manager singleton to report a given licence tier."""
    import graqle.licensing.manager as M

    class _Mgr:
        @property
        def current_tier(self):
            return getattr(M.LicenseTier, tier_name)

    monkeypatch.setattr(M, "_manager", _Mgr())


def _force_tier_raises(monkeypatch):
    import graqle.licensing.manager as M

    class _Boom:
        @property
        def current_tier(self):
            raise RuntimeError("licence subsystem down")

    monkeypatch.setattr(M, "_manager", _Boom())


# ---- requires_edition decoration-time validation ------------------------------


def test_requires_edition_rejects_community():
    with pytest.raises(ValueError, match="never gated"):
        requires_edition(Edition.COMMUNITY)


def test_requires_edition_rejects_non_edition():
    with pytest.raises(TypeError):
        requires_edition("studio")  # type: ignore[arg-type]


# ---- DEFENCE IN DEPTH: forced edition without licence ------------------------


def test_forced_edition_without_licence_blocked(monkeypatch):
    monkeypatch.setenv("GRAQLE_EDITION", "enterprise")
    E.reset_edition_cache()
    _force_tier(monkeypatch, "FREE")  # no real paid licence

    @requires_edition(Edition.ENTERPRISE)
    def secret():
        return "unlocked"

    with pytest.raises(EntitlementError):
        secret()


def test_edition_and_matching_licence_unlocks(monkeypatch):
    monkeypatch.setenv("GRAQLE_EDITION", "enterprise")
    E.reset_edition_cache()
    _force_tier(monkeypatch, "ENTERPRISE")

    @requires_edition(Edition.ENTERPRISE)
    def secret():
        return "unlocked"

    assert secret() == "unlocked"


def test_studio_gate_blocked_in_community(monkeypatch):
    _force_tier(monkeypatch, "FREE")  # default community

    @requires_edition(Edition.STUDIO)
    def studio_only():
        return "ok"

    with pytest.raises(EntitlementError):
        studio_only()


def test_studio_gate_satisfied_by_pro_and_team(monkeypatch):
    for tier in ("PRO", "TEAM"):
        monkeypatch.setenv("GRAQLE_EDITION", "studio")
        E.reset_edition_cache()
        _force_tier(monkeypatch, tier)

        @requires_edition(Edition.STUDIO)
        def f():
            return tier

        assert f() == tier


def test_enterprise_gate_not_satisfied_by_team(monkeypatch):
    # edition forced enterprise but licence only team => blocked (tier insufficient)
    monkeypatch.setenv("GRAQLE_EDITION", "enterprise")
    E.reset_edition_cache()
    _force_tier(monkeypatch, "TEAM")

    @requires_edition(Edition.ENTERPRISE)
    def f():
        return "x"

    with pytest.raises(EntitlementError):
        f()


def test_licence_exception_fails_closed(monkeypatch):
    monkeypatch.setenv("GRAQLE_EDITION", "enterprise")
    E.reset_edition_cache()
    _force_tier_raises(monkeypatch)

    @requires_edition(Edition.ENTERPRISE)
    def f():
        return "x"

    with pytest.raises(EntitlementError):
        f()  # licence read raised → treated as free → blocked


# ---- async support ------------------------------------------------------------


def test_requires_edition_async(monkeypatch):
    _force_tier(monkeypatch, "FREE")

    @requires_edition(Edition.STUDIO)
    async def af():
        return "ok"

    with pytest.raises(EntitlementError):
        asyncio.run(af())


def test_requires_edition_async_unlocks(monkeypatch):
    monkeypatch.setenv("GRAQLE_EDITION", "enterprise")
    E.reset_edition_cache()
    _force_tier(monkeypatch, "ENTERPRISE")

    @requires_edition(Edition.ENTERPRISE)
    async def af():
        return "ok"

    assert asyncio.run(af()) == "ok"


def test_metadata_preserved(monkeypatch):
    @requires_edition(Edition.STUDIO)
    def documented():
        """Doc stays."""

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "Doc stays."


# ---- requires_feature ---------------------------------------------------------


def test_requires_feature_rejects_empty():
    with pytest.raises(ValueError):
        requires_feature("")


def test_requires_feature_enterprise_shortcircuits(monkeypatch):
    monkeypatch.setenv("GRAQLE_EDITION", "enterprise")
    E.reset_edition_cache()
    _force_tier(monkeypatch, "ENTERPRISE")

    @requires_feature("any_feature")
    def f():
        return "ok"

    assert f() == "ok"  # top-tier short-circuit, no check_license call


def test_requires_feature_delegates_to_check_license(monkeypatch):
    _force_tier(monkeypatch, "FREE")
    called = {}

    def fake_check(feature):
        called["feature"] = feature

    monkeypatch.setattr("graqle.licensing.check_license", fake_check)

    @requires_feature("ontology_generator")
    def f():
        return "ok"

    assert f() == "ok"
    assert called["feature"] == "ontology_generator"


def test_requires_feature_async(monkeypatch):
    monkeypatch.setenv("GRAQLE_EDITION", "enterprise")
    E.reset_edition_cache()
    _force_tier(monkeypatch, "ENTERPRISE")

    @requires_feature("x")
    async def af():
        return "ok"

    assert asyncio.run(af()) == "ok"


def test_licence_tier_value_helper_fail_closed(monkeypatch):
    _force_tier_raises(monkeypatch)
    assert ENT._licence_tier_value() == "free"


def test_entitled_for_community_is_always_true(monkeypatch):
    # _entitled_for(COMMUNITY) returns True unconditionally (the free floor needs
    # no edition/licence). Direct unit — decorators reject COMMUNITY at decoration,
    # so this defensive branch is exercised here.
    _force_tier(monkeypatch, "FREE")
    assert ENT._entitled_for(Edition.COMMUNITY) is True
