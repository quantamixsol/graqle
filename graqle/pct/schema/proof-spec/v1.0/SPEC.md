# GraQle Proof Spec — v1.0

**Spec version:** `1.0`
**Status:** FROZEN
**Versioning:** This spec version is **independent of the GraQle SDK version**.
An SDK release never implies a spec change, and a spec change never requires an
SDK major bump. Pin to `proof-spec/v1.0/` and you are pinned regardless of which
SDK version produced a bundle.

---

## 1. What this spec is

A GraQle **proof bundle** is portable, offline-verifiable evidence that one
governed-trace record was committed inside a batch at a point in time, signed by
a known key.

This document plus the three schemas beside it are sufficient to implement a
compatible verifier **without reading GraQle source code**. Implementations are
checked mechanically against the conformance corpus in `../../conformance/`.

**Scope — envelope only.** This spec defines the *shape and classification
contract* of the artifacts: field names, types, status enums, the Merkle
structure, and process exit codes. It deliberately does not describe how GraQle
scores, ranks, or reasons about anything, and no such internal is required to
verify a proof.

## 2. Artifacts

| Schema | What it describes |
|---|---|
| `bundle.schema.json` | The proof bundle a verifier consumes |
| `keyring.schema.json` | The trusted-key manifest it is evaluated against |
| `verify-result.schema.json` | The JSON a verifier emits under `--format json` |

## 3. Verification procedure (normative)

A conformant verifier performs these steps **in this order**, and the **first
failure stops evaluation**:

1. **Shape** — the bundle has the required fields with the required types.
   Otherwise → `MALFORMED_BUNDLE`.
2. **Leaf recompute** — recompute the record's leaf hash and compare it against
   the stated `leaf.leaf_hash`. Mismatch → `TAMPERED_LEAF`.
3. **Merkle inclusion** — fold `leaf_hash` with `merkle.merkle_path` using
   `merkle.merkle_path_directions` and compare against `merkle.merkle_root`.
   Mismatch → `WRONG_ROOT`.
4. **Signature trust** — resolve `signature.kid` in the keyring. Absent →
   `UNKNOWN_KID`. Present but not trusted at `signature.signed_at` (revoked,
   outside its window, or a bad signature) → `UNTRUSTED_KID`.
5. **Rekor (optional)** — if and only if a `rekor` block is present, check
   offline that it commits to the same `merkle_root`. Inconsistent →
   `REKOR_MISMATCH`. **A bundle with no receipt is still valid.**

Ordering is normative because a later check is not meaningful once an earlier
invariant is broken: an inclusion proof against a tampered leaf tells you
nothing.

### 3.1 What the signature covers

The ed25519 signature is over the canonical (RFC 8785 JCS) encoding of exactly
these four fields:

```
proof_format_version, merkle_root, kid, signed_at
```

The Merkle root already commits to every leaf in the batch (RFC 6962), so
signing the root transitively authenticates the record.

> **`proof_format_version` is signature-covered.** A verifier MUST treat it as
> opaque bytes. Rewriting, normalizing, or "upgrading" this value changes the
> signed preimage and will invalidate an otherwise-valid signature. At spec v1.0
> the field is therefore type-constrained but **not** value-constrained.

**Why leaving it value-unconstrained is safe.** The field is inside *both* the
signed preimage *and* the leaf hash, so cryptography — not schema validation —
is what pins it. Forging it fails closed in both directions:

| Forgery | Result |
|---|---|
| Change it in the wrapper only | `UNTRUSTED_KID` — signature no longer validates |
| Change it in wrapper **and** record | `TAMPERED_LEAF` — leaf hash no longer matches |

A schema `enum` would therefore add no security, while breaking legitimately
divergent values already in circulation. Producers SHOULD nonetheless emit a
consistent value; consumers MUST NOT rewrite one.

### 3.2 Key lifecycle

`ACTIVE → RETIRED → REVOKED`, monotonic — a key never moves backwards.

- **ACTIVE** — signs new proofs; verifies.
- **RETIRED** — signs nothing new, but proofs it made earlier **still verify**.
  Retirement is not revocation.
- **REVOKED** — rejected unconditionally.

## 4. Result contract

```json
{ "ok": true, "failure": "OK",
  "checks": { "leaf": true, "merkle": true, "signature": true },
  "rekor_checked": false }
```

Two rules carry the most interop weight:

- **Absent ≠ false.** A check that did not run is **absent** from `checks`. A
  check that ran and failed is present with `false`. Treating absent as `false`
  is a conformance failure.
