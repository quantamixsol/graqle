"""External anchor backends for Layer 5 tamper-evidence (R25-EU01).

An anchor submits a Merkle batch root to an external append-only transparency
log and returns a receipt proving the root was logged. Phase 1 ships the
Sigstore Rekor anchor (:mod:`graqle.governance.tamper_evidence.anchors
.sigstore_rekor`); PCT-compatible logs follow in Phase 2.
"""
