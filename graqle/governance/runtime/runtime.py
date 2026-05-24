"""Mode A explicit-attest runtime capture (ADR-221 §4.1 / R0).

A deployed AI system calls :meth:`GovernedRuntime.attest` once per governed
decision. This module turns that call into a durable, PII-safe, tamper-evidence-
ready GovernedTrace record using the **shipped** Layer 5 primitives — it adds no
new cryptography, it composes the existing ones.

Design rules (R0):

* **Composition, not modification.** Nothing in ``tamper_evidence`` or
  ``layer_status`` is touched; this package reuses ``leaf_hash_for_record`` (which
  itself projects to the frozen leaf allowlist + RFC 8785-canonicalizes) and
  ``canon`` so a runtime record's leaf hash is identical to what the Layer 5
  batcher/committer would compute for the same fields.
* **0 ms on the write path is the contract.** ``attest`` does a bounded amount of
  local work (hash + one append) and returns; it never blocks on Rekor. The
  pluggable :class:`AttestationSink` is where the R2 anchoring worker attaches to
  batch → Merkle-commit → anchor out of band.
* **PII never enters the record.** Callers pass already-hashed / pseudonymised
  inputs; ``attest`` additionally folds the inputs+output into a single
  ``content_hash`` and stores only that on the leaf. Raw personal data is the
  caller's to keep out — :func:`pseudonymize` is provided for the common case.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from graqle.governance.tamper_evidence.canonicalize import canon
from graqle.governance.tamper_evidence.merkle import leaf_hash_for_record

__all__ = [
    "GovernedRuntime",
    "RuntimeDecision",
    "AttestationSink",
    "DurableJsonlSink",
    "InMemorySink",
    "pseudonymize",
]

# Default home for the durable runtime-attestation store. Sibling of the §8.3
# layer-transition sidecar; a SEPARATE physical store so runtime decision records
# and internal layer-status events never intermingle.
_DEFAULT_ATTEST_DIR = Path.home() / ".graqle" / "runtime_attestations"

# Proof-format version carried inside the leaf (R25-EU08: version-in-leaf defeats
# replay across format versions). Matches the Layer 5 default.
PROOF_FORMAT_VERSION = "1.0.0"

# Defence-in-depth bound on a single attested record's serialized size. Records are
# JSON-encoded (so control characters are escaped — a value cannot forge a new log
# line), but an unbounded caller-supplied governance_metadata/output could bloat the
# store; cap the serialized record and reject oversized ones loudly. Generous enough
# for any legitimate governed decision; full per-field redaction is the R1 mapping
# config's job (ADR-221 §4.3).
MAX_RECORD_BYTES = 64 * 1024


def _utc_now_iso() -> str:
    """Current UTC time as ISO-8601 with a trailing ``Z`` (matches audit_log_v3)."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def pseudonymize(value: str, *, salt: str = "") -> str:
    """Return a stable, non-reversible pseudonym for an identifier.

    SHA-256 over ``salt + value`` → hex. Same input + salt always yields the same
    pseudonym (so a subject can be correlated across decisions for audit) but the
    raw identifier cannot be recovered. Use this for applicant ids, candidate ids,
    patient ids, etc. before they ever reach :meth:`GovernedRuntime.attest`.

    A per-deployment ``salt`` (kept out of the record) defends against rainbow-table
    recovery of low-entropy ids.
    """
    digest = hashlib.sha256((salt + value).encode("utf-8")).hexdigest()
    return f"anon-{digest[:24]}"


@dataclass(frozen=True)
class RuntimeDecision:
    """One governed decision captured from a deployed AI system (ADR-221 §4.2).

    Attributes
    ----------
    domain:
        Decision domain (``"loan"`` | ``"recruitment"`` | ``"health"`` | …).
    model_id:
        Identifier of the deciding model/version (links to the model node in the
        KG in later phases).
    decision_id:
        Stable id for this decision (the leaf ``record_id``). Auto-generated if not
        supplied.
    timestamp_unix:
        Decision time (epoch seconds, UTC). Defaults to now.
    inputs:
        PII-safe input digest — hashes/pseudonyms only. Folded into ``content_hash``;
        never stored raw on the leaf.
    output:
        The governed decision + reason. Folded into ``content_hash``.
    governance_metadata:
        The leaf-visible governance fields (decision, reason_code, confidence,
        human_review, model_id, domain). This is the one map that enters the Merkle
        leaf, so it must be PII-free by construction.
    policy_id:
        Optional active-policy identifier, recorded in the wrapper.
    """

    domain: str
    model_id: str
    governance_metadata: dict[str, Any]
    inputs: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    decision_id: str = ""
    timestamp_unix: int = 0
    policy_id: str | None = None


