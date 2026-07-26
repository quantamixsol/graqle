"""CR-010.R5 — secrets provider abstraction (behind ``GRAQLE_USE_SECRETS_RESOLVER``).

A single, governed entry point for resolving a credential from one of four
providers — ``env | file | keychain | command`` — so that moving a deployment
from a developer laptop (macOS keychain) to a hosted environment (a mounted
secrets file) is a one-line ``graqle.yaml`` change and never a code change.

    Today, credentials are read env-only at point-of-use:
    ``backends/api.py`` reads ``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY``
    directly; ``cloud/credentials.py`` reads ``GRAQLE_API_KEY``; the keychain
    lookups live in repo shell scripts, not importable SDK code. Enterprise
    policy environments mount secrets as files and forbid everything else.
    This module is the new single choke point for credential access.

This first PR (PR-010.R5a) lands the module **behind a feature flag**
(``GRAQLE_USE_SECRETS_RESOLVER``, default OFF) with **zero callers migrated** —
purely additive, lowest possible risk, mirroring CR-002 PR-002a. Migration of
the read sites happens in PR-010.R5b; the default flips ON in PR-010.R5c.

Design (composition over inheritance — this module never mutates
``settings.py`` or ``resolver.py``):
  - Reuses ``SecretStr`` from ``graqle.config.resolver`` so every resolved
    value masks in ``repr``/``str`` and compares in constant time. A resolved
    secret can therefore never leak into logs, reports, or governed traces.
  - Mirrors ``resolve_neo4j``'s explicit, auditable priority chain and records
    which provider won in ``ResolvedSecret.provider``.
  - **Fail-closed:** a required secret that no provider can produce raises
    ``SecretResolutionError`` — it does not silently fall through to "".
  - The ``command`` provider runs an argv list **without a shell**
    (no ``shell=True``) so there is no shell-injection surface.
  - No exception, log line, or audit field ever contains the secret value;
    only the credential *name*, the *provider*, and a *redacted* reference.

See: .gsm/external/Change Requests/CR-010.R5-secrets-provider-abstraction.md
"""

from __future__ import annotations

# -- graqle:intelligence --
# module: graqle.config.secrets
# risk: LOW (new file, behind feature flag GRAQLE_USE_SECRETS_RESOLVER default
#            OFF, no callers migrated in PR-010.R5a)
# dependencies: os, sys, shlex, subprocess, pathlib, dataclasses, typing,
#               graqle.config.resolver (SecretStr), graqle.config.exceptions
# constraints: MUST NEVER embed a resolved credential value in an exception,
#              log line, or audit field. MUST NEVER use shell=True. MUST remain
#              composition-only (no mutation of settings.py / resolver.py).
# import-DAG: secrets -> resolver -> exceptions is acyclic and MUST stay so.
#             resolver.py MUST NOT import from secrets.py (would close a cycle
#             that unit tests importing modules individually would not catch —
#             CR-010.R5 graq_predict latent risk (a)).
# -- /graqle:intelligence --

import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

from graqle.config.exceptions import (
    SecretProviderUnsupportedError,
    SecretResolutionError,
)
from graqle.config.resolver import ResolvedConfig, SecretStr

# ─────────────── Public API ─────────────────────────────────────────────────

Provider = Literal["env", "file", "keychain", "command"]

VALID_PROVIDERS: frozenset[str] = frozenset({"env", "file", "keychain", "command"})
"""The provider names accepted in a ``secrets:`` block or an override map."""

_DEFAULT_PROVIDER: Provider = "env"
_COMMAND_TIMEOUT_S = 10.0


def is_secrets_resolver_enabled() -> bool:
    """Returns True iff the ``GRAQLE_USE_SECRETS_RESOLVER`` flag is set ON.

    Unlike ``resolver.is_resolver_enabled()`` (which defaults ON), this flag
    defaults **OFF**. PR-010.R5a ships the module inert; callers keep their
    exact current ``os.environ`` behaviour until PR-010.R5b migrates them and
    PR-010.R5c flips this default. Truthy values: ``1``, ``true``, ``yes``
    (case-insensitive). Everything else — including unset — is OFF.
    """
    raw = os.environ.get("GRAQLE_USE_SECRETS_RESOLVER", "0").strip().lower()
    return raw in {"1", "true", "yes"}


