"""``graq pct`` CLI sub-app — PCT issue + validate.

Implements ADR-205 §2.5. Two sub-commands:

    graq pct issue   --request <request.json> --signing-key <key.pem> \
                     --kid <K> --issuer <URL> [-o <out.jws>]
    graq pct validate --token <token-file> --keys-url <.well-known/pct-keys.json> \
                     [--expected-action <X>] [--expected-jurisdiction <ISO>]

Exit codes:
    0 — ALLOW (validate) or token written (issue)
    1 — BLOCK (validate)
    2 — Bad CLI input or unreadable file

The sub-app is purely a thin shell around
:func:`graqle.pct.issuer.issue_pct` and
:func:`graqle.pct.validator.validate_pct`. NO reasoning happens here;
the sub-app NEVER imports a GraQle-internal trade-secret module. See
:doc:`graqle/pct/extensions/README.md` for cross-link discipline.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import typer

from graqle.cli.console import create_console

console = create_console()


pct_app = typer.Typer(
    name="pct",
    help="PCT (Proof Claims Token) operations — issue and validate per OPSF spec v0.1.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_request_json(path: Path) -> dict[str, Any]:
    """Read + parse a PCT issue-request JSON file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        console.print(f"[red]Cannot read request file {path}: {exc}[/red]")
        raise typer.Exit(2) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        console.print(f"[red]Request file is not valid JSON: {exc}[/red]")
        raise typer.Exit(2) from exc


def _load_rsa_private_key(path: Path):
    """Load an RSA private key from a PEM file (PKCS#8 or PKCS#1)."""
    from cryptography.hazmat.primitives import serialization

    try:
        pem_bytes = path.read_bytes()
    except OSError as exc:
        console.print(f"[red]Cannot read key file {path}: {exc}[/red]")
        raise typer.Exit(2) from exc
    try:
        return serialization.load_pem_private_key(pem_bytes, password=None)
    except Exception as exc:
        console.print(f"[red]Failed to load PEM private key: {exc}[/red]")
        raise typer.Exit(2) from exc


