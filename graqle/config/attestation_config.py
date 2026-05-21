"""Layer 5 cryptographic tamper-evidence configuration surface.

R25-EU01 / ADR-RT-003. This module defines the typed configuration hierarchy
for GraQle's Layer 5 (cryptographic tamper-evidence) stack: RFC 6962 Merkle
commitments over RFC 8785-canonicalised governed-trace records, anchored to
Sigstore Rekor.

Optional in ``graqle.yaml`` under an ``attestation:`` block. Omitting the block
preserves all defaults (Layer 5 disabled), producing behaviour byte-identical
to v0.58.1.

Every model uses ``ConfigDict(extra="forbid")`` so a typo'd configuration key
fails loudly at load time rather than silently disabling a security control.

Secret-class fields (``webhook_alert_url`` and, in sibling modules, the
operator-override token and ed25519 signing-key path) are accepted via
environment variable ONLY — never from ``graqle.yaml`` — and are redacted by
the existing ``graqle.core.redaction`` machinery on any output candidate.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RekorConfig(BaseModel):
    """Sigstore Rekor anchor configuration (R25-EU01 Task 1.4)."""

    model_config = ConfigDict(extra="forbid")

    url: str = "https://rekor.sigstore.dev"
    public_key_path: str = ".graqle/rekor.pub"
    retry_max_attempts: int = Field(3, ge=1, le=10)


class ReplayQueueConfig(BaseModel):
    """Durable local replay-queue fallback configuration (CONDITION-3).

    The replay queue is the chosen Rekor-availability fallback: when Rekor is
    unreachable, batch roots are queued here with cryptographic integrity
    verification and replayed on recovery. See ADR-RT-003 / PLAN brief §3.1
    for the 5-state overflow protocol.
    """

    model_config = ConfigDict(extra="forbid")

    directory: str = ".graqle/replay_queue/"
    max_entries: int = Field(10000, ge=100, le=1_000_000)
    integrity_check: bool = True
    max_retries: int = Field(3, ge=0, le=10)
    retry_backoff_seconds: list[int] = Field(default_factory=lambda: [5, 30, 300])
    on_queue_full: Literal["pause_writes", "reject"] = "pause_writes"


class CryptoConfig(BaseModel):
    """Cryptographic version + cache configuration.

    ``leaf_input_version`` and ``wrapper_format_version`` are the two
    proof-format axes from R25-EU08 (leaf-hash-input schema vs wrapper schema).
    """

    model_config = ConfigDict(extra="forbid")

    leaf_input_version: str = "1.0.0"
    wrapper_format_version: str = "1.0.0"
    key_state_cache_ttl_seconds: int = Field(3600, ge=0, le=86400)


class SecurityConfig(BaseModel):
    """Security posture for the attestation layer.

    ``fail_open_on_anchor_error`` defaults to ``False`` (fail-closed) and must
    never be silently flipped on: when Rekor anchoring fails, the system surfaces
    the error rather than silently skipping the tamper-evidence commitment.
    """

    model_config = ConfigDict(extra="forbid")

    fail_open_on_anchor_error: bool = False
    operator_override_enabled: bool = True
    webhook_alert_url: str | None = None

    @field_validator("webhook_alert_url", mode="before")
    @classmethod
    def _reject_secret_from_yaml(cls, value: object, info) -> object:
        """Secret-class field — env-var-only.

        ``webhook_alert_url`` may carry a token in the URL, so it must be
        supplied via the ``GRAQLE_ATTESTATION_WEBHOOK_URL`` environment variable,
        never from ``graqle.yaml``. When the validation context marks the source
        as ``"yaml"``, a value here is rejected with a clear remediation message.
        Absent a context (the env-var load path), the value is accepted.
        """
        if value is None:
            return value
        context = getattr(info, "context", None) or {}
        if context.get("source") == "yaml":
            raise ValueError(
                "webhook_alert_url is a secret-class field and must not be set in "
                "graqle.yaml. Provide it via the GRAQLE_ATTESTATION_WEBHOOK_URL "
                "environment variable instead."
            )
        return value


class AttestationConfig(BaseModel):
    """Top-level Layer 5 attestation configuration.

    Composes the Rekor anchor, replay-queue fallback, crypto-version, and
    security sub-configs. ``enabled`` defaults to ``False`` — Layer 5 is opt-in
    in v0.59.0; a deployment flips it on its own timeline.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    anchor: Literal["sigstore_rekor"] = "sigstore_rekor"
    fallback_anchor: Literal["local_replay_queue"] | None = "local_replay_queue"
    batch_max_seconds: int = Field(5, ge=1, le=300)
    batch_max_records: int = Field(1000, ge=1, le=100_000)
    commit_deadline_seconds: int = Field(60, ge=5, le=3600)
    rekor: RekorConfig = Field(default_factory=RekorConfig)
    replay_queue: ReplayQueueConfig = Field(default_factory=ReplayQueueConfig)
    crypto: CryptoConfig = Field(default_factory=CryptoConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)


class LayerSwitchConfig(BaseModel):
    """Layer-switch configuration (ADR-RT-003 §2.2).

    Each of the five layers L1..L5 exposes an independent ``enabled`` flag. In
    production, layers are monotonic-on once a governed record is written under
    them (enforced in graqle.governance.layer_status, not here); this model only
    declares the configured intent at load time.
    """

    model_config = ConfigDict(extra="forbid")

    environment: Literal["production", "development"] = "production"
    l1_kg_substrate: bool = True
    l2_reasoning_loop: bool = True
    l3_governed_trace: bool = True
    l4_pct_integration: bool = True
    l5_cryptographic_tamper_evidence: bool = False
