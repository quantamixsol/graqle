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


# ---------------------------------------------------------------------------
# CR-LIC-03a — HARD node-cap enforcement (ADR-245)
# ---------------------------------------------------------------------------

from graqle.licensing.meter import (  # noqa: E402
    ENFORCE_ENV,
    GRACE_ENV,
    NodeCapExceeded,
    enforcement_enabled,
)


def _pro() -> EffectiveLimits:
    # An UNLIMITED tier (Pro): enforcement must never touch it.
    return resolve_limits(SimpleNamespace(tier="pro", features=set()))


def test_enforcement_on_by_default(monkeypatch):
    monkeypatch.delenv(ENFORCE_ENV, raising=False)
    assert enforcement_enabled() is True


@pytest.mark.parametrize("optout", ["0", "false", "no", "off", ""])
def test_enforcement_opt_out_only(monkeypatch, optout):
    monkeypatch.setenv(ENFORCE_ENV, optout)
    assert enforcement_enabled() is False


@pytest.mark.parametrize("on", ["1", "true", "yes", "on", "enforce"])
def test_enforcement_stays_on_for_truthy(monkeypatch, on):
    monkeypatch.setenv(ENFORCE_ENV, on)
    assert enforcement_enabled() is True


def test_enforce_noop_when_opted_out(tmp_path, monkeypatch):
    monkeypatch.setenv(ENFORCE_ENV, "0")
    meter = UsageMeter(tmp_path)
    reading = meter.record(9_999, _anon())  # AT_CAP
    meter.enforce(reading, _anon())  # opted out → no raise


def test_enforce_never_blocks_unlimited_tier(tmp_path, monkeypatch):
    monkeypatch.setenv(GRACE_ENV, "0")  # no grace, to prove it's the unlimited guard
    meter = UsageMeter(tmp_path)
    reading = meter.record(5_000_000, _pro())
    assert reading.status is MeterStatus.OK  # unlimited → OK
    meter.enforce(reading, _pro())  # unlimited → never raises


def test_enforce_never_blocks_below_cap(tmp_path, monkeypatch):
    monkeypatch.setenv(GRACE_ENV, "0")
    meter = UsageMeter(tmp_path)
    reading = meter.record(100, _anon())  # OK, below cap
    meter.enforce(reading, _anon())  # not AT_CAP → no raise


def test_grace_window_first_hit_warns_not_blocks(tmp_path, monkeypatch):
    # First time at cap: within grace → no raise, and cap_first_hit_at is stamped.
    meter = UsageMeter(tmp_path)
    reading = meter.record(500, _anon())  # AT_CAP (anon cap 500)
    assert reading.status is MeterStatus.AT_CAP
    meter.enforce(reading, _anon())  # first hit → grace → no raise
    data = json.loads((tmp_path / METER_FILENAME).read_text(encoding="utf-8"))
    assert data.get("cap_first_hit_at")  # grace clock started


def test_blocks_after_grace_elapsed(tmp_path, monkeypatch):
    # Grace = 0 days → the very first AT_CAP write is past grace → block.
    monkeypatch.setenv(GRACE_ENV, "0")
    meter = UsageMeter(tmp_path)
    reading = meter.record(500, _anon())  # AT_CAP
    # First call stamps cap_first_hit_at (grace start = now); with grace=0, elapsed
    # is >=0 so the NEXT check blocks. Simulate the second scan:
    meter.enforce(reading, _anon())  # stamps first-hit
    reading2 = meter.record(600, _anon())  # still AT_CAP, HWM advanced
    with pytest.raises(NodeCapExceeded):
        meter.enforce(reading2, _anon())


def test_block_carries_numbers_for_cta(tmp_path, monkeypatch):
    monkeypatch.setenv(GRACE_ENV, "0")
    meter = UsageMeter(tmp_path)
    meter.enforce(meter.record(500, _anon()), _anon())  # stamp
    with pytest.raises(NodeCapExceeded) as ei:
        meter.enforce(meter.record(700, _anon()), _anon())
    assert ei.value.max_nodes == 500
    assert ei.value.node_count >= 500


