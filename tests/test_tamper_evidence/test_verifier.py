"""Tests for the standalone offline proof-bundle verifier (WS-A1, moat M2).

These tests build a REAL signed + Merkle-anchored bundle end-to-end from the
shipped primitives (no mocks for the crypto): a genuine ``MerkleTree`` over real
records and a genuine ``Ed25519KeyManifest`` signing key. Each failure mode is
then exercised by fault-injecting a single field into a valid bundle, so the
typed failures are proven against real cryptographic rejection rather than
stubbed behaviour. Coverage is realistic (fault injection reaches every
defensive branch), per the 100%-realistic-coverage standing directive.

The bundle the fixtures build is exactly the canonical WS-A1 schema, so these
tests also pin the moat-M2 wire format.
"""

from __future__ import annotations

import copy
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from graqle.governance.custody.ed25519_key_manifest import (
    Ed25519KeyManifest,
    KeyState,
)
from graqle.governance.tamper_evidence.merkle import MerkleTree
from graqle.governance.tamper_evidence.verifier import (
    VerifyFailure,
    VerifyResult,
    VerifierError,
    _assert_isolated,
    _extract_anchored_root_hex,
    _parse_signed_at,
    _require_obj,
    _verify_rekor_offline,
    verify_bundle,
)

# ── Fixture constants ────────────────────────────────────────────────────────
KID = "graqle-sdk-signing-2026-Q2"
SIGNED_AT = "2026-05-31T13:00:00Z"
SIGNED_AT_DT = datetime(2026, 5, 31, 13, 0, 0, tzinfo=timezone.utc)
PROOF_FORMAT_VERSION = "1"


def _record(record_id: str = "rec-A") -> dict:
    """A valid governed-trace record carrying the required leaf fields."""
    return {
        "proof_format_version": PROOF_FORMAT_VERSION,
        "record_id": record_id,
        "content_hash": "a" * 64,
        "timestamp_unix": 1748000000,
        "governance_metadata": {"gate": "CLEAR"},
        # a wrapper field outside LEAF_HASH_FIELDS — must NOT affect the leaf:
        "ignored_wrapper_field": "noise",
    }


def _manifest_with_key(
    *,
    state: KeyState = KeyState.ACTIVE,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
) -> tuple[Ed25519KeyManifest, Ed25519PrivateKey]:
    """A manifest holding one signing key (ACTIVE by default), plus its private key."""
    manifest = Ed25519KeyManifest()
    private_key = Ed25519PrivateKey.generate()
    manifest.register(
        kid=KID,
        public_key=private_key.public_key(),
        valid_from=valid_from or (SIGNED_AT_DT - timedelta(days=1)),
        valid_until=valid_until or (SIGNED_AT_DT + timedelta(days=365)),
        state=KeyState.ACTIVE,  # register active so we can sign, then transition
        private_key=private_key,
    )
    if state is KeyState.RETIRED:
        manifest.retire(KID)
    elif state is KeyState.REVOKED:
        manifest.revoke(KID)
    return manifest, private_key


def _build_valid_bundle(
    *,
    records: list[dict] | None = None,
    index: int = 0,
    manifest: Ed25519KeyManifest | None = None,
    include_rekor: bool = False,
) -> dict:
    """Build a fully valid, signed, Merkle-anchored proof bundle.

    Signs with an ACTIVE key (signing requires ACTIVE), then the caller may swap
    in a manifest whose key has since been retired/revoked to test verify-time
    trust transitions independently of sign-time.
    """
    records = records or [_record("rec-A"), _record("rec-B"), _record("rec-C")]
    tree = MerkleTree.from_records(records)
    proof = tree.inclusion_proof(index)
    root_hex = tree.root_hex

    signing_manifest = Ed25519KeyManifest()
    signing_priv = Ed25519PrivateKey.generate()
    signing_manifest.register(
        kid=KID,
        public_key=signing_priv.public_key(),
        valid_from=SIGNED_AT_DT - timedelta(days=1),
        valid_until=SIGNED_AT_DT + timedelta(days=365),
        private_key=signing_priv,
    )
    # Reconstruct the exact signed message the verifier will rebuild (SD-001).
    from graqle.governance.tamper_evidence.verifier import _signed_message

    message = _signed_message(PROOF_FORMAT_VERSION, root_hex, KID, SIGNED_AT)
    sig_hex = signing_manifest.sign(KID, message, at=SIGNED_AT_DT).hex()

    bundle = {
        "proof_format_version": PROOF_FORMAT_VERSION,
        "record": records[index],
        "leaf": {
            "leaf_index": index,
            "tree_size": tree.size,
            "leaf_hash": proof.leaf_hash.hex(),
        },
        "merkle": {
            "merkle_root": root_hex,
            "merkle_path": [h.hex() for h in proof.merkle_path],
            "merkle_path_directions": list(proof.merkle_path_directions),
        },
        "signature": {
            "alg": "ed25519",
            "kid": KID,
            "sig": sig_hex,
            "signed_at": SIGNED_AT,
        },
    }
    if include_rekor:
        bundle["rekor"] = {
            "log_index": 42,
            "log_id": "rekor.sigstore.dev",
            "signed_tree_head": root_hex,  # GraQle committer records root hex here
            "inclusion_cert": "deadbeef",
            "integrated_time": 1748000100,
        }

    # The verifying manifest trusts the SAME public key the signer used.
    if manifest is None:
        manifest = Ed25519KeyManifest()
        manifest.register(
            kid=KID,
            public_key=signing_priv.public_key(),
            valid_from=SIGNED_AT_DT - timedelta(days=1),
            valid_until=SIGNED_AT_DT + timedelta(days=365),
        )
    bundle["_test_manifest"] = manifest  # stashed for the test; popped before verify
    bundle["_test_signing_pub"] = signing_priv.public_key()
    return bundle


