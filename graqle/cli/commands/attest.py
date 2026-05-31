"""``graq attest`` CLI sub-app — offline proof-bundle verification (WS-A2).

The ``attest`` group is the CLI home for tamper-evidence attestation operations.
Its first command is ``verify``, a thin Typer shell over
:func:`graqle.verify.run_verify` (WS-A1's ``verify_bundle``):

    graq attest verify <bundle.json> --key <pub.pem>
    graq attest verify <bundle.json> --keys <keyring.json> --format json
    graq attest verify <bundle.json> --key <pub.pem> --rekor-sth <sth.json>

Why a new ``attest`` group rather than ``graq verify``: ``graq verify`` is
already taken by the dev-intelligence "verify staged changes vs compiled
intelligence" command (``graqle.intelligence.verify``). ``attest`` matches the
runtime attestation domain (``attest()`` / ``AttestationSink`` / anchoring) and
leaves room for future ``graq attest`` subcommands. The equivalent
dependency-light entrypoint is ``python -m graqle.verify``.

This sub-app NEVER imports a GraQle-internal trade-secret module and stays in the
verifier's isolation domain (stdlib + cryptography + the verify core).

Exit codes: 0 verified · 1 not verified · 2 bad CLI input / unreadable file.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from graqle.cli.console import create_console
from graqle.verify import EXIT_OK, VerifyUsageError, run_verify

console = create_console()


attest_app = typer.Typer(
    name="attest",
    help="Tamper-evidence attestation operations — verify proof bundles offline.",
    no_args_is_help=True,
)


@attest_app.command(name="verify")
def verify_command(
    bundle: str = typer.Argument(
        ...,
        help="Path to the proof-bundle JSON file to verify.",
    ),
    key: str = typer.Option(
        None,
        "--key",
        "-k",
        help="Path to a single ed25519 public-key PEM trusted for this proof.",
    ),
    keys: str = typer.Option(
        None,
        "--keys",
        help=(
            "Path to a JSON keyring with explicit per-kid windows + lifecycle "
            "states (audit a proof under its historical trust state)."
        ),
    ),
    rekor_sth: str = typer.Option(
        None,
        "--rekor-sth",
        help=(
            "Optional Rekor signed-tree-head JSON to check against (offline; "
            "treated as data, never fetched)."
        ),
    ),
    output_format: str = typer.Option(
        "text",
        "--format",
        help="Output format: text (default) or json.",
    ),
) -> None:
    """Verify a GraQle-format tamper-evidence proof bundle offline.

    Composes leaf-recompute + Merkle inclusion + ed25519 trust + optional offline
    Rekor binding. No network, no proprietary code — free forever.
    """
    if output_format not in ("text", "json"):
        console.print(
            f"[red]error: --format must be 'text' or 'json', got "
            f"{output_format!r}[/red]"
        )
        raise typer.Exit(2)

    try:
        exit_code, result = run_verify(
            bundle_path=Path(bundle),
            key_path=Path(key) if key else None,
            keys_path=Path(keys) if keys else None,
            rekor_sth_path=Path(rekor_sth) if rekor_sth else None,
        )
    except VerifyUsageError as exc:
        if output_format == "json":
            # Plain (un-highlighted) JSON to stdout so a consumer can parse it;
            # the non-zero exit still signals the usage failure.
            typer.echo(json.dumps({"ok": False, "error": str(exc)}))
        else:
            console.print(f"[red]error: {exc}[/red]")
        raise typer.Exit(2) from exc

    if output_format == "json":
        # Plain JSON (NOT console.print_json, which injects Rich ANSI colour
        # codes that break `... --format json | jq`).
        typer.echo(json.dumps(result))
    else:
        if result["ok"]:
            console.print(f"[green]VERIFIED[/green]: {result['failure']}")
        else:
            console.print(f"[red]FAILED[/red]: {result['failure']}")
        for step, passed in result["checks"].items():
            mark = "[green]pass[/green]" if passed else "[red]FAIL[/red]"
            console.print(f"  {step}: {mark}")
        if not result["rekor_checked"]:
            console.print(
                "  rekor: [yellow]not checked[/yellow] (no receipt in bundle)"
            )

    # Map verified/failed to the process exit code (0/1). Exit(0) is clean
    # success; Exit(1) signals a proof that did not verify.
    raise typer.Exit(EXIT_OK if exit_code == EXIT_OK else 1)
