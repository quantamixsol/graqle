"""Tests for the Layer 5 attestation config hierarchy (v0.59.0 PR-0)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from graqle.config.attestation_config import (
    AttestationConfig,
    CryptoConfig,
    LayerSwitchConfig,
    RekorConfig,
    ReplayQueueConfig,
    SecurityConfig,
)
from graqle.config.settings import GraqleConfig


def test_defaults_layer5_off_and_failclosed():
    """Omitting any config preserves defaults: L5 off, fail-closed."""
    cfg = AttestationConfig()
    assert cfg.enabled is False
    assert cfg.security.fail_open_on_anchor_error is False
    assert cfg.anchor == "sigstore_rekor"
    assert cfg.fallback_anchor == "local_replay_queue"


def test_fail_open_defaults_false():
    """fail_open_on_anchor_error must default False (never silently fail-open)."""
    assert SecurityConfig().fail_open_on_anchor_error is False


@pytest.mark.parametrize(
    "model",
    [
        RekorConfig,
        ReplayQueueConfig,
        CryptoConfig,
        SecurityConfig,
        AttestationConfig,
        LayerSwitchConfig,
    ],
)
def test_rejects_unknown_keys(model):
    """extra='forbid' is load-bearing: a typo'd key fails loudly."""
    with pytest.raises(ValidationError):
        model(this_is_a_typo=True)


def test_validates_ranges():
    """Field range constraints reject out-of-bounds values."""
    with pytest.raises(ValidationError):
        AttestationConfig(commit_deadline_seconds=1)  # below ge=5
    with pytest.raises(ValidationError):
        AttestationConfig(batch_max_records=0)  # below ge=1
    with pytest.raises(ValidationError):
        RekorConfig(retry_max_attempts=99)  # above le=10
    with pytest.raises(ValidationError):
        ReplayQueueConfig(max_entries=1)  # below ge=100


def test_secret_rejected_in_yaml():
    """webhook_alert_url is secret-class: rejected when sourced from yaml."""
    with pytest.raises(ValidationError):
        SecurityConfig.model_validate(
            {"webhook_alert_url": "https://hooks.example/T0K3N"},
            context={"source": "yaml"},
        )


def test_secret_accepted_from_env_path():
    """Same field is accepted when no yaml-source context is present (env path)."""
    cfg = SecurityConfig.model_validate(
        {"webhook_alert_url": "https://hooks.example/T0K3N"}
    )
    assert cfg.webhook_alert_url == "https://hooks.example/T0K3N"


def test_replay_queue_overflow_default():
    """on_queue_full defaults to pause_writes (no silent drop)."""
    assert ReplayQueueConfig().on_queue_full == "pause_writes"


def test_layer_switch_l5_off_by_default():
    """L5 starts disabled; L1-L4 enabled."""
    ls = LayerSwitchConfig()
    assert ls.l5_cryptographic_tamper_evidence is False
    assert ls.l1_kg_substrate is True
    assert ls.environment == "production"


def test_composed_into_graqle_config_default():
    """GraqleConfig exposes an attestation block defaulting to L5-off."""
    cfg = GraqleConfig()
    assert cfg.attestation.enabled is False
    assert cfg.attestation.security.fail_open_on_anchor_error is False


def test_backward_compat_no_attestation_block():
    """A config dict with no 'attestation' key still validates (additive)."""
    cfg = GraqleConfig.model_validate({})
    assert cfg.attestation.enabled is False


def test_from_yaml_rejects_secret_in_yaml(tmp_path):
    """End-to-end: a webhook_alert_url literal set in graqle.yaml is rejected.

    Rejection happens at the pre-interpolation ``_reject_yaml_secrets`` guard
    (raises ValueError) — defense-in-depth ahead of the per-field validator.
    Accepts either ValueError (guard) or ValidationError (field validator),
    since ValidationError is not a ValueError subclass in pydantic v2."""
    yaml_path = tmp_path / "graqle.yaml"
    yaml_path.write_text(
        "attestation:\n"
        "  security:\n"
        "    webhook_alert_url: https://hooks.example/T0K3N\n",
        encoding="utf-8",
    )
    with pytest.raises((ValueError, ValidationError)):
        GraqleConfig.from_yaml(yaml_path)


def test_from_yaml_allows_non_secret_attestation(tmp_path):
    """from_yaml accepts a non-secret attestation block (e.g. enabling L5)."""
    yaml_path = tmp_path / "graqle.yaml"
    yaml_path.write_text(
        "attestation:\n  enabled: true\n",
        encoding="utf-8",
    )
    cfg = GraqleConfig.from_yaml(yaml_path)
    assert cfg.attestation.enabled is True


def test_from_yaml_rejects_secret_env_reference(tmp_path, monkeypatch):
    """Closes the interpolation-bypass class (security sentinel BLOCKER): a
    ${ENV_REF} for a secret-class field in yaml is rejected BEFORE interpolation,
    so the env-ref cannot obscure that the field was supplied via yaml."""
    monkeypatch.setenv("SOME_WEBHOOK", "https://hooks.example/T0K3N")
    yaml_path = tmp_path / "graqle.yaml"
    yaml_path.write_text(
        "attestation:\n"
        "  security:\n"
        "    webhook_alert_url: ${SOME_WEBHOOK}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        GraqleConfig.from_yaml(yaml_path)
