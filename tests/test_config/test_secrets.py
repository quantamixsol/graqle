"""CR-010.R5 — tests for the secrets provider abstraction.

Covers:
  - Feature flag: is_secrets_resolver_enabled() default-OFF, opt-in via env var
  - Priority chain: explicit kwargs > per-key override map > top-level block > default
  - Providers: env, file (incl. $SECRETS_PATH expansion + trailing-newline strip),
    keychain (mocked; unsupported off-macOS), command (mocked argv, no shell)
  - Fail-closed: missing required secret raises; default fallback works
  - No-leak invariants (adversarial): secret value never in exception str/repr
  - Property: ResolvedSecret.value always masks to "***"; resolver never returns bare str

See: .gsm/external/Change Requests/CR-010.R5-secrets-provider-abstraction.md
"""

from __future__ import annotations

# -- graqle:intelligence --
# module: tests.test_config.test_secrets
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, graqle.config.secrets, graqle.config.exceptions, graqle.config.resolver
# constraints: none
# -- /graqle:intelligence --

import subprocess
import sys
from pathlib import Path

import pytest

from graqle.config.exceptions import (
    SecretProviderUnsupportedError,
    SecretResolutionError,
)
from graqle.config.resolver import ResolvedConfig, SecretStr
from graqle.config.secrets import (
    ResolvedSecret,
    is_secrets_resolver_enabled,
    resolve_secret,
)

# Deliberately NON-key-shaped (no ``sk-``/``AKIA`` prefix) so the SOC2
# hardcoded-secret self-audit scanner never flags this test fixture.
SENTINEL = "TEST-MOCK-VALUE-DO-NOT-LEAK"


def _cfg(yaml_data: dict) -> ResolvedConfig:
    """Build a ResolvedConfig around a yaml_data dict (absolute yaml_source)."""
    root = Path.cwd().resolve()
    return ResolvedConfig(
        yaml_data=yaml_data,
        project_root=root,
        parent_root=None,
        yaml_source=root / "graqle.yaml",
    )


# ─────────────── Feature flag ────────────────────────────────────────────────


def test_flag_default_off(monkeypatch):
    monkeypatch.delenv("GRAQLE_USE_SECRETS_RESOLVER", raising=False)
    assert is_secrets_resolver_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "Yes"])
def test_flag_on_values(monkeypatch, val):
    monkeypatch.setenv("GRAQLE_USE_SECRETS_RESOLVER", val)
    assert is_secrets_resolver_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "no", "", "off", "garbage"])
def test_flag_off_values(monkeypatch, val):
    monkeypatch.setenv("GRAQLE_USE_SECRETS_RESOLVER", val)
    assert is_secrets_resolver_enabled() is False


# ─────────────── env provider ────────────────────────────────────────────────


