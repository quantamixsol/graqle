"""BizQ S2 hosted anchoring (R2) — proprietary Studio backend.

The hosted anchoring worker that turns customer ``attest()`` records into
publicly-anchored, independently-verifiable proof bundles:

    customer attest() -> SqsAttestationSink.write -> SQS
      -> batch Lambda -> Committer(RekorAnchor) -> Merkle root anchored to
         Sigstore Rekor -> ed25519-signed proof bundles -> S3 proofs/
         -> MeterEvent("proof_anchored") per anchored leaf

This package lives OUTSIDE the importable ``graqle`` package (under
``studio_backend/``) so it never ships in the public Community wheel — it is
proprietary Studio-backend code. It COMPOSES the shipped Layer-5 primitives
(``Committer``, ``MerkleTree``, ``RekorAnchor``, ``make_meter_observer``); it does
not re-implement anchoring.

NOTE: unlike the verifier-at-scale Lambda, the anchoring worker is a *producer*
surface, so it is free to import server-side helpers. It does NOT import the
verifier (``verify_bundle``) — the moat-M2 isolation guard forbids the verifier
from co-residing with any networked surface, and the worker is networked (SQS,
Rekor, S3). Verification of the bundles it produces happens in the SEPARATE
verifier-at-scale Lambda.
"""
