"""Tests for the R2 anchoring worker core + signer (BizQ S2).

The headline test is the **closed loop**: a batch anchored by ``anchor_records``
produces proof bundles that ``verify_bundle`` (the Phase-2 surface) reports as
``verified: true``. That proves the producer and verifier agree on SD-001 + the
bundle schema, end-to-end, with a real ed25519 signature and a real Merkle tree
(only Rekor is faked, via an injected transport — no network).

These tests import the worker by file path (it lives outside the ``graqle``
package) and DO import ``verify_bundle`` — which is fine here because the test
process is not a deployed anchoring Lambda; the moat-M2 isolation is a
*deployment* boundary (worker Lambda) not a test-time one. We verify in a
separate step that the worker's own import graph does not pull the verifier.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_ANCHORING = Path(__file__).resolve().parents[1]


def _load(modname: str, relpath: str):
    spec = importlib.util.spec_from_file_location(modname, _ANCHORING / relpath)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec so @dataclass can resolve cls.__module__ (it looks up
    # sys.modules[cls.__module__].__dict__ for type hints).
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod

# Import the SUT modules by path (studio_backend is not an installed package here).
signer_mod = _load("vas_signer", "signer.py")
worker_mod = _load("vas_worker", "worker.py")
RootSigner = signer_mod.RootSigner
SignerError = signer_mod.SignerError
load_signer_from_secrets_manager = signer_mod.load_signer_from_secrets_manager
anchor_records = worker_mod.anchor_records
AnchorWorkerError = worker_mod.AnchorWorkerError

from graqle.governance.tamper_evidence.anchors.sigstore_rekor import AnchorError
from graqle.governance.custody.ed25519_key_manifest import Ed25519KeyManifest
from graqle.verify import manifest_from_single_key
from graqle.governance.tamper_evidence.verifier import verify_bundle
from cryptography.hazmat.primitives import serialization

KID = "graqle-studio-anchor-2026-Q2"
FIXED_NOW = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)


def _record(rid: str) -> dict[str, Any]:
    return {
        "proof_format_version": "1",
        "record_id": rid,
        "content_hash": "a" * 64,
        "timestamp_unix": 1748000000,
        "governance_metadata": {"gate": "CLEAR"},
    }


class _FakeReceipt:
    def __init__(self, log_index=7):
        self.log_index = log_index
        self.log_id = "fake-log"
        self.signed_tree_head = "sth"
        self.inclusion_cert = "cert"
        self.integrated_time = 1748000100


class _FakeAnchor:
    """Stands in for RekorAnchor — records the root + sig + key, returns a receipt."""

    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.anchored_roots: list[bytes] = []
        self.last_signature: bytes | None = None
        self.last_public_key: bytes | None = None

    def anchor(self, root_bytes: bytes, signature=None, public_key=None):
        if self.fail:
            raise AnchorError("simulated rekor outage")
        self.anchored_roots.append(root_bytes)
        self.last_signature = signature
        self.last_public_key = public_key
        return _FakeReceipt()


def _signer() -> tuple[Any, str]:
    priv = Ed25519PrivateKey.generate()
    s = RootSigner.from_private_key(KID, priv)
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return s, pub_pem


def _rekor_signer():
    """A dedicated ECDSA P-256 Rekor signer (separate from the ed25519 RootSigner)."""
    from cryptography.hazmat.primitives.asymmetric import ec

    EcdsaRekorSigner = signer_mod.EcdsaRekorSigner
    return EcdsaRekorSigner.from_private_key(ec.generate_private_key(ec.SECP256R1()))


_REKOR = _rekor_signer()


# ── the closed loop: anchored bundles verify ─────────────────────────────────
def test_anchored_bundles_verify_true():
    s, pub_pem = _signer()
    anchor = _FakeAnchor()
    records = [_record("r1"), _record("r2"), _record("r3")]
    result = anchor_records(
        records, signer=s, rekor_signer=_REKOR, anchor=anchor, batch_id="b1", clock=lambda: FIXED_NOW
    )
    assert len(result.bundles) == 3
    assert result.merkle_root and result.rekor_log_index == 7
    assert len(anchor.anchored_roots) == 1  # one root per batch
    # The worker passes a real ECDSA signature over the root + the EC public-key
    # PEM to the anchor (what a Rekor hashedrekord needs; ed25519 is unsupported
    # by hashedrekord so anchoring uses a dedicated ECDSA key).
    assert anchor.last_signature is not None and len(anchor.last_signature) > 0
    assert anchor.last_public_key is not None and b"BEGIN PUBLIC KEY" in anchor.last_public_key

    # Every produced bundle verifies against the signer's public key (Phase-2 path).
    for bundle in result.bundles:
        manifest = manifest_from_single_key(pub_pem.encode("utf-8"), KID)
        vr = verify_bundle(bundle, manifest)
        assert vr.ok is True, f"bundle failed: {vr.failure}"
        assert vr.rekor_checked is True  # the rekor block was checked + bound
        assert bundle["signature"]["kid"] == KID
        assert "rekor" in bundle and bundle["rekor"]["log_index"] == 7
        # GraQle convention: signed_tree_head carries the root hex (offline
        # binding); the real Rekor STH is preserved separately for rekor-cli.
        assert bundle["rekor"]["signed_tree_head"] == result.merkle_root
        assert bundle["rekor"]["rekor_sth_raw"] == "sth"


def test_tampered_bundle_fails_verify():
    s, pub_pem = _signer()
    result = anchor_records(
        [_record("r1"), _record("r2")], signer=s, rekor_signer=_REKOR, anchor=_FakeAnchor(),
        batch_id="b2", clock=lambda: FIXED_NOW,
    )
    bundle = result.bundles[0]
    bundle["leaf"]["leaf_hash"] = "f" * 64  # tamper after the fact
    manifest = manifest_from_single_key(pub_pem.encode("utf-8"), KID)
    vr = verify_bundle(bundle, manifest)
    assert vr.ok is False


# ── meter observer: one fire per anchored leaf ───────────────────────────────
def test_meter_observer_fires_once_per_anchored_leaf():
    s, _ = _signer()
    fired: list[tuple[str, dict]] = []
    anchor_records(
        [_record("r1"), _record("r2"), _record("r3")],
        signer=s, rekor_signer=_REKOR, anchor=_FakeAnchor(), batch_id="b3",
        meter_observer=lambda h, ctx: fired.append((h, ctx)),
        clock=lambda: FIXED_NOW,
    )
    assert len(fired) == 3
    # context carries batch metadata, never affects billing identity
    for leaf_hash, ctx in fired:
        assert len(leaf_hash) == 64
        assert ctx["batch_id"] == "b3"
        assert ctx["rekor_log_index"] == 7
        assert ctx["edition"] == "studio"


# ── fail-closed: anchor failure emits nothing, bills nothing ─────────────────
def test_fail_closed_anchor_error_raises_no_emit():
    s, _ = _signer()
    fired = []
    with pytest.raises(AnchorWorkerError):
        anchor_records(
            [_record("r1")], signer=s, rekor_signer=_REKOR, anchor=_FakeAnchor(fail=True), batch_id="b4",
            meter_observer=lambda h, ctx: fired.append(h),
            clock=lambda: FIXED_NOW,
        )
    assert fired == []  # nothing billed when nothing anchored


def test_fail_open_anchor_error_emits_unanchored_no_meter():
    s, pub_pem = _signer()
    fired = []
    result = anchor_records(
        [_record("r1"), _record("r2")], signer=s, rekor_signer=_REKOR, anchor=_FakeAnchor(fail=True),
        batch_id="b5", fail_open_on_anchor_error=True,
        meter_observer=lambda h, ctx: fired.append(h),
        clock=lambda: FIXED_NOW,
    )
    # Bundles exist but carry no rekor block, and NOTHING is billed (unanchored).
    assert len(result.bundles) == 2
    assert all("rekor" not in b for b in result.bundles)
    assert fired == []
    # Signature is still valid; it just isn't publicly anchored.
    manifest = manifest_from_single_key(pub_pem.encode("utf-8"), KID)
    assert verify_bundle(result.bundles[0], manifest).ok is True


def test_empty_records_raises():
    s, _ = _signer()
    with pytest.raises(AnchorWorkerError):
        anchor_records([], signer=s, rekor_signer=_REKOR, anchor=_FakeAnchor(), batch_id="b6")


def test_naive_clock_is_normalised_to_utc():
    """A naive datetime from the clock is treated as UTC (signed_at has tz)."""
    s, pub_pem = _signer()
    naive = datetime(2026, 6, 2, 12, 0, 0)  # no tzinfo
    result = anchor_records(
        [_record("r1")], signer=s, rekor_signer=_REKOR, anchor=_FakeAnchor(), batch_id="b7",
        clock=lambda: naive,
    )
    signed_at = result.bundles[0]["signature"]["signed_at"]
    assert signed_at.endswith("+00:00")  # normalised to UTC
    manifest = manifest_from_single_key(pub_pem.encode("utf-8"), KID)
    assert verify_bundle(result.bundles[0], manifest).ok is True


class _ReceiptNoLogIndex:
    log_index = None
    log_id = "x"
    signed_tree_head = "raw-sth"
    inclusion_cert = "c"
    integrated_time = 1


class _AnchorNoLogIndex:
    def anchor(self, root_bytes, signature=None, public_key=None):
        return _ReceiptNoLogIndex()


def test_meter_context_omits_log_index_when_absent():
    s, _ = _signer()
    fired = []
    anchor_records(
        [_record("r1")], signer=s, rekor_signer=_REKOR, anchor=_AnchorNoLogIndex(), batch_id="b8",
        meter_observer=lambda h, ctx: fired.append(ctx), clock=lambda: FIXED_NOW,
    )
    assert len(fired) == 1
    assert "rekor_log_index" not in fired[0]  # omitted when receipt has none
    assert fired[0]["batch_id"] == "b8"


# ── signer unit coverage ─────────────────────────────────────────────────────
def test_signer_from_private_bytes_roundtrip():
    priv = Ed25519PrivateKey.generate()
    raw = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    s = RootSigner.from_private_bytes(KID, raw)
    block = s.sign_root(proof_format_version="1", merkle_root_hex="ab" * 32, signed_at="2026-06-02T12:00:00+00:00")
    assert block["alg"] == "ed25519" and block["kid"] == KID and block["sig"]


def test_signer_bad_seed_length():
    with pytest.raises(SignerError):
        RootSigner.from_private_bytes(KID, b"tooshort")


def test_signer_bad_kid():
    priv = Ed25519PrivateKey.generate()
    with pytest.raises(SignerError):
        RootSigner.from_private_key("", priv)


def test_signer_private_key_wrong_type():
    with pytest.raises(SignerError):
        RootSigner.from_private_key(KID, "not a key")  # type: ignore[arg-type]


def test_signer_from_private_bytes_invalid_seed(monkeypatch):
    # 32 bytes is structurally valid for ed25519, so force the inner load to
    # raise to exercise the defensive wrap (signer.py from_private_bytes except).
    import vas_signer as sm

    def _boom(_):
        raise ValueError("bad seed")

    monkeypatch.setattr(sm.Ed25519PrivateKey, "from_private_bytes", staticmethod(_boom))
    with pytest.raises(SignerError):
        RootSigner.from_private_bytes(KID, b"\x00" * 32)


def test_signer_sign_failure_wrapped(monkeypatch):
    s, _ = _signer()
    # Force the manifest.sign to raise → wrapped as SignerError.
    monkeypatch.setattr(
        type(s._manifest), "sign",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kms down")),
    )
    with pytest.raises(SignerError):
        s.sign_root(proof_format_version="1", merkle_root_hex="ab" * 32, signed_at="2026-06-02T12:00:00+00:00")


def test_signer_bad_root_hex():
    s, _ = _signer()
    with pytest.raises(SignerError):
        s.sign_root(proof_format_version="1", merkle_root_hex="", signed_at="2026-06-02T12:00:00+00:00")


def test_signer_root_wrong_length():
    s, _ = _signer()
    with pytest.raises(SignerError):
        s.sign_root(proof_format_version="1", merkle_root_hex="ab" * 16, signed_at="2026-06-02T12:00:00+00:00")


def test_signer_root_not_hex():
    s, _ = _signer()
    with pytest.raises(SignerError):
        s.sign_root(proof_format_version="1", merkle_root_hex="z" * 64, signed_at="2026-06-02T12:00:00+00:00")


def test_signer_bad_signed_at():
    s, _ = _signer()
    with pytest.raises(SignerError):
        s.sign_root(proof_format_version="1", merkle_root_hex="ab" * 32, signed_at="")


def test_sign_raw_and_public_key_pem_roundtrip():
    """The raw signature over the root verifies under the published public key."""
    from cryptography.hazmat.primitives import serialization

    s, pub_pem = _signer()
    root = bytes.fromhex("cd" * 32)
    raw_sig = signer_mod._sign_raw(s, root)
    pem = signer_mod._public_key_pem(s)
    assert b"BEGIN PUBLIC KEY" in pem
    pub = serialization.load_pem_public_key(pem)
    pub.verify(raw_sig, root)  # raises on bad signature — passing == valid


def test_sign_raw_wraps_failure(monkeypatch):
    s, _ = _signer()
    monkeypatch.setattr(
        type(s._manifest), "sign",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(SignerError):
        signer_mod._sign_raw(s, b"\x00" * 32)


# ── Secrets Manager loader (injected fake client) ────────────────────────────
class _FakeSM:
    def __init__(self, payload):
        self.payload = payload

    def get_secret_value(self, SecretId):
        return self.payload


def test_load_signer_from_secrets_manager_hex_string():
    priv = Ed25519PrivateKey.generate()
    raw = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    client = _FakeSM({"SecretString": raw.hex()})
    s = load_signer_from_secrets_manager(secret_id="x", kid=KID, client=client)
    assert s.kid == KID
    block = s.sign_root(proof_format_version="1", merkle_root_hex="cd" * 32, signed_at="2026-06-02T12:00:00+00:00")
    assert block["sig"]


def test_load_signer_from_secrets_manager_binary():
    priv = Ed25519PrivateKey.generate()
    raw = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    client = _FakeSM({"SecretBinary": raw})
    s = load_signer_from_secrets_manager(secret_id="x", kid=KID, client=client)
    assert s.kid == KID


def test_load_signer_from_secrets_manager_bad_hex():
    client = _FakeSM({"SecretString": "nothex!!"})
    with pytest.raises(SignerError):
        load_signer_from_secrets_manager(secret_id="x", kid=KID, client=client)


def test_load_signer_from_secrets_manager_empty():
    client = _FakeSM({})
    with pytest.raises(SignerError):
        load_signer_from_secrets_manager(secret_id="x", kid=KID, client=client)


def test_load_signer_fetch_error():
    class _Boom:
        def get_secret_value(self, SecretId):
            raise RuntimeError("denied")

    with pytest.raises(SignerError):
        load_signer_from_secrets_manager(secret_id="x", kid=KID, client=_Boom())


# ── EcdsaRekorSigner (the dedicated Rekor anchoring key) ─────────────────────
def test_ecdsa_rekor_signer_signs_and_verifies():
    """sign_root_for_rekor returns an ECDSA sig over prehashed-SHA256(root) + EC PEM."""
    import hashlib

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, utils

    rk = _rekor_signer()
    root = bytes.fromhex("ab" * 32)
    sig, pem = rk.sign_root_for_rekor(root)
    assert b"BEGIN PUBLIC KEY" in pem
    pub = serialization.load_pem_public_key(pem)
    # The signature is over the SHA-256 digest, prehashed (Rekor's expectation).
    digest = hashlib.sha256(root).digest()
    pub.verify(sig, digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))  # raises if bad


def test_ecdsa_rekor_signer_rejects_non_ec_key():
    EcdsaRekorSigner = signer_mod.EcdsaRekorSigner
    with pytest.raises(SignerError):
        EcdsaRekorSigner.from_private_key("not a key")


def test_ecdsa_rekor_signer_from_pem_roundtrip():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    EcdsaRekorSigner = signer_mod.EcdsaRekorSigner
    priv = ec.generate_private_key(ec.SECP256R1())
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    rk = EcdsaRekorSigner.from_pem(pem)
    sig, pub_pem = rk.sign_root_for_rekor(b"\x01" * 32)
    assert sig and b"BEGIN PUBLIC KEY" in pub_pem


def test_ecdsa_rekor_signer_from_pem_bad():
    EcdsaRekorSigner = signer_mod.EcdsaRekorSigner
    with pytest.raises(SignerError):
        EcdsaRekorSigner.from_pem(b"not a pem")


def test_ecdsa_rekor_signer_sign_failure_wrapped(monkeypatch):
    rk = _rekor_signer()
    monkeypatch.setattr(type(rk._private_key), "sign",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("hsm down")))
    with pytest.raises(SignerError):
        rk.sign_root_for_rekor(b"\x00" * 32)


def test_load_ecdsa_rekor_signer_from_secrets_manager():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    load = signer_mod.load_ecdsa_rekor_signer_from_secrets_manager
    priv = ec.generate_private_key(ec.SECP256R1())
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")

    class _SM:
        def get_secret_value(self, SecretId):
            return {"SecretString": pem}

    rk = load(secret_id="x", client=_SM())
    sig, _ = rk.sign_root_for_rekor(b"\x02" * 32)
    assert sig


def test_load_ecdsa_rekor_signer_missing_pem():
    load = signer_mod.load_ecdsa_rekor_signer_from_secrets_manager

    class _SM:
        def get_secret_value(self, SecretId):
            return {}

    with pytest.raises(SignerError):
        load(secret_id="x", client=_SM())


def test_load_ecdsa_rekor_signer_fetch_error():
    load = signer_mod.load_ecdsa_rekor_signer_from_secrets_manager

    class _Boom:
        def get_secret_value(self, SecretId):
            raise RuntimeError("denied")

    with pytest.raises(SignerError):
        load(secret_id="x", client=_Boom())
