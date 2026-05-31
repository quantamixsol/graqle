"""Standalone offline verifier for GraQle-format tamper-evidence proof bundles.

This module is the **canonical verifier** (moat M2) and the engineered form of
the survive-our-disappearance invariant: given a proof bundle, a trusted-key
manifest, and nothing else — no network, no GraQle service, no proprietary
code — it answers whether the proof holds. If GraQle vanished tomorrow, a third
party with this file (or a re-implementation of it) and the public signing keys
could still verify every proof we ever emitted.

It is FREE and open forever (Apache-2.0, Community edition) and is NEVER gated.

Isolation contract (the moat invariant)
----------------------------------------
``verify_bundle`` composes only four already-shipped primitives —
:func:`~graqle.governance.tamper_evidence.merkle.leaf_hash_for_record`,
:class:`~graqle.governance.tamper_evidence.merkle.InclusionProof`,
:func:`~graqle.governance.tamper_evidence.canonicalize.canon`, and
:class:`~graqle.governance.custody.ed25519_key_manifest.Ed25519KeyManifest` —
plus the Python standard library and ``cryptography`` (a core dependency).

It imports **nothing** from ``graqle.server``, ``graqle.studio``, or any
anchoring/network client. Rekor inclusion data, if checked, is passed *in the
bundle as data* and is never fetched. A runtime import guard (below) fails loudly
at import time if a server/studio module is already loaded in the process, so a
regression that smuggles a proprietary or network dependency into the verifier's
import graph is caught immediately rather than silently breaking the moat. The
same isolation is enforced statically by the WS-A3 CI AST gate; runtime + CI is
defense-in-depth (a CI-only check would let a runtime regression pass unseen).

Canonical proof-bundle schema (R25-EU01 §358 "Proof Bundle Schema")
-------------------------------------------------------------------
``verify_bundle`` accepts a JSON-style ``dict`` with these fields::

    {
      "proof_format_version": "1",          # str, must match leaf's version
      "record": { ... },                    # the governed-trace record; MUST
                                            #   itself carry proof_format_version
                                            #   (enforced by canon_leaf)
      "leaf": {
        "leaf_index": 3,                    # int, position in the tree
        "tree_size": 8,                     # int, number of leaves
        "leaf_hash": "<hex>"                # the record's RFC 6962 leaf hash
      },
      "merkle": {
        "merkle_root": "<hex>",             # the batch root
        "merkle_path": ["<hex>", ...],      # sibling hashes bottom-up
        "merkle_path_directions": [0, 1, …] # 0 = sibling-left, 1 = sibling-right
      },
      "signature": {
        "alg": "ed25519",                   # only ed25519 is accepted
        "kid": "graqle-sdk-signing-2026-Q2",
        "sig": "<hex>",                     # ed25519 signature over signed_message
        "signed_at": "2026-05-31T13:00:00Z" # RFC 3339 UTC; the trust instant
      },
      "rekor": {                            # OPTIONAL — offline data, never fetched
        "log_index": 42,
        "log_id": "...",
        "signed_tree_head": "...",
        "inclusion_cert": "...",
        "integrated_time": 1748000000
      }
    }

What the signature covers (SD-001, locked 2026-05-31)
-----------------------------------------------------
The ed25519 signature is over ``canon`` of::

    {
      "proof_format_version": <version>,
      "merkle_root": <merkle_root hex>,
      "kid": <kid>,
      "signed_at": <signed_at>
    }

The Merkle root already commits to every leaf in the batch (RFC 6962), so
signing the root transitively authenticates the record without re-signing each
leaf. The signature is therefore small and shareable across every proof in a
batch, and it binds the exact bytes Rekor anchors. ``verify_bundle`` reconstructs
this message byte-for-byte via :func:`canon`, so the literal order of these four
fields is irrelevant — JCS sorts keys — but the field *set* is frozen interop
contract.

Verification steps (each failure is typed, never an exception to the caller)
----------------------------------------------------------------------------
1. **Shape** — missing/malformed fields → :attr:`VerifyFailure.MALFORMED_BUNDLE`.
2. **Leaf recompute** — ``leaf_hash_for_record(record)`` must equal the stated
   ``leaf_hash`` (constant-time) → :attr:`VerifyFailure.TAMPERED_LEAF`.
3. **Merkle inclusion** — the reconstructed :class:`InclusionProof` must recompute
   to ``merkle_root`` → :attr:`VerifyFailure.WRONG_ROOT`.
4. **Signature trust** — ``trusted_keys.verify(kid, signed_message, sig,
   at=signed_at)`` under the 3-state custody lifecycle → an unknown kid is
   :attr:`VerifyFailure.UNKNOWN_KID`; a falsey result (revoked, out-of-window, or
   cryptographically invalid) is :attr:`VerifyFailure.UNTRUSTED_KID`.
5. **Rekor (optional)** — if a ``rekor`` block is present its ``signed_tree_head``
   must commit to ``merkle_root`` → :attr:`VerifyFailure.REKOR_MISMATCH`,
   ``rekor_checked=True``. Absent → ``rekor_checked=False`` and the proof can
   still be ``ok`` (a locally-anchored proof is valid without a public log).

The whole function is pure: no I/O, no network, no file handles, no clock reads
beyond parsing ``signed_at`` from the bundle. All hash/identity comparisons use
:func:`hmac.compare_digest` to resist timing oracles.
"""

