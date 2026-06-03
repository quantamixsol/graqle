"""Tests for the SQS-triggered batch anchoring Lambda (BizQ S2).

Exercises parse_records / s3_key (pure) and lambda_handler end-to-end with
injected fakes (no AWS, no network): a fake signer, a fake Rekor anchor, and a
fake S3 client. Confirms: bundles written to S3 verify; fail-closed anchor →
whole batch redriven, nothing written; per-bundle S3 failure → only that message
redriven; un-parseable messages dropped.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_HANDLER_DIR = Path(__file__).resolve().parents[1]
_ANCHORING = _HANDLER_DIR.parents[1] / "anchoring"


def _load(modname: str, path: Path):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


# Load handler + the anchoring deps it composes (register under the names the
# handler imports, so its `from studio_backend.anchoring...` resolves to these).
signer_mod = _load("studio_backend.anchoring.signer", _ANCHORING / "signer.py")
worker_mod = _load("studio_backend.anchoring.worker", _ANCHORING / "worker.py")
handler_mod = _load("anchor_worker_handler", _HANDLER_DIR / "handler.py")

parse_records = handler_mod.parse_records
s3_key = handler_mod.s3_key
lambda_handler = handler_mod.lambda_handler
RootSigner = signer_mod.RootSigner

from graqle.governance.tamper_evidence.anchors.sigstore_rekor import AnchorError
from graqle.verify import manifest_from_single_key
from graqle.governance.tamper_evidence.verifier import verify_bundle

KID = "graqle-studio-anchor-2026-Q2"
FIXED = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)


def _record(rid):
    return {"proof_format_version": "1", "record_id": rid, "content_hash": "a" * 64,
            "timestamp_unix": 1748000000, "governance_metadata": {"gate": "CLEAR"}}


def _sqs_event(*records):
    return {"Records": [{"messageId": f"m{i}", "body": json.dumps(r)}
                        for i, r in enumerate(records)]}


class _FakeReceipt:
    log_index = 9
    log_id = "log"
    signed_tree_head = "raw-sth"
    inclusion_cert = "cert"
    integrated_time = 1748000100


class _FakeAnchor:
    def __init__(self, fail=False):
        self.fail = fail

    def anchor(self, root_bytes, signature=None, public_key=None):
        if self.fail:
            raise AnchorError("rekor down")
        return _FakeReceipt()


class _FakeS3:
    def __init__(self, fail_substr=None):
        # Fail any key containing fail_substr (e.g. a leaf_hash) — stable across
        # invocations even though the batch_id (and thus full key) changes.
        self.fail_substr = fail_substr
        self.objects: dict[str, bytes] = {}

    def put_object(self, *, Bucket, Key, Body, ContentType):
        if self.fail_substr is not None and self.fail_substr in Key:
            raise RuntimeError("s3 put failed")
        self.objects[Key] = Body


@pytest.fixture()
def signer():
    priv = Ed25519PrivateKey.generate()
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return RootSigner.from_private_key(KID, priv), pub_pem


def _ecdsa_rekor_signer():
    from cryptography.hazmat.primitives.asymmetric import ec

    return signer_mod.EcdsaRekorSigner.from_private_key(
        ec.generate_private_key(ec.SECP256R1())
    )


def _patch_deps(monkeypatch, signer, anchor, s3):
    rekor_signer = _ecdsa_rekor_signer()
    monkeypatch.setattr(
        handler_mod, "_build_dependencies",
        lambda: (signer, rekor_signer, anchor, s3),
    )
    monkeypatch.setenv("ANCHOR_S3_BUCKET", "graqle-graphs-eu")
    monkeypatch.setenv("ANCHOR_S3_PREFIX", "proofs")


# ── pure helpers ─────────────────────────────────────────────────────────────
def test_s3_key_shape():
    assert s3_key("proofs", "batch1", "deadbeef") == "proofs/batch1/deadbeef.json"
    assert s3_key("proofs/", "b", "h") == "proofs/b/h.json"  # trailing slash trimmed


def test_parse_records_ok():
    out = parse_records(_sqs_event(_record("r1"), _record("r2")))
    assert [mid for mid, _ in out] == ["m0", "m1"]


def test_parse_records_drops_unparseable():
    event = {"Records": [
        {"messageId": "good", "body": json.dumps(_record("r1"))},
        {"messageId": "bad", "body": "{not json"},
        {"messageId": "nonobj", "body": json.dumps([1, 2, 3])},
    ]}
    out = parse_records(event)
    assert [mid for mid, _ in out] == ["good"]  # only the valid object survives


def test_parse_records_empty():
    assert parse_records({}) == []
    assert parse_records({"Records": []}) == []


def test_build_dependencies_requires_signing_env(monkeypatch):
    """_build_dependencies fails fast (no AWS call) when signing env is unset."""
    monkeypatch.delenv("ANCHOR_SIGNING_SECRET_ID", raising=False)
    monkeypatch.delenv("ANCHOR_SIGNING_KID", raising=False)
    with pytest.raises(RuntimeError):
        handler_mod._build_dependencies()


# ── lambda_handler: happy path → bundles in S3 that verify ───────────────────
def test_handler_anchors_and_writes_verifiable_bundles(monkeypatch, signer):
    s, pub_pem = signer
    s3 = _FakeS3()
    _patch_deps(monkeypatch, s, _FakeAnchor(), s3)

    resp = lambda_handler(_sqs_event(_record("r1"), _record("r2"), _record("r3")))
    assert resp["batchItemFailures"] == []
    assert len(s3.objects) == 3

    manifest = manifest_from_single_key(pub_pem.encode("utf-8"), KID)
    for key, body in s3.objects.items():
        assert key.startswith("proofs/") and key.endswith(".json")
        bundle = json.loads(body)
        vr = verify_bundle(bundle, manifest)
        assert vr.ok is True, vr.failure
        assert vr.rekor_checked is True


def test_handler_empty_event_no_failures(monkeypatch, signer):
    s, _ = signer
    _patch_deps(monkeypatch, s, _FakeAnchor(), _FakeS3())
    assert lambda_handler({"Records": []}) == {"batchItemFailures": []}


# ── fail-closed: anchor error → whole batch redriven, nothing written ────────
def test_handler_fail_closed_anchor_error(monkeypatch, signer):
    s, _ = signer
    s3 = _FakeS3()
    _patch_deps(monkeypatch, s, _FakeAnchor(fail=True), s3)

    resp = lambda_handler(_sqs_event(_record("r1"), _record("r2")))
    ids = {f["itemIdentifier"] for f in resp["batchItemFailures"]}
    assert ids == {"m0", "m1"}     # every message redriven
    assert s3.objects == {}        # nothing written when nothing anchored


# ── dependency build failure → whole batch redriven ──────────────────────────
def test_handler_dep_build_failure_redrives_all(monkeypatch):
    def _boom():
        raise RuntimeError("secrets manager down")

    monkeypatch.setattr(handler_mod, "_build_dependencies", _boom)
    resp = lambda_handler(_sqs_event(_record("r1")))
    assert resp["batchItemFailures"] == [{"itemIdentifier": "m0"}]


# ── per-bundle S3 failure → only that message redriven ───────────────────────
def test_handler_partial_s3_failure(monkeypatch, signer):
    s, _ = signer
    # Discover r1's stable leaf_hash by anchoring once with an all-pass S3.
    s3_pass = _FakeS3()
    _patch_deps(monkeypatch, s, _FakeAnchor(), s3_pass)
    lambda_handler(_sqs_event(_record("r1"), _record("r2")))
    # Find r1's bundle key (its leaf_hash is stable across runs for the same record).
    r1_leaf = None
    for key, body in s3_pass.objects.items():
        if json.loads(body)["record"]["record_id"] == "r1":
            r1_leaf = json.loads(body)["leaf"]["leaf_hash"]
    assert r1_leaf is not None

    # Now fail only the put for r1's leaf_hash; r2 must still be written.
    s3_one_fail = _FakeS3(fail_substr=r1_leaf)
    _patch_deps(monkeypatch, s, _FakeAnchor(), s3_one_fail)
    resp = lambda_handler(_sqs_event(_record("r1"), _record("r2")))
    failed = {f["itemIdentifier"] for f in resp["batchItemFailures"]}
    assert len(failed) == 1            # only the message whose S3 put failed
    assert len(s3_one_fail.objects) == 1  # the other bundle was written
