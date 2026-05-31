"""``python -m graqle.verify`` — offline proof-bundle verification entrypoint.

A stdlib-only (argparse) entrypoint over :func:`graqle.verify.run_verify`, kept
deliberately dependency-light so it runs in a studio-free interpreter with only
``graqle`` installed (no extras, no Typer) — this is the surface the WS-A3
subprocess invariant exercises.

Usage::

    python -m graqle.verify <bundle.json> --key <pub.pem>
    python -m graqle.verify <bundle.json> --keys <keyring.json> --format json
    python -m graqle.verify <bundle.json> --key <pub.pem> --rekor-sth <sth.json>

Exit codes: 0 verified · 1 not verified · 2 usage/input error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from graqle.verify import EXIT_USAGE, VerifyUsageError, run_verify


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m graqle.verify",
        description=(
            "Verify a GraQle-format tamper-evidence proof bundle offline. "
            "No network; no proprietary code. Exit 0 = verified, 1 = not "
            "verified, 2 = usage error."
        ),
    )
    parser.add_argument(
        "bundle",
        help="Path to the proof-bundle JSON file to verify.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--key",
        metavar="PUB.PEM",
        help="Path to a single ed25519 public-key PEM trusted for this proof.",
    )
    group.add_argument(
        "--keys",
        metavar="KEYRING.JSON",
        help=(
            "Path to a JSON keyring with explicit per-kid windows + lifecycle "
            "states (for auditing a proof under its historical trust state)."
        ),
    )
    parser.add_argument(
        "--rekor-sth",
        metavar="STH.JSON",
        default=None,
        help=(
            "Optional Rekor signed-tree-head JSON to check the proof against "
            "(offline; treated as data, never fetched)."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse args, run verification, print the result, return the exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        exit_code, result = run_verify(
            bundle_path=Path(args.bundle),
            key_path=Path(args.key) if args.key else None,
            keys_path=Path(args.keys) if args.keys else None,
            rekor_sth_path=Path(args.rekor_sth) if args.rekor_sth else None,
        )
    except VerifyUsageError as exc:
        # Usage/input error -> exit 2, message to stderr (machine-readable too
        # when --format json so a caller never has to parse prose).
        if args.format == "json":
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        else:
            print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.format == "json":
        print(json.dumps(result))
    else:
        status = "VERIFIED" if result["ok"] else "FAILED"
        print(f"{status}: {result['failure']}")
        for step, passed in result["checks"].items():
            print(f"  {step}: {'pass' if passed else 'FAIL'}")
        if not result["rekor_checked"]:
            print("  rekor: not checked (no receipt in bundle)")
    return exit_code


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    sys.exit(main())