from __future__ import annotations

import hmac
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from graqle.governance.custody.ed25519_key_manifest import (
    Ed25519KeyManifest,
    UnknownKidError,
)
from graqle.governance.tamper_evidence.canonicalize import canon
from graqle.governance.tamper_evidence.errors import TamperEvidenceError
from graqle.governance.tamper_evidence.merkle import (
    InclusionProof,
    leaf_hash_for_record,
)

# ── Runtime import-isolation guard (moat M2, defense-in-depth with WS-A3 CI) ──
#
# The verifier's value is that it depends on nothing proprietary and nothing
# networked. If a server/studio module is already imported in this process when
# the verifier is imported, *something* has wired the verifier into a surface it
# must stay free of — fail loudly here rather than let the moat erode silently.
# We check sys.modules (already-imported), NOT a fresh import, so this never
# itself pulls server/studio in. The WS-A3 CI AST gate enforces the same
# invariant statically on the import graph; the two together are belt-and-braces.
_FORBIDDEN_MODULE_PREFIXES = ("graqle.server", "graqle.studio")


def _assert_isolated(loaded_modules: object = None) -> None:
    """Raise if a forbidden (server/studio) module is present in ``sys.modules``.

    ``loaded_modules`` defaults to ``sys.modules``; it is injectable purely so
    the isolation guard itself is unit-testable without manipulating the real
    interpreter module table. A module counts as forbidden if its dotted name
    equals or is a sub-package of any entry in
    :data:`_FORBIDDEN_MODULE_PREFIXES`.
    """
    modules = sys.modules if loaded_modules is None else loaded_modules
    offenders = sorted(
        name
        for name in modules
        if any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in _FORBIDDEN_MODULE_PREFIXES
        )
    )
    if offenders:
        raise ImportError(
            "graqle.governance.tamper_evidence.verifier must stay isolated from "
            "proprietary/networked surfaces, but these forbidden modules are "
            f"already loaded: {offenders}. The standalone verifier is moat M2 — "
            "it may import only merkle, canonicalize, custody.ed25519_key_manifest, "
            "the standard library, and cryptography. See the WS-A3 CI gate."
        )


_assert_isolated()


class VerifierError(TamperEvidenceError):
    """Base class for verifier-level *misuse* errors (NOT failed verifications).

    ``verify_bundle`` never raises on a *failed* verification — a bad proof yields
    a :class:`VerifyResult` with ``ok=False`` and a typed :class:`VerifyFailure`.
    This error type is reserved for misuse of the API itself (e.g. passing
    something that is not a key manifest), so callers can distinguish "the proof
    did not verify" from "you called me wrong".
    """


class VerifyFailure(str, Enum):
    """The single, typed reason a bundle failed to verify (or ``OK``).

    A ``str`` enum so the value is JSON/log friendly and stable across releases:
    these names are part of the public verifier contract (machine-readable
    ``--format json`` in WS-A2 emits them verbatim). Each non-OK member maps to
    exactly one verification step, so a caller can branch on *why* a proof failed
    without parsing prose.
    """

    OK = "OK"
    MALFORMED_BUNDLE = "MALFORMED_BUNDLE"
    TAMPERED_LEAF = "TAMPERED_LEAF"
    WRONG_ROOT = "WRONG_ROOT"
    UNKNOWN_KID = "UNKNOWN_KID"
    UNTRUSTED_KID = "UNTRUSTED_KID"
    REKOR_MISMATCH = "REKOR_MISMATCH"


# Verification step names, used as keys in VerifyResult.checks. Frozen so the
# result shape is a stable contract for the CLI / external auditors.
_CHECK_LEAF = "leaf"
_CHECK_MERKLE = "merkle"
_CHECK_SIGNATURE = "signature"
_CHECK_REKOR = "rekor"