def _split(bundle: dict) -> tuple[dict, Ed25519KeyManifest]:
    """Pop the stashed test manifest out of a fixture bundle."""
    b = copy.deepcopy(
        {k: v for k, v in bundle.items() if not k.startswith("_test_")}
    )
    return b, bundle["_test_manifest"]


# ── Happy path ───────────────────────────────────────────────────────────────
def test_valid_bundle_verifies():
    bundle, manifest = _split(_build_valid_bundle())
    result = verify_bundle(bundle, manifest)
    assert isinstance(result, VerifyResult)
    assert result.ok is True
    assert result.failure is VerifyFailure.OK
    assert result.checks == {"leaf": True, "merkle": True, "signature": True}
    assert result.rekor_checked is False


def test_valid_bundle_with_rekor_verifies():
    bundle, manifest = _split(_build_valid_bundle(include_rekor=True))
    result = verify_bundle(bundle, manifest)
    assert result.ok is True
    assert result.rekor_checked is True
    assert result.checks["rekor"] is True


@pytest.mark.parametrize("index", [0, 1, 2])
def test_every_leaf_index_verifies(index):
    bundle, manifest = _split(_build_valid_bundle(index=index))
    assert verify_bundle(bundle, manifest).ok is True


def test_wrapper_field_does_not_affect_leaf():
    """A field outside LEAF_HASH_FIELDS can change without breaking the proof."""
    bundle, manifest = _split(_build_valid_bundle())
    bundle["record"]["ignored_wrapper_field"] = "totally-different"
    assert verify_bundle(bundle, manifest).ok is True


# ── Failure modes (fault injection) ──────────────────────────────────────────
def test_tampered_leaf_hash_fails():
    bundle, manifest = _split(_build_valid_bundle())
    bundle["leaf"]["leaf_hash"] = "f" * 64
    result = verify_bundle(bundle, manifest)
    assert result.ok is False
    assert result.failure is VerifyFailure.TAMPERED_LEAF


def test_tampered_record_fails_as_tampered_leaf():
    bundle, manifest = _split(_build_valid_bundle())
    bundle["record"]["content_hash"] = "b" * 64  # a leaf field -> changes the hash
    result = verify_bundle(bundle, manifest)
    assert result.ok is False
    assert result.failure is VerifyFailure.TAMPERED_LEAF


def test_record_missing_proof_format_version_fails_as_tampered_leaf():
    bundle, manifest = _split(_build_valid_bundle())
    del bundle["record"]["proof_format_version"]
    result = verify_bundle(bundle, manifest)
    assert result.ok is False
    assert result.failure is VerifyFailure.TAMPERED_LEAF


def test_wrong_root_fails():
    bundle, manifest = _split(_build_valid_bundle())
    bundle["merkle"]["merkle_root"] = "0" * 64
    result = verify_bundle(bundle, manifest)
    assert result.ok is False
    assert result.failure is VerifyFailure.WRONG_ROOT
    assert result.checks == {"leaf": True}


