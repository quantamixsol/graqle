"""GraQle v0.59.0 — cryptographic governance, a real use case, step by step.

Scenario: a bank's AI declines a loan application. That governed decision must be
recorded so that — months later — an auditor can prove the record was not altered,
WITHOUT any access to the bank's or GraQle's systems. A tamperer then tries to
change the recorded decision, and a key is compromised. We show, step by step,
that the tamper is caught and the revocation is enforced.

This walks all five GraQle governance layers end to end (L1 substrate + L2 reasoning
are the foundation; this script exercises L3 governed-trace shape, L5 cryptographic
tamper-evidence, the runtime layer-switch / monotonic-on rule, and ed25519 key
custody). Nothing is mocked: real ed25519 keys, real RFC 8785 canonicalization,
real RFC 6962 Merkle tree.

Run it against the published package to prove the public artifact works:

    python -m venv demo-venv
    demo-venv/bin/python -m pip install graqle           # or graqle==0.59.0
    demo-venv/bin/python examples/v059_cryptographic_governance_usecase.py

Expected: nine steps print, ending with "USE CASE COMPLETE". Exit code 0.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from graqle.__version__ import __version__
from graqle.governance.custody import Ed25519KeyManifest
from graqle.governance.layer_status import LayerMonotonicityViolation, LayerStatusRegistry
from graqle.governance.tamper_evidence.canonicalize import canon_leaf
from graqle.governance.tamper_evidence.merkle import MerkleTree, leaf_hash_for_record

UTC = timezone.utc
NOW = datetime(2026, 5, 24, 13, 0, tzinfo=UTC)
L5 = "l5_cryptographic_tamper_evidence"
_STEP = 0


def step(title: str) -> None:
    global _STEP
    _STEP += 1
    print(f"\n{'=' * 70}\nSTEP {_STEP}: {title}\n{'=' * 70}")


def main() -> None:
    print(f"GraQle v{__version__}  -  loan-denial governed-decision use case")
    print("(running against the installed package)")

    # -----------------------------------------------------------------------
    step("The bank's AI makes a governed decision (the raw event)")
    # -----------------------------------------------------------------------
    decision = {
        "proof_format_version": "1.0.0",
        "record_id": "loan-app-88213",
        "timestamp_unix": int(NOW.timestamp()),
        "governance_metadata": {
            "decision": "DECLINE",
            "applicant_ref": "anon-7f3a",  # pseudonymous, no PII in the trace
            "model": "credit-risk-v4",
            "reason_code": "DTI_ABOVE_THRESHOLD",
            "human_review": "not_required",
        },
        # WRAPPER fields (operational metadata) — must NOT affect the leaf hash:
        "content_hash": "sha256:" + hashlib.sha256(b"loan-app-88213/DECLINE").hexdigest(),
        "created_at_iso": NOW.isoformat().replace("+00:00", "Z"),
    }
    md = decision["governance_metadata"]
    print(f"Decision: {md['decision']} for {decision['record_id']} reason {md['reason_code']}")

    # -----------------------------------------------------------------------
    step("Layer 5 turns ON in production - and locks (monotonic-on, Article 12)")
    # -----------------------------------------------------------------------
    registry = LayerStatusRegistry(environment="production")
    state = registry.record_first_write(L5, first_record_id=decision["record_id"])
    print(f"  L5 enabled={state.enabled}  monotonic_on={state.monotonic_on}")
    print(f"  first governed record at: {state.first_record_at_iso}")
    print("  Compliance officer now tries to quietly switch L5 OFF...")
    try:
        registry.request_enabled(L5, False)
        print("  !!! disabled (THIS WOULD BE A BUG)")
    except LayerMonotonicityViolation:
        print("  REFUSED: LayerMonotonicityViolation - and the attempt itself is audited.")
    print(f"  audit timeline for L5: {[h['event'] for h in registry.history(L5)]}")

    # -----------------------------------------------------------------------
    step("Canonicalize (RFC 8785) - and prove the leaf/wrapper split")
    # -----------------------------------------------------------------------
    leaf_bytes = canon_leaf(decision)
    print(f"  leaf canonical bytes ({len(leaf_bytes)} B): {leaf_bytes[:72]!r}...")
    print("  -> 'created_at_iso' and 'content_hash' are WRAPPER fields; they appear")
    print("     in the wrapper canon but NOT in the leaf hash input.")
    assert canon_leaf({**decision, "ingest_node": "eu-central-1b"}) == leaf_bytes
    print("  PROVEN: adding a wrapper field did NOT change the leaf bytes.")

    # -----------------------------------------------------------------------
    step("Commit to a Merkle batch (RFC 6962) - the day's governed decisions")
    # -----------------------------------------------------------------------
    batch = [
        decision,
        {"proof_format_version": "1.0.0", "record_id": "loan-app-88214",
         "timestamp_unix": int(NOW.timestamp()) + 5, "content_hash": "sha256:bbb",
         "governance_metadata": {"decision": "APPROVE", "reason_code": "OK"}},
        {"proof_format_version": "1.0.0", "record_id": "loan-app-88215",
         "timestamp_unix": int(NOW.timestamp()) + 9, "content_hash": "sha256:ccc",
         "governance_metadata": {"decision": "DECLINE", "reason_code": "THIN_FILE"}},
    ]
    root_hex = MerkleTree.from_records(batch).root_hex
    print(f"  batch size: {len(batch)} governed decisions")
    print(f"  our decision's leaf hash: {leaf_hash_for_record(decision).hex()[:32]}...")
    print(f"  MERKLE ROOT: {root_hex}")
    print("  ^ this single root commits to all decisions in the batch.")

    # -----------------------------------------------------------------------
    step("Sign the batch root with an ed25519 key under a validity window (C-P2-1)")
    # -----------------------------------------------------------------------
    signing_priv = Ed25519PrivateKey.generate()
    kid = "graqle-bank-signing-2026-Q2"
    window = dict(valid_from=datetime(2026, 4, 1, tzinfo=UTC),
                  valid_until=datetime(2026, 7, 1, tzinfo=UTC))
    keys = Ed25519KeyManifest()
    keys.register(kid, signing_priv.public_key(), private_key=signing_priv, **window)
    signature = keys.sign(kid, bytes.fromhex(root_hex), at=NOW)
    print(f"  signed root with kid={kid}")
    print(f"  ed25519 signature ({len(signature)} B): {signature.hex()[:48]}...")

    # -----------------------------------------------------------------------
    step("Anchor: publish {root, kid, signature} to a public transparency log")
    # -----------------------------------------------------------------------
    # In production this is Sigstore Rekor (an external, append-only public log
    # GraQle does not control). Here we model the published, immutable anchor.
    anchor = {"merkle_root": root_hex, "kid": kid, "signature_hex": signature.hex(),
              "anchored_at": NOW.isoformat().replace("+00:00", "Z")}
    print(f"  ANCHOR (public, immutable): root={anchor['merkle_root'][:24]}... kid={anchor['kid']}")
    print("  In production this lands in Sigstore Rekor - anyone can fetch it later.")

    # -----------------------------------------------------------------------
    step("SIX MONTHS LATER - an auditor verifies, with NO access to bank/GraQle")
    # -----------------------------------------------------------------------
    # The auditor holds only: the decision record, the public anchor, and the
    # public key for the kid. They re-derive everything themselves.
    auditor = Ed25519KeyManifest()
    auditor.register(kid, signing_priv.public_key(), **window)  # public key only, no private
    root_ok = MerkleTree.from_records(batch).root_hex == anchor["merkle_root"]
    sig_ok = auditor.verify(kid, bytes.fromhex(anchor["merkle_root"]),
                            bytes.fromhex(anchor["signature_hex"]), at=NOW)
    print(f"  recomputed Merkle root matches anchor? {root_ok}")
    print(f"  ed25519 signature valid for that root? {sig_ok}")
    verdict = "AUTHENTIC - record provably unaltered" if root_ok and sig_ok else "FAILED"
    print(f"  VERDICT: {verdict}")
    assert root_ok and sig_ok

    # -----------------------------------------------------------------------
    step("A TAMPERER flips the decision DECLINE -> APPROVE and re-presents it")
    # -----------------------------------------------------------------------
    tampered = {**decision,
                "governance_metadata": {**decision["governance_metadata"], "decision": "APPROVE"}}
    tampered_root = MerkleTree.from_records([tampered, batch[1], batch[2]]).root_hex
    roots_differ = tampered_root != anchor["merkle_root"]
    sig_on_tamper = auditor.verify(kid, bytes.fromhex(tampered_root),
                                   bytes.fromhex(anchor["signature_hex"]), at=NOW)
    print(f"  tampered decision: {tampered['governance_metadata']['decision']}")
    print(f"  original anchored root : {anchor['merkle_root'][:32]}...")
    print(f"  tampered recomputed root: {tampered_root[:32]}...")
    print(f"  root changed by the tamper? {roots_differ}")
    print(f"  signature still valid on tampered root? {sig_on_tamper}")
    caught = roots_differ and not sig_on_tamper
    print(f"  VERDICT: {'TAMPER DETECTED - math does not lie' if caught else 'MISSED'}")
    assert caught

    # -----------------------------------------------------------------------
    step("Key compromised? Revoke it - past forgeries with that key stop verifying")
    # -----------------------------------------------------------------------
    auditor.revoke(kid)
    print(f"  key {kid} state -> {auditor.get(kid).state.value}")
    after_revoke = auditor.verify(kid, bytes.fromhex(anchor["merkle_root"]),
                                  bytes.fromhex(anchor["signature_hex"]), at=NOW)
    print(f"  even the ORIGINAL valid signature now verifies? {after_revoke}")
    print("  REVOKED keys are rejected unconditionally - the compromise escape hatch.")
    assert after_revoke is False

    print(f"\n{'#' * 70}")
    print("USE CASE COMPLETE - all steps executed against the installed graqle:")
    print("  decision -> monotonic-on lock -> RFC8785 canon -> RFC6962 Merkle ->")
    print("  ed25519 sign (windowed key) -> public anchor -> auditor verifies AUTHENTIC")
    print("  -> tamper DETECTED -> revocation enforced.")
    print("Tampering with a governed AI decision is mathematically detectable by anyone.")
    print("#" * 70)


if __name__ == "__main__":
    main()
