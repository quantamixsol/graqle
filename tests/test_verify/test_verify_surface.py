"""Tests for the WS-A2 offline verification surface (core + CLI + module entrypoint).

Covers:
- graqle.verify core: run_verify, manifest loaders, usage errors, json shape.
- graqle.cli.commands.attest: `graq attest verify` via Typer CliRunner.
- graqle.verify.__main__: argparse entrypoint + exit codes (in-process via main()).
- python -m graqle.verify in a studio-free subprocess (true isolation, AC-1/AC-3).

All fixtures build a REAL signed + Merkle-anchored bundle from the shipped
primitives and write it to temp files, so the surface is exercised end-to-end
(no mocks). Realistic 100% coverage via fault injection of each input path.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from typer.testing import CliRunner

from graqle.cli.main import app
from graqle.governance.tamper_evidence.merkle import MerkleTree
from graqle.verify import (
    EXIT_FAILED,
    EXIT_OK,
    EXIT_USAGE,
    VerifyUsageError,
    load_manifest,
    manifest_from_keyring,
    manifest_from_single_key,
    result_to_dict,
    run_verify,
)
from graqle.verify.__main__ import main as module_main

runner = CliRunner()

KID = "graqle-sdk-signing-2026-Q2"
SIGNED_AT = "2026-05-31T13:00:00Z"
SIGNED_AT_DT = datetime(2026, 5, 31, 13, 0, 0, tzinfo=timezone.utc)


def _record(rid="r1"):
    return {
        "proof_format_version": "1",
        "record_id": rid,
        "content_hash": "a" * 64,
        "timestamp_unix": 1748000000,
        "governance_metadata": {"gate": "CLEAR"},
    }


def _make_bundle_and_key(tmp_path: Path, *, include_rekor=False):
    """Write a valid signed bundle + the signer's public-key PEM to temp files.

    Returns (bundle_path, key_pem_path, priv, root_hex).
    """
    from graqle.verify import _WIDE_OPEN_FROM  # noqa: F401 (ensure import path valid)
    from graqle.governance.tamper_evidence.verifier import _signed_message

    records = [_record("r1"), _record("r2")]
    tree = MerkleTree.from_records(records)
    proof = tree.inclusion_proof(0)
    root_hex = tree.root_hex

    priv = Ed25519PrivateKey.generate()
    from graqle.governance.custody.ed25519_key_manifest import Ed25519KeyManifest

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

    bundle = {
        "proof_format_version": "1",
        "record": records[0],
        "leaf": {
            "leaf_index": 0,
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
            "log_index": 1,
            "log_id": "rekor",
            "signed_tree_head": root_hex,
            "inclusion_cert": "abcd",
            "integrated_time": 1748000100,
        }

    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key_path = tmp_path / "pub.pem"
    key_path.write_bytes(pub_pem)

    return bundle_path, key_path, priv, root_hex


def _keyring_path(tmp_path: Path, priv: Ed25519PrivateKey, *, state="ACTIVE"):
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    keyring = {
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
    p = tmp_path / "keyring.json"
    p.write_text(json.dumps(keyring), encoding="utf-8")
    return p


# ── core: run_verify ─────────────────────────────────────────────────────────
def test_run_verify_ok_with_single_key(tmp_path):
    bundle_path, key_path, _, _ = _make_bundle_and_key(tmp_path)
    code, result = run_verify(bundle_path=bundle_path, key_path=key_path)
    assert code == EXIT_OK
    assert result["ok"] is True
    assert result["failure"] == "OK"


def test_run_verify_ok_with_keyring(tmp_path):
    bundle_path, _, priv, _ = _make_bundle_and_key(tmp_path)
    keys_path = _keyring_path(tmp_path, priv)
    code, result = run_verify(bundle_path=bundle_path, keys_path=keys_path)
    assert code == EXIT_OK
    assert result["ok"] is True


def test_run_verify_revoked_keyring_fails(tmp_path):
    bundle_path, _, priv, _ = _make_bundle_and_key(tmp_path)
    keys_path = _keyring_path(tmp_path, priv, state="REVOKED")
    code, result = run_verify(bundle_path=bundle_path, keys_path=keys_path)
    assert code == EXIT_FAILED
    assert result["ok"] is False
    assert result["failure"] == "UNTRUSTED_KID"


def test_run_verify_tampered_bundle_fails(tmp_path):
    bundle_path, key_path, _, _ = _make_bundle_and_key(tmp_path)
    data = json.loads(bundle_path.read_text())
    data["leaf"]["leaf_hash"] = "f" * 64
    bundle_path.write_text(json.dumps(data))
    code, result = run_verify(bundle_path=bundle_path, key_path=key_path)
    assert code == EXIT_FAILED
    assert result["failure"] == "TAMPERED_LEAF"


def test_run_verify_rekor_in_bundle(tmp_path):
    bundle_path, key_path, _, _ = _make_bundle_and_key(tmp_path, include_rekor=True)
    code, result = run_verify(bundle_path=bundle_path, key_path=key_path)
    assert code == EXIT_OK
    assert result["rekor_checked"] is True


def test_run_verify_external_rekor_sth_file(tmp_path):
    bundle_path, key_path, _, root_hex = _make_bundle_and_key(tmp_path)
    sth_path = tmp_path / "sth.json"
    sth_path.write_text(json.dumps({
        "log_index": 1, "log_id": "r", "signed_tree_head": root_hex,
        "inclusion_cert": "x",
    }))
    code, result = run_verify(
        bundle_path=bundle_path, key_path=key_path, rekor_sth_path=sth_path
    )
    assert code == EXIT_OK
    assert result["rekor_checked"] is True


def test_run_verify_external_rekor_sth_mismatch(tmp_path):
    bundle_path, key_path, _, _ = _make_bundle_and_key(tmp_path)
    sth_path = tmp_path / "sth.json"
    sth_path.write_text(json.dumps({
        "log_index": 1, "log_id": "r", "signed_tree_head": "d" * 64,
        "inclusion_cert": "x",
    }))
    code, result = run_verify(
        bundle_path=bundle_path, key_path=key_path, rekor_sth_path=sth_path
    )
    assert code == EXIT_FAILED
    assert result["failure"] == "REKOR_MISMATCH"


# ── core: usage errors (exit 2) ──────────────────────────────────────────────
def test_run_verify_missing_bundle_file(tmp_path):
    with pytest.raises(VerifyUsageError):
        run_verify(bundle_path=tmp_path / "nope.json", key_path=tmp_path / "k.pem")


def test_run_verify_bundle_not_json(tmp_path):
    p = tmp_path / "b.json"
    p.write_text("not json{")
    kp = tmp_path / "k.pem"
    kp.write_bytes(b"x")
    with pytest.raises(VerifyUsageError):
        run_verify(bundle_path=p, key_path=kp)


def test_run_verify_bundle_not_object(tmp_path):
    p = tmp_path / "b.json"
    p.write_text("[1,2,3]")
    kp = tmp_path / "k.pem"
    kp.write_bytes(b"x")
    with pytest.raises(VerifyUsageError):
        run_verify(bundle_path=p, key_path=kp)


def test_run_verify_no_key_or_keys(tmp_path):
    bundle_path, _, _, _ = _make_bundle_and_key(tmp_path)
    with pytest.raises(VerifyUsageError):
        run_verify(bundle_path=bundle_path)


def test_run_verify_both_key_and_keys(tmp_path):
    bundle_path, key_path, priv, _ = _make_bundle_and_key(tmp_path)
    keys_path = _keyring_path(tmp_path, priv)
    with pytest.raises(VerifyUsageError):
        run_verify(bundle_path=bundle_path, key_path=key_path, keys_path=keys_path)


def test_run_verify_rekor_sth_not_object(tmp_path):
    bundle_path, key_path, _, _ = _make_bundle_and_key(tmp_path)
    sth = tmp_path / "sth.json"
    sth.write_text("[1,2]")
    with pytest.raises(VerifyUsageError):
        run_verify(bundle_path=bundle_path, key_path=key_path, rekor_sth_path=sth)


def test_run_verify_missing_key_file(tmp_path):
    bundle_path, _, _, _ = _make_bundle_and_key(tmp_path)
    with pytest.raises(VerifyUsageError):
        run_verify(bundle_path=bundle_path, key_path=tmp_path / "nope.pem")


def test_run_verify_key_but_no_kid_in_bundle(tmp_path):
    bundle_path, key_path, _, _ = _make_bundle_and_key(tmp_path)
    data = json.loads(bundle_path.read_text())
    del data["signature"]["kid"]
    bundle_path.write_text(json.dumps(data))
    with pytest.raises(VerifyUsageError):
        run_verify(bundle_path=bundle_path, key_path=key_path)


# ── core: manifest loaders ───────────────────────────────────────────────────
def test_manifest_from_single_key_bad_pem():
    with pytest.raises(VerifyUsageError):
        manifest_from_single_key(b"not a pem", KID)


def test_manifest_from_single_key_non_ed25519(tmp_path):
    from cryptography.hazmat.primitives.asymmetric import rsa

    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = rsa_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    with pytest.raises(VerifyUsageError):
        manifest_from_single_key(pem, KID)


def test_manifest_from_keyring_not_object():
    with pytest.raises(VerifyUsageError):
        manifest_from_keyring(["not", "a", "dict"])


def test_manifest_from_keyring_empty_keys():
    with pytest.raises(VerifyUsageError):
        manifest_from_keyring({"keys": []})


def test_manifest_from_keyring_entry_not_object():
    with pytest.raises(VerifyUsageError):
        manifest_from_keyring({"keys": ["nope"]})


def test_manifest_from_keyring_missing_kid(tmp_path):
    pub = Ed25519PrivateKey.generate().public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    with pytest.raises(VerifyUsageError):
        manifest_from_keyring({"keys": [{"public_key_pem": pub}]})


def test_manifest_from_keyring_missing_pem():
    with pytest.raises(VerifyUsageError):
        manifest_from_keyring({"keys": [{"kid": "k"}]})


def test_manifest_from_keyring_bad_state():
    pub = Ed25519PrivateKey.generate().public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    with pytest.raises(VerifyUsageError):
        manifest_from_keyring({"keys": [{"kid": "k", "public_key_pem": pub, "state": "BOGUS"}]})


def test_manifest_from_keyring_non_string_state():
    pub = Ed25519PrivateKey.generate().public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    with pytest.raises(VerifyUsageError):
        manifest_from_keyring({"keys": [{"kid": "k", "public_key_pem": pub, "state": 5}]})


def test_manifest_from_keyring_bad_timestamp():
    pub = Ed25519PrivateKey.generate().public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    with pytest.raises(VerifyUsageError):
        manifest_from_keyring(
            {"keys": [{"kid": "k", "public_key_pem": pub, "valid_from": "not-a-date"}]}
        )


def test_manifest_from_keyring_non_string_timestamp():
    pub = Ed25519PrivateKey.generate().public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    with pytest.raises(VerifyUsageError):
        manifest_from_keyring(
            {"keys": [{"kid": "k", "public_key_pem": pub, "valid_from": 12345}]}
        )


def test_manifest_from_keyring_defaults_state_active(tmp_path):
    bundle_path, _, priv, _ = _make_bundle_and_key(tmp_path)
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    # no state/window fields -> defaults (ACTIVE, wide-open) -> verifies
    m = manifest_from_keyring({"keys": [{"kid": KID, "public_key_pem": pub}]})
    entry = m.get(KID)
    from graqle.governance.custody.ed25519_key_manifest import KeyState

    assert entry.state is KeyState.ACTIVE


def test_load_manifest_keyring_not_dict(tmp_path):
    p = tmp_path / "k.json"
    p.write_text('"a string"')
    with pytest.raises(VerifyUsageError):
        load_manifest(key_path=None, keys_path=p, bundle={})


def test_manifest_from_keyring_naive_timestamp(tmp_path):
    # A keyring window timestamp WITHOUT a timezone -> treated as UTC (line 148).
    bundle_path, _, priv, _ = _make_bundle_and_key(tmp_path)
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    m = manifest_from_keyring(
        {
            "keys": [
                {
                    "kid": KID,
                    "public_key_pem": pub,
                    "valid_from": "2026-04-01T00:00:00",  # naive — no Z, no offset
                    "valid_until": "2026-12-31T23:59:59",
                }
            ]
        }
    )
    entry = m.get(KID)
    assert entry.valid_from.tzinfo is not None  # normalised to UTC


# ── core: result_to_dict shape ───────────────────────────────────────────────
def test_result_to_dict_shape(tmp_path):
    bundle_path, key_path, _, _ = _make_bundle_and_key(tmp_path)
    _, result = run_verify(bundle_path=bundle_path, key_path=key_path)
    assert set(result.keys()) == {"ok", "failure", "checks", "rekor_checked"}


# ── CLI: graq attest verify ──────────────────────────────────────────────────
def test_cli_verify_ok_text(tmp_path):
    bundle_path, key_path, _, _ = _make_bundle_and_key(tmp_path)
    res = runner.invoke(app, ["attest", "verify", str(bundle_path), "--key", str(key_path)])
    assert res.exit_code == 0
    assert "VERIFIED" in res.stdout


def test_cli_verify_ok_json(tmp_path):
    bundle_path, key_path, _, _ = _make_bundle_and_key(tmp_path)
    res = runner.invoke(
        app, ["attest", "verify", str(bundle_path), "--key", str(key_path), "--format", "json"]
    )
    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert payload["ok"] is True


def test_cli_verify_failed(tmp_path):
    bundle_path, key_path, _, _ = _make_bundle_and_key(tmp_path)
    data = json.loads(bundle_path.read_text())
    data["merkle"]["merkle_root"] = "0" * 64
    bundle_path.write_text(json.dumps(data))
    res = runner.invoke(app, ["attest", "verify", str(bundle_path), "--key", str(key_path)])
    assert res.exit_code == 1
    assert "FAILED" in res.stdout


def test_cli_verify_usage_error(tmp_path):
    res = runner.invoke(
        app, ["attest", "verify", str(tmp_path / "nope.json"), "--key", str(tmp_path / "k.pem")]
    )
    assert res.exit_code == 2


def test_cli_verify_usage_error_json(tmp_path):
    res = runner.invoke(
        app,
        ["attest", "verify", str(tmp_path / "nope.json"), "--key", str(tmp_path / "k.pem"), "--format", "json"],
    )
    assert res.exit_code == 2


def test_cli_verify_bad_format(tmp_path):
    bundle_path, key_path, _, _ = _make_bundle_and_key(tmp_path)
    res = runner.invoke(
        app, ["attest", "verify", str(bundle_path), "--key", str(key_path), "--format", "xml"]
    )
    assert res.exit_code == 2


def test_cli_verify_keyring_and_rekor(tmp_path):
    bundle_path, _, priv, _ = _make_bundle_and_key(tmp_path, include_rekor=True)
    keys_path = _keyring_path(tmp_path, priv)
    res = runner.invoke(app, ["attest", "verify", str(bundle_path), "--keys", str(keys_path)])
    assert res.exit_code == 0
    assert "rekor" not in res.stdout.lower() or "pass" in res.stdout.lower()


# ── module entrypoint: graqle.verify.main() in-process ───────────────────────
def test_module_main_ok(tmp_path):
    bundle_path, key_path, _, _ = _make_bundle_and_key(tmp_path)
    code = module_main([str(bundle_path), "--key", str(key_path)])
    assert code == EXIT_OK


def test_module_main_json(tmp_path, capsys):
    bundle_path, key_path, _, _ = _make_bundle_and_key(tmp_path)
    code = module_main([str(bundle_path), "--key", str(key_path), "--format", "json"])
    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert json.loads(out)["ok"] is True


def test_module_main_failed(tmp_path):
    bundle_path, key_path, _, _ = _make_bundle_and_key(tmp_path)
    data = json.loads(bundle_path.read_text())
    data["leaf"]["leaf_hash"] = "f" * 64
    bundle_path.write_text(json.dumps(data))
    code = module_main([str(bundle_path), "--key", str(key_path)])
    assert code == EXIT_FAILED


def test_module_main_usage_error(tmp_path):
    code = module_main([str(tmp_path / "nope.json"), "--key", str(tmp_path / "k.pem")])
    assert code == EXIT_USAGE


def test_module_main_usage_error_json(tmp_path, capsys):
    code = module_main(
        [str(tmp_path / "nope.json"), "--key", str(tmp_path / "k.pem"), "--format", "json"]
    )
    assert code == EXIT_USAGE
    err = capsys.readouterr().err
    assert json.loads(err)["ok"] is False


def test_module_main_text_no_rekor_note(tmp_path, capsys):
    bundle_path, key_path, _, _ = _make_bundle_and_key(tmp_path)
    module_main([str(bundle_path), "--key", str(key_path)])
    out = capsys.readouterr().out
    assert "rekor: not checked" in out


def test_module_main_text_with_rekor_no_note(tmp_path, capsys):
    # rekor_checked True -> the "not checked" note is skipped (branch 101->103).
    bundle_path, key_path, _, _ = _make_bundle_and_key(tmp_path, include_rekor=True)
    code = module_main([str(bundle_path), "--key", str(key_path)])
    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert "rekor: not checked" not in out


# ── subprocess invariant: studio-free interpreter (AC-1/AC-3) ────────────────
def test_module_entrypoint_in_studio_free_subprocess(tmp_path):
    bundle_path, key_path, _, _ = _make_bundle_and_key(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "graqle.verify", str(bundle_path), "--key", str(key_path)],
        shell=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "VERIFIED" in proc.stdout
