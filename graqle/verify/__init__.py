"""Offline proof-bundle verification surface (WS-A2) — CLI + ``python -m`` core.

This package is the *user-facing* skin over
:func:`graqle.governance.tamper_evidence.verifier.verify_bundle` (WS-A1, moat M2).
It ships in **Community** (Apache-2.0) and is NEVER gated: anyone with
``pip install graqle``, a proof bundle, and the signer's public key(s) can verify
a proof offline, with no network and no proprietary code.

Two entrypoints share the one core here:

* ``python -m graqle.verify <bundle.json> --key <pub.pem>`` (this package's
  :mod:`graqle.verify.__main__`), and
* ``graq attest verify <bundle.json> --key <pub.pem>`` (the Typer sub-app in
  :mod:`graqle.cli.commands.attest`).

Both call :func:`run_verify`, so the verification logic, exit codes, and JSON
output are identical regardless of which surface is used.

Isolation contract
-------------------
This module imports only the standard library, ``cryptography``, and the two
isolated tamper-evidence modules (the verifier + the ed25519 key manifest). It
imports **nothing** from ``graqle.server``/``graqle.studio``/anchoring/network,
so ``python -m graqle.verify`` runs in a studio-free interpreter (WS-A3
subprocess invariant). The WS-A3 CI AST gate enforces this statically.

Key material formats
--------------------
``run_verify`` accepts the trusted keys two ways:

* ``--key <pub.pem>`` — a single ed25519 public-key PEM. The bundle's own
  ``signature.kid`` is registered under a wide-open trust window, so a single
  PEM "just works" for the common case (you trust this one key for this proof).
  The bundle's lifecycle/window security still comes from the *signing* side;
  with a bare PEM the verifier trusts the key for any time.
* ``--keys <keyring.json>`` — a JSON keyring giving explicit per-kid windows and
  lifecycle states, so an auditor can verify a proof under the *exact* trust
  state that applied when it was produced (e.g. a since-revoked key)::

      {
        "keys": [
          {
            "kid": "graqle-sdk-signing-2026-Q2",
            "public_key_pem": "-----BEGIN PUBLIC KEY-----\\n...",
            "valid_from": "2026-04-01T00:00:00Z",
            "valid_until": "2026-12-31T23:59:59Z",
            "state": "ACTIVE"        # ACTIVE | RETIRED | REVOKED
          }
        ]
      }

Exit codes (shared by both surfaces)
------------------------------------
* ``0`` — the bundle verified (``VerifyResult.ok``).
* ``1`` — the bundle did not verify (a typed failure).
* ``2`` — bad CLI input / unreadable or malformed key/bundle file (a usage
  error, distinct from a proof that simply failed to verify).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from graqle.governance.custody.ed25519_key_manifest import (
    Ed25519KeyManifest,
    KeyState,
)
from graqle.governance.tamper_evidence.verifier import (
    VerifyResult,
    verify_bundle,
)

# Exit codes — a module-level contract shared by both surfaces.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

# A bare --key PEM is trusted across this wide window (the bundle's own
# signing-time lifecycle is the real control; a single PEM means "I trust this
# key for this proof" without the caller having to state a window).
_WIDE_OPEN_FROM = datetime(1970, 1, 1, tzinfo=timezone.utc)
_WIDE_OPEN_UNTIL = datetime(9999, 12, 31, tzinfo=timezone.utc)


class VerifyUsageError(Exception):
    """A usage error (bad/unreadable input) — maps to exit code 2.

    Distinct from a proof that fails to verify (exit 1): this means the caller
    gave us something we could not even attempt to verify (missing file, bad
    PEM, malformed keyring JSON).
    """


def _load_public_key(pem_bytes: bytes):
    """Load an ed25519 public key from PEM bytes, raising VerifyUsageError on failure."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PublicKey,
    )

    try:
        key = serialization.load_pem_public_key(pem_bytes)
    except Exception as exc:  # cryptography raises a variety of types
        raise VerifyUsageError(f"could not parse public-key PEM: {exc}") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise VerifyUsageError(
            "public key is not an ed25519 key; the GraQle verifier only trusts "
            "ed25519 signing keys"
        )
    return key


def _parse_state(raw: object, kid: str) -> KeyState:
    """Parse a keyring entry's lifecycle state string to a KeyState."""
    if raw is None:
        return KeyState.ACTIVE
    if not isinstance(raw, str):
        raise VerifyUsageError(f"keyring entry {kid!r}: state must be a string")
    try:
        return KeyState[raw.strip().upper()]
    except KeyError as exc:
        raise VerifyUsageError(
            f"keyring entry {kid!r}: unknown state {raw!r}; expected one of "
            "ACTIVE, RETIRED, REVOKED"
        ) from exc