@dataclass(frozen=True)
class VerifyResult:
    """The outcome of :func:`verify_bundle` — a value object, never an exception.

    Attributes
    ----------
    ok:
        ``True`` iff every *attempted* check passed. The optional Rekor check not
        being attempted (no ``rekor`` block) does not make ``ok`` False — a
        locally-anchored proof is valid without a public-log receipt.
    failure:
        The single typed reason verification failed, or :attr:`VerifyFailure.OK`
        when ``ok`` is True. Exactly one failure is reported: checks run in order
        (leaf → merkle → signature → rekor) and the first failure short-circuits,
        because a later check is meaningless once an earlier invariant is broken
        (e.g. an inclusion proof against a tampered leaf is not informative).
    checks:
        Per-step booleans for the checks that ran (``leaf``/``merkle``/
        ``signature`` always when reached; ``rekor`` only when a receipt was
        present). A step that did not run is absent from the mapping rather than
        recorded ``False``, so ``checks`` distinguishes "ran and passed", "ran and
        failed", and "not attempted".
    rekor_checked:
        Whether an offline Rekor inclusion check was performed (i.e. a ``rekor``
        block was present and validated). ``False`` means no receipt was in the
        bundle, NOT that one was present and failed (that would be ``ok=False``
        with ``failure=REKOR_MISMATCH``).
    """

    ok: bool
    failure: VerifyFailure
    checks: dict[str, bool] = field(default_factory=dict)
    rekor_checked: bool = False


def _fail(failure: VerifyFailure, checks: dict[str, bool]) -> VerifyResult:
    """Build a failed :class:`VerifyResult` carrying the checks run so far."""
    return VerifyResult(
        ok=False,
        failure=failure,
        checks=dict(checks),
        rekor_checked=checks.get(_CHECK_REKOR, False),
    )


def _require_obj(mapping: object, key: str) -> dict[str, Any]:
    """Return ``mapping[key]`` requiring both to be dicts, else raise.

    Used inside the shape-validation try/except so a missing key or a non-dict
    where a dict was expected both surface as MALFORMED_BUNDLE rather than an
    uncaught exception escaping ``verify_bundle``.
    """
    if not isinstance(mapping, dict):
        raise TypeError(f"expected an object to read {key!r} from")
    value = mapping[key]
    if not isinstance(value, dict):
        raise TypeError(f"{key!r} must be an object")
    return value


def _hex_to_bytes(value: object) -> bytes:
    """Decode a hex string to bytes, raising on any non-str / malformed hex.

    A bundle field that should be hex but is an int, None, or malformed hex is a
    shape error (MALFORMED_BUNDLE), so this raises ValueError/TypeError that the
    caller's shape guard converts into a typed failure.
    """
    if not isinstance(value, str):
        raise TypeError(f"expected a hex string, got {type(value).__name__}")
    return bytes.fromhex(value)