# ─────────────── Frozen value object ─────────────────────────────────────────


@dataclass(frozen=True)
class ResolvedSecret:
    """Immutable result of resolving one credential.

    Attributes:
        value: The credential, wrapped in ``SecretStr`` so it masks to ``***``
            in ``repr``/``str`` and compares in constant time. Call
            ``value.get_secret_value()`` to retrieve the raw string — sparingly.
        provider: Which provider produced the value
            (``env | file | keychain | command``).
        source_ref_redacted: A log-safe description of *where* the value came
            from — the reference with ``Path.home()`` masked and any obvious
            value-bearing tail removed. Safe to print; never the value itself.
    """

    value: SecretStr
    provider: Provider
    source_ref_redacted: str


# ─────────────── Internal helpers ────────────────────────────────────────────


def _redact_ref(ref: str) -> str:
    """Return a log-safe form of ``ref`` (an env name, path, or argv string).

    Masks any ``Path.home()`` prefix to ``~`` (so we never log a full home
    directory) and truncates very long references. ``ref`` is provider
    *configuration*, not the secret value, but redacting home keeps error
    messages clean and avoids leaking usernames.
    """
    s = str(ref)
    home = str(Path.home())
    if home and s.startswith(home):
        s = "~" + s[len(home):]
    if len(s) > 120:
        s = s[:117] + "..."
    return s


def _resolve_provider_and_ref(
    name: str,
    cfg: ResolvedConfig | None,
    provider: str | None,
    ref: str | None,
) -> tuple[Provider, str]:
    """Resolve the (provider, ref) pair for ``name`` by explicit, auditable priority.

    Priority chain (highest first) — mirrors ``resolve_neo4j``:
        1. Explicit ``provider`` / ``ref`` kwargs.
        2. Per-key override map: ``cfg.yaml_data['secrets']['keys'][name]``.
        3. Top-level default block: ``cfg.yaml_data['secrets']`` (``provider``,
           and ``ref`` if given).
        4. Hard default: provider ``env``, ref == ``name``.

    Raises:
        SecretResolutionError: if a resolved provider name is not one of
            ``VALID_PROVIDERS`` (fail-closed on a misconfigured yaml).
    """
    resolved_provider: str | None = provider
    resolved_ref: str | None = ref

    secrets_section: Mapping[str, Any] = {}
    if cfg is not None and isinstance(cfg.yaml_data, Mapping):
        section = cfg.yaml_data.get("secrets") or {}
        if isinstance(section, Mapping):
            secrets_section = section

    # (2) per-key override map
    if (resolved_provider is None or resolved_ref is None) and secrets_section:
        keys = secrets_section.get("keys") or {}
        if isinstance(keys, Mapping):
            entry = keys.get(name)
            if isinstance(entry, Mapping):
                if resolved_provider is None and entry.get("provider"):
                    resolved_provider = str(entry["provider"])
                if resolved_ref is None and entry.get("ref"):
                    resolved_ref = str(entry["ref"])

    # (3) top-level default block
    if resolved_provider is None and secrets_section.get("provider"):
        resolved_provider = str(secrets_section["provider"])
    if resolved_ref is None and secrets_section.get("ref"):
        # A top-level ``ref`` describes the *single-secret* config shape
        # (``secrets: {provider: file, ref: /path}`` — one credential for the
        # whole SDK). It must NOT be adopted for a *named* lookup in a
        # multi-key block, or every unmatched name would resolve from the same
        # ref. We therefore adopt it ONLY when ALL hold (CR-010.R5 sentinel M-3):
        #   - no explicit ``provider`` kwarg was passed (this call isn't an override),
        #   - no explicit ``ref`` kwarg was passed (already guarded above), and
        #   - the section has no ``keys`` sub-map (it is the single-secret shape).
        # Otherwise fall through to the env-name default (4), which is safe.
        is_single_secret_shape = provider is None and "keys" not in secrets_section
        if is_single_secret_shape:
            resolved_ref = str(secrets_section["ref"])

    # (4) hard defaults
    if resolved_provider is None:
        resolved_provider = _DEFAULT_PROVIDER
    if resolved_ref is None:
        resolved_ref = name

    if resolved_provider not in VALID_PROVIDERS:
        raise SecretResolutionError(
            name=name,
            provider=str(resolved_provider),
            reason=(
                f"unknown provider; valid providers are "
                f"{sorted(VALID_PROVIDERS)}"
            ),
        )

    return resolved_provider, resolved_ref  # type: ignore[return-value]