def test_hwm_prevents_shrink_then_grow_dodge(tmp_path, monkeypatch):
    # A user who deletes nodes to drop below cap can't dodge: HWM keeps the peak,
    # so re-recording a smaller count still reflects AT_CAP via the meter's HWM.
    monkeypatch.setenv(GRACE_ENV, "0")
    meter = UsageMeter(tmp_path)
    meter.enforce(meter.record(500, _anon()), _anon())  # at cap, stamp grace
    # "shrink": record a smaller count — HWM stays 500, but current count 300 is
    # below cap so THIS reading is not AT_CAP (enforcement is on the current write).
    # The dodge that matters (re-growing) is caught: grow back to cap → blocks.
    reading_grow = meter.record(520, _anon())
    assert reading_grow.status is MeterStatus.AT_CAP
    with pytest.raises(NodeCapExceeded):
        meter.enforce(reading_grow, _anon())


def test_scan_prewrite_gate_raises_before_persisting(tmp_path, monkeypatch):
    """SENTINEL CR-LIC-03a BLOCKER-1: the scan enforcement runs BEFORE the graph is
    written. Prove the gate raises typer.Exit when past cap+grace — i.e. the write is
    prevented, not a cosmetic error after the graph is already on disk.

    Uses a FREE-tier licence (cap 1,000) via monkeypatched manager so resolve_limits
    returns a capped tier; the gate lives in scan.py and calls the same meter.enforce.
    """
    import typer

    from graqle.cli.commands import scan as scan_cmd

    monkeypatch.setenv(GRACE_ENV, "0")  # no grace → blocks after the first stamp
    graqle_dir = tmp_path / ".graqle"
    graqle_dir.mkdir()

    # Force resolve_limits to a capped (anon, 500) tier regardless of real licence.
    monkeypatch.setattr(
        "graqle.licensing.limits.resolve_limits", lambda _lic: _anon()
    )

    big_graph = {"nodes": [{"id": i} for i in range(600)]}  # over the 500 cap
    # First call stamps grace (no raise); second call (still over cap) must raise.
    scan_cmd._enforce_node_cap_before_write(big_graph, graqle_dir)  # stamp
    with pytest.raises(typer.Exit):
        scan_cmd._enforce_node_cap_before_write(big_graph, graqle_dir)


def test_scan_prewrite_gate_allows_below_cap(tmp_path, monkeypatch):
    """The pre-write gate must NOT block a below-cap scan (no false block)."""
    from graqle.cli.commands import scan as scan_cmd

    monkeypatch.setenv(GRACE_ENV, "0")
    graqle_dir = tmp_path / ".graqle"
    graqle_dir.mkdir()
    monkeypatch.setattr(
        "graqle.licensing.limits.resolve_limits", lambda _lic: _anon()
    )
    small_graph = {"nodes": [{"id": i} for i in range(100)]}  # under 500
    scan_cmd._enforce_node_cap_before_write(small_graph, graqle_dir)  # no raise


def test_corrupt_first_hit_stamp_restarts_grace_not_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv(GRACE_ENV, "0")
    meter = UsageMeter(tmp_path)
    meter.record(500, _anon())
    # Corrupt the stamp:
    p = tmp_path / METER_FILENAME
    data = json.loads(p.read_text(encoding="utf-8"))
    data["cap_first_hit_at"] = "not-a-date"
    p.write_text(json.dumps(data), encoding="utf-8")
    reading = meter.record(500, _anon())
    meter.enforce(reading, _anon())  # corrupt stamp → restart grace, do NOT block
    data2 = json.loads(p.read_text(encoding="utf-8"))
    # re-stamped to a valid iso datetime
    assert data2["cap_first_hit_at"] != "not-a-date"
