"""P5a (ADR-222): EU AI Act irreversible-latch core tests.

The latch is the security-critical heart of the optional EU AI Act layer. These
tests pin its hard contract:
- one-way ratchet: enable, upgrade (advisory->blocking) OK; downgrade refused.
- the latch can never be turned off (no disable path).
- tamper-evident: content edit / chain break / key swap -> tampered, fail closed.
- fail-closed: a tampered chain that ever enabled stays enabled (can't disable
  by tampering).
- audited override records a signed event, latch stays on.
- config defaults OFF.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graqle.compliance.eu_ai_act_latch import (
    EuAiActLatch,
    LatchDowngradeRefused,
    LatchError,
    LatchTamperError,
)

_T0 = "2026-06-08T00:00:00Z"
_T1 = "2026-06-08T00:01:00Z"
_T2 = "2026-06-08T00:02:00Z"


def _latch(tmp_path: Path) -> EuAiActLatch:
    return EuAiActLatch(tmp_path)


# ── happy path / ratchet ───────────────────────────────────────────────

def test_absent_latch_is_disabled(tmp_path):
    st = _latch(tmp_path).read_state()
    assert st.enabled is False
    assert st.mode is None
    assert st.tampered is False


def test_enable_then_read(tmp_path):
    L = _latch(tmp_path)
    st = L.enable(mode="advisory", risk_class="limited", ts=_T0)
    assert st.enabled is True
    assert st.mode == "advisory"
    assert st.risk_class == "limited"
    # re-read from disk is identical and clean
    st2 = L.read_state()
    assert st2.enabled is True and st2.mode == "advisory" and st2.tampered is False


def test_upgrade_advisory_to_blocking_allowed(tmp_path):
    L = _latch(tmp_path)
    L.enable(mode="advisory", risk_class="limited", ts=_T0)
    st = L.enable(mode="blocking", risk_class="high", ts=_T1)
    assert st.mode == "blocking"
    assert st.risk_class == "high"
    assert st.event_count == 2


def test_downgrade_blocking_to_advisory_refused(tmp_path):
    L = _latch(tmp_path)
    L.enable(mode="blocking", risk_class="high", ts=_T0)
    with pytest.raises(LatchDowngradeRefused):
        L.enable(mode="advisory", risk_class="high", ts=_T1)
    # state unchanged — still blocking
    assert L.read_state().mode == "blocking"


def test_no_disable_path_exists():
    # The latch API has NO method to set enabled=False — by design.
    assert not hasattr(EuAiActLatch, "disable")


def test_reassert_same_mode_allowed(tmp_path):
    L = _latch(tmp_path)
    L.enable(mode="blocking", risk_class="high", ts=_T0)
    st = L.enable(mode="blocking", risk_class="high", ts=_T1)  # equal mode OK
    assert st.mode == "blocking"
    assert st.event_count == 2


# ── override (D-1) ─────────────────────────────────────────────────────

def test_override_records_and_keeps_latch_on(tmp_path):
    L = _latch(tmp_path)
    L.enable(mode="blocking", risk_class="high", ts=_T0)
    st = L.record_override(
        justification="formatting only, no model logic", actor="harish",
        action="edit", ts=_T1,
    )
    assert st.override_count == 1
    # latch is NOT downgraded by an override
    assert st.enabled is True and st.mode == "blocking"


def test_override_requires_justification(tmp_path):
    L = _latch(tmp_path)
    L.enable(mode="blocking", risk_class="high", ts=_T0)
    with pytest.raises(LatchError):
        L.record_override(justification="  ", actor="x", action="y", ts=_T1)


def test_override_requires_enabled_latch(tmp_path):
    L = _latch(tmp_path)
    with pytest.raises(LatchError):
        L.record_override(justification="j", actor="x", action="y", ts=_T0)


# ── tamper evidence / fail-closed ──────────────────────────────────────

def _latch_file(tmp_path: Path) -> Path:
    return tmp_path / ".graqle" / "eu_ai_act_latch.jsonl"


def test_content_tamper_detected_and_fails_closed(tmp_path):
    L = _latch(tmp_path)
    L.enable(mode="blocking", risk_class="high", ts=_T0)
    p = _latch_file(tmp_path)
    ev = json.loads(p.read_text().splitlines()[0])
    ev["body"]["mode"] = "advisory"  # attempt to weaken via raw edit
    p.write_text(json.dumps(ev) + "\n")
    st = L.read_state()
    assert st.tampered is True
    # fail closed: stays enabled + blocking, the tamper cannot weaken it
    assert st.enabled is True
    assert st.mode == "blocking"


def test_chain_break_detected(tmp_path):
    L = _latch(tmp_path)
    L.enable(mode="advisory", risk_class="limited", ts=_T0)
    L.enable(mode="blocking", risk_class="high", ts=_T1)
    p = _latch_file(tmp_path)
    lines = p.read_text().splitlines()
    # drop the first event -> second event's prev_hash no longer matches genesis
    p.write_text(lines[1] + "\n")
    assert L.read_state().tampered is True


def test_key_swap_detected(tmp_path):
    # An attacker re-signs a forged event with a DIFFERENT key. The chain
    # requires one stable signing key, so the swap is detected.
    L = _latch(tmp_path)
    L.enable(mode="blocking", risk_class="high", ts=_T0)
    # forge a second latch (different key) and append its event
    import shutil
    other_dir = tmp_path / "other"
    other = EuAiActLatch(other_dir)
    other.enable(mode="blocking", risk_class="high", ts=_T1)
    forged = (other_dir / ".graqle" / "eu_ai_act_latch.jsonl").read_text().splitlines()[0]
    p = _latch_file(tmp_path)
    p.write_text(p.read_text() + forged + "\n")
    assert L.read_state().tampered is True


def test_write_over_tampered_chain_refused(tmp_path):
    L = _latch(tmp_path)
    L.enable(mode="blocking", risk_class="high", ts=_T0)
    p = _latch_file(tmp_path)
    ev = json.loads(p.read_text().splitlines()[0])
    ev["hash"] = "deadbeef" * 8
    p.write_text(json.dumps(ev) + "\n")
    with pytest.raises(LatchTamperError):
        L.enable(mode="blocking", risk_class="high", ts=_T1)


# ── fail-closed on IO / corruption (P5a Sentinel BLOCKER fix) ──────────

def test_read_state_never_raises_on_malformed_jsonl(tmp_path):
    # Realistic tamper: corrupt the JSON structure but the enable event bytes
    # remain — read_state must NOT raise and must fail closed = stay enabled.
    L = _latch(tmp_path)
    L.enable(mode="blocking", risk_class="high", ts=_T0)
    p = _latch_file(tmp_path)
    p.write_text(p.read_text() + "{ broken json with enable marker here\n")
    st = L.read_state()  # must not raise
    assert st.tampered is True
    assert st.enabled is True  # was enabled -> stays on through corruption


def test_read_state_garbage_only_is_not_falsely_enabled(tmp_path):
    # Pure garbage with no enable evidence must NOT be reported as enabled
    # (you cannot fake-enable the latch by writing junk).
    L = _latch(tmp_path)
    (tmp_path / ".graqle").mkdir(parents=True)
    _latch_file(tmp_path).write_text("random junk no markers\n")
    st = L.read_state()  # must not raise
    assert st.enabled is False


def test_read_state_fail_closed_when_key_corrupt(tmp_path):
    L = _latch(tmp_path)
    L.enable(mode="blocking", risk_class="high", ts=_T0)
    # corrupt the key file — read_state must still not raise
    (tmp_path / ".graqle" / "eu_ai_act_latch.key").write_bytes(b"not a key")
    st = L.read_state()
    assert st.enabled is True  # verification still works off embedded pub; clean
    # (the embedded pub in each event verifies the chain; private key is only for writes)


def test_empty_file_is_clean_disabled(tmp_path):
    L = _latch(tmp_path)
    (tmp_path / ".graqle").mkdir(parents=True)
    _latch_file(tmp_path).write_text("")  # empty file, never enabled
    st = L.read_state()
    assert st.enabled is False
    assert st.tampered is False


# ── config defaults ────────────────────────────────────────────────────

def test_config_defaults_off():
    from graqle.config.settings import GraqleConfig

    e = GraqleConfig().governance.eu_ai_act
    assert e.enabled is False
    assert e.mode == "blocking"
    assert e.risk_class == "high"


def test_config_loads_from_yaml():
    from graqle.config.settings import GraqleConfig

    c = GraqleConfig(**{"governance": {"eu_ai_act": {
        "enabled": True, "mode": "advisory", "risk_class": "limited"}}})
    e = c.governance.eu_ai_act
    assert e.enabled is True and e.mode == "advisory" and e.risk_class == "limited"