- **`ok` ignores an unattempted Rekor check.** No receipt means
  `rekor_checked: false` with `ok: true`.

## 5. Exit codes

| Code | Meaning |
|---|---|
| `0` | Verified |
| `1` | Did not verify (a typed failure) |
| `2` | Usage error — unreadable/malformed input, or a bad key file |

Code `2` is deliberately distinct from `1`: "I could not attempt this" is not
"this proof is bad". CI can therefore separate infrastructure faults from
genuine verification failures.

A usage error emits a **different, deliberately non-conforming payload** —
because no verification was attempted, there is no result to report:

```json
{ "ok": false, "error": "bundle file is not valid JSON: ..." }
```

It carries no `failure` and no `checks`, and it does **not** validate against
`verify-result.schema.json`. The **exit code is the contract** for this case;
the payload is a human diagnostic whose message text is not normative.

## 6. Conformance

Run every case in `../../conformance/corpus-manifest.json`:

```
<verifier> verify <bundle> --keys <keyring> --format json
```

For each case assert, in order: the process exit code; that stdout validates
against `verify-result.schema.json`; that `failure` matches; and that every key
listed in `checks_present` is present and every key in `checks_absent` is
**absent**.

An implementation that reproduces all cases is **conformant at spec v1.0**.
Because expectations are declarative data and the boundary is subprocess + JSON,
this is checkable mechanically and in any language.

> ### ⚠️ The corpus keyrings are NOT trust material
>
> Every keyring in the corpus carries `"_test_only": true`. Its signing key is
> derived from a **fixed, published seed** so the vectors are byte-reproducible
> by anyone — which necessarily means **anyone can mint bundles that verify
> against it**.
>
> - **MUST NOT** load a keyring marked `_test_only` into a production trust store.
> - The corpus ships **public keys only**; no private key material is in the wheel.
> - A verifier has **no ambient trust store**: it trusts exactly the keyring the
>   caller passes on each invocation, so the corpus cannot silently widen trust.
>
> Treat these files the way you would treat a well-known test vector: useful for
> proving your implementation agrees, never evidence that anything is authentic.

## 7. Threat model — why the ordering is published

Publishing the check order and short-circuit behaviour is a deliberate decision,
not an oversight.

Disclosing that checks stop at the first failure reveals only **which check
reported**, never a way around one. Every check is an independent cryptographic
invariant: to pass step 2 an attacker must produce a preimage colliding with the
committed leaf hash; to pass step 3, an RFC 6962 path colliding with the root; to
pass step 4, an ed25519 forgery under a trusted key. Knowing the order does not
weaken any of them, and skipped checks are skipped precisely *because* an earlier
invariant already failed closed — the bundle is rejected either way.

The alternative — an unspecified order — would mean two conformant verifiers
could classify the same bundle differently, which is precisely the interop
failure this spec exists to prevent. **Determinism is the security property
here.** A verifier is an oracle only for what it already returns publicly: a
single typed reason.

What is deliberately **not** published: how GraQle scores, ranks, weights, or
reasons about anything. None of it is required to verify a proof.

## 8. Stability

Frozen at v1.0:

- the `failure` enum is **closed** — adding a member is a spec version change;
- check-ordering and short-circuit semantics;
- absent-vs-false semantics;
- the exit-code contract;
- the four-field signature preimage.

Additive, non-breaking changes ship as `v1.1`. Anything that changes how an
existing valid bundle classifies is `v2.0`.

### 8.1 Extension posture (read this before extending)

The bundle envelope permits unknown top-level members, and the `record` is
intentionally open: a governed-trace record carries domain fields this spec does
not enumerate, and only a frozen allowlist of them feeds the leaf hash.

The consequence is deliberate but easy to misread:

> **Validating against this schema does NOT validate an extension.** An
> extension namespace (for example a future compliance-claims extension) will
> pass v1.0 validation without being checked, because v1.0 does not know it
> exists.

So an extension MUST publish **its own** schema and be validated against it in
addition to this one. Do not treat a green v1.0 validation as assurance about
fields v1.0 never defined. Conversely, extension fields are safe here precisely
because they cannot alter the leaf hash or the signed preimage — they are
carried, not trusted.

### 8.2 Note for future cryptographic-chain work

`proof_format_version` is inside both the signed preimage and the leaf hash.
Any future change that canonicalizes, normalizes, or unifies its value is a
**signature-breaking change**: it invalidates every previously-issued bundle
signed under the old value. It therefore requires an explicit migration path
(dual-accept window or re-issuance), never an in-place rewrite.
