"""GraQle v0.59.0 — end-to-end feature check (dogfood) against the installed package.

Exercises every NEW Layer 5 feature against whatever `import graqle` resolves to in
the current environment. Prints PASS/FAIL per feature and a final verdict; exits
non-zero on any failure. No mocks — real ed25519 keys, real hashes.

Use it as a smoke test of a published release:

    python -m venv check-venv
    check-venv/bin/python -m pip install graqle           # or graqle==0.59.0
    check-venv/bin/python examples/v059_e2e_dogfood.py

Expected last line: "ALL NEW v0.59.0 FEATURES VERIFIED WORKING".
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone

UTC = timezone.utc
results: list[tuple[str, bool, str]] = []


def check(name, fn):
    try:
        fn()
        results.append((name, True, ""))
        print(f"PASS  {name}")
    except Exception as exc:  # noqa: BLE001
        results.append((name, False, f"{type(exc).__name__}: {exc}"))
        print(f"FAIL  {name}\n      {traceback.format_exc().splitlines()[-1]}")


def t_version():
    from graqle.__version__ import __version__
    assert __version__ == "0.59.0", f"expected 0.59.0, got {__version__}"


def t_imports():
    from graqle.governance.custody import (  # noqa: F401
        Ed25519KeyManifest,
        KeyEntry,
        KeyManifestError,
        KeyState,
    )
    from graqle.governance.layer_status import (  # noqa: F401
        LayerMonotonicityViolation,
        LayerStatusRegistry,
        flip_to_monotonic_on_atomic,
    )
    from graqle.governance.tamper_evidence.canonicalize import canon, canon_leaf  # noqa: F401
    from graqle.governance.tamper_evidence.leaf_input_schema import (  # noqa: F401
        LEAF_HASH_FIELDS,
        project_leaf_input,
    )
    from graqle.governance.tamper_evidence.merkle import (  # noqa: F401
        MerkleTree,
        leaf_hash_for_record,
    )


def t_custody_sign_verify():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from graqle.governance.custody import Ed25519KeyManifest
    priv = Ed25519PrivateKey.generate()
    m = Ed25519KeyManifest()
    t0, t_end = datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC)
    at = datetime(2026, 5, 15, tzinfo=UTC)
    m.register("graqle-sdk-signing-2026-Q2", priv.public_key(), t0, t_end, private_key=priv)
    sig = m.sign("graqle-sdk-signing-2026-Q2", b"governed proof bundle", at=at)
    assert m.verify("graqle-sdk-signing-2026-Q2", b"governed proof bundle", sig, at=at) is True
    assert m.verify("graqle-sdk-signing-2026-Q2", b"TAMPERED", sig, at=at) is False


def t_custody_lifecycle():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from graqle.governance.custody import Ed25519KeyManifest, KeyState
    priv = Ed25519PrivateKey.generate()
    m = Ed25519KeyManifest()
    t0, t_end = datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC)
    at = datetime(2026, 5, 15, tzinfo=UTC)
    m.register("k", priv.public_key(), t0, t_end, private_key=priv)
    sig = m.sign("k", b"msg", at=at)
    m.retire("k")
    assert m.get("k").state is KeyState.RETIRED
    assert m.verify("k", b"msg", sig, at=at) is True  # historical proof still trusted
    try:
        m.sign("k", b"new", at=at)
        raise AssertionError("retired key signed!")
    except Exception as exc:  # noqa: BLE001
        assert "Signable" in type(exc).__name__ or "sign" in type(exc).__name__.lower()
    m.revoke("k")
    assert m.get("k").state is KeyState.REVOKED
    assert m.verify("k", b"msg", sig, at=at) is False
    try:
        m.retire("k")
        raise AssertionError("un-revoked!")
    except Exception as exc:  # noqa: BLE001
        assert "Transition" in type(exc).__name__ or "monotonic" in str(exc).lower()


def t_custody_window():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from graqle.governance.custody import Ed25519KeyManifest
    priv = Ed25519PrivateKey.generate()
    m = Ed25519KeyManifest()
    t0, t_end = datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC)
    m.register("k", priv.public_key(), t0, t_end, private_key=priv)
    sig = m.sign("k", b"msg", at=datetime(2026, 5, 15, tzinfo=UTC))
    assert m.verify("k", b"msg", sig, at=datetime(2026, 8, 1, tzinfo=UTC)) is False


def t_merkle_roundtrip():
    from graqle.governance.tamper_evidence.merkle import MerkleTree
    recs = [
        {"proof_format_version": "1.0.0", "record_id": f"r{i}",
         "content_hash": f"sha256:{i}", "timestamp_unix": 1_780_000_000 + i,
         "governance_metadata": {"decision": "ALLOW"}}
        for i in range(5)
    ]
    root1 = MerkleTree.from_records(recs).root_hex
    assert isinstance(root1, str) and len(root1) == 64
    assert MerkleTree.from_records(recs).root_hex == root1


def t_leaf_vs_wrapper():
    from graqle.governance.tamper_evidence.merkle import leaf_hash_for_record
    base = {"proof_format_version": "1.0.0", "record_id": "r1",
            "content_hash": "sha256:abc", "timestamp_unix": 1_780_000_000,
            "governance_metadata": {"d": "ALLOW"}}
    h = leaf_hash_for_record(base)
    assert leaf_hash_for_record({**base, "created_at_iso": "2026-06-14T11:23:45Z"}) == h
    assert leaf_hash_for_record({**base, "content_hash": "sha256:TAMPERED"}) != h


def t_canon_rejects_nonfinite():
    # NaN/Inf in an ALLOWLISTED leaf field (governance_metadata) reaches the float
    # validator; a non-allowlisted field is projected out first (the leaf/wrapper split).
    from graqle.governance.tamper_evidence.canonicalize import canon, canon_leaf
    for bad in (float("nan"), float("inf"), float("-inf")):
        rec = {"proof_format_version": "1.0.0", "record_id": "r",
               "content_hash": "sha256:x", "timestamp_unix": 1,
               "governance_metadata": {"score": bad}}
        for fn, arg in ((canon_leaf, rec), (canon, {"a": bad})):
            try:
                fn(arg)
                raise AssertionError(f"{fn.__name__} accepted non-finite {bad}")
            except Exception as exc:  # noqa: BLE001
                assert "Float" in type(exc).__name__, f"unexpected {type(exc).__name__}"


def t_monotonic_on(tmpdir):
    from graqle.governance.layer_status import LayerMonotonicityViolation, LayerStatusRegistry
    layer = "l5_cryptographic_tamper_evidence"
    reg = LayerStatusRegistry(environment="production", transition_dir=tmpdir)
    assert reg.record_first_write(layer).monotonic_on is True
    try:
        reg.request_enabled(layer, False)
        raise AssertionError("disabled a monotonic-on layer!")
    except LayerMonotonicityViolation:
        pass
    reg.record_first_write(layer)
    assert len([h for h in reg.history(layer) if h["event"] == "monotonic_on"]) == 1


def t_cas_persist_fn(tmpdir):
    from graqle.governance.layer_status import LayerStatusRegistry
    layer = "l5_cryptographic_tamper_evidence"
    calls = []
    reg = LayerStatusRegistry(
        environment="production", transition_dir=tmpdir,
        persist_fn=lambda lid, iso, rid: calls.append((lid, rid)) or True,
    )
    reg.record_first_write(layer, first_record_id="rec-1")
    reg.record_first_write(layer, first_record_id="rec-2")  # idempotent
    assert calls == [(layer, "rec-1")]
    flip = next(h for h in reg.history(layer) if h["event"] == "monotonic_on")
    assert flip["detail"]["cas_won"] is True


def main():
    import tempfile
    check("version == 0.59.0", t_version)
    check("all new v0.59.0 modules import", t_imports)
    check("custody: ed25519 sign/verify + tamper-detect", t_custody_sign_verify)
    check("custody: ACTIVE->RETIRED->REVOKED lifecycle + monotonic", t_custody_lifecycle)
    check("custody: validity window enforced", t_custody_window)
    check("merkle: RFC6962 tree root deterministic", t_merkle_roundtrip)
    check("leaf-vs-wrapper split (wrapper-neutral, leaf-sensitive)", t_leaf_vs_wrapper)
    check("canonicalize: rejects NaN/Inf", t_canon_rejects_nonfinite)
    with tempfile.TemporaryDirectory() as d1:
        check("layer_status: monotonic-on enforced + idempotent", lambda: t_monotonic_on(d1))
    with tempfile.TemporaryDirectory() as d2:
        check("layer_status: LS-7 CAS persist_fn driven once", lambda: t_cas_persist_fn(d2))

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n{'=' * 60}\nv0.59.0 E2E DOGFOOD: {passed}/{total} passed")
    if passed != total:
        print("FAILURES:")
        for name, ok, err in results:
            if not ok:
                print(f"  - {name}: {err}")
        sys.exit(1)
    print("ALL NEW v0.59.0 FEATURES VERIFIED WORKING")


if __name__ == "__main__":
    main()