@runtime_checkable
class AttestationSink(Protocol):
    """Where an attested record is durably recorded.

    R0 ships a durable JSONL sink (default) and an in-memory sink (tests). The R2
    anchoring worker implements this same one-method interface to batch →
    Merkle-commit → Rekor-anchor, so swapping the sink is the only change needed to
    move from "durable local trail" to "publicly anchored".
    """

    def write(self, record: dict[str, Any]) -> None:
        """Durably record one attested governed-trace record. MUST raise on failure."""
        ...


class DurableJsonlSink:
    """Append-only, fsync'd JSONL sink (mirrors the §8.3 transition sidecar).

    One file per UTC day under ``directory``. Each ``write`` is an
    ``O_APPEND`` + ``fsync`` so a crash cannot lose an acknowledged record — the
    same durability discipline the Layer 5 WAL and layer-status sidecar use.
    """

    def __init__(self, directory: str | Path | None = None) -> None:
        self._dir = Path(directory) if directory is not None else _DEFAULT_ATTEST_DIR

    def write(self, record: dict[str, Any]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        file_path = self._dir / f"{today}.jsonl"
        line = json.dumps(record, default=str, sort_keys=True) + "\n"
        # mode 0o600 — owner-only. Governed-decision records are audit material; the
        # store must not be world-readable (the OS umask further restricts, never
        # widens). No-op on Windows (POSIX perms ignored) but correct on Linux/CI.
        fd = os.open(str(file_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)


class InMemorySink:
    """Non-durable sink that keeps records in a list. For tests/embedding only."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def write(self, record: dict[str, Any]) -> None:
        self.records.append(record)


class GovernedRuntime:
    """The Mode A runtime-capture entry point (ADR-221 §4.1).

    Construct once at process start, then call :meth:`attest` once per governed
    decision. Thread-safe to share: it holds no mutable state beyond the (itself
    append-only) sink.

    Parameters
    ----------
    sink:
        Where attested records are recorded. Defaults to a :class:`DurableJsonlSink`
        under ``~/.graqle/runtime_attestations``.
    salt:
        Optional pseudonymisation salt applied by :meth:`attest` if a caller asks
        for an identifier to be pseudonymised (see ``pseudonymize_ref``).
    """

    def __init__(self, sink: AttestationSink | None = None, *, salt: str = "") -> None:
        self._sink: AttestationSink = sink if sink is not None else DurableJsonlSink()
        self._salt = salt

    def attest(
        self,
        domain: str,
        model_id: str,
        output: dict[str, Any],
        inputs: dict[str, Any] | None = None,
        *,
        decision_id: str | None = None,
        timestamp_unix: int | None = None,
        policy_id: str | None = None,
        confidence: float | None = None,
        human_review: str | None = None,
        reason_code: str | None = None,
    ) -> dict[str, Any]:
        """Capture one governed decision and durably record it. Returns the record.

        Builds a GovernedTrace leaf record whose leaf fields are exactly the frozen
        ``LEAF_HASH_FIELDS`` (``proof_format_version``, ``record_id``,
        ``content_hash``, ``timestamp_unix``, ``governance_metadata``), computes the
        Merkle leaf hash with the shipped :func:`leaf_hash_for_record`, attaches the
        wrapper fields (domain, model_id, policy_id, created_at_iso, leaf_hash_hex),
        and writes the whole record to the sink.

        ``inputs`` + ``output`` are folded into a single ``content_hash`` (SHA-256 of
        their RFC 8785 canonical bytes) and are NOT stored raw on the leaf — the leaf
        carries only the hash and the PII-free ``governance_metadata``. Pass already
        hashed/pseudonymised values in ``inputs`` (see :func:`pseudonymize`).

        Parameters mirror :class:`RuntimeDecision`; ``confidence`` / ``human_review`` /
        ``reason_code`` are convenience promotions into ``governance_metadata``.

        Returns the attested record dict (also handed to the sink) so callers can log
        or assert on it.

        Raises
        ------
        ValueError
            If ``domain`` or ``model_id`` is empty / not a non-empty string (both
            are leaf-visible governance fields, so an anonymous attestation would
            produce an unattributable audit record), or if ``output`` is not a dict
            / ``inputs`` is neither a dict nor ``None``.
        """
        if not isinstance(domain, str) or not domain:
            raise ValueError("domain must be a non-empty string")
        if not isinstance(model_id, str) or not model_id:
            raise ValueError("model_id must be a non-empty string")
        if not isinstance(output, dict):
            raise ValueError("output must be a dict (the governed decision + reason)")
        if inputs is not None and not isinstance(inputs, dict):
            raise ValueError("inputs must be a dict of PII-safe digests, or None")
        rec_id = decision_id if decision_id else uuid.uuid4().hex
        ts = timestamp_unix if timestamp_unix is not None else int(
            datetime.now(timezone.utc).timestamp()
        )

        # PII-safe content hash over canonical inputs+output. canon() rejects
        # NaN/Inf/non-JSON-native values, so a non-canonical payload fails loudly
        # rather than producing a non-deterministic hash.
        payload = {"inputs": dict(inputs or {}), "output": dict(output)}
        content_hash = "sha256:" + hashlib.sha256(canon(payload)).hexdigest()

        # Leaf-visible governance metadata. PII-free by construction: only the
        # decision + its governance attributes, never the raw inputs.
        governance_metadata: dict[str, Any] = {
            "domain": domain,
            "model_id": model_id,
            "decision": output.get("decision"),
        }
        if reason_code is not None:
            governance_metadata["reason_code"] = reason_code
        elif "reason_code" in output:
            governance_metadata["reason_code"] = output["reason_code"]
        if confidence is not None:
            governance_metadata["confidence"] = confidence
        if human_review is not None:
            governance_metadata["human_review"] = human_review

        leaf_record = {
            "proof_format_version": PROOF_FORMAT_VERSION,
            "record_id": rec_id,
            "content_hash": content_hash,
            "timestamp_unix": ts,
            "governance_metadata": governance_metadata,
        }
        leaf_hash_hex = leaf_hash_for_record(leaf_record).hex()

        # The full attested record = leaf fields + wrapper fields. Wrapper fields
        # never enter the leaf hash (proven by canon_leaf projecting them out), so
        # they can be added freely for operational/audit context.
        record: dict[str, Any] = {
            **leaf_record,
            "domain": domain,
            "model_id": model_id,
            "policy_id": policy_id,
            "created_at_iso": _utc_now_iso(),
            "leaf_hash_hex": leaf_hash_hex,
            "_runtime_attestation": True,
        }
        # Defence-in-depth: reject an oversized record loudly rather than bloating
        # the durable store. JSON encoding already neutralises control-character /
        # log-forging injection (a newline in a value is escaped to \\n); this bound
        # guards volume. Computed on the canonical serialization the sink will write.
        size = len(json.dumps(record, default=str, sort_keys=True).encode("utf-8"))
        if size > MAX_RECORD_BYTES:
            raise ValueError(
                f"attested record is {size} bytes, exceeding MAX_RECORD_BYTES "
                f"({MAX_RECORD_BYTES}); shrink governance_metadata/output (per-field "
                f"redaction is the R1 mapping config's job)"
            )
        self._sink.write(record)
        return record

    def attest_decision(self, decision: RuntimeDecision) -> dict[str, Any]:
        """Attest a pre-built :class:`RuntimeDecision` (the structured-input form)."""
        return self.attest(
            domain=decision.domain,
            model_id=decision.model_id,
            output=decision.output,
            inputs=decision.inputs,
            decision_id=decision.decision_id or None,
            timestamp_unix=decision.timestamp_unix or None,
            policy_id=decision.policy_id,
            **{
                k: v
                for k, v in decision.governance_metadata.items()
                if k in ("confidence", "human_review", "reason_code")
            },
        )

    def pseudonymize_ref(self, value: str) -> str:
        """Pseudonymise ``value`` with this runtime's configured salt."""
        return pseudonymize(value, salt=self._salt)