# ─────────────── Provider implementations ───────────────────────────────────


def _provider_env(name: str, ref: str) -> str | None:
    """``env`` provider: read ``os.environ[ref]``. Returns None if unset/empty."""
    val = os.environ.get(ref)
    return val if val else None


def _provider_file(name: str, ref: str) -> str | None:
    """``file`` provider: read the file at ``ref`` and return its contents.

    Natively supports mounted-secret stores of the ``$SECRETS_PATH/<name>``
    shape: ``${SECRETS_PATH}`` (and any other env var) is expanded via
    ``os.path.expandvars`` and ``~`` via ``expanduser``. A single trailing
    newline is stripped (mounted files commonly end with one). Returns None if
    the resolved path does not exist.

    Raises:
        SecretResolutionError: the path exists but could not be read. The
            reason names the OSError type only — never the file contents.
    """
    path = Path(os.path.expandvars(os.path.expanduser(ref)))
    if not path.exists():
        # Absent file — a *different* signal than an empty file. Return None so
        # the caller's ``default`` / fail-closed contract applies uniformly.
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:  # permission, is-a-directory, etc.
        raise SecretResolutionError(
            name=name,
            provider="file",
            reason=f"could not read {_redact_ref(str(path))}: {type(e).__name__}",
        ) from e
    stripped = raw[:-1] if raw.endswith("\n") else raw
    if stripped == "":
        # The file EXISTS but is empty. In mounted-secret stores (K8s, the
        # $SECRETS_PATH pattern) an empty file is a provisioning fault — the
        # mount raced ahead of the secret injection — not a "secret absent"
        # signal. Fail-closed LOUDLY and distinctly so an operator can tell a
        # misprovisioned mount from an unconfigured secret. (CR-010.R5 sentinel
        # M-1.) We never fall through to a default here: an empty required
        # secret must never be silently substituted.
        raise SecretResolutionError(
            name=name,
            provider="file",
            reason=f"secret file {_redact_ref(str(path))} exists but is empty",
        )
    return stripped