def _require_int(value: object, name: str) -> int:
    """Return ``value`` as an int, rejecting bool (a bool is not a valid index)."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int")
    return value


def _parse_signed_at(value: object) -> datetime:
    """Parse an RFC 3339 ``signed_at`` to a timezone-aware UTC ``datetime``.

    Accepts a trailing ``Z`` (common in proof bundles) as well as explicit
    offsets. A naive timestamp is treated as UTC. A non-string or unparseable
    value raises, surfacing as MALFORMED_BUNDLE.
    """
    if not isinstance(value, str):
        raise TypeError(f"signed_at must be a string, got {type(value).__name__}")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _signed_message(
    proof_format_version: object, merkle_root_hex: str, kid: str, signed_at: str
) -> bytes:
    """Reconstruct the exact bytes the signature covers (SD-001).

    Canonicalizes the frozen four-field set with :func:`canon` (RFC 8785 JCS).
    JCS sorts object keys, so the literal order here is irrelevant — what is
    fixed is the field *set*. Building this from the bundle's own values means a
    verifier recomputes the signer's message rather than trusting any precomputed
    "signed_message" the bundle might (maliciously) carry.
    """
    return canon(
        {
            "proof_format_version": proof_format_version,
            "merkle_root": merkle_root_hex,
            "kid": kid,
            "signed_at": signed_at,
        }
    )


def verify_bundle(
    proof_bundle: dict[str, Any], trusted_keys: Ed25519KeyManifest
) -> VerifyResult:
    """Verify a GraQle-format proof bundle offline against a trusted-key manifest.

    Parameters
    ----------
    proof_bundle:
        A bundle conforming to the schema in the module docstring. Treated as
        untrusted input: any structural defect yields
        :attr:`VerifyFailure.MALFORMED_BUNDLE` rather than an exception.
    trusted_keys:
        The :class:`Ed25519KeyManifest` holding the public keys (and their
        validity windows + lifecycle states) the verifier trusts. A verify-only
        manifest holding only public material is the common case.

    Returns
    -------
    VerifyResult
        ``ok=True`` with ``failure=OK`` iff every attempted check passed; else
        ``ok=False`` with the single typed :class:`VerifyFailure` for the first
        failing step. Never raises for a bad *proof*; raises
        :class:`VerifierError` only for caller misuse (a non-manifest
        ``trusted_keys``).
    """
    if not isinstance(trusted_keys, Ed25519KeyManifest):
        raise VerifierError(
            "trusted_keys must be an Ed25519KeyManifest holding the public keys "
            f"to trust; got {type(trusted_keys).__name__}"
        )

    checks: dict[str, bool] = {}

    # ── Step 0: shape ────────────────────────────────────────────────────────
    # Pull every field we need up front; any KeyError/TypeError/ValueError here
    # means the bundle is structurally malformed. We catch broadly (those three
    # families only) so a missing key, a wrong type, or bad hex all map to one
    # typed failure instead of leaking a stack trace to the caller.
    try:
        if not isinstance(proof_bundle, dict):
            raise TypeError("proof_bundle must be an object")
        proof_format_version = proof_bundle["proof_format_version"]

        record = proof_bundle["record"]
        if not isinstance(record, dict):
            raise TypeError("record must be an object")

        leaf = _require_obj(proof_bundle, "leaf")
        leaf_index = _require_int(leaf["leaf_index"], "leaf_index")
        tree_size = _require_int(leaf["tree_size"], "tree_size")
        stated_leaf_hash = _hex_to_bytes(leaf["leaf_hash"])

        merkle = _require_obj(proof_bundle, "merkle")
        merkle_root_hex = merkle["merkle_root"]
        merkle_root = _hex_to_bytes(merkle_root_hex)
        merkle_path_hex = merkle["merkle_path"]
        directions = merkle["merkle_path_directions"]
        if not isinstance(merkle_path_hex, list) or not isinstance(directions, list):
            raise TypeError("merkle_path and merkle_path_directions must be arrays")
        merkle_path = [_hex_to_bytes(h) for h in merkle_path_hex]

        signature = _require_obj(proof_bundle, "signature")
        alg = signature["alg"]
        kid = signature["kid"]
        sig_bytes = _hex_to_bytes(signature["sig"])
        signed_at_raw = signature["signed_at"]
        if not isinstance(kid, str):
            raise TypeError("signature.kid must be a string")
        signed_at = _parse_signed_at(signed_at_raw)
    except (KeyError, TypeError, ValueError):
        return _fail(VerifyFailure.MALFORMED_BUNDLE, checks)

    # Only ed25519 is accepted; an unexpected alg is a malformed/unsupported
    # bundle, not a trust failure (we never reached a key).
    if alg != "ed25519":
        return _fail(VerifyFailure.MALFORMED_BUNDLE, checks)

    # ── Step 1: leaf recompute ───────────────────────────────────────────────
    # Recompute the leaf hash from the record itself and compare (constant-time)
    # to the stated leaf hash. canon_leaf (inside leaf_hash_for_record) requires
    # proof_format_version inside the record; a record lacking it raises, which
    # we treat as a tampered/invalid leaf rather than a malformed wrapper.
    try:
        recomputed_leaf = leaf_hash_for_record(record)
    except (TamperEvidenceError, ValueError, TypeError):
        return _fail(VerifyFailure.TAMPERED_LEAF, checks)
    if not hmac.compare_digest(recomputed_leaf, stated_leaf_hash):
        return _fail(VerifyFailure.TAMPERED_LEAF, checks)
    checks[_CHECK_LEAF] = True

    # ── Step 2: Merkle inclusion ─────────────────────────────────────────────
    # Reconstruct the inclusion proof from the RECOMPUTED leaf hash (not the
    # stated one — using the recomputed hash means the inclusion proof is checked
    # against the bytes we actually trust). InclusionProof's constructor enforces
    # path/direction length + value integrity; a structural defect there is a
    # malformed proof, surfaced as WRONG_ROOT (the merkle step did not pass).
    try:
        inclusion = InclusionProof(
            leaf_index=leaf_index,
            tree_size=tree_size,
            leaf_hash=recomputed_leaf,
            merkle_path=merkle_path,
            merkle_path_directions=list(directions),
        )
        merkle_ok = inclusion.verify(merkle_root)
    except (TamperEvidenceError, ValueError, TypeError):
        return _fail(VerifyFailure.WRONG_ROOT, checks)
    if not merkle_ok:
        return _fail(VerifyFailure.WRONG_ROOT, checks)
    checks[_CHECK_MERKLE] = True

    # ── Step 3: signature trust ──────────────────────────────────────────────
    # Verify the ed25519 signature over the reconstructed signed_message at the
    # proof's recorded time. An unknown kid is a distinct, caller-relevant
    # condition (the signer is not in the manifest at all) vs. a known-but-
    # untrusted key (revoked / out-of-window) or a bad signature — the latter two
    # are indistinguishable by design (manifest.verify returns False) and both
    # collapse to UNTRUSTED_KID.
    signed_message = _signed_message(
        proof_format_version, merkle_root_hex, kid, signed_at_raw
    )
    try:
        signature_ok = trusted_keys.verify(kid, signed_message, sig_bytes, at=signed_at)
    except UnknownKidError:
        return _fail(VerifyFailure.UNKNOWN_KID, checks)
    if not signature_ok:
        return _fail(VerifyFailure.UNTRUSTED_KID, checks)
    checks[_CHECK_SIGNATURE] = True

    # ── Step 4: optional offline Rekor inclusion ─────────────────────────────
    # A rekor block is OPTIONAL. When present, it must commit to the same root we
    # just verified the record into. We do NOT contact the network: the receipt's
    # signed_tree_head is treated as data and checked for consistency with
    # merkle_root. A present-but-inconsistent receipt fails closed.
    rekor = proof_bundle.get("rekor")
    if rekor is not None:
        if not _verify_rekor_offline(rekor, merkle_root_hex):
            checks[_CHECK_REKOR] = False
            return _fail(VerifyFailure.REKOR_MISMATCH, checks)
        checks[_CHECK_REKOR] = True

    return VerifyResult(
        ok=True,
        failure=VerifyFailure.OK,
        checks=dict(checks),
        rekor_checked=checks.get(_CHECK_REKOR, False),
    )


def _verify_rekor_offline(rekor: object, merkle_root_hex: str) -> bool:
    """Offline consistency check of a Rekor receipt against the Merkle root.

    This is a *data* check, never a network call (the verifier's isolation
    contract). A well-formed receipt must (a) be an object carrying the required
    fields and (b) bind the same ``merkle_root`` the inclusion proof verified
    into — the receipt's ``signed_tree_head`` must reference that exact root hex.

    Full cryptographic validation of Rekor's signed tree head against the Rekor
    public key (Sigstore key material) is performed by an external auditor /
    ``rekor-cli`` and is intentionally out of scope for the offline SDK verifier,
    which holds no Rekor key material and makes no network calls. What we
    guarantee here is that the binding the bundle asserts is internally
    consistent: the receipt in the bundle is *about this root*, so a receipt
    copied from a different anchor cannot be passed off as this proof's anchor.
    Returns ``True`` iff the receipt is well-formed and references
    ``merkle_root_hex``; ``False`` (fail closed) for any structural defect or a
    root mismatch.
    """
    if not isinstance(rekor, dict):
        return False
    required = ("log_index", "log_id", "signed_tree_head", "inclusion_cert")
    if any(key_name not in rekor for key_name in required):
        return False
    signed_tree_head = rekor["signed_tree_head"]
    if not isinstance(signed_tree_head, str):
        return False
    # The receipt must reference the exact root hex we verified into. We compare
    # constant-time on the encoded bytes; the root hex carried in the STH is the
    # binding between this receipt and this proof.
    return hmac.compare_digest(
        merkle_root_hex.encode("utf-8"),
        _extract_anchored_root_hex(signed_tree_head).encode("utf-8"),
    )


def _extract_anchored_root_hex(signed_tree_head: str) -> str:
    """Extract the anchored root hex a Rekor STH commits to.

    Bundles produced by GraQle's own committer record the anchored root hex
    directly as the ``signed_tree_head`` value (the STH's root_hash field,
    lower-hex). External Rekor STHs carry the root inside a signed JSON blob;
    parsing/validating those against the Rekor public key is the external
    auditor's job (see :func:`_verify_rekor_offline`). Here we return the value
    as-is so the offline binding check compares like-for-like; a mismatch with
    ``merkle_root_hex`` fails closed upstream.
    """
    return signed_tree_head


__all__ = [
    "VerifyFailure",
    "VerifyResult",
    "VerifierError",
    "verify_bundle",
]