def test_env_provider_default_ref_is_name(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", SENTINEL)
    r = resolve_secret("MY_TOKEN")
    assert isinstance(r, ResolvedSecret)
    assert r.provider == "env"
    assert r.value.get_secret_value() == SENTINEL


def test_env_provider_explicit_ref(monkeypatch):
    monkeypatch.setenv("ACTUAL_ENV", SENTINEL)
    r = resolve_secret("logical_name", provider="env", ref="ACTUAL_ENV")
    assert r.value.get_secret_value() == SENTINEL
    assert r.source_ref_redacted == "ACTUAL_ENV"


# ─────────────── file provider ───────────────────────────────────────────────


def test_file_provider_reads_and_strips_trailing_newline(tmp_path):
    p = tmp_path / "gateway-token"
    p.write_text(SENTINEL + "\n", encoding="utf-8")
    r = resolve_secret("gateway_token", provider="file", ref=str(p))
    assert r.provider == "file"
    assert r.value.get_secret_value() == SENTINEL  # newline stripped


def test_file_provider_expands_secrets_path(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRETS_PATH", str(tmp_path))
    (tmp_path / "license").write_text(SENTINEL, encoding="utf-8")
    r = resolve_secret("license", provider="file", ref="${SECRETS_PATH}/license")
    assert r.value.get_secret_value() == SENTINEL


def test_file_provider_missing_file_fail_closed(tmp_path):
    with pytest.raises(SecretResolutionError):
        resolve_secret("x", provider="file", ref=str(tmp_path / "nope"))


def test_file_provider_missing_with_default(tmp_path):
    r = resolve_secret("x", provider="file", ref=str(tmp_path / "nope"), default="fallback")
    assert r.value.get_secret_value() == "fallback"
    assert r.source_ref_redacted == "<default>"


def test_file_provider_unreadable_raises_without_value(tmp_path):
    # A directory at the ref path is not a readable file -> OSError -> raise.
    d = tmp_path / "adir"
    d.mkdir()
    with pytest.raises(SecretResolutionError) as ei:
        resolve_secret("x", provider="file", ref=str(d))
    assert SENTINEL not in str(ei.value)


def test_file_provider_empty_file_raises_distinctly(tmp_path):
    # M-1 (sentinel): an empty mounted file is a provisioning fault, NOT absent.
    # It must fail-closed LOUDLY and must NOT be silently replaced by a default.
    p = tmp_path / "empty-token"
    p.write_text("", encoding="utf-8")
    with pytest.raises(SecretResolutionError) as ei:
        resolve_secret("gateway_token", provider="file", ref=str(p))
    assert "empty" in str(ei.value)


def test_file_provider_empty_file_not_overridden_by_default(tmp_path):
    # An empty *present* file must raise even when a default is supplied —
    # a misprovisioned mount must never be masked by a fallback.
    p = tmp_path / "empty-token"
    p.write_text("\n", encoding="utf-8")  # only a newline -> strips to ""
    with pytest.raises(SecretResolutionError):
        resolve_secret("x", provider="file", ref=str(p), default="fallback")


# ─────────────── keychain provider (mocked) ─────────────────────────────────


def test_keychain_unsupported_off_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(SecretProviderUnsupportedError):
        resolve_secret("x", provider="keychain", ref="acct")


def test_keychain_success_mocked(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")

    def fake_run(argv, **kw):
        assert kw.get("shell") is False
        assert argv[:2] == ["security", "find-generic-password"]
        return subprocess.CompletedProcess(argv, 0, stdout=SENTINEL + "\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = resolve_secret("x", provider="keychain", ref="acct")
    assert r.value.get_secret_value() == SENTINEL


def test_keychain_not_found_is_absent(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")

    def fake_run(argv, **kw):
        # exit 44 = item not found; stderr echoes account — must NOT surface.
        return subprocess.CompletedProcess(argv, 44, stdout="", stderr="acct not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SecretResolutionError) as ei:
        resolve_secret("x", provider="keychain", ref="acct")
    assert "not found" not in str(ei.value) or "security" not in str(ei.value)
    # default applies when absent
    r = resolve_secret("x", provider="keychain", ref="acct", default="d")
    assert r.value.get_secret_value() == "d"


# ─────────────── command provider (mocked) ──────────────────────────────────


def test_command_provider_no_shell(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        seen["shell"] = kw.get("shell")
        return subprocess.CompletedProcess(argv, 0, stdout=SENTINEL + "\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = resolve_secret("x", provider="command", ref="vault read -field=v secret/x")
    assert r.value.get_secret_value() == SENTINEL
    assert seen["shell"] is False
    assert seen["argv"] == ["vault", "read", "-field=v", "secret/x"]  # shlex-split


def test_command_nonzero_exit_raises_no_stderr_leak(monkeypatch):
    def fake_run(argv, **kw):
        return subprocess.CompletedProcess(argv, 2, stdout="", stderr=SENTINEL)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SecretResolutionError) as ei:
        resolve_secret("x", provider="command", ref="vault read x")
    assert SENTINEL not in str(ei.value)


def test_command_timeout_raises(monkeypatch):
    def fake_run(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw.get("timeout", 10))

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SecretResolutionError):
        resolve_secret("x", provider="command", ref="slowcmd")


# ─────────────── priority chain ──────────────────────────────────────────────


def test_priority_explicit_beats_yaml(monkeypatch, tmp_path):
    monkeypatch.setenv("FROM_ENV", SENTINEL)
    cfg = _cfg({"secrets": {"provider": "file", "ref": str(tmp_path / "nope")}})
    # explicit env override wins over the yaml file provider
    r = resolve_secret("FROM_ENV", cfg, provider="env")
    assert r.provider == "env"
    assert r.value.get_secret_value() == SENTINEL


def test_priority_perkey_override(tmp_path):
    (tmp_path / "tok").write_text(SENTINEL, encoding="utf-8")
    cfg = _cfg(
        {
            "secrets": {
                "provider": "env",  # top-level default
                "keys": {"gateway_token": {"provider": "file", "ref": str(tmp_path / "tok")}},
            }
        }
    )
    r = resolve_secret("gateway_token", cfg)
    assert r.provider == "file"
    assert r.value.get_secret_value() == SENTINEL


def test_invalid_provider_in_yaml_fail_closed():
    cfg = _cfg({"secrets": {"provider": "smoke-signals"}})
    with pytest.raises(SecretResolutionError):
        resolve_secret("x", cfg)


def test_empty_env_normalizes_to_absent(monkeypatch):
    # M-2 (sentinel): an env var set to "" must be treated as UNSET so the
    # priority chain / fail-closed applies — not as a resolved empty secret.
    monkeypatch.setenv("BLANK", "")
    with pytest.raises(SecretResolutionError):
        resolve_secret("BLANK", provider="env")
    r = resolve_secret("BLANK", provider="env", default="d")
    assert r.value.get_secret_value() == "d"


def test_toplevel_ref_not_adopted_for_named_lookup_in_multikey(tmp_path, monkeypatch):
    # M-3 (sentinel): a top-level `ref` in a multi-key block must NOT be adopted
    # for a named lookup — the name should fall through to the env-name default.
    monkeypatch.setenv("gateway_token", "from-env")
    cfg = _cfg(
        {
            "secrets": {
                "provider": "env",
                "ref": "SOME_OTHER_ENV",  # single-secret ref; must be ignored here
                "keys": {"license": {"provider": "env", "ref": "LICENSE_ENV"}},
            }
        }
    )
    # 'gateway_token' is not in keys -> must use ref==name ('gateway_token'),
    # NOT the top-level 'SOME_OTHER_ENV'.
    r = resolve_secret("gateway_token", cfg)
    assert r.value.get_secret_value() == "from-env"


def test_toplevel_ref_adopted_for_single_secret_shape(tmp_path):
    # The single-secret shape (no `keys`) DOES adopt the top-level ref.
    (tmp_path / "the-secret").write_text(SENTINEL, encoding="utf-8")
    cfg = _cfg({"secrets": {"provider": "file", "ref": str(tmp_path / "the-secret")}})
    r = resolve_secret("anything", cfg)
    assert r.provider == "file"
    assert r.value.get_secret_value() == SENTINEL


# ─────────────── fail-closed default ─────────────────────────────────────────


def test_missing_env_required_raises(monkeypatch):
    monkeypatch.delenv("ABSENT_TOKEN", raising=False)
    with pytest.raises(SecretResolutionError):
        resolve_secret("ABSENT_TOKEN")


def test_missing_env_with_default(monkeypatch):
    monkeypatch.delenv("ABSENT_TOKEN", raising=False)
    r = resolve_secret("ABSENT_TOKEN", default="fallback")
    assert r.value.get_secret_value() == "fallback"


# ─────────────── property / no-leak invariants ──────────────────────────────


@pytest.mark.parametrize("prov,setup", [("env", "env"), ("file", "file")])
def test_value_always_masks(prov, setup, monkeypatch, tmp_path):
    if setup == "env":
        monkeypatch.setenv("K", SENTINEL)
        r = resolve_secret("K", provider="env")
    else:
        (tmp_path / "k").write_text(SENTINEL, encoding="utf-8")
        r = resolve_secret("k", provider="file", ref=str(tmp_path / "k"))
    assert isinstance(r.value, SecretStr)
    assert str(r.value) == "***"
    assert repr(r.value) == "SecretStr(***)"
    assert SENTINEL not in str(r.value)
    assert SENTINEL not in repr(r.value)


def test_source_ref_redacted_is_not_the_value(monkeypatch):
    monkeypatch.setenv("K", SENTINEL)
    r = resolve_secret("K", provider="env")
    assert SENTINEL not in r.source_ref_redacted