def _provider_keychain(name: str, ref: str) -> str | None:
    """``keychain`` provider: macOS ``security find-generic-password -w -s <ref>``.

    Moves the previously-scripted keychain lookups into the SDK. Runs argv
    without a shell. Only available on macOS (``sys.platform == 'darwin'``).

    Raises:
        SecretProviderUnsupportedError: on any non-macOS platform.
        SecretResolutionError: the ``security`` tool errored (non-zero exit or
            missing binary). stderr is intentionally NOT surfaced — it can echo
            the account name and we keep the message minimal.
    """
    if sys.platform != "darwin":
        raise SecretProviderUnsupportedError(provider="keychain", platform=sys.platform)
    argv = ["security", "find-generic-password", "-w", "-s", ref]
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
            argv,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_S,
            shell=False,
        )
    except FileNotFoundError as e:
        raise SecretResolutionError(
            name=name, provider="keychain", reason="`security` tool not found"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise SecretResolutionError(
            name=name, provider="keychain", reason="keychain lookup timed out"
        ) from e
    if proc.returncode != 0:
        # Non-zero usually means "item not found" — treat as absent, not error,
        # so a `default` can apply. Never surface stderr (may echo the account).
        return None
    out = proc.stdout
    if out.endswith("\n"):
        out = out[:-1]
    return out or None


def _provider_command(name: str, ref: str) -> str | None:
    """``command`` provider: run ``ref`` as an argv and return its stdout.

    For vault CLIs (e.g. ``vault read -field=value secret/x``). ``ref`` may be a
    string (split with ``shlex.split``, POSIX rules) or an already-split list.
    Runs **without a shell** — there is no shell-injection surface. Bounded by a
    10s timeout. A single trailing newline is stripped.

    Raises:
        SecretResolutionError: the command exited non-zero, timed out, or the
            binary was missing. stderr is NOT included in the message (a vault
            CLI can echo secret material into stderr).
    """
    if isinstance(ref, str):
        argv = shlex.split(ref, posix=True)
    else:  # pragma: no cover — defensive; ref is typed str at call sites
        argv = list(ref)
    if not argv:
        raise SecretResolutionError(
            name=name, provider="command", reason="empty command"
        )
    try:
        proc = subprocess.run(  # noqa: S603 — argv list, shell=False
            argv,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_S,
            shell=False,
        )
    except FileNotFoundError as e:
        raise SecretResolutionError(
            name=name,
            provider="command",
            reason=f"command not found: {_redact_ref(argv[0])}",
        ) from e
    except subprocess.TimeoutExpired as e:
        raise SecretResolutionError(
            name=name, provider="command", reason="command timed out"
        ) from e
    if proc.returncode != 0:
        raise SecretResolutionError(
            name=name,
            provider="command",
            reason=f"command exited {proc.returncode}",
        )
    out = proc.stdout
    if out.endswith("\n"):
        out = out[:-1]
    return out or None


_PROVIDERS = {
    "env": _provider_env,
    "file": _provider_file,
    "keychain": _provider_keychain,
    "command": _provider_command,
}


# ─────────────── Public resolution function ──────────────────────────────────


def resolve_secret(
    name: str,
    cfg: ResolvedConfig | None = None,
    *,
    default: str | None = None,
    provider: str | None = None,
    ref: str | None = None,
) -> ResolvedSecret:
    """Resolve a single credential ``name`` via the configured provider.

    Provider + reference are chosen by an explicit, auditable priority chain
    (see ``_resolve_provider_and_ref``): explicit kwargs > per-key override map
    > top-level ``secrets:`` block > env-with-ref==name default.

    Args:
        name: Logical credential name (e.g. ``"gateway_token"``). Doubles as the
            env-var name / keychain account when no explicit ``ref`` is given.
        cfg: A resolved ``graqle.yaml`` (from ``resolver.resolve_config``). Its
            ``secrets:`` block supplies provider/ref defaults. May be None.
        default: Fallback returned (wrapped in ``SecretStr``) when no provider
            produces a value. When None, a missing secret is **fail-closed** and
            raises ``SecretResolutionError``.
        provider: Explicit provider override (highest priority).
        ref: Explicit reference override (highest priority).

    Returns:
        ResolvedSecret: the masked value plus provider + redacted-ref audit data.

    Raises:
        SecretResolutionError: no value found and ``default`` is None, or a
            provider failed, or the provider name is invalid.
        SecretProviderUnsupportedError: provider unavailable on this platform
            (e.g. ``keychain`` off macOS).
    """
    resolved_provider, resolved_ref = _resolve_provider_and_ref(
        name, cfg, provider, ref
    )

    impl = _PROVIDERS[resolved_provider]
    value = impl(name, resolved_ref)

    if value is None:
        if default is not None:
            return ResolvedSecret(
                value=SecretStr(default),
                provider=resolved_provider,
                source_ref_redacted="<default>",
            )
        raise SecretResolutionError(
            name=name,
            provider=resolved_provider,
            reason=(
                f"no value from provider (ref={_redact_ref(resolved_ref)}) "
                f"and no default supplied"
            ),
        )

    return ResolvedSecret(
        value=SecretStr(value),
        provider=resolved_provider,
        source_ref_redacted=_redact_ref(resolved_ref),
    )
