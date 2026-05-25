"""Runtime governance layer — attach GraQle to a deployed AI system (ADR-221, R0).

The *author-time* surface governs how AI code is written. This *run-time* surface
governs what a deployed AI **decides**: each production decision (a loan score, a
hiring screen, a triage call) is captured as a governed, tamper-evidence-ready
record on the same Layer 5 substrate (frozen leaf-hash-input schema → RFC 6962
Merkle → ed25519 → Sigstore Rekor).

R0 ships **Mode A — the explicit attest() call** (ADR-221 §4.1). One added line at
the point of inference durably records a PII-safe governed trace and returns
immediately (0 ms on the write path):

    from graqle.governance.runtime import GovernedRuntime

    gov = GovernedRuntime()                      # default durable JSONL sink

    def score_application(app):
        decision = model.predict(app)            # the deployed AI, untouched
        gov.attest(                              # <-- the one added line
            domain="loan",
            model_id="credit-risk-v4",
            inputs={"applicant_ref": app.pseudonym, "features_hash": hash_features(app)},
            output={"decision": decision.label, "reason_code": decision.reason},
        )
        return decision

``attest()`` builds the GovernedTrace leaf record, computes its Merkle leaf hash with
the **shipped** ``leaf_hash_for_record`` (so a runtime record is byte-for-byte
compatible with what the Layer 5 batcher/committer commit), and writes it to a
pluggable :class:`AttestationSink`. The default sink is a durable, fsync'd,
append-only JSONL store; the R2 anchoring worker plugs into the same interface to
batch → Merkle-commit → Rekor-anchor out of band.
"""

from __future__ import annotations

from typing import Any

from graqle.governance.runtime.fastapi import governed
from graqle.governance.runtime.mapping import (
    DomainMapping,
    MappingError,
    load_mapping,
)
from graqle.governance.runtime.runtime import (
    AttestationSink,
    DurableJsonlSink,
    GovernedRuntime,
    InMemorySink,
    RuntimeDecision,
    pseudonymize,
)

__all__ = [
    # R0 — Mode A
    "GovernedRuntime",
    "RuntimeDecision",
    "AttestationSink",
    "DurableJsonlSink",
    "InMemorySink",
    "pseudonymize",
    # R1 — Mode B
    "governed",
    "GraqleGovernanceMiddleware",  # noqa: F822 - exposed lazily via module __getattr__ (PEP 562)
    "DomainMapping",
    "load_mapping",
    "MappingError",
]


def __getattr__(name: str) -> Any:
    """Lazily re-export GraqleGovernanceMiddleware (PEP 562) — defers Starlette import."""
    if name == "GraqleGovernanceMiddleware":
        from graqle.governance.runtime.fastapi import GraqleGovernanceMiddleware

        return GraqleGovernanceMiddleware
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
