"""Tests for the ed25519 key-custody manifest (R25-EU01 Task 1.7 / C-P2-1).

Covers the validity window, the monotonic ACTIVE→RETIRED→REVOKED lifecycle, and
the sign/verify trust rules. Uses real ed25519 keys from ``cryptography`` (a core
dependency) — no mocks of the crypto primitives, so the proofs are genuine.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from graqle.governance.custody import (
    Ed25519KeyManifest,
    KeyEntry,
    KeyManifestError,
    KeyState,
)
from graqle.governance.custody.ed25519_key_manifest import (
    IllegalKeyTransitionError,
    KeyNotSignableError,
    UnknownKidError,
)

UTC = timezone.utc
T0 = datetime(2026, 4, 1, tzinfo=UTC)  # window start
T_MID = datetime(2026, 5, 15, tzinfo=UTC)  # within window
T_END = datetime(2026, 7, 1, tzinfo=UTC)  # window end
T_AFTER = datetime(2026, 8, 1, tzinfo=UTC)  # after window
T_BEFORE = datetime(2026, 3, 1, tzinfo=UTC)  # before window


def _keypair():
    priv = Ed25519PrivateKey.generate()
    return priv, priv.public_key()


def _manifest_with_active(kid="graqle-sdk-signing-2026-Q2", with_private=True):
    priv, pub = _keypair()
    m = Ed25519KeyManifest()
    m.register(
        kid,
        pub,
        valid_from=T0,
        valid_until=T_END,
        private_key=priv if with_private else None,
    )
    return m, kid, priv, pub


# ---- registration ----------------------------------------------------------


class TestRegistration:
    def test_register_returns_active_entry(self):
        m, kid, _, pub = _manifest_with_active()
        entry = m.get(kid)
        assert isinstance(entry, KeyEntry)
        assert entry.kid == kid
        assert entry.state is KeyState.ACTIVE
        assert entry.public_key is pub

    def test_kids_lists_registered(self):
        m, kid, _, _ = _manifest_with_active()
        assert m.kids() == (kid,)

    @pytest.mark.parametrize("bad", ["", None, 123])
    def test_empty_or_nonstring_kid_raises(self, bad):
        m = Ed25519KeyManifest()
        _, pub = _keypair()
        with pytest.raises(ValueError):
            m.register(bad, pub, valid_from=T0, valid_until=T_END)

    def test_inverted_window_raises(self):
        m = Ed25519KeyManifest()
        _, pub = _keypair()
        with pytest.raises(ValueError, match="valid_until precedes valid_from"):
            m.register("k", pub, valid_from=T_END, valid_until=T0)

    def test_duplicate_kid_refused(self):
        m, kid, _, _ = _manifest_with_active()
        _, pub2 = _keypair()
        with pytest.raises(ValueError, match="already registered"):
            m.register(kid, pub2, valid_from=T0, valid_until=T_END)

    def test_get_unknown_kid_raises(self):
        m = Ed25519KeyManifest()
        with pytest.raises(UnknownKidError):
            m.get("nope")
        # also a KeyError subclass
        with pytest.raises(KeyError):
            m.get("nope")

    def test_verify_only_registration_without_private_key(self):
        m, kid, _, _ = _manifest_with_active(with_private=False)
        # can verify-trust but cannot sign
        assert m.get(kid).is_verify_trusted(T_MID) is True
        with pytest.raises(KeyNotSignableError, match="no private key is held"):
            m.sign(kid, b"msg", at=T_MID)


# ---- validity window -------------------------------------------------------


class TestValidityWindow:
    def test_within_window_inclusive_bounds(self):
        entry = _manifest_with_active()[0].get("graqle-sdk-signing-2026-Q2")
        assert entry.is_within_window(T0) is True  # inclusive start
        assert entry.is_within_window(T_END) is True  # inclusive end
        assert entry.is_within_window(T_MID) is True

    def test_outside_window(self):
        entry = _manifest_with_active()[0].get("graqle-sdk-signing-2026-Q2")
        assert entry.is_within_window(T_BEFORE) is False
        assert entry.is_within_window(T_AFTER) is False

    def test_naive_datetime_treated_as_utc(self):
        entry = _manifest_with_active()[0].get("graqle-sdk-signing-2026-Q2")
        naive_mid = datetime(2026, 5, 15)  # no tzinfo
        assert entry.is_within_window(naive_mid) is True

    def test_aware_non_utc_datetime_converted(self):
        entry = _manifest_with_active()[0].get("graqle-sdk-signing-2026-Q2")
        # 2026-04-01T01:00+02:00 == 2026-03-31T23:00Z -> just BEFORE the window
        before_in_other_tz = datetime(2026, 4, 1, 1, 0, tzinfo=timezone(timedelta(hours=2)))
        assert entry.is_within_window(before_in_other_tz) is False


# ---- lifecycle -------------------------------------------------------------


class TestLifecycle:
    def test_active_can_sign_and_verify(self):
        e = _manifest_with_active()[0].get("graqle-sdk-signing-2026-Q2")
        assert e.can_sign(T_MID) is True
        assert e.is_verify_trusted(T_MID) is True

    def test_retire_is_verify_only(self):
        m, kid, _, _ = _manifest_with_active()
        m.retire(kid)
        e = m.get(kid)
        assert e.state is KeyState.RETIRED
        assert e.can_sign(T_MID) is False
        assert e.is_verify_trusted(T_MID) is True

    def test_revoke_rejects_everything(self):
        m, kid, _, _ = _manifest_with_active()
        m.revoke(kid)
        e = m.get(kid)
        assert e.state is KeyState.REVOKED
        assert e.can_sign(T_MID) is False
        assert e.is_verify_trusted(T_MID) is False

    def test_active_to_retired_to_revoked_chain(self):
        m, kid, _, _ = _manifest_with_active()
        assert m.retire(kid).state is KeyState.RETIRED
        assert m.revoke(kid).state is KeyState.REVOKED

    def test_active_can_jump_straight_to_revoked(self):
        m, kid, _, _ = _manifest_with_active()
        assert m.revoke(kid).state is KeyState.REVOKED

    def test_cannot_un_retire(self):
        m, kid, _, _ = _manifest_with_active()
        m.retire(kid)
        # retiring again (same rank) is illegal, and there is no "activate"
        with pytest.raises(IllegalKeyTransitionError):
            m.retire(kid)

    def test_cannot_un_revoke(self):
        m, kid, _, _ = _manifest_with_active()
        m.revoke(kid)
        with pytest.raises(IllegalKeyTransitionError, match="monotonic"):
            m.retire(kid)
        with pytest.raises(IllegalKeyTransitionError):
            m.revoke(kid)

    def test_transition_on_unknown_kid_raises(self):
        m = Ed25519KeyManifest()
        with pytest.raises(UnknownKidError):
            m.retire("nope")

    def test_retire_drops_private_key(self):
        m, kid, _, _ = _manifest_with_active()
        m.retire(kid)
        # even though the window is open, signing is impossible after retire
        with pytest.raises(KeyNotSignableError):
            m.sign(kid, b"msg", at=T_MID)

    def test_illegal_transition_error_is_keymanifesterror(self):
        m, kid, _, _ = _manifest_with_active()
        m.revoke(kid)
        with pytest.raises(KeyManifestError):
            m.revoke(kid)


# ---- sign / verify (real ed25519) ------------------------------------------


class TestSignVerify:
    def test_sign_then_verify_roundtrip(self):
        m, kid, _, _ = _manifest_with_active()
        msg = b"canonical proof bundle bytes"
        sig = m.sign(kid, msg, at=T_MID)
        assert m.verify(kid, msg, sig, at=T_MID) is True

    def test_verify_rejects_tampered_message(self):
        m, kid, _, _ = _manifest_with_active()
        sig = m.sign(kid, b"original", at=T_MID)
        assert m.verify(kid, b"tampered", sig, at=T_MID) is False

    def test_verify_rejects_garbage_signature(self):
        m, kid, _, _ = _manifest_with_active()
        assert m.verify(kid, b"msg", b"not-a-signature", at=T_MID) is False

    def test_retired_key_still_verifies_historical_proof(self):
        m, kid, _, _ = _manifest_with_active()
        sig = m.sign(kid, b"msg", at=T_MID)
        m.retire(kid)
        # the proof was made while ACTIVE; a retired key still verifies it
        assert m.verify(kid, b"msg", sig, at=T_MID) is True

    def test_revoked_key_rejects_even_valid_signature(self):
        m, kid, _, _ = _manifest_with_active()
        sig = m.sign(kid, b"msg", at=T_MID)
        m.revoke(kid)
        # cryptographically valid, but the key is revoked -> not trusted
        assert m.verify(kid, b"msg", sig, at=T_MID) is False

    def test_verify_rejects_out_of_window(self):
        m, kid, _, _ = _manifest_with_active()
        sig = m.sign(kid, b"msg", at=T_MID)
        assert m.verify(kid, b"msg", sig, at=T_AFTER) is False
        assert m.verify(kid, b"msg", sig, at=T_BEFORE) is False

    def test_sign_out_of_window_raises(self):
        m, kid, _, _ = _manifest_with_active()
        with pytest.raises(KeyNotSignableError, match="in_window=False"):
            m.sign(kid, b"msg", at=T_AFTER)

    def test_sign_on_retired_raises(self):
        m, kid, _, _ = _manifest_with_active()
        m.retire(kid)
        with pytest.raises(KeyNotSignableError):
            m.sign(kid, b"msg", at=T_MID)

    def test_verify_unknown_kid_raises(self):
        m = Ed25519KeyManifest()
        with pytest.raises(UnknownKidError):
            m.verify("nope", b"msg", b"sig", at=T_MID)

    def test_sign_unknown_kid_raises(self):
        m = Ed25519KeyManifest()
        with pytest.raises(UnknownKidError):
            m.sign("nope", b"msg", at=T_MID)

    def test_sign_and_verify_default_now(self):
        # window spanning "now" so the default at=now() path is exercised
        priv, pub = _keypair()
        m = Ed25519KeyManifest()
        now = datetime.now(UTC)
        m.register(
            "k-now",
            pub,
            valid_from=now - timedelta(days=1),
            valid_until=now + timedelta(days=1),
            private_key=priv,
        )
        sig = m.sign("k-now", b"msg")  # at defaults to now
        assert m.verify("k-now", b"msg", sig) is True  # at defaults to now

    def test_register_retired_then_verify_only(self):
        priv, pub = _keypair()
        m = Ed25519KeyManifest()
        # register directly as RETIRED with a private key: verify-only, no sign
        m.register(
            "k", pub, valid_from=T0, valid_until=T_END, state=KeyState.RETIRED,
            private_key=priv,
        )
        assert m.get("k").is_verify_trusted(T_MID) is True
        with pytest.raises(KeyNotSignableError):
            m.sign("k", b"msg", at=T_MID)
