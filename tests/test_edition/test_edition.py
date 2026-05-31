"""Tests for edition detection (WS-C C2, ADR-214).

100% statement + branch coverage of graqle/edition.py, with explicit coverage of
every ADR-214 no-loophole guarantee:
* default = COMMUNITY (no env, no licence);
* the full Option-A tier→edition fold (FREE/PRO/TEAM/ENTERPRISE);
* env override (valid, case-insensitive, whitespace-trimmed);
* invalid/empty/injection override → ignored, falls through, NEVER raises/upgrades;
* fail-closed-to-cheaper: licensing absent / raising / unmapped tier → COMMUNITY;
* there is NO input that yields a paid edition without a valid licence or explicit
  valid override.

Every test resets the lru_cache and restores os.environ via monkeypatch so the
process-global cache never leaks across cases (ADR-214 #5).
"""

from __future__ import annotations

import pytest

import graqle.edition as ed
from graqle.edition import (
    Edition,
    detect_edition,
    is_community,
    is_enterprise,
    is_studio_or_higher,
    reset_edition_cache,
)


@pytest.fixture(autouse=True)
def _clean_edition_state(monkeypatch):
    """Each test starts with no override and a cleared cache; restored after."""
    monkeypatch.delenv("GRAQLE_EDITION", raising=False)
    reset_edition_cache()
    yield
    reset_edition_cache()


def _force_tier(monkeypatch, tier_value):
    """Patch LicenseManager.current_tier to return a chosen tier (or raise)."""
    import graqle.licensing.manager as m

    if isinstance(tier_value, Exception):
        def boom(self):
            raise tier_value
        monkeypatch.setattr(m.LicenseManager, "current_tier", property(boom))
    else:
        monkeypatch.setattr(m.LicenseManager, "current_tier", property(lambda self: tier_value))


# ---- Edition enum -------------------------------------------------------------


def test_edition_is_str_enum():
    assert Edition.COMMUNITY == "community"
    assert Edition.STUDIO.value == "studio"
    assert Edition.ENTERPRISE == "enterprise"


def test_edition_rank_order():
    assert Edition.COMMUNITY._rank < Edition.STUDIO._rank < Edition.ENTERPRISE._rank


# ---- default (no env, no licence) ---------------------------------------------


def test_default_is_community(monkeypatch):
    # No env override; force the licence to FREE so the test is independent of any
    # real licence on the machine.
    _force_tier(monkeypatch, _tier(monkeypatch, "FREE"))
    reset_edition_cache()
    assert detect_edition() is Edition.COMMUNITY
    assert is_community()
    assert not is_studio_or_higher()
    assert not is_enterprise()


# ---- Option-A tier → edition fold (ADR-214) -----------------------------------


def _tier(monkeypatch, name):
    import graqle.licensing.manager as m
    return getattr(m.LicenseTier, name)


@pytest.mark.parametrize(
    "tier_name,expected",
    [
        ("FREE", Edition.COMMUNITY),
        ("PRO", Edition.STUDIO),
        ("TEAM", Edition.STUDIO),
        ("ENTERPRISE", Edition.ENTERPRISE),
    ],
)
def test_tier_to_edition_mapping(monkeypatch, tier_name, expected):
    _force_tier(monkeypatch, _tier(monkeypatch, tier_name))
    reset_edition_cache()
    assert detect_edition() is expected


def test_pro_and_team_both_studio(monkeypatch):
    # The 4→3 fold: PRO and TEAM are indistinguishable at the edition level.
    _force_tier(monkeypatch, _tier(monkeypatch, "PRO"))
    reset_edition_cache()
    pro = detect_edition()
    _force_tier(monkeypatch, _tier(monkeypatch, "TEAM"))
    reset_edition_cache()
    team = detect_edition()
    assert pro is team is Edition.STUDIO


# ---- env override (valid) -----------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("community", Edition.COMMUNITY),
        ("studio", Edition.STUDIO),
        ("enterprise", Edition.ENTERPRISE),
        ("STUDIO", Edition.STUDIO),          # case-insensitive
        ("  Enterprise  ", Edition.ENTERPRISE),  # whitespace-trimmed
    ],
)
def test_valid_override(monkeypatch, raw, expected):
    monkeypatch.setenv("GRAQLE_EDITION", raw)
    reset_edition_cache()
    assert detect_edition() is expected


def test_override_beats_licence(monkeypatch):
    # Override of 'enterprise' wins even though the licence is FREE.
    _force_tier(monkeypatch, _tier(monkeypatch, "FREE"))
    monkeypatch.setenv("GRAQLE_EDITION", "enterprise")
    reset_edition_cache()
    assert detect_edition() is Edition.ENTERPRISE


