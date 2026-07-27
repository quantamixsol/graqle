"""Regenerate the CR-010.R1 conformance corpus fixtures + golden vectors.

Development convenience ONLY. The **committed** JSON files under ``fixtures/``
are the ground truth for conformance — a third-party implementer reads those,
never this script. Running this script must be idempotent: same inputs, same
bytes out (no timestamps, no randomness).

Determinism
-----------
The signing key is derived from a FIXED seed (never a real key, never
``os.urandom``) so the corpus is byte-stable across regenerations and machines.
That is a deliberate property of a *test* corpus: the vectors must be
reproducible by anyone. It is NOT a production key and is labelled as such.

Usage::

    python -m graqle.pct.schema.conformance.generate_fixtures

Then re-run the conformance tests to confirm the corpus still classifies
identically.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from graqle.governance.tamper_evidence.canonicalize import canon
from graqle.governance.tamper_evidence.merkle import MerkleTree

FIXTURES = Path(__file__).parent / "fixtures"

# A FIXED, PUBLICLY-KNOWN test seed. Not a secret, not a production key.
_TEST_SEED = bytes(range(32))

KID = "graqle-conformance-test-key"
OTHER_KID = "graqle-conformance-rotated-key"
SIGNED_AT = "2026-01-01T00:00:00Z"
PROOF_FORMAT_VERSION = "1"

# Four records -> a 4-leaf tree. The corpus proves leaf 1 of 4.
#
# Every field below is inside the frozen LEAF_HASH_FIELDS allowlist
# (content_hash, governance_metadata, proof_format_version, record_id,
# timestamp_unix). This matters: canon_leaf PROJECTS the record onto that
# allowlist, so a field outside it provably cannot change the leaf hash — the
# TC-003 tamper must therefore mutate a leaf-committed field to be meaningful.
_RECORDS: list[dict[str, Any]] = [
    {
        "proof_format_version": PROOF_FORMAT_VERSION,
        "record_id": f"conformance-record-{i}",
        "content_hash": f"{i:064x}",
        "timestamp_unix": 1767225600 + i,
        "governance_metadata": {"decision": ["ALLOW", "DENY", "ALLOW", "WARN"][i]},
    }
    for i in range(4)
]
_TARGET_INDEX = 1


def _signing_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(_TEST_SEED)


def _other_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))


def _public_pem(key: Ed25519PrivateKey) -> str:
    return (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )


def _signed_message(merkle_root_hex: str, kid: str, signed_at: str) -> bytes:
    """Rebuild the SD-001 signing preimage (locked 2026-05-31).

    The signature covers exactly these four fields, canonicalized with JCS.
    ``proof_format_version`` is part of the preimage — which is precisely why
    it is signature-covered and cannot be rewritten by any normalization shim.
    """
    return canon(
        {
            "proof_format_version": PROOF_FORMAT_VERSION,
            "merkle_root": merkle_root_hex,
            "kid": kid,
            "signed_at": signed_at,
        }
    )


def _base_bundle() -> dict[str, Any]:
    """Build a genuine, fully-verifying proof bundle for leaf 1 of 4."""
    tree = MerkleTree.from_records(_RECORDS)
    proof = tree.inclusion_proof(_TARGET_INDEX)
    root_hex = tree.root.hex()

    key = _signing_key()
    sig = key.sign(_signed_message(root_hex, KID, SIGNED_AT)).hex()

    merkle_fields = proof.to_bundle()
    return {
        "proof_format_version": PROOF_FORMAT_VERSION,
        "record": _RECORDS[_TARGET_INDEX],
        "leaf": {
            "leaf_index": merkle_fields["leaf_index"],
            "tree_size": merkle_fields["tree_size"],
            "leaf_hash": proof.leaf_hash.hex(),
        },
        "merkle": {
            "merkle_root": root_hex,
            "merkle_path": merkle_fields["merkle_path"],
            "merkle_path_directions": merkle_fields["merkle_path_directions"],
        },
        "signature": {
            "alg": "ed25519",
            "kid": KID,
            "sig": sig,
            "signed_at": SIGNED_AT,
        },
    }


def _flip_last_hex(value: str) -> str:
    """Flip the final hex nibble — a minimal, surgical corruption."""
    last = value[-1]
    return value[:-1] + ("1" if last != "1" else "2")


def _write(name: str, payload: Any) -> None:
    path = FIXTURES / name
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"  wrote {path.name}")


#: Machine-readable marker stamped into every corpus keyring. Sentinel pass 1,
#: finding (b): the signing key is derived from a FIXED, publicly-known seed so
#: the corpus is reproducible — which means anything it signs is forgeable by
#: anyone. A human-readable kid ("...-test-key") is not enough; a grep-able,
#: assertable flag lets CI prove no conformance keyring ever reaches a real
#: trust store.
TEST_ONLY_MARKER = "_test_only"


def _keyring(kid: str, pem: str, state: str = "ACTIVE", **extra: str) -> dict[str, Any]:
    entry: dict[str, Any] = {"kid": kid, "public_key_pem": pem, "state": state}
    entry.update(extra)
    return {
        TEST_ONLY_MARKER: True,
        "_warning": (
            "CONFORMANCE TEST DATA — NOT FOR PRODUCTION. The matching private "
            "key is derived from a fixed, publicly-known seed and can be "
            "reproduced by anyone. Never add this key to a real trust store."
        ),
        "keys": [entry],
    }


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    print("Regenerating CR-010.R1 conformance fixtures...")

    key = _signing_key()
    pem = _public_pem(key)
    base = _base_bundle()

    # --- keyrings -------------------------------------------------------
    _write("keyring_default.json", _keyring(KID, pem))
    _write("keyring_revoked.json", _keyring(KID, pem, state="REVOKED"))
    _write(
        "keyring_expired.json",
        _keyring(
            KID,
            pem,
            state="ACTIVE",
            valid_from="2020-01-01T00:00:00Z",
            valid_until="2020-12-31T23:59:59Z",
        ),
    )
    # Rotated: the keyring knows only a DIFFERENT kid -> bundle kid is unknown.
    _write("keyring_rotated.json", _keyring(OTHER_KID, _public_pem(_other_key())))

    # --- TC-001 valid ---------------------------------------------------
    _write("tc001_valid.json", base)

    # --- TC-002 malformed (required `merkle` block removed) -------------
    malformed = json.loads(json.dumps(base))
    del malformed["merkle"]
    _write("tc002_malformed.json", malformed)

    # --- TC-003 tampered leaf -------------------------------------------
    # The record is mutated but leaf/merkle/signature are left EXACTLY as
    # signed. That is what a real tamper looks like: the attacker edits the
    # payload and cannot re-derive the committed leaf hash. Leaf recompute
    # therefore disagrees with the stated leaf_hash -> TAMPERED_LEAF.
    # (Regenerating the leaf hash from the mutated record instead would make
    # the bundle self-consistent and classify OK — an empirically-caught trap.)
    tampered = json.loads(json.dumps(base))
    tampered["record"]["content_hash"] = _flip_last_hex(
        tampered["record"]["content_hash"]
    )
    _write("tc003_tampered_leaf.json", tampered)

    # --- TC-004 wrong root (root mutated; signature still over old root)-
    # Leaf recompute passes, inclusion recompute != stated root -> WRONG_ROOT.
    wrong_root = json.loads(json.dumps(base))
    wrong_root["merkle"]["merkle_root"] = _flip_last_hex(
        wrong_root["merkle"]["merkle_root"]
    )
    _write("tc004_wrong_root.json", wrong_root)

    # --- TC-005 / TC-006 / TC-006b reuse the valid bundle ---------------
    # They differ only by which KEYRING is supplied, which is the point: the
    # bundle is untouched, the TRUST STATE changes.

    # --- TC-007 rekor receipt mismatch ----------------------------------
    rekor = json.loads(json.dumps(base))
    rekor["rekor"] = {
        "log_index": 42,
        "log_id": "conformance-test-log",
        "signed_tree_head": _flip_last_hex(base["merkle"]["merkle_root"]),
        "inclusion_cert": "conformance-test-cert",
        "integrated_time": 1767225600,
    }
    _write("tc007_rekor_mismatch.json", rekor)

    # --- TC-008 unreadable input (not valid JSON at all) ----------------
    (FIXTURES / "tc008_not_json.txt").write_text(
        "this file is deliberately not JSON - exit code 2\n", encoding="utf-8"
    )
    print("  wrote tc008_not_json.txt")

    print("Done. Re-run the conformance tests to confirm classification.")


if __name__ == "__main__":
    main()