def test_tampered_merkle_path_fails_wrong_root():
    bundle, manifest = _split(_build_valid_bundle())
    # flip one sibling hash in the path
    path = bundle["merkle"]["merkle_path"]
    path[0] = "c" * 64
    result = verify_bundle(bundle, manifest)
    assert result.ok is False
    assert result.failure is VerifyFailure.WRONG_ROOT


def test_inconsistent_path_lengths_fail_wrong_root():
    bundle, manifest = _split(_build_valid_bundle())
    # break the InclusionProof __post_init__ invariant
    bundle["merkle"]["merkle_path_directions"] = [0]
    bundle["merkle"]["merkle_path"] = ["a" * 64, "b" * 64]
    result = verify_bundle(bundle, manifest)
    assert result.ok is False
    assert result.failure is VerifyFailure.WRONG_ROOT


def test_unknown_kid_fails():
    bundle, _ = _split(_build_valid_bundle())
    empty_manifest = Ed25519KeyManifest()  # no keys registered
    result = verify_bundle(bundle, empty_manifest)
    assert result.ok is False
    assert result.failure is VerifyFailure.UNKNOWN_KID


def test_revoked_kid_fails_untrusted():
    # Sign valid, then verify against a manifest where the key is REVOKED.
    revoked_manifest, _ = _manifest_with_key(state=KeyState.REVOKED)
    bundle, _ = _split(_build_valid_bundle())
    # point the manifest's key at the SAME public key the bundle was signed with
    bundle_full = _build_valid_bundle()
    signing_pub = bundle_full["_test_signing_pub"]
    revoked_manifest2 = Ed25519KeyManifest()
    revoked_manifest2.register(
        kid=KID,
        public_key=signing_pub,
        valid_from=SIGNED_AT_DT - timedelta(days=1),
        valid_until=SIGNED_AT_DT + timedelta(days=365),
    )
    revoked_manifest2.revoke(KID)
    clean_bundle, _ = _split(bundle_full)
    result = verify_bundle(clean_bundle, revoked_manifest2)
    assert result.ok is False
    assert result.failure is VerifyFailure.UNTRUSTED_KID


def test_out_of_window_kid_fails_untrusted():
    bundle_full = _build_valid_bundle()
    signing_pub = bundle_full["_test_signing_pub"]
    # window that does NOT include SIGNED_AT
    manifest = Ed25519KeyManifest()
    manifest.register(
        kid=KID,
        public_key=signing_pub,
        valid_from=SIGNED_AT_DT + timedelta(days=10),
        valid_until=SIGNED_AT_DT + timedelta(days=20),
    )
    clean_bundle, _ = _split(bundle_full)
    result = verify_bundle(clean_bundle, manifest)
    assert result.ok is False
    assert result.failure is VerifyFailure.UNTRUSTED_KID


def test_retired_kid_still_verifies():
    """A RETIRED key still verifies historical proofs (within window)."""
    bundle_full = _build_valid_bundle()
    signing_pub = bundle_full["_test_signing_pub"]
    manifest = Ed25519KeyManifest()
    manifest.register(
        kid=KID,
        public_key=signing_pub,
        valid_from=SIGNED_AT_DT - timedelta(days=1),
        valid_until=SIGNED_AT_DT + timedelta(days=365),
    )
    manifest.retire(KID)
    clean_bundle, _ = _split(bundle_full)
    assert verify_bundle(clean_bundle, manifest).ok is True


def test_wrong_key_signature_fails_untrusted():
    """A signature from a different key than the manifest trusts is rejected."""
    bundle, _ = _split(_build_valid_bundle())
    other_priv = Ed25519PrivateKey.generate()
    manifest = Ed25519KeyManifest()
    manifest.register(
        kid=KID,
        public_key=other_priv.public_key(),  # different key
        valid_from=SIGNED_AT_DT - timedelta(days=1),
        valid_until=SIGNED_AT_DT + timedelta(days=365),
    )
    result = verify_bundle(bundle, manifest)
    assert result.ok is False
    assert result.failure is VerifyFailure.UNTRUSTED_KID


def test_tampered_signed_at_fails_untrusted():
    """Changing signed_at changes the signed message -> signature no longer valid."""
    bundle, manifest = _split(_build_valid_bundle())
    bundle["signature"]["signed_at"] = "2026-06-01T00:00:00Z"
    result = verify_bundle(bundle, manifest)
    assert result.ok is False
    # still within window, but message differs -> crypto invalid -> UNTRUSTED_KID
    assert result.failure is VerifyFailure.UNTRUSTED_KID


