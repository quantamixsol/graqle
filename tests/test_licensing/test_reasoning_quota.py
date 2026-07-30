"""W3 (ADR-245) — free monthly reasoning-quota wall."""

from __future__ import annotations

import json

import pytest

from graqle.licensing.reasoning_quota import (
    FREE_REASONS_PER_MONTH,
    QUOTA_FILENAME,
    ReasoningQuota,
    ReasoningQuotaExceeded,
    quota_enforcement_enabled,
)


@pytest.fixture(autouse=True)
def _free_tier(monkeypatch):
    """Default every test to a FREE (unverified) tier unless it overrides."""
    monkeypatch.setattr(
        "graqle.licensing.reasoning_quota._paid_tier", lambda: False
    )
    monkeypatch.delenv("GRAQLE_ENFORCE_CAPS", raising=False)


def _paid(monkeypatch):
    monkeypatch.setattr(
        "graqle.licensing.reasoning_quota._paid_tier", lambda: True
    )


# ── enforcement flag (shared with node-cap) ─────────────────────────────────

def test_enforcement_on_by_default(monkeypatch):
    monkeypatch.delenv("GRAQLE_ENFORCE_CAPS", raising=False)
    assert quota_enforcement_enabled() is True


@pytest.mark.parametrize("optout", ["0", "false", "no", "off", ""])
def test_enforcement_opt_out_only(monkeypatch, optout):
    monkeypatch.setenv("GRAQLE_ENFORCE_CAPS", optout)
    assert quota_enforcement_enabled() is False


# ── free-tier counting + block ──────────────────────────────────────────────

def test_free_records_and_allows_under_cap(tmp_path):
    q = ReasoningQuota(tmp_path)
    r = q.check_and_record()
    assert r.allowed and r.used == 1 and r.limit == FREE_REASONS_PER_MONTH
    # persisted
    data = json.loads((tmp_path / QUOTA_FILENAME).read_text(encoding="utf-8"))
    assert sum(v for k, v in data.items() if k != "schema_version") == 1


def test_free_blocks_after_cap(tmp_path):
    q = ReasoningQuota(tmp_path)
    for _ in range(FREE_REASONS_PER_MONTH):
        q.check_and_record()
    with pytest.raises(ReasoningQuotaExceeded):
        q.check_and_record()


def test_block_carries_numbers(tmp_path):
    q = ReasoningQuota(tmp_path)
    for _ in range(FREE_REASONS_PER_MONTH):
        q.check_and_record()
    with pytest.raises(ReasoningQuotaExceeded) as ei:
        q.check_and_record()
    assert ei.value.used == FREE_REASONS_PER_MONTH
    assert ei.value.limit == FREE_REASONS_PER_MONTH


# ── paid tier: unlimited, never blocks ──────────────────────────────────────

def test_paid_tier_unlimited(tmp_path, monkeypatch):
    _paid(monkeypatch)
    q = ReasoningQuota(tmp_path)
    for _ in range(FREE_REASONS_PER_MONTH * 3):
        r = q.check_and_record()
        assert r.allowed and r.limit == -1  # unlimited
    # paid path does not even write the counter
    assert not (tmp_path / QUOTA_FILENAME).exists()


# ── internal reasoning is EXEMPT (no W2/W3 double-charge) ────────────────────

def test_internal_reasoning_exempt(tmp_path):
    q = ReasoningQuota(tmp_path)
    # Way past the cap, but internal=True → never blocks, never counts.
    for _ in range(FREE_REASONS_PER_MONTH * 2):
        r = q.check_and_record(internal=True)
        assert r.allowed
    # A subsequent user (non-internal) call still starts at 1 (internal didn't count).
    r = q.check_and_record()
    assert r.used == 1


# ── opt-out disables the block ──────────────────────────────────────────────

def test_opt_out_never_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAQLE_ENFORCE_CAPS", "0")
    q = ReasoningQuota(tmp_path)
    for _ in range(FREE_REASONS_PER_MONTH + 5):
        q.check_and_record()  # opted out → never raises


# ── fail-open: metering error never breaks reasoning ────────────────────────