def _parse_ts(raw: object, kid: str, field_name: str, default: datetime) -> datetime:
    """Parse an RFC 3339 timestamp from a keyring entry, or use ``default``."""
    if raw is None:
        return default
    if not isinstance(raw, str):
        raise VerifyUsageError(
            f"keyring entry {kid!r}: {field_name} must be an RFC 3339 string"
        )
    text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise VerifyUsageError(
            f"keyring entry {kid!r}: {field_name} is not a valid RFC 3339 "
            f"timestamp: {raw!r}"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def manifest_from_single_key(pem_bytes: bytes, kid: str) -> Ed25519KeyManifest:
    """Build a one-key manifest trusting ``kid`` across a wide-open window.

    Used for the ``--key <pub.pem>`` convenience path: the single PEM is
    registered under the bundle's own ``kid`` so ``verify_bundle`` finds it.
    """
    manifest = Ed25519KeyManifest()
    manifest.register(
        kid=kid,
        public_key=_load_public_key(pem_bytes),
        valid_from=_WIDE_OPEN_FROM,
        valid_until=_WIDE_OPEN_UNTIL,
    )
    return manifest


def manifest_from_keyring(keyring: dict[str, Any]) -> Ed25519KeyManifest:
    """Build a manifest from a parsed keyring dict (explicit windows + states).

    Raises :class:`VerifyUsageError` on any malformed entry — a keyring is
    operator-supplied trust configuration, so a defect must be loud, not
    silently dropped (mirrors the pct keyring-loader discipline).
    """
    if not isinstance(keyring, dict) or not isinstance(keyring.get("keys"), list):
        raise VerifyUsageError(
            "keyring must be a JSON object with a 'keys' array"
        )
    manifest = Ed25519KeyManifest()
    seen = 0
    for entry in keyring["keys"]:
        if not isinstance(entry, dict):
            raise VerifyUsageError("each keyring entry must be a JSON object")
        kid = entry.get("kid")
        pem = entry.get("public_key_pem")
        if not isinstance(kid, str) or not kid:
            raise VerifyUsageError("keyring entry missing a non-empty 'kid'")
        if not isinstance(pem, str) or not pem:
            raise VerifyUsageError(
                f"keyring entry {kid!r} missing a non-empty 'public_key_pem'"
            )
        state = _parse_state(entry.get("state"), kid)
        valid_from = _parse_ts(entry.get("valid_from"), kid, "valid_from", _WIDE_OPEN_FROM)
        valid_until = _parse_ts(
            entry.get("valid_until"), kid, "valid_until", _WIDE_OPEN_UNTIL
        )
        manifest.register(
            kid=kid,
            public_key=_load_public_key(pem.encode("ascii")),
            valid_from=valid_from,
            valid_until=valid_until,
            state=state,
        )
        seen += 1
    if seen == 0:
        raise VerifyUsageError("keyring 'keys' array is empty — no keys to trust")
    return manifest


def _read_json_file(path: Path, what: str) -> Any:
    """Read + parse a JSON file, raising VerifyUsageError on any I/O or parse error."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise VerifyUsageError(f"cannot read {what} file {path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise VerifyUsageError(f"{what} file is not valid JSON: {exc}") from exc


def load_manifest(
    *, key_path: Path | None, keys_path: Path | None, bundle: dict[str, Any]
) -> Ed25519KeyManifest:
    """Build the trusted-key manifest from --key or --keys.

    Exactly one of ``key_path`` / ``keys_path`` must be given. With ``--key``,
    the single PEM is registered under the bundle's own ``signature.kid``.
    """
    if (key_path is None) == (keys_path is None):
        raise VerifyUsageError(
            "provide exactly one of --key <pub.pem> or --keys <keyring.json>"
        )
    if key_path is not None:
        try:
            pem_bytes = key_path.read_bytes()
        except OSError as exc:
            raise VerifyUsageError(f"cannot read key file {key_path}: {exc}") from exc
        sig = bundle.get("signature")
        kid = sig.get("kid") if isinstance(sig, dict) else None
        if not isinstance(kid, str) or not kid:
            raise VerifyUsageError(
                "bundle has no signature.kid to register the --key under; "
                "use --keys with an explicit kid instead"
            )
        return manifest_from_single_key(pem_bytes, kid)
    keyring = _read_json_file(keys_path, "keyring")
    return manifest_from_keyring(keyring)


def result_to_dict(result: VerifyResult) -> dict[str, Any]:
    """Render a VerifyResult as a JSON-serializable dict (the --format json shape)."""
    return {
        "ok": result.ok,
        "failure": result.failure.value,
        "checks": dict(result.checks),
        "rekor_checked": result.rekor_checked,
    }


def run_verify(
    *,
    bundle_path: Path,
    key_path: Path | None = None,
    keys_path: Path | None = None,
    rekor_sth_path: Path | None = None,
) -> tuple[int, dict[str, Any]]:
    """Verify a bundle file and return ``(exit_code, result_dict)``.

    The single core both surfaces (CLI + ``python -m``) call. Reads the bundle
    JSON, builds the trusted-key manifest, optionally injects an external Rekor
    STH file into the bundle's ``rekor`` block, runs :func:`verify_bundle`, and
    maps the outcome to an exit code. Raises :class:`VerifyUsageError` (exit 2)
    for input problems; returns exit 0/1 for a verified/failed proof.
    """
    bundle = _read_json_file(bundle_path, "bundle")
    if not isinstance(bundle, dict):
        raise VerifyUsageError("bundle file must contain a JSON object")

    # Optional external Rekor STH file: injected as DATA into the bundle's rekor
    # block (never fetched). If the bundle already carries a rekor block, an
    # explicit --rekor-sth file overrides it so an auditor can supply their own.
    if rekor_sth_path is not None:
        sth = _read_json_file(rekor_sth_path, "rekor STH")
        if not isinstance(sth, dict):
            raise VerifyUsageError("rekor STH file must contain a JSON object")
        bundle = {**bundle, "rekor": sth}

    manifest = load_manifest(key_path=key_path, keys_path=keys_path, bundle=bundle)
    result = verify_bundle(bundle, manifest)
    exit_code = EXIT_OK if result.ok else EXIT_FAILED
    return exit_code, result_to_dict(result)


__all__ = [
    "EXIT_OK",
    "EXIT_FAILED",
    "EXIT_USAGE",
    "VerifyUsageError",
    "manifest_from_single_key",
    "manifest_from_keyring",
    "load_manifest",
    "result_to_dict",
    "run_verify",
]