# ── Rekor ────────────────────────────────────────────────────────────────────
def test_rekor_mismatch_fails():
    bundle, manifest = _split(_build_valid_bundle(include_rekor=True))
    bundle["rekor"]["signed_tree_head"] = "d" * 64  # references a different root
    result = verify_bundle(bundle, manifest)
    assert result.ok is False
    assert result.failure is VerifyFailure.REKOR_MISMATCH
    assert result.checks["rekor"] is False
    assert result.rekor_checked is False


def test_rekor_missing_required_field_fails():
    bundle, manifest = _split(_build_valid_bundle(include_rekor=True))
    del bundle["rekor"]["log_id"]
    result = verify_bundle(bundle, manifest)
    assert result.ok is False
    assert result.failure is VerifyFailure.REKOR_MISMATCH


def test_rekor_non_dict_fails():
    assert _verify_rekor_offline("not-a-dict", "a" * 64) is False


def test_rekor_non_string_sth_fails():
    rekor = {
        "log_index": 1,
        "log_id": "x",
        "signed_tree_head": 12345,  # not a string
        "inclusion_cert": "y",
    }
    assert _verify_rekor_offline(rekor, "a" * 64) is False


def test_extract_anchored_root_hex_identity():
    assert _extract_anchored_root_hex("abc123") == "abc123"


# ── Malformed bundles ────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.pop("proof_format_version"),
        lambda b: b.pop("record"),
        lambda b: b.pop("leaf"),
        lambda b: b.pop("merkle"),
        lambda b: b.pop("signature"),
        lambda b: b.__setitem__("record", "not-a-dict"),
        lambda b: b.__setitem__("leaf", "not-a-dict"),
        lambda b: b["leaf"].__setitem__("leaf_index", "not-an-int"),
        lambda b: b["leaf"].__setitem__("leaf_index", True),  # bool is not an int
        lambda b: b["leaf"].__setitem__("tree_size", None),
        lambda b: b["leaf"].__setitem__("leaf_hash", 123),  # not a hex string
        lambda b: b["leaf"].__setitem__("leaf_hash", "zz"),  # invalid hex
        lambda b: b["merkle"].__setitem__("merkle_path", "not-a-list"),
        lambda b: b["merkle"].__setitem__("merkle_path_directions", "not-a-list"),
        lambda b: b["merkle"].__setitem__("merkle_path", [123]),  # non-str in list
        lambda b: b["signature"].__setitem__("kid", 999),  # not a string
        lambda b: b["signature"].__setitem__("sig", "zz"),  # invalid hex
        lambda b: b["signature"].__setitem__("signed_at", 12345),  # not a string
        lambda b: b["signature"].__setitem__("signed_at", "not-a-date"),
        lambda b: b["signature"].__setitem__("alg", "rsa"),  # unsupported alg
    ],
)
def test_malformed_bundle_variants(mutate):
    bundle, manifest = _split(_build_valid_bundle())
    mutate(bundle)
    result = verify_bundle(bundle, manifest)
    assert result.ok is False
    assert result.failure is VerifyFailure.MALFORMED_BUNDLE


def test_non_dict_bundle_is_malformed():
    _, manifest = _split(_build_valid_bundle())
    result = verify_bundle("not-a-bundle", manifest)
    assert result.ok is False
    assert result.failure is VerifyFailure.MALFORMED_BUNDLE


# ── Caller misuse ────────────────────────────────────────────────────────────
def test_non_manifest_trusted_keys_raises_verifier_error():
    bundle, _ = _split(_build_valid_bundle())
    with pytest.raises(VerifierError):
        verify_bundle(bundle, trusted_keys={"not": "a manifest"})


# ── _require_obj helper (defensive non-dict guard) ───────────────────────────
def test_require_obj_rejects_non_dict_mapping():
    # The verify_bundle entry guard already ensures proof_bundle is a dict, so
    # this defensive branch is exercised directly via the helper (fault
    # injection, not pragma-hiding).
    with pytest.raises(TypeError):
        _require_obj("not-a-dict", "leaf")


def test_require_obj_rejects_non_dict_value():
    with pytest.raises(TypeError):
        _require_obj({"leaf": "not-a-dict"}, "leaf")


def test_require_obj_returns_dict():
    assert _require_obj({"leaf": {"a": 1}}, "leaf") == {"a": 1}


# ── signed_at parsing ────────────────────────────────────────────────────────
def test_parse_signed_at_z_suffix():
    assert _parse_signed_at("2026-05-31T13:00:00Z") == SIGNED_AT_DT


def test_parse_signed_at_explicit_offset():
    parsed = _parse_signed_at("2026-05-31T15:00:00+02:00")
    assert parsed == SIGNED_AT_DT


