"""R2 hosted anchoring worker core (BizQ S2, Studio backend).

Turns a batch of governed records into publicly-anchored, ed25519-signed,
independently-verifiable proof bundles. This is the core the SQS-triggered batch
Lambda calls; it is a pure function of (records, signer, anchor, clock) with no
AWS coupling, so it is fully testable without the cloud.

Pipeline (charter Phase 3, grounded in the shipped Layer-5 primitives):

    records
      -> MerkleTree.from_records            # one batch -> one root
      -> RekorAnchor.anchor(root)           # public Sigstore Rekor (real)
      -> RootSigner.sign_root(root)         # SD-001 ed25519 signature block
      -> per leaf: InclusionProof.to_bundle # assemble verify_bundle-shaped dict
      -> meter_observer(leaf_hash, ctx)     # one billable proof_anchored / leaf

Each emitted bundle is exactly the schema ``verify_bundle`` accepts (record +
leaf + merkle + signature [+ rekor]), so a bundle this worker produces verifies
in the separate verifier-at-scale Lambda — the loop is closed and tested.

Fail-closed: if anchoring fails and the config is fail-closed (the default,
``SecurityConfig.fail_open_on_anchor_error=False``), the batch is NOT emitted —
no proof bundle is written and no meter event fires (a proof that was not
anchored is not a hosted proof and must not be billed). The caller surfaces the
failure (e.g. leaves the SQS messages for redrive to the DLQ).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from graqle.governance.tamper_evidence.anchors.sigstore_rekor import (
    AnchorError,
    RekorAnchor,
)
from graqle.governance.tamper_evidence.merkle import MerkleTree

from studio_backend.anchoring.signer import EcdsaRekorSigner, RootSigner

logger = logging.getLogger("studio_backend.anchoring.worker")

PROOF_FORMAT_VERSION = "1"

# meter_observer(leaf_hash, context) -> None  (never-raise; from make_meter_observer)
MeterObserver = Callable[[str, dict[str, Any]], None]


class AnchorWorkerError(Exception):
    """Raised when a batch cannot be anchored under a fail-closed policy."""


@dataclass(frozen=True)
class AnchoredBatch:
    """The result of anchoring one batch: the bundles + batch-level metadata."""

    batch_id: str
    merkle_root: str
    rekor_log_index: int | None
    bundles: list[dict[str, Any]] = field(default_factory=list)


def _utc_now_iso(clock: Callable[[], datetime] | None) -> str:
    """RFC 3339 UTC timestamp; ``clock`` injectable for deterministic tests."""
    now = clock() if clock is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).isoformat()


def anchor_records(
    records: list[dict[str, Any]],
    *,
    signer: RootSigner,
    rekor_signer: EcdsaRekorSigner,
    anchor: RekorAnchor,
    batch_id: str,
    meter_observer: MeterObserver | None = None,
    fail_open_on_anchor_error: bool = False,
    edition: str = "studio",
    clock: Callable[[], datetime] | None = None,
) -> AnchoredBatch:
    """Anchor a batch of records and return signed, verifiable proof bundles.

    Parameters
    ----------
    records:
        The governed-trace records to anchor (each MUST carry
        ``proof_format_version`` — enforced by ``leaf_hash_for_record``/``canon``).
    signer:
        The ed25519 :class:`RootSigner` (its public key is in the trust source).
    anchor:
        A :class:`RekorAnchor` (real Sigstore in prod; a fake transport in tests).
    batch_id:
        Caller-supplied unique id for this batch (used in S3 keys + audit ctx).
    meter_observer:
        Optional never-raise callback fired once per anchored leaf with
        ``(leaf_hash, context)`` — the billable ``proof_anchored`` count point.
        Pass ``make_meter_observer(...)``; omit to anchor without metering.
    fail_open_on_anchor_error:
        If False (default, fail-closed), an anchor failure raises
        :class:`AnchorWorkerError` and NO bundle/meter is produced. If True, the
        batch is committed locally without a Rekor block (not recommended).
    edition:
        Stamped into the meter context. Defaults to ``"studio"``.

    Returns
    -------
    AnchoredBatch
        ``bundles`` are ready to persist to S3 and to feed to ``verify_bundle``.
    """
    if not isinstance(records, list) or not records:
        raise AnchorWorkerError("anchor_records requires a non-empty list of records")

    tree = MerkleTree.from_records(records)
    root_hex = tree.root_hex
    root_bytes = bytes.fromhex(root_hex)
    signed_at = _utc_now_iso(clock)

    # 1. Sign the root ONCE (the signature commits to the root, which commits to
    #    every leaf — RFC 6962 — so one signature covers the whole batch). We
    #    produce TWO signatures from the same key:
    #      * the SD-001 bundle signature (over canon{...}) — what verify_bundle checks;
    #      * a raw signature over the root bytes — what Rekor's hashedrekord records.
    signature_block = signer.sign_root(
        proof_format_version=PROOF_FORMAT_VERSION,
        merkle_root_hex=root_hex,
        signed_at=signed_at,
    )
    # Rekor's hashedrekord needs an ECDSA signature over the root's SHA-256
    # digest (raw ed25519 is unsupported there). The dedicated ECDSA anchoring
    # key signs for Rekor; the bundle's own signature stays ed25519 (above).
    root_signature, public_key_pem = rekor_signer.sign_root_for_rekor(root_bytes)

    # 2. Anchor the signed root to Rekor (fail-closed by default). The real Rekor
    #    hashedrekord records the (root-hash, signature, public-key) triple.
    rekor_block: dict[str, Any] | None = None
    rekor_log_index: int | None = None
    try:
        receipt = anchor.anchor(root_bytes, root_signature, public_key_pem)
        rekor_block = _receipt_to_bundle_block(receipt, root_hex)
        rekor_log_index = getattr(receipt, "log_index", None)
    except AnchorError as exc:
        if not fail_open_on_anchor_error:
            # A proof that is not anchored is not a hosted proof — do NOT emit or
            # bill it. Surface the failure so the caller can redrive (DLQ).
            raise AnchorWorkerError(
                f"batch {batch_id} anchor failed (fail-closed): {exc}"
            ) from exc
        logger.warning(
            "batch %s anchor failed but fail_open is set — committing without Rekor block",
            batch_id,
        )

    # 3. Assemble one verify_bundle-shaped proof bundle per leaf, and fire the
    #    meter once per anchored leaf.
    bundles: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        proof = tree.inclusion_proof(index)
        leaf_hash_hex = proof.leaf_hash.hex()
        merkle = proof.to_bundle()  # leaf_index, tree_size, merkle_path[, directions]
        bundle: dict[str, Any] = {
            "proof_format_version": PROOF_FORMAT_VERSION,
            "record": record,
            "leaf": {
                "leaf_index": merkle["leaf_index"],
                "tree_size": merkle["tree_size"],
                "leaf_hash": leaf_hash_hex,
            },
            "merkle": {
                "merkle_root": root_hex,
                "merkle_path": merkle["merkle_path"],
                "merkle_path_directions": merkle["merkle_path_directions"],
            },
            "signature": signature_block,
        }
        if rekor_block is not None:
            bundle["rekor"] = rekor_block
        bundles.append(bundle)

        # Count point: one anchored leaf == one billable proof_anchored event.
        # Only fire when the batch is actually anchored (rekor present) — a
        # fail-open unanchored batch is not billed.
        if meter_observer is not None and rekor_block is not None:
            context = {
                "batch_id": batch_id,
                "edition": edition,
                "merkle_root": root_hex,
            }
            if rekor_log_index is not None:
                context["rekor_log_index"] = rekor_log_index
            # Per-record billing attribution: each leaf carries ITS OWN record's
            # tenant_id (a batch may mix tenants), threaded from the ingress
            # (SqsAttestationSink) so StudioMeter bills the right tenant.
            tenant_id = record.get("tenant_id") if isinstance(record, dict) else None
            if isinstance(tenant_id, str) and tenant_id:
                context["tenant_id"] = tenant_id
            meter_observer(leaf_hash_hex, context)

    return AnchoredBatch(
        batch_id=batch_id,
        merkle_root=root_hex,
        rekor_log_index=rekor_log_index,
        bundles=bundles,
    )


def _receipt_to_bundle_block(receipt: Any, root_hex: str) -> dict[str, Any]:
    """Project a RekorReceipt onto the bundle's optional ``rekor`` block (data only).

    The block is pure data (never re-fetched). Two distinct fields carry the two
    distinct things:

    * ``signed_tree_head`` = the anchored **root hex** — this is the GraQle bundle
      convention the offline verifier checks (``_verify_rekor_offline`` requires
      ``signed_tree_head`` to reference the exact ``merkle_root`` the inclusion
      proof verified into; ``_extract_anchored_root_hex`` returns it as-is). It is
      the internal-consistency binding "this receipt is about THIS root".
    * ``rekor_sth_raw`` = Rekor's *actual* signed tree head (Rekor's signed
      commitment to its log state) — preserved verbatim for an external auditor /
      ``rekor-cli`` to validate against Sigstore key material (out of scope for the
      offline SDK verifier, which holds no Rekor key material).

    Missing receipt attributes degrade to None rather than raising.
    """
    return {
        "log_index": getattr(receipt, "log_index", None),
        "log_id": getattr(receipt, "log_id", None),
        # Offline-binding value the verifier checks (root hex, GraQle convention).
        "signed_tree_head": root_hex,
        "inclusion_cert": getattr(receipt, "inclusion_cert", None),
        "integrated_time": getattr(receipt, "integrated_time", None),
        # Rekor's real signed tree head, preserved for external rekor-cli validation.
        "rekor_sth_raw": getattr(receipt, "signed_tree_head", None),
    }


__all__ = [
    "AnchorWorkerError",
    "AnchoredBatch",
    "anchor_records",
    "PROOF_FORMAT_VERSION",
]