def test_fail_open_on_meter_error(tmp_path, monkeypatch):
    q = ReasoningQuota(tmp_path)

    def _boom(*a, **k):
        raise OSError("disk gone")

    monkeypatch.setattr(q, "_load", _boom)
    # Must NOT raise (fail-open) — reasoning never breaks on a quota fault.
    r = q.check_and_record()
    assert r.allowed


def test_malformed_json_fails_open(tmp_path):
    """A corrupt/partial quota file must fail-open (treated as empty), never crash."""
    (tmp_path / QUOTA_FILENAME).write_text('{"2026-07": "NaN", tru', encoding="utf-8")
    q = ReasoningQuota(tmp_path)
    # Load treats the bad file as empty → this is the 1st record, allowed.
    r = q.check_and_record()
    assert r.allowed


def test_quota_exceeded_escapes_fail_open(tmp_path):
    """MAJOR-2 regression: the block must NOT be swallowed by the fail-open handler.
    Even when the quota is exhausted, ReasoningQuotaExceeded propagates."""
    q = ReasoningQuota(tmp_path)
    for _ in range(FREE_REASONS_PER_MONTH):
        q.check_and_record()
    # This must RAISE (not silently pass via fail-open).
    with pytest.raises(ReasoningQuotaExceeded):
        q.check_and_record()


def test_peek_does_not_record(tmp_path):
    q = ReasoningQuota(tmp_path)
    q.peek()
    q.peek()
    # peek never writes the counter
    assert not (tmp_path / QUOTA_FILENAME).exists()


# ── tier-trust: uses VERIFIED tier, not a raw env/key (CR-LIC-03b alignment) ─

def test_uses_verified_tier_not_raw_env(tmp_path, monkeypatch):
    # Setting a raw env tier must NOT grant unlimited — only a verified paid licence does.
    monkeypatch.setenv("GRAQLE_LICENSE_TIER", "enterprise")  # unverified
    # _paid_tier (verified) is False by the autouse fixture → still FREE-capped.
    q = ReasoningQuota(tmp_path)
    for _ in range(FREE_REASONS_PER_MONTH):
        q.check_and_record()
    with pytest.raises(ReasoningQuotaExceeded):
        q.check_and_record()  # unverified env did NOT buy unlimited


# ── Pre-merge review findings (F2, F3), pinned as regression tests ──────────

def test_peek_matches_check_and_record_when_enforcement_disabled(monkeypatch, tmp_path):
    """F3: peek() checked only the tier, so it disagreed with check_and_record.

    With enforcement opted out at the cap, check_and_record ALLOWS the call; peek()
    reported allowed=False. Any status surface reading peek would have shown a user
    'blocked' while their calls were succeeding.
    """
    import datetime

    from graqle.licensing.reasoning_quota import (
        FREE_REASONS_PER_MONTH,
        ReasoningQuota,
    )

    monkeypatch.setenv("GRAQLE_ENFORCE_CAPS", "0")
    month = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m")
    (tmp_path / "reasoning_quota.json").write_text(
        json.dumps({month: FREE_REASONS_PER_MONTH}), encoding="utf-8"
    )
    quota = ReasoningQuota(tmp_path)

    assert quota.peek().allowed is True
    assert quota.check_and_record().allowed is True  # the two must agree


def test_old_months_are_pruned(monkeypatch, tmp_path):
    """F2: month keys accumulated forever — nothing trimmed the file."""
    import datetime

    from graqle.licensing.reasoning_quota import ReasoningQuota

    monkeypatch.delenv("GRAQLE_ENFORCE_CAPS", raising=False)
    seed = {f"{y}-{m:02d}": 1 for y in (2020, 2021, 2022) for m in range(1, 13)}
    seed["schema_version"] = 1
    (tmp_path / "reasoning_quota.json").write_text(json.dumps(seed), encoding="utf-8")

    ReasoningQuota(tmp_path).check_and_record()
    after = json.loads((tmp_path / "reasoning_quota.json").read_text(encoding="utf-8"))

    stale = [k for k in after if k.startswith(("2020-", "2021-", "2022-"))]
    assert not stale, f"old months not pruned: {stale}"
    assert after["schema_version"] == 1, "pruning must not eat non-month keys"
    assert datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m") in after
