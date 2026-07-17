"""CR-LIC-01 — tier-derived limits resolution + warn-only high-water-mark meter."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from graqle.licensing.limits import (
    ANONYMOUS_MAX_NODES,
    TIER_MAX_NODES,
    EffectiveLimits,
    resolve_limits,
)
from graqle.licensing.manager import LicenseTier
from graqle.licensing.meter import METER_FILENAME, MeterStatus, UsageMeter


# ---------------------------------------------------------------------------
# resolve_limits
# ---------------------------------------------------------------------------


def test_anonymous_gets_500():
    limits = resolve_limits(None)
    assert limits.max_nodes == ANONYMOUS_MAX_NODES == 500
    assert limits.source == "anonymous"
    assert not limits.unlimited


def test_registered_free_key_gets_1000():
    lic = SimpleNamespace(tier=LicenseTier.FREE, features=set())
    limits = resolve_limits(lic)
    assert limits.max_nodes == 1_000
    assert limits.source == "tier:free"


@pytest.mark.parametrize(
    "tier", [LicenseTier.PRO, LicenseTier.TEAM, LicenseTier.ENTERPRISE]
)
def test_paid_tiers_uncapped(tier):
    limits = resolve_limits(SimpleNamespace(tier=tier, features=set()))
    assert limits.unlimited
    assert limits.max_nodes is None
    assert limits.warn_threshold() is None


def test_tier_accepts_string_values():
    limits = resolve_limits(SimpleNamespace(tier="free", features=set()))
    assert limits.max_nodes == TIER_MAX_NODES[LicenseTier.FREE]


def test_unknown_tier_fails_to_free_cap_not_unlimited():
    limits = resolve_limits(SimpleNamespace(tier="platinum", features=set()))
    assert limits.max_nodes == TIER_MAX_NODES[LicenseTier.FREE]
    assert limits.source == "tier:unknown"


def test_signed_feature_override_wins():
    lic = SimpleNamespace(tier=LicenseTier.FREE, features={"max_nodes:5000"})
    limits = resolve_limits(lic)
    assert limits.max_nodes == 5_000
    assert limits.source == "override"


def test_largest_override_wins():
    lic = SimpleNamespace(
        tier=LicenseTier.FREE, features={"max_nodes:2000", "max_nodes:800"}
    )
    assert resolve_limits(lic).max_nodes == 2_000


@pytest.mark.parametrize(
    "bad", ["max_nodes:", "max_nodes:abc", "max_nodes:-5", "max_nodes:0", 42]
)
def test_malformed_overrides_ignored(bad):
    lic = SimpleNamespace(tier=LicenseTier.FREE, features={bad} if isinstance(bad, str) else {bad})
    limits = resolve_limits(lic)
    assert limits.max_nodes == TIER_MAX_NODES[LicenseTier.FREE]
    assert limits.source == "tier:free"


def test_warn_threshold_is_80_percent():
    assert EffectiveLimits(max_nodes=500, source="anonymous").warn_threshold() == 400


# ---------------------------------------------------------------------------
# UsageMeter
# ---------------------------------------------------------------------------


def _anon() -> EffectiveLimits:
    return resolve_limits(None)


def test_meter_ok_below_warn(tmp_path):
    reading = UsageMeter(tmp_path).record(100, _anon())
    assert reading.status is MeterStatus.OK
    assert reading.high_water_mark == 100
    assert reading.percent_used == 20


def test_meter_warns_at_80_percent(tmp_path):
    reading = UsageMeter(tmp_path).record(400, _anon())
    assert reading.status is MeterStatus.WARN


def test_meter_at_cap(tmp_path):
    reading = UsageMeter(tmp_path).record(500, _anon())
    assert reading.status is MeterStatus.AT_CAP
    assert reading.percent_used == 100


def test_meter_never_blocks_above_cap(tmp_path):
    # Warn-only phase: recording far beyond the cap still succeeds.
    reading = UsageMeter(tmp_path).record(15_453, _anon())
    assert reading.status is MeterStatus.AT_CAP
    assert reading.high_water_mark == 15_453


def test_high_water_mark_never_decreases(tmp_path):
    meter = UsageMeter(tmp_path)
    meter.record(450, _anon())
    reading = meter.record(50, _anon())
    assert reading.node_count == 50
    assert reading.high_water_mark == 450


def test_meter_persists_across_instances(tmp_path):
    UsageMeter(tmp_path).record(321, _anon())
    assert UsageMeter(tmp_path).high_water_mark == 321
    data = json.loads((tmp_path / METER_FILENAME).read_text(encoding="utf-8"))
    assert data["high_water_mark"] == 321
    assert data["schema_version"] == 1


def test_corrupt_meter_file_treated_as_empty(tmp_path):
    (tmp_path / METER_FILENAME).write_text("{not json", encoding="utf-8")
    meter = UsageMeter(tmp_path)
    assert meter.high_water_mark == 0
    reading = meter.record(10, _anon())
    assert reading.status is MeterStatus.OK
    assert reading.high_water_mark == 10


def test_unlimited_license_always_ok(tmp_path):
    limits = resolve_limits(SimpleNamespace(tier=LicenseTier.PRO, features=set()))
    reading = UsageMeter(tmp_path).record(1_000_000, limits)
    assert reading.status is MeterStatus.OK
    assert reading.percent_used is None


def test_meter_skips_rewrite_when_hwm_unchanged(tmp_path):
    # Shared-repo diff churn guard: a scan that doesn't advance the HWM must
    # not touch the file (pre-merge debate point 3).
    meter = UsageMeter(tmp_path)
    meter.record(400, _anon())
    before = (tmp_path / METER_FILENAME).read_bytes()
    meter.record(400, _anon())
    meter.record(120, _anon())
    assert (tmp_path / METER_FILENAME).read_bytes() == before


def test_meter_self_gitignores(tmp_path):
    UsageMeter(tmp_path).record(10, _anon())
    gi = tmp_path / ".gitignore"
    assert gi.exists()
    assert "meter.json" in gi.read_text(encoding="utf-8")


def test_meter_leaves_existing_gitignore_alone(tmp_path):
    (tmp_path / ".gitignore").write_text("custom\n", encoding="utf-8")
    UsageMeter(tmp_path).record(10, _anon())
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == "custom\n"


def test_meter_tolerates_bad_node_count(tmp_path):
    reading = UsageMeter(tmp_path).record("garbage", _anon())  # type: ignore[arg-type]
    assert reading.status is MeterStatus.OK
    assert reading.node_count == 0