def test_parse_signed_at_naive_treated_as_utc():
    parsed = _parse_signed_at("2026-05-31T13:00:00")
    assert parsed == SIGNED_AT_DT


def test_parse_signed_at_non_string_raises():
    with pytest.raises(TypeError):
        _parse_signed_at(12345)


# ── Import-isolation guard ───────────────────────────────────────────────────
def test_isolation_guard_passes_when_clean():
    # No graqle.server / graqle.studio module -> no raise.
    _assert_isolated({"graqle.core.graph": object(), "os": object()})


@pytest.mark.parametrize(
    "forbidden",
    ["graqle.server", "graqle.server.lambda_handler", "graqle.studio", "graqle.studio.app"],
)
def test_isolation_guard_raises_on_forbidden_module(forbidden):
    with pytest.raises(ImportError) as exc:
        _assert_isolated({forbidden: object(), "graqle.core": object()})
    assert "isolated" in str(exc.value)


def test_isolation_guard_allows_lookalike_prefixes():
    # 'graqle.serverless' is NOT 'graqle.server' (prefix must be a dotted boundary)
    _assert_isolated({"graqle.serverless_helper": object()})


def test_module_import_did_not_load_server_or_studio():
    # Importing the verifier must NOT pull graqle.server/graqle.studio into
    # sys.modules. This is checked in a CLEAN subprocess (not the current
    # interpreter): sys.modules is process-global, so other tests in the full
    # suite that legitimately import server/studio would pollute a same-process
    # check and make it spuriously fail (local-isolated-green != CI-full-suite).
    # A fresh interpreter that imports only the verifier isolates the question to
    # "does importing the verifier load server/studio" — which is what we mean.
    script = (
        "import sys;"
        "import graqle.governance.tamper_evidence.verifier;"
        "bad = [n for n in sys.modules if n == 'graqle.server' "
        "or n.startswith('graqle.server.') or n == 'graqle.studio' "
        "or n.startswith('graqle.studio.')];"
        "assert not bad, bad;"
        "print('CLEAN')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        shell=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "CLEAN" in proc.stdout


# ── Subprocess invariant: verify in a studio-free interpreter (AC-1/AC-3) ─────
def test_verify_in_subprocess_without_studio():
    """verify_bundle works in a fresh interpreter that never imports studio.

    Uses shell=False with a fixed argv (no shell injection surface). Proves the
    verifier is genuinely standalone: a fresh process imports only the verifier
    and its allowed deps and verifies a real bundle, exiting 0.
    """
    script = (
        "import sys;"
        "from datetime import datetime, timedelta, timezone;"
        "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey;"
        "from graqle.governance.custody.ed25519_key_manifest import Ed25519KeyManifest;"
        "from graqle.governance.tamper_evidence.merkle import MerkleTree;"
        "from graqle.governance.tamper_evidence.verifier import verify_bundle, _signed_message;"
        "recs=[{'proof_format_version':'1','record_id':'r','content_hash':'a'*64,"
        "'timestamp_unix':1,'governance_metadata':{}}];"
        "t=MerkleTree.from_records(recs);p=t.inclusion_proof(0);"
        "at=datetime(2026,5,31,13,tzinfo=timezone.utc);"
        "priv=Ed25519PrivateKey.generate();m=Ed25519KeyManifest();"
        "m.register(kid='k',public_key=priv.public_key(),"
        "valid_from=at-timedelta(days=1),valid_until=at+timedelta(days=1),private_key=priv);"
        "msg=_signed_message('1',t.root_hex,'k','2026-05-31T13:00:00Z');"
        "sig=m.sign('k',msg,at=at).hex();"
        "b={'proof_format_version':'1','record':recs[0],"
        "'leaf':{'leaf_index':0,'tree_size':t.size,'leaf_hash':p.leaf_hash.hex()},"
        "'merkle':{'merkle_root':t.root_hex,'merkle_path':[h.hex() for h in p.merkle_path],"
        "'merkle_path_directions':list(p.merkle_path_directions)},"
        "'signature':{'alg':'ed25519','kid':'k','sig':sig,'signed_at':'2026-05-31T13:00:00Z'}};"
        "r=verify_bundle(b,m);"
        "assert r.ok, r.failure;"
        "assert 'graqle.server' not in sys.modules and 'graqle.studio' not in sys.modules;"
        "print('SUBPROC_OK')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        shell=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "SUBPROC_OK" in proc.stdout