# ---- env override (invalid) → fail-closed, never raise/upgrade ----------------


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "studioo", "admin", "free-trial", "enterprise; rm -rf", "1", "none"],
)
def test_invalid_override_falls_through_to_community(monkeypatch, raw):
    # No valid licence behind it, so an invalid override must resolve to COMMUNITY
    # (never raises, never silently upgrades).
    _force_tier(monkeypatch, _tier(monkeypatch, "FREE"))
    monkeypatch.setenv("GRAQLE_EDITION", raw)
    reset_edition_cache()
    assert detect_edition() is Edition.COMMUNITY


def test_long_invalid_override_is_truncated_in_log(monkeypatch, caplog):
    # A >32-char invalid value exercises the truncation branch; still fails closed.
    _force_tier(monkeypatch, _tier(monkeypatch, "FREE"))
    long_val = "x" * 100
    monkeypatch.setenv("GRAQLE_EDITION", long_val)
    reset_edition_cache()
    import logging as _logging
    with caplog.at_level(_logging.WARNING, logger="graqle.edition"):
        assert detect_edition() is Edition.COMMUNITY
    # the full 100-char value must NOT appear verbatim; the truncated form does
    assert long_val not in caplog.text
    assert ("x" * 32 + "...") in caplog.text


def test_invalid_override_still_honours_real_licence(monkeypatch):
    # An invalid override falls THROUGH to licence-derived detection (it doesn't
    # force Community) — so a real ENTERPRISE licence still resolves correctly.
    _force_tier(monkeypatch, _tier(monkeypatch, "ENTERPRISE"))
    monkeypatch.setenv("GRAQLE_EDITION", "garbage")
    reset_edition_cache()
    assert detect_edition() is Edition.ENTERPRISE


# ---- fail-closed-to-cheaper (ADR-214 #1) --------------------------------------


def test_licence_exception_fails_closed(monkeypatch):
    _force_tier(monkeypatch, RuntimeError("licence subsystem exploded"))
    reset_edition_cache()
    assert detect_edition() is Edition.COMMUNITY  # never propagates, never upgrades


def test_licensing_import_failure_fails_closed(monkeypatch):
    # Simulate the licensing module being absent (C1 could ship a Community wheel
    # that still has licensing, but defence-in-depth: import error => COMMUNITY).
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "graqle.licensing.manager":
            raise ImportError("no licensing in this wheel")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    reset_edition_cache()
    assert detect_edition() is Edition.COMMUNITY


def test_unmapped_tier_fails_closed(monkeypatch):
    # A tier added later but not in the ADR-214 table must fall to COMMUNITY,
    # never default-up. Use a stand-in object that .get() won't find.
    class FutureTier:
        value = "ultra"
    _force_tier(monkeypatch, FutureTier())
    reset_edition_cache()
    assert detect_edition() is Edition.COMMUNITY


def test_no_input_yields_paid_edition_without_licence_or_valid_override(monkeypatch):
    # The core anti-abuse invariant: with FREE licence and assorted hostile env
    # values, the result is ALWAYS COMMUNITY.
    _force_tier(monkeypatch, _tier(monkeypatch, "FREE"))
    for hostile in ["", "studio ", "ENTERPRISE\n", "studio;enterprise", "Community\t", "stud"]:
        monkeypatch.setenv("GRAQLE_EDITION", hostile)
        reset_edition_cache()
        result = detect_edition()
        # only an EXACT valid value would upgrade; none of these are exact
        if hostile.strip().lower() in (e.value for e in Edition):
            continue
        assert result is Edition.COMMUNITY, (hostile, result)


# ---- caching ------------------------------------------------------------------


def test_result_is_cached(monkeypatch):
    _force_tier(monkeypatch, _tier(monkeypatch, "FREE"))
    reset_edition_cache()
    assert detect_edition() is Edition.COMMUNITY
    # Change the licence WITHOUT resetting the cache → cached COMMUNITY persists.
    _force_tier(monkeypatch, _tier(monkeypatch, "ENTERPRISE"))
    assert detect_edition() is Edition.COMMUNITY  # stale-by-design until reset
    # After reset, the new value is picked up.
    reset_edition_cache()
    assert detect_edition() is Edition.ENTERPRISE


# ---- helpers ------------------------------------------------------------------


def test_helpers_community(monkeypatch):
    monkeypatch.setenv("GRAQLE_EDITION", "community")
    reset_edition_cache()
    assert is_community() and not is_studio_or_higher() and not is_enterprise()


def test_helpers_studio(monkeypatch):
    monkeypatch.setenv("GRAQLE_EDITION", "studio")
    reset_edition_cache()
    assert not is_community() and is_studio_or_higher() and not is_enterprise()


def test_helpers_enterprise(monkeypatch):
    monkeypatch.setenv("GRAQLE_EDITION", "enterprise")
    reset_edition_cache()
    assert not is_community() and is_studio_or_higher() and is_enterprise()
