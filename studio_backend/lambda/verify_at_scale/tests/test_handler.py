"""Tests for the hosted verifier-at-scale Lambda (BizQ S2, Studio backend).

Covers the pure ``verify_request`` core and the ``lambda_handler`` Function-URL
entrypoint with REAL signed + Merkle-anchored bundles (no mocks) and fault
injection of every input path. Also asserts the moat-M2 isolation invariant:
the handler imports cleanly in a ``graqle.server``-free interpreter, and never
constructs a metering event.

The handler module is NOT importable as ``graqle.*`` (it lives outside the
package, by design — see the handler docstring), so these tests import it by
file path via importlib.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_HANDLER_PATH = Path(__file__).resolve().parents[1] / "handler.py"


def _load_handler():
    spec = importlib.util.spec_from_file_location("vas_handler", _HANDLER_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


handler_mod = _load_handler()
verify_request = handler_mod.verify_request
lambda_handler = handler_mod.lambda_handler
HTTP_OK = handler_mod.HTTP_OK
HTTP_BAD_REQUEST = handler_mod.HTTP_BAD_REQUEST
HTTP_PAYLOAD_TOO_LARGE = handler_mod.HTTP_PAYLOAD_TOO_LARGE
MAX_BODY_BYTES = handler_mod.MAX_BODY_BYTES

KID = "graqle-sdk-signing-2026-Q2"
SIGNED_AT = "2026-05-31T13:00:00Z"
SIGNED_AT_DT = datetime(2026, 5, 31, 13, 0, 0, tzinfo=timezone.utc)


def _record(rid: str = "r1") -> dict[str, Any]:
    return {
        "proof_format_version": "1",
        "record_id": rid,
        "content_hash": "a" * 64,
        "timestamp_unix": 1748000000,
        "governance_metadata": {"gate": "CLEAR"},
    }


def _make_bundle_and_pem(*, include_rekor: bool = False):
    """Build a valid signed bundle (dict) + signer public-key PEM (str)."""
    from graqle.governance.custody.ed25519_key_manifest import Ed25519KeyManifest
    from graqle.governance.tamper_evidence.merkle import MerkleTree
    from graqle.governance.tamper_evidence.verifier import _signed_message

    records = [_record("r1"), _record("r2")]
    tree = MerkleTree.from_records(records)
    proof = tree.inclusion_proof(0)
    root_hex = tree.root_hex

    priv = Ed25519PrivateKey.generate()
    signer = Ed25519KeyManifest()
    signer.register(
        kid=KID,
        public_key=priv.public_key(),
        valid_from=SIGNED_AT_DT - timedelta(days=1),
        valid_until=SIGNED_AT_DT + timedelta(days=365),
        private_key=priv,
    )
    msg = _signed_message("1", root_hex, KID, SIGNED_AT)
    sig_hex = signer.sign(KID, msg, at=SIGNED_AT_DT).hex()

    bundle: dict[str, Any] = {
        "proof_format_version": "1",
        "record": records[0],
        "leaf": {"leaf_index": 0, "tree_size": tree.size, "leaf_hash": proof.leaf_hash.hex()},
        "merkle": {
            "merkle_root": root_hex,
            "merkle_path": [h.hex() for h in proof.merkle_path],
            "merkle_path_directions": list(proof.merkle_path_directions),
        },
        "signature": {"alg": "ed25519", "kid": KID, "sig": sig_hex, "signed_at": SIGNED_AT},
    }
    if include_rekor:
        bundle["rekor"] = {
            "log_index": 1,
            "log_id": "rekor",
            "signed_tree_head": root_hex,
            "inclusion_cert": "abcd",
            "integrated_time": 1748000100,
        }

    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return bundle, pub_pem, priv


def _keyring(pub_pem: str, *, state: str = "ACTIVE") -> dict[str, Any]:
    return {
        "keys": [
            {
                "kid": KID,
                "public_key_pem": pub_pem,
                "valid_from": "2026-04-01T00:00:00Z",
                "valid_until": "2026-12-31T23:59:59Z",
                "state": state,
            }
        ]
    }


# ── verify_request: happy paths ──────────────────────────────────────────────
def test_ok_with_public_key():
    bundle, pub_pem, _ = _make_bundle_and_pem()
    status, body = verify_request({"proof_bundle": bundle, "public_key": pub_pem})
    assert status == HTTP_OK
    assert body["verified"] is True
    assert body["ok"] is True
    assert body["failure"] == "OK"
    assert isinstance(body["checks"], dict)
    assert body["rekor_checked"] is False


def test_ok_with_keyring():
    bundle, pub_pem, _ = _make_bundle_and_pem()
    status, body = verify_request({"proof_bundle": bundle, "keyring": _keyring(pub_pem)})
    assert status == HTTP_OK
    assert body["verified"] is True


def test_ok_with_rekor_sth_injected():
    bundle, pub_pem, _ = _make_bundle_and_pem(include_rekor=True)
    sth = bundle["rekor"]
    status, body = verify_request(
        {"proof_bundle": bundle, "public_key": pub_pem, "rekor_sth": sth}
    )
    assert status == HTTP_OK
    assert body["verified"] is True
    assert body["rekor_checked"] is True


# ── verify_request: well-formed request, failed proof (still 200) ────────────
def test_tampered_leaf_is_200_not_verified():
    bundle, pub_pem, _ = _make_bundle_and_pem()
    bundle["leaf"]["leaf_hash"] = "f" * 64
    status, body = verify_request({"proof_bundle": bundle, "public_key": pub_pem})
    assert status == HTTP_OK
    assert body["verified"] is False
    assert body["failure"] == "TAMPERED_LEAF"


def test_wrong_root_is_200_not_verified():
    bundle, pub_pem, _ = _make_bundle_and_pem()
    bundle["merkle"]["merkle_root"] = "0" * 64
    status, body = verify_request({"proof_bundle": bundle, "public_key": pub_pem})
    assert status == HTTP_OK
    assert body["verified"] is False


def test_revoked_kid_is_200_not_verified():
    bundle, pub_pem, _ = _make_bundle_and_pem()
    status, body = verify_request(
        {"proof_bundle": bundle, "keyring": _keyring(pub_pem, state="REVOKED")}
    )
    assert status == HTTP_OK
    assert body["verified"] is False
    assert body["failure"] == "UNTRUSTED_KID"


# ── verify_request: usage errors → 400 ───────────────────────────────────────
def test_body_not_dict():
    status, body = verify_request("not a dict")
    assert status == HTTP_BAD_REQUEST
    assert "JSON object" in body["error"]


def test_missing_proof_bundle():
    _, pub_pem, _ = _make_bundle_and_pem()
    status, body = verify_request({"public_key": pub_pem})
    assert status == HTTP_BAD_REQUEST
    assert "proof_bundle" in body["error"]


def test_proof_bundle_not_object():
    _, pub_pem, _ = _make_bundle_and_pem()
    status, body = verify_request({"proof_bundle": "nope", "public_key": pub_pem})
    assert status == HTTP_BAD_REQUEST
    assert "proof_bundle" in body["error"]


def test_both_key_forms():
    bundle, pub_pem, _ = _make_bundle_and_pem()
    status, body = verify_request(
        {"proof_bundle": bundle, "public_key": pub_pem, "keyring": _keyring(pub_pem)}
    )
    assert status == HTTP_BAD_REQUEST
    assert "exactly one" in body["error"]


def test_neither_key_form():
    bundle, _, _ = _make_bundle_and_pem()
    status, body = verify_request({"proof_bundle": bundle})
    assert status == HTTP_BAD_REQUEST
    assert "exactly one" in body["error"]


def test_public_key_not_string():
    bundle, _, _ = _make_bundle_and_pem()
    status, body = verify_request({"proof_bundle": bundle, "public_key": 123})
    assert status == HTTP_BAD_REQUEST
    assert "PEM string" in body["error"]


def test_public_key_empty_string():
    bundle, _, _ = _make_bundle_and_pem()
    status, body = verify_request({"proof_bundle": bundle, "public_key": "   "})
    assert status == HTTP_BAD_REQUEST
    assert "PEM string" in body["error"]


def test_bad_pem():
    bundle, _, _ = _make_bundle_and_pem()
    status, body = verify_request(
        {"proof_bundle": bundle, "public_key": "-----BEGIN PUBLIC KEY-----\nnope\n"}
    )
    assert status == HTTP_BAD_REQUEST
    assert "PEM" in body["error"]


def test_bundle_without_signature_kid():
    bundle, pub_pem, _ = _make_bundle_and_pem()
    del bundle["signature"]["kid"]
    status, body = verify_request({"proof_bundle": bundle, "public_key": pub_pem})
    assert status == HTTP_BAD_REQUEST
    assert "kid" in body["error"]


def test_keyring_not_dict():
    bundle, _, _ = _make_bundle_and_pem()
    status, body = verify_request({"proof_bundle": bundle, "keyring": ["nope"]})
    assert status == HTTP_BAD_REQUEST
    assert "keyring" in body["error"]


def test_keyring_empty_keys():
    bundle, _, _ = _make_bundle_and_pem()
    status, body = verify_request({"proof_bundle": bundle, "keyring": {"keys": []}})
    assert status == HTTP_BAD_REQUEST
    assert "empty" in body["error"]


def test_rekor_sth_not_object():
    bundle, pub_pem, _ = _make_bundle_and_pem()
    status, body = verify_request(
        {"proof_bundle": bundle, "public_key": pub_pem, "rekor_sth": "nope"}
    )
    assert status == HTTP_BAD_REQUEST
    assert "rekor_sth" in body["error"]


def test_max_body_bytes_is_sane():
    assert MAX_BODY_BYTES >= 64 * 1024


# ── lambda_handler: Function URL event shapes ────────────────────────────────
def test_lambda_handler_ok():
    import json

    bundle, pub_pem, _ = _make_bundle_and_pem()
    event = {"body": json.dumps({"proof_bundle": bundle, "public_key": pub_pem})}
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == HTTP_OK
    assert resp["headers"]["Content-Type"] == "application/json"
    payload = json.loads(resp["body"])
    assert payload["verified"] is True
    # CORS handled by Function URL config (ADR-056) — handler sets no CORS header.
    assert not any(h.lower().startswith("access-control-") for h in resp["headers"])


def test_lambda_handler_dict_body_passthrough():
    """Some integrations deliver an already-parsed dict body."""
    import json

    bundle, pub_pem, _ = _make_bundle_and_pem()
    event = {"body": {"proof_bundle": bundle, "public_key": pub_pem}}
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == HTTP_OK
    assert json.loads(resp["body"])["verified"] is True


def test_lambda_handler_base64_body():
    import base64
    import json

    bundle, pub_pem, _ = _make_bundle_and_pem()
    raw = json.dumps({"proof_bundle": bundle, "public_key": pub_pem}).encode("utf-8")
    event = {"body": base64.b64encode(raw).decode("ascii"), "isBase64Encoded": True}
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == HTTP_OK


def test_lambda_handler_bad_base64():
    event = {"body": "!!!not base64!!!", "isBase64Encoded": True}
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == HTTP_BAD_REQUEST


def test_lambda_handler_missing_body():
    resp = lambda_handler({}, None)
    assert resp["statusCode"] == HTTP_BAD_REQUEST


def test_lambda_handler_bad_json():
    resp = lambda_handler({"body": "{not json"}, None)
    assert resp["statusCode"] == HTTP_BAD_REQUEST


def test_lambda_handler_oversize_body():
    big = "x" * (MAX_BODY_BYTES + 1)
    resp = lambda_handler({"body": big}, None)
    assert resp["statusCode"] == HTTP_PAYLOAD_TOO_LARGE


# ── moat M2: isolation + no-meter ────────────────────────────────────────────
def test_handler_imports_clean_of_server_in_subprocess():
    """Importing the handler must NOT pull graqle.server/studio into the process.

    This is the deployment-boundary form of the moat-M2 isolation invariant: the
    verify Lambda runs in an interpreter free of proprietary/networked surfaces.
    Run in a fresh subprocess so the assertion is real (this test process may
    have loaded other things).
    """
    code = (
        "import importlib.util, sys;"
        f"spec=importlib.util.spec_from_file_location('h', r'{_HANDLER_PATH}');"
        "m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m);"
        "bad=[n for n in sys.modules if n=='graqle.server' or n.startswith('graqle.server.')"
        " or n=='graqle.studio' or n.startswith('graqle.studio.')];"
        "print('OFFENDERS:'+repr(bad)); sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, f"isolation breached: {proc.stdout}\n{proc.stderr}"
    assert "OFFENDERS:[]" in proc.stdout


def test_verify_emits_no_meter_event(monkeypatch):
    """The free verify path must NEVER construct a MeterEvent."""
    import graqle.metering.events as meter_events

    calls = {"n": 0}
    real_init = meter_events.MeterEvent.__init__

    def _spy(self, *a, **k):  # pragma: no cover - only fires on violation
        calls["n"] += 1
        return real_init(self, *a, **k)

    monkeypatch.setattr(meter_events.MeterEvent, "__init__", _spy)

    bundle, pub_pem, _ = _make_bundle_and_pem()
    verify_request({"proof_bundle": bundle, "public_key": pub_pem})
    assert calls["n"] == 0