def _build_public_key_resolver(keys_path: Path):
    """Build a kid→RSAPublicKey resolver from a local pct-keys.json file.

    Production deployments will fetch this over HTTPS from the issuer's
    ``.well-known/pct-keys.json`` (CR-011 / R25-EU05 ships the loader).
    For PR-010b-1 the CLI accepts a local file path so the surface is
    testable without a network round-trip.
    """
    from cryptography.hazmat.primitives import serialization

    try:
        keys_data = json.loads(keys_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        console.print(f"[red]Cannot read keys file {keys_path}: {exc}[/red]")
        raise typer.Exit(2) from exc

    kid_to_pem: dict[str, str] = {}
    dropped_kids: list[str] = []
    for entry in keys_data.get("keys", []):
        if isinstance(entry, dict) and entry.get("kid") and entry.get("public_key_pem"):
            kid_to_pem[entry["kid"]] = entry["public_key_pem"]
        else:
            # MAJOR-C2 sentinel pass 4 fix: do NOT silently drop malformed
            # key entries. Surface them to stderr so a config error is
            # visible. Don't fail hard — a single bad entry shouldn't
            # break the whole keyring — but the operator must see it.
            bad_kid = entry.get("kid", "<missing-kid>") if isinstance(entry, dict) else "<non-dict-entry>"
            dropped_kids.append(str(bad_kid))

    if dropped_kids:
        console.print(
            f"[yellow]warn: dropped {len(dropped_kids)} malformed key "
            f"entries from {keys_path} (kid values: {dropped_kids!r}). "
            f"Check that each entry has both 'kid' and 'public_key_pem' "
            f"fields.[/yellow]"
        )

    def resolver(kid: str):
        pem = kid_to_pem.get(kid)
        if not pem:
            return None
        try:
            return serialization.load_pem_public_key(pem.encode("ascii"))
        except Exception as exc:
            # Defensive: a PEM parse failure for a present kid is
            # different from "kid unknown" — surface it.
            console.print(
                f"[yellow]warn: PEM for kid={kid!r} failed to parse: "
                f"{type(exc).__name__}; treating as unresolvable.[/yellow]"
            )
            return None

    return resolver


# ---------------------------------------------------------------------------
# `graq pct issue`
# ---------------------------------------------------------------------------


@pct_app.command(name="issue")
def issue_command(
    request: str = typer.Option(
        ...,
        "--request",
        "-r",
        help="Path to JSON file describing the PCT issue request.",
    ),
    signing_key: str = typer.Option(
        ...,
        "--signing-key",
        "-k",
        help="Path to PEM file containing the RSA private signing key.",
    ),
    kid: str = typer.Option(
        ...,
        "--kid",
        help="Key identifier embedded in the JWS header.",
    ),
    issuer: str = typer.Option(
        ...,
        "--issuer",
        help="Issuer URI placed in the PCT payload.",
    ),
    output: str = typer.Option(
        "-",
        "--output",
        "-o",
        help="Output file for the JWS, or '-' for stdout (default).",
    ),
) -> None:
    """Mint a PCT JWS from a structured request file."""
    from graqle.pct.issuer import PctIssueRequest, PctIssueError, issue_pct

    req_data = _read_request_json(Path(request))
    try:
        req_obj = PctIssueRequest(**req_data)
    except TypeError as exc:
        console.print(
            f"[red]Request JSON does not match PctIssueRequest dataclass: "
            f"{exc}[/red]"
        )
        raise typer.Exit(2) from exc

    key = _load_rsa_private_key(Path(signing_key))

    try:
        token = issue_pct(
            req_obj,
            signing_key=key,
            kid=kid,
            issuer_url=issuer,
        )
    except PctIssueError as exc:
        console.print(f"[red]PCT issue failed: {exc}[/red]")
        raise typer.Exit(2) from exc

    if output == "-":
        sys.stdout.write(token + "\n")
    else:
        Path(output).expanduser().write_text(token + "\n", encoding="utf-8")
        console.print(f"[green]PCT written to {output}[/green]")


# ---------------------------------------------------------------------------
# `graq pct validate`
# ---------------------------------------------------------------------------


@pct_app.command(name="validate")
def validate_command(
    token: str = typer.Option(
        ...,
        "--token",
        "-t",
        help="Path to file containing the JWS compact-form token.",
    ),
    keys: str = typer.Option(
        ...,
        "--keys",
        "-K",
        help="Path to a .well-known/pct-keys.json file (or compatible).",
    ),
    expected_action: str = typer.Option(
        None,
        "--expected-action",
        help="If supplied, BLOCK unless this string is in allowed_purposes.",
    ),
    expected_jurisdiction: str = typer.Option(
        None,
        "--expected-jurisdiction",
        help="ISO 3166-1 alpha-2; if supplied, BLOCK unless in permitted_regions.",
    ),
) -> None:
    """Validate a PCT JWS and emit ALLOW/BLOCK + structured reasons."""
    from graqle.pct.validator import validate_pct

    try:
        token_str = Path(token).read_text(encoding="utf-8").strip()
    except OSError as exc:
        console.print(f"[red]Cannot read token file {token}: {exc}[/red]")
        raise typer.Exit(2) from exc

    resolver = _build_public_key_resolver(Path(keys))

    result = validate_pct(
        token_str,
        public_key_resolver=resolver,
        expected_action=expected_action,
        expected_jurisdiction=expected_jurisdiction,
    )

    output = {
        "decision": result.decision,
        "pct_id": result.pct_id,
        "issuer": result.issuer,
        "failure_reasons": result.failure_reasons,
    }
    sys.stdout.write(json.dumps(output, indent=2) + "\n")
    raise typer.Exit(0 if result.decision == "ALLOW" else 1)
