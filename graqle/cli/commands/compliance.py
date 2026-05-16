"""graq compliance — EU AI Act compliance surfaces.

Provides two commands:

  * ``graq compliance status`` (PR-009b) — read-only posture introspection.
  * ``graq compliance export`` (PR-009c) — export the on-disk audit trail
    as JSONL evidence for Article 12 record-keeping, with optional
    SHA-256 sidecar for tamper evidence.

PR-009b — status surface
========================

Surfaces which EU AI Act articles GraQle documents alignment with, the
runtime configuration flags that drive deployer-visible disclosure
behaviour, and audit-trail metadata that deployers can quote in their
own Article 9 risk-management file or Article 12 record-keeping.

This command never writes — it reads:

  1. The shipped compliance documentation (``docs/compliance/eu-ai-act/``)
     to enumerate which Articles GraQle currently claims alignment with.
  2. ``GRAQLE_EU_AI_ACT_MODE`` from the environment to report whether
     deployer-visible disclosure surfaces (Article 50 banner, MCP
     envelope ``compliance`` block) are armed for this process. The
     env var is the single switch; CLI flags do not override it (Article
     14 oversight discipline — runtime posture decided by config, not
     ad-hoc CLI args).
  3. The on-disk audit trail at ``.graqle/governance/audit/`` to report
     the last session timestamp and entry count. This is a metadata-only
     read; session contents are not surfaced (export is the separate
     ``graq compliance export`` command — PR-009c).

Article 13 link: the JSON shape mirrors the ``compliance`` block that
will appear in every MCP envelope when ``GRAQLE_EU_AI_ACT_MODE=on``
(planned in PR-009d), so customer-side compliance pipelines can use the
SAME parsing logic against the CLI output and against live MCP envelopes.

PR-009c — export surface
========================

Materialises the on-disk audit trail at ``.graqle/governance/audit/``
into a single JSONL stream (one session per line). Optional ``--since``
and ``--until`` filters bound the export to a date range.

When ``--sha256-sidecar`` is set, also writes ``<output>.sha256`` with
one SHA-256 hash per output line, in the same order. The hashes provide
Article 12-evidence tamper detection — a customer can verify their
archive hasn't been mutated by re-hashing each line and comparing.

This is the **raising** counterpart to ``status`` — bad input dates,
permission errors, broken session JSON all surface as non-zero exit
codes with a stderr message. The ``status`` command is the non-raising
introspection surface.
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.compliance
# risk: LOW (impact radius: 1 modules — main only)
# consumers: main
# dependencies: __future__, json, os, pathlib, typer, console
# constraints: read-only — never writes to audit log or config
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import typer

from graqle.cli.console import create_console

console = create_console()

compliance_app = typer.Typer(
    name="compliance",
    help="EU AI Act compliance posture introspection (read-only).",
    no_args_is_help=True,
)


# Articles GraQle's documentation currently maps to. The order matches the
# README compliance index. Each entry: (article_number, applicability_date,
# applies_to_graqle). The list is the authoritative ordering for the JSON
# output and the text table — if you add a new doc file in
# ``docs/compliance/eu-ai-act/``, add the row HERE too, otherwise the
# integrity test in ``tests/test_compliance/`` will fail.
ARTICLES_COVERED: list[tuple[str, str, str]] = [
    ("4", "2025-02-02", "YES"),
    ("12", "2026-08-02", "INDIRECTLY"),
    ("13", "2026-08-02", "INDIRECTLY"),
    ("14", "2026-08-02", "INDIRECTLY"),
    ("15", "2026-08-02", "INDIRECTLY"),
    ("25", "2026-08-02", "YES"),
    ("50", "2026-08-02", "YES"),
]

SYSTEM_CARD_URL = (
    "https://github.com/quantamixsol/graqle/blob/master/"
    "docs/compliance/eu-ai-act/README.md"
)


def _read_eu_ai_act_mode() -> bool:
    """Return True iff ``GRAQLE_EU_AI_ACT_MODE`` is set to a truthy value.

    Recognised truthy values (case-insensitive): ``on``, ``true``, ``1``,
    ``yes``. Anything else (including unset) returns False.
    """
    raw = os.environ.get("GRAQLE_EU_AI_ACT_MODE", "").strip().lower()
    return raw in {"on", "true", "1", "yes"}


def _read_audit_trail_metadata(audit_root: Path) -> dict[str, Any]:
    """Read metadata about the on-disk audit trail without loading sessions.

    Returns a dict with:
      * ``path``        — the directory string (resolved absolute path).
      * ``exists``      — whether the directory exists.
      * ``session_count`` — number of ``*.json`` files in the directory.
      * ``last_session_id`` — the lexically-greatest session id (matches
        the ``YYYYMMDD_HHMMSS`` format used by AuditTrail.start_session
        so lexical sort == chronological order), or None if no sessions.

    Never reads session file contents — this is metadata only, by design.
    Session contents are surfaced by ``graq audit export`` (PR-009c).

    All filesystem errors (PermissionError, OSError on glob, transient
    races where the dir disappears mid-call) fold back into the
    "no sessions visible" result — Article-12 read-side observability
    must never raise. The export command is the surface that raises.
    """
    # ``.resolve()`` can itself raise on Windows for some symlink loops;
    # fall back to ``.absolute()`` if so, and to the raw string as a
    # final defence. Either way the result carries SOME string — this
    # function must never raise (Article 12 read-side observability).
    try:
        resolved: Path | str = audit_root.resolve()
    except OSError:
        try:
            resolved = audit_root.absolute()
        except OSError:
            resolved = str(audit_root)
    result: dict[str, Any] = {
        "path": str(resolved),
        "exists": False,
        "session_count": 0,
        "last_session_id": None,
    }
    try:
        if not audit_root.exists():
            return result
        result["exists"] = True
        files = sorted(audit_root.glob("*.json"))
    except (PermissionError, OSError):
        # Directory exists but we can't read it — surface as exists=True
        # if we got that far, else stay False. Either way no sessions.
        return result
    result["session_count"] = len(files)
    if files:
        result["last_session_id"] = files[-1].stem
    return result


def _build_status_payload(repo_root: Path) -> dict[str, Any]:
    """Assemble the full status payload as a plain dict.

    Splitting this out from the typer command keeps the JSON shape testable
    without invoking the typer runner — the test suite calls this directly.

    ``repo_root`` is treated as untrusted input — we ``expanduser()`` it
    (so ``~`` works for users) and rely on ``_read_audit_trail_metadata``
    to do the bounded filesystem read. No symlink traversal happens past
    the audit subdir.
    """
    # Version import is wrapped — a broken install (e.g. partial wheel)
    # must not crash the compliance status surface, since this command
    # is exactly what a customer would run during a compliance audit
    # if they suspect something else is broken.
    try:
        from graqle.__version__ import __version__
    except ImportError:
        __version__ = "unknown"

    safe_root = Path(repo_root).expanduser()
    audit_meta = _read_audit_trail_metadata(
        safe_root / ".graqle" / "governance" / "audit"
    )
    # v0.57.0: embed the CR-010 subsystem status under a dedicated key
    # so the existing JSON schema stays backward-compatible (the old
    # `eu_ai_act_mode` boolean still appears at top level; the new
    # subsystem detail lives in its own nested envelope). Schema is
    # versioned independently from this status payload's own
    # schema_version.
    try:
        from graqle.compliance.switch_status import build_switch_status
        eu_ai_act_subsystems = build_switch_status()
    except ImportError:
        eu_ai_act_subsystems = {"status": "unavailable"}
    return {
        "graqle_version": __version__,
        "eu_ai_act_mode": _read_eu_ai_act_mode(),
        "eu_ai_act_subsystems": eu_ai_act_subsystems,
        "articles_covered": [a[0] for a in ARTICLES_COVERED],
        "articles_detail": [
            {
                "article": a[0],
                "applicability_date": a[1],
                "applies_to_graqle": a[2],
            }
            for a in ARTICLES_COVERED
        ],
        "system_card_url": SYSTEM_CARD_URL,
        "audit_trail": audit_meta,
        # Schema version stays at "1" because the new `eu_ai_act_subsystems`
        # field is purely ADDITIVE — existing consumers that pin on schema
        # v1 still see every field they relied on. The subsystems envelope
        # has its OWN versioning (`switch_status.SWITCH_STATUS_SCHEMA_VERSION`)
        # so a future breaking change there doesn't force a top-level bump.
        "schema_version": "1",
    }


def _render_text(payload: dict[str, Any]) -> None:
    """Render the status payload as a Rich-formatted table for humans."""
    from rich.table import Table

    mode = payload["eu_ai_act_mode"]
    mode_color = "green" if mode else "yellow"
    mode_label = "ON" if mode else "OFF (default)"

    console.print()
    console.print("[bold]GraQle EU AI Act compliance posture[/bold]")
    console.print(f"  Version:            {payload['graqle_version']}")
    console.print(
        f"  EU_AI_ACT_MODE:     [{mode_color}]{mode_label}[/{mode_color}]"
    )
    console.print(f"  Schema version:     {payload['schema_version']}")
    console.print(f"  System card:        {payload['system_card_url']}")

    table = Table(title="Articles covered", show_lines=False)
    table.add_column("Article", style="cyan", no_wrap=True)
    table.add_column("Applicability", style="white")
    table.add_column("Applies to GraQle", style="white")
    for row in payload["articles_detail"]:
        verdict_style = "green" if row["applies_to_graqle"] == "YES" else "yellow"
        table.add_row(
            f"Art {row['article']}",
            row["applicability_date"],
            f"[{verdict_style}]{row['applies_to_graqle']}[/{verdict_style}]",
        )
    console.print(table)

    audit = payload["audit_trail"]
    console.print("[bold]Audit trail[/bold]")
    if audit["exists"]:
        last = audit["last_session_id"] or "<none>"
        console.print(
            f"  Path:             {audit['path']}"
        )
        console.print(
            f"  Session count:    {audit['session_count']}"
        )
        console.print(
            f"  Last session id:  {last}"
        )
    else:
        console.print(
            f"  [yellow]No audit trail yet — directory not present.[/yellow]"
        )
        console.print(
            f"  Expected at:      {audit['path']}"
        )
    console.print()
    if not mode:
        console.print(
            "[dim]Tip: set GRAQLE_EU_AI_ACT_MODE=on to arm Article 50 disclosure"
            " surfaces (lands in PR-009d).[/dim]"
        )


@compliance_app.command(name="status")
def status_command(
    output_format: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format: text (default, Rich table) or json (compliance pipelines).",
    ),
    repo_root: str = typer.Option(
        ".",
        "--repo-root",
        help="Directory to read the audit trail from (default: current working dir).",
    ),
    include_robustness: bool = typer.Option(
        False,
        "--include-robustness",
        help="Include the Article 15 machine-readable robustness attestation.",
    ),
) -> None:
    """Show GraQle's EU AI Act compliance posture (read-only).

    \b
    Examples:
        graq compliance status
        graq compliance status --format json
        graq compliance status --include-robustness --format json
        graq compliance status --repo-root /path/to/project --format json
    """
    fmt = (output_format or "text").strip().lower()
    if fmt not in {"text", "json"}:
        console.print(
            f"[red]Unknown --format value: {output_format!r}. "
            "Use 'text' or 'json'.[/red]"
        )
        raise typer.Exit(2)

    payload = _build_status_payload(Path(repo_root))

    # PR-009e: optional Article 15 robustness attestation. Pull from
    # graqle.compliance.robustness (a sibling module of disclosure).
    # Wrapped so a partial install can't crash the status command —
    # the payload renders without the robustness block if the module
    # somehow fails to import.
    if include_robustness:
        try:
            from graqle.compliance.robustness import build_robustness_attestation
            payload["robustness"] = build_robustness_attestation().to_dict()
        except Exception as _exc:  # noqa: BLE001 — never let the attestation crash status
            import logging
            logging.getLogger("graqle.cli.compliance").debug(
                "Robustness attestation unavailable: %s", _exc,
            )
            payload["robustness"] = {
                "error": "robustness attestation module unavailable",
            }

    if fmt == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    _render_text(payload)
    if include_robustness and "robustness" in payload:
        _render_robustness_text(payload["robustness"])


def _render_robustness_text(robustness: dict[str, Any]) -> None:
    """Render the Article 15 robustness attestation as a Rich table."""
    from rich.table import Table

    console.print("[bold]Article 15 robustness attestation[/bold]")
    if "error" in robustness:
        console.print(f"  [red]{robustness['error']}[/red]")
        return

    console.print(
        f"  Article 15 aligned:  "
        f"[green]{robustness.get('article_15_aligned', False)}[/green]"
    )
    console.print(
        f"  Indirect (not high-risk):  "
        f"[yellow]{robustness.get('article_15_indirect', False)}[/yellow]"
    )
    console.print(
        f"  Security disclosure: {robustness.get('security_disclosure_email', '')}"
    )
    console.print(
        f"  Security policy:     {robustness.get('security_policy_url', '')}"
    )

    defences = robustness.get("defences", [])
    if defences:
        table = Table(title=f"Defences ({len(defences)})", show_lines=False)
        table.add_column("Id", style="cyan", no_wrap=False)
        table.add_column("Threat class", style="white")
        for d in defences:
            table.add_row(d.get("id", ""), d.get("threat_class", ""))
        console.print(table)

    claims = robustness.get("measurable_claims", [])
    if claims:
        table = Table(title=f"Measurable claims ({len(claims)})", show_lines=False)
        table.add_column("Metric", style="cyan", no_wrap=False)
        table.add_column("Claim", style="white")
        for c in claims:
            table.add_row(c.get("metric_id", ""), c.get("claim", ""))
        console.print(table)

    boundary = robustness.get("adversarial_input_boundary", "")
    if boundary:
        console.print()
        console.print("[bold]Adversarial input boundary[/bold]")
        console.print(f"  [dim]{boundary}[/dim]")


# ---------------------------------------------------------------------------
# PR-009c — `graq compliance export` (Article 12 evidence trail)
# ---------------------------------------------------------------------------


def _parse_iso_date_bound(raw: str, label: str) -> str:
    """Parse a YYYY-MM-DD bound into a string suitable for prefix comparison.

    Session ids are formatted as ``YYYYMMDD_HHMMSS`` (no dashes). We
    normalise the user input (which is ``YYYY-MM-DD`` per ISO style) to
    that prefix shape so we can compare lexically against session ids.

    Uses ``datetime.strptime`` for full calendar validation — rejects
    2026-02-31, 2026-04-31, etc. (sentinel-flagged scenarios). The
    rejection is per-Article-12 hygiene: a malformed date in a customer's
    audit-export script is worth surfacing loudly, not silently producing
    an empty window.

    Raises ``typer.BadParameter`` with a clear message on malformed input
    — the export surface IS allowed to raise.
    """
    from datetime import datetime

    raw_clean = (raw or "").strip()
    if not raw_clean:
        raise typer.BadParameter(f"--{label} cannot be empty.")
    # Strict shape check first — strptime is permissive about
    # non-zero-padded fields (it accepts ``2026-8-01``) but our session
    # ids are strictly ``YYYYMMDD``, so we require zero-padded input.
    parts = raw_clean.split("-")
    if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
        raise typer.BadParameter(
            f"--{label} must be YYYY-MM-DD (zero-padded), got {raw!r}."
        )
    try:
        dt = datetime.strptime(raw_clean, "%Y-%m-%d")
    except ValueError as exc:
        raise typer.BadParameter(
            f"--{label} must be a valid YYYY-MM-DD date, got {raw!r}: {exc}"
        ) from exc
    return dt.strftime("%Y%m%d")


def _session_id_in_range(
    session_id: str, since_prefix: str | None, until_prefix: str | None
) -> bool:
    """Check whether ``session_id`` falls within [since, until] inclusive.

    Both bounds are compared lexically against the session id's
    ``YYYYMMDD`` prefix (first 8 chars). Either bound may be None.
    Session ids that don't have an 8-char digit prefix are excluded —
    they pre-date the canonical naming and shouldn't appear in an
    Article-12 evidence export.
    """
    if len(session_id) < 8 or not session_id[:8].isdigit():
        return False
    head = session_id[:8]
    if since_prefix is not None and head < since_prefix:
        return False
    if until_prefix is not None and head > until_prefix:
        return False
    return True


def _stream_audit_sessions(
    audit_dir: Path,
    since_prefix: str | None,
    until_prefix: str | None,
):
    """Yield ``(session_id, json_text)`` tuples in chronological order.

    Each session file is parsed and re-serialised in canonical form
    (``sort_keys=True`` + ``separators=(',', ':')``) so the export is
    deterministic across runs regardless of the on-disk indent/key order.
    The Article-12 doc commits to this canonical-form semantics (not
    byte-identity to the indented on-disk JSON).

    Sessions outside the [since, until] window are skipped. Malformed
    filenames are skipped silently (they shouldn't be in an audit dir).
    Read errors on individual files raise ``OSError`` so the caller can
    surface a clear stderr message — this is the raising surface.

    Symlink hardening: session files that are symlinks are SKIPPED with
    a no-op (not exported). The audit trail must be append-only on
    real files. A symlink in the audit dir is either an admin mistake
    or an attempt to inject foreign content; either way, refusing to
    follow is the safe default.
    """
    import sys as _sys

    if not audit_dir.exists():
        return
    for fpath in sorted(audit_dir.glob("*.json")):
        # Symlink hardening — refuse to follow symlinks in the audit dir.
        # The audit trail is append-only on real files; symlinks here
        # are an admin mistake or a content-injection attempt.
        # Surface the skip to stderr so the operator notices missing
        # records during their compliance pull.
        if fpath.is_symlink():
            _sys.stderr.write(
                f"warn: skipping symlink in audit dir: {fpath.name}\n"
            )
            continue
        sid = fpath.stem
        if not _session_id_in_range(sid, since_prefix, until_prefix):
            continue
        text = fpath.read_text(encoding="utf-8")
        # Collapse to a single line for JSONL — sessions are stored
        # indent-formatted on disk for human inspection; the export
        # is wire-format. ``sort_keys=True`` + ``separators=(",", ":")``
        # gives DETERMINISTIC byte ordering across runs — re-exporting
        # the same input window produces byte-identical output, which
        # is the property a customer's tamper-detection sidecar needs.
        # (Byte-identity to the *on-disk* JSON would defeat that goal
        # because indent whitespace and key order can drift on disk
        # while the canonical-form export stays stable.)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise OSError(
                f"audit session {sid} is not valid JSON: {exc}"
            ) from exc
        yield sid, json.dumps(data, sort_keys=True, separators=(",", ":"))


def _sha256_hex(text: str) -> str:
    """Return SHA-256 hex digest of UTF-8 encoded text."""
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@compliance_app.command(name="export")
def export_command(
    output: str = typer.Option(
        "-",
        "--output",
        "-o",
        help="Output file path, or '-' for stdout (default).",
    ),
    since: str = typer.Option(
        None,
        "--since",
        help="Earliest session date in YYYY-MM-DD (inclusive). Omit for no lower bound.",
    ),
    until: str = typer.Option(
        None,
        "--until",
        help="Latest session date in YYYY-MM-DD (inclusive). Omit for no upper bound.",
    ),
    sha256_sidecar: bool = typer.Option(
        False,
        "--sha256-sidecar",
        help="Also write <output>.sha256 with one hex digest per output line.",
    ),
    repo_root: str = typer.Option(
        ".",
        "--repo-root",
        help="Directory containing .graqle/governance/audit/ (default: cwd).",
    ),
) -> None:
    """Export the on-disk audit trail as JSONL evidence for Article 12.

    Each output line is one audit session, re-serialised with
    ``sort_keys=True`` for deterministic byte ordering. The session
    fields themselves are unchanged from on-disk (no redaction beyond
    what's already in the live audit log).

    Exit codes:
      0 — export succeeded (even if zero sessions were in range).
      2 — bad input (malformed --since/--until, sidecar without --output,
          unwritable output path).
      3 — corrupt audit session on disk (export aborted at that session).

    \b
    Examples:
        graq compliance export                                  # all sessions to stdout
        graq compliance export -o evidence.jsonl                # to file
        graq compliance export --since 2026-08-01 --until 2026-08-31 \\
            -o august.jsonl --sha256-sidecar                    # monthly evidence + sidecar
    """
    since_prefix = _parse_iso_date_bound(since, "since") if since else None
    until_prefix = _parse_iso_date_bound(until, "until") if until else None
    if since_prefix and until_prefix and since_prefix > until_prefix:
        raise typer.BadParameter(
            f"--since ({since}) must be on or before --until ({until})."
        )

    if sha256_sidecar and output == "-":
        # Sidecar requires a real file path so we know where to put it.
        console.print(
            "[red]--sha256-sidecar requires --output to be a file path (not '-').[/red]"
        )
        raise typer.Exit(2)

    safe_root = Path(repo_root).expanduser()
    audit_dir = safe_root / ".graqle" / "governance" / "audit"

    sidecar_lines: list[str] = []
    session_count = 0

    # Build the output writer. We accumulate to a list first for sidecar
    # consistency, then commit to disk/stdout. For very large exports
    # this could be streamed; for v1 we accept the in-memory cost since
    # Article-12 evidence is typically a single-day batch.
    import sys
    output_lines: list[str] = []
    try:
        for sid, line in _stream_audit_sessions(
            audit_dir, since_prefix, until_prefix
        ):
            output_lines.append(line)
            if sha256_sidecar:
                sidecar_lines.append(_sha256_hex(line))
            session_count += 1
    except OSError as exc:
        console.print(f"[red]Audit export failed: {exc}[/red]")
        raise typer.Exit(3) from exc

    if output == "-":
        sys.stdout.write("\n".join(output_lines))
        if output_lines:
            sys.stdout.write("\n")
        sys.stdout.flush()
    else:
        out_path = Path(output).expanduser()
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                ("\n".join(output_lines) + ("\n" if output_lines else "")),
                encoding="utf-8",
            )
        except OSError as exc:
            console.print(
                f"[red]Cannot write --output {output!r}: {exc}[/red]"
            )
            raise typer.Exit(2) from exc
        if sha256_sidecar:
            sidecar_path = out_path.with_suffix(out_path.suffix + ".sha256")
            try:
                sidecar_path.write_text(
                    ("\n".join(sidecar_lines) + ("\n" if sidecar_lines else "")),
                    encoding="utf-8",
                )
            except OSError as exc:
                console.print(
                    f"[red]Cannot write sidecar {sidecar_path}: {exc}[/red]"
                )
                raise typer.Exit(2) from exc

    # Diagnostic — only when writing to a file (don't pollute stdout
    # of the JSONL stream).
    if output != "-":
        sidecar_note = " + sha256 sidecar" if sha256_sidecar else ""
        console.print(
            f"[green]Exported {session_count} session(s) to {output}"
            f"{sidecar_note}.[/green]"
        )


# ---------------------------------------------------------------------------
# PR-010d — `graq compliance baseline-doc generate` (CG-MKT-02 / Q16.1)
# ---------------------------------------------------------------------------


baseline_doc_app = typer.Typer(
    name="baseline-doc",
    help="VERITAS Q16.1 baseline-document operations (EU AI Act Article 11).",
    no_args_is_help=True,
)
compliance_app.add_typer(baseline_doc_app)


@baseline_doc_app.command(name="generate")
def baseline_doc_generate_command(
    output: str = typer.Option(
        ...,
        "--output",
        "-o",
        help="Output file path (JSONL by default, PDF when --format pdf).",
    ),
    signoff: str = typer.Option(
        None,
        "--signoff",
        help="Email or identity of the human operator countersigning the artefact.",
    ),
    output_format: str = typer.Option(
        "jsonl",
        "--format",
        "-f",
        help="Output format: jsonl (default, append-only) or pdf (requires reportlab).",
    ),
    test_archive_ref: str = typer.Option(
        None,
        "--test-archive-ref",
        help="SHA-256 of the CI test-run record (operator-supplied via CI).",
    ),
) -> None:
    """Generate a fresh VERITAS Q16.1 baseline document.

    Produces a dated, version-pinned baseline document with quantitative
    metrics + test archive ref + version records + optional stakeholder
    sign-off. Maps to EU AI Act Article 11 + ISO 42001 Cl. 6.2.

    The artefact is content-addressed: identical SDK version + identical
    metrics produce the same ``baseline_id`` (a SHA-256 hex digest).

    See ``docs/compliance/eu-ai-act/baseline-document-schema.md`` for the
    full schema and regulatory mapping.
    """
    from graqle.compliance.baseline_doc import (
        build_baseline_document,
        to_jsonl,
        to_pdf,
    )

    fmt = output_format.strip().lower()
    if fmt not in ("jsonl", "pdf"):
        console.print(
            f"[red]Invalid --format {output_format!r}; "
            f"expected 'jsonl' or 'pdf'.[/red]"
        )
        raise typer.Exit(2)

    doc = build_baseline_document(
        signoff=signoff,
        test_archive_ref=test_archive_ref,
    )

    out_path = Path(output).expanduser()
    if fmt == "jsonl":
        to_jsonl(doc, out_path)
    else:  # pdf
        try:
            to_pdf(doc, out_path)
        except RuntimeError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(2) from exc

    signoff_str = f" (signoff: {signoff})" if signoff else " (unsigned)"
    console.print(
        f"[green]baseline_id={doc.baseline_id[:16]}… written to "
        f"{out_path}{signoff_str}.[/green]"
    )


# ---------------------------------------------------------------------------
# PR-010e — `graq compliance periodic-assessment run` (CG-MKT-03 / Q16.3)
# ---------------------------------------------------------------------------


periodic_assessment_app = typer.Typer(
    name="periodic-assessment",
    help="VERITAS Q16.3 periodic-assessment operations (EU AI Act Article 9 + ISO 42001 Cl. 9.1).",
    no_args_is_help=True,
)
compliance_app.add_typer(periodic_assessment_app)


@periodic_assessment_app.command(name="run")
def periodic_assessment_run_command(
    period_start: str = typer.Option(
        ...,
        "--period-start",
        help="Window start as ISO 8601 (e.g. 2026-06-01T00:00:00Z).",
    ),
    period_end: str = typer.Option(
        ...,
        "--period-end",
        help="Window end as ISO 8601 (exclusive).",
    ),
    cadence: str = typer.Option(
        "monthly",
        "--cadence",
        help="Cadence label: monthly | quarterly | annual.",
    ),
    traces_file: str = typer.Option(
        None,
        "--traces-file",
        help="Path to JSONL trace corpus. When omitted, an empty corpus is assumed (the assessment will report n_calls=0).",
    ),
    baseline_id: str = typer.Option(
        "",
        "--baseline-id",
        help="SHA-256 of the most recent Q16.1 baseline document (AC-Q163-6).",
    ),
    output: str = typer.Option(
        ...,
        "--output",
        "-o",
        help="Output file path (JSONL).",
    ),
) -> None:
    """Generate a VERITAS Q16.3 periodic-assessment artefact.

    Reads R18 trace corpus (or operator-supplied JSONL), computes
    quality metrics + remediation candidates per R25-EU04 § Q16.3,
    emits JSONL artefact linked to the most recent baseline_id.
    """
    from graqle.compliance.periodic_assessment import (
        assess_window,
        to_jsonl,
    )

    cadence_clean = cadence.strip().lower()
    if cadence_clean not in ("monthly", "quarterly", "annual"):
        console.print(
            f"[red]Invalid --cadence {cadence!r}; expected "
            f"monthly | quarterly | annual.[/red]"
        )
        raise typer.Exit(2)

    # Load traces from JSONL when supplied.
    traces: list = []
    if traces_file:
        tp = Path(traces_file).expanduser()
        if not tp.exists():
            console.print(f"[red]Traces file not found: {tp}[/red]")
            raise typer.Exit(2)
        try:
            with tp.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    traces.append(json.loads(line))
        except (OSError, json.JSONDecodeError) as exc:
            console.print(f"[red]Cannot parse traces file: {exc}[/red]")
            raise typer.Exit(2) from exc

    assessment = assess_window(
        traces=traces,
        period_start_iso=period_start,
        period_end_iso=period_end,
        cadence=cadence_clean,
        baseline_id=baseline_id,
    )
    out_path = Path(output).expanduser()
    to_jsonl(assessment, out_path)
    console.print(
        f"[green]assessment_id={assessment.assessment_id[:16]}… "
        f"({assessment.n_calls} calls, "
        f"{len(assessment.remediation_actions)} remediation candidates) "
        f"written to {out_path}.[/green]"
    )


# ---------------------------------------------------------------------------
# PR-010e — `graq compliance feedback record` + `feedback ingest` (CG-MKT-04 / Q16.5)
# ---------------------------------------------------------------------------


feedback_app = typer.Typer(
    name="feedback",
    help="VERITAS Q16.5 feedback-trend operations (OBSERVATION ONLY per Q-PATENT 2026-05-22).",
    no_args_is_help=True,
)
compliance_app.add_typer(feedback_app)


@feedback_app.command(name="record")
def feedback_record_command(
    rating: float = typer.Option(
        ...,
        "--rating",
        "-r",
        help="Numeric rating (typically 1.0..5.0).",
    ),
    session_id: str = typer.Option(
        None,
        "--session-id",
        help="GraQle session ID for cross-linking.",
    ),
    note: str = typer.Option(
        None,
        "--note",
        help="Free-text note (max 4096 chars).",
    ),
    output: str = typer.Option(
        ".graqle/feedback/feedback.jsonl",
        "--output",
        "-o",
        help="Output JSONL log (append-only).",
    ),
) -> None:
    """Record a feedback observation (AC-Q165-1).

    Writes a :class:`~graqle.compliance.evidence_state.FeedbackRecord`
    to the append-only log. Observation-only — does NOT trigger any
    recalibration or pipeline state change per the Q-PATENT 2026-05-22
    boundary.
    """
    from graqle.compliance.evidence_state import (
        FeedbackRecord,
        append_feedback_record,
    )
    from datetime import datetime, timezone

    rec = FeedbackRecord(
        source="explicit_cli",
        rating=float(rating),
        timestamp_iso=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        session_id=session_id,
        note=note,
    )
    try:
        append_feedback_record(rec, Path(output).expanduser())
    except (TypeError, ValueError) as exc:
        console.print(f"[red]Invalid feedback record: {exc}[/red]")
        raise typer.Exit(2) from exc
    console.print(
        f"[green]Recorded explicit_cli rating={rating} to {output}.[/green]"
    )


@feedback_app.command(name="ingest")
def feedback_ingest_command(
    input_file: str = typer.Option(
        ...,
        "--file",
        "-f",
        help="Path to JSONL input with external feedback records.",
    ),
    output: str = typer.Option(
        ".graqle/feedback/feedback.jsonl",
        "--output",
        "-o",
        help="Output JSONL log to append to.",
    ),
) -> None:
    """Ingest external feedback JSONL (AC-Q165-2)."""
    from graqle.compliance.evidence_state import ingest_feedback_jsonl

    try:
        records = ingest_feedback_jsonl(
            Path(input_file).expanduser(),
            Path(output).expanduser(),
        )
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    except ValueError as exc:
        console.print(f"[red]Invalid feedback JSONL: {exc}[/red]")
        raise typer.Exit(2) from exc
    console.print(
        f"[green]Ingested {len(records)} record(s) from {input_file} "
        f"into {output}.[/green]"
    )


# ---------------------------------------------------------------------------
# PR-010f — `graq compliance eur-lex-check` + `eur-lex-refresh` (CG-MKT-06)
# ---------------------------------------------------------------------------


@compliance_app.command(name="eur-lex-check")
def eur_lex_check_command(
    docs_dir: str = typer.Option(
        "docs/compliance",
        "--docs-dir",
        help="Root directory containing markdown files that reference EUR-Lex URLs.",
    ),
    baseline: str = typer.Option(
        ".graqle/eur-lex-baseline.json",
        "--baseline",
        help="Path to the committed baseline JSON file.",
    ),
    offline: bool = typer.Option(
        False,
        "--offline",
        help="Skip network fetches (air-gapped operators).",
    ),
) -> None:
    """Check EUR-Lex authoritative-source drift vs the committed baseline.

    Per CG-MKT-06. Runs weekly in CI. Returns exit 1 when any EUR-Lex
    URL referenced in compliance docs has drifted vs the baseline,
    so the compliance team can review the regulator-side change before
    a customer audit team notices a stale citation.
    """
    from graqle.compliance.eur_lex_guard import check_drift

    report = check_drift(
        search_roots=[Path(docs_dir).expanduser()],
        baseline_path=Path(baseline).expanduser(),
        offline=offline,
    )
    sys.stdout.write(json.dumps(report.to_dict(), indent=2) + "\n")
    if report.has_drift:
        console.print(
            f"[red]EUR-Lex drift detected: {report.n_drifted} drifted, "
            f"{report.n_missing_from_baseline} new, "
            f"{report.n_missing_from_current} removed, "
            f"{report.n_fetch_errors} fetch errors.[/red]"
        )
        raise typer.Exit(1)
    console.print(
        f"[green]No EUR-Lex drift. "
        f"{report.n_unchanged}/{report.n_urls_checked} URLs verified.[/green]"
    )


# ---------------------------------------------------------------------------
# v0.57.0 — `graq compliance switch` (single-source UX for the EU AI Act toggle)
# ---------------------------------------------------------------------------


switch_app = typer.Typer(
    name="switch",
    help=(
        "EU AI Act mode switch — consolidated status across every "
        "compliance subsystem (Article 14, Article 50, claim-limits, "
        "baseline-doc, periodic-assessment, feedback-trend, EUR-Lex guard)."
    ),
    no_args_is_help=True,
)
compliance_app.add_typer(switch_app)


_SWITCH_ENV_VAR: str = "GRAQLE_EU_AI_ACT_MODE"
_DISCLOSURE_ENV_VAR: str = "GRAQLE_AI_DISCLOSURE"


@switch_app.command(name="status")
def switch_status_command(
    output_format: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format: text (human-readable) or json (machine-readable).",
    ),
) -> None:
    """Show the consolidated EU AI Act mode posture.

    Surfaces all 7 EU-AI-Act-aware subsystems in one envelope:
    Article 50 disclosure, Article 14 human-review gate, R25-EU11
    claim-limits, VERITAS Q16.1 baseline-doc, Q16.3 periodic-assessment,
    Q16.5 OBSERVATION-ONLY feedback-trend, EUR-Lex drift guard.
    """
    from graqle.compliance.switch_status import build_switch_status

    status = build_switch_status()

    fmt = output_format.strip().lower()
    if fmt == "json":
        sys.stdout.write(json.dumps(status, indent=2, sort_keys=True) + "\n")
        return
    if fmt != "text":
        console.print(
            f"[red]Invalid --format {output_format!r}; "
            f"expected 'text' or 'json'.[/red]"
        )
        raise typer.Exit(2)

    # Rich text rendering.
    master = status["master_switch"]
    is_on = master["is_on"]
    mode_color = "green" if is_on else "yellow"
    mode_label = "ON" if is_on else "OFF (default)"

    console.print()
    console.print("[bold]GraQle EU AI Act mode switch[/bold]")
    console.print(
        f"  [bold]{_SWITCH_ENV_VAR}:[/bold] [{mode_color}]{mode_label}[/{mode_color}]"
    )
    raw = master["raw_value"]
    if raw:
        console.print(f"  Raw value: {raw!r}")
    console.print(
        f"  Truthy values accepted: "
        f"{', '.join(master['truthy_values_accepted'])}"
    )

    from rich.table import Table

    table = Table(title="EU AI Act subsystems", show_lines=False)
    table.add_column("Subsystem", style="cyan", no_wrap=True)
    table.add_column("Armed", style="white")
    table.add_column("Anchor", style="dim")

    subsystems = status["subsystems"]
    rows = [
        ("ai_disclosure", "article_50_user_disclosure"),
        ("article_14_human_review_gate", "article_14_human_review_gate"),
        ("claim_limits", "claim_limits_default_deny"),
        ("baseline_document", "veritas_q161_baseline_document"),
        ("periodic_assessment", "veritas_q163_periodic_assessment"),
        ("feedback_trend", "veritas_q165_feedback_trend"),
        ("eur_lex_drift_guard", "eur_lex_drift_guard"),
    ]
    for key, _ in rows:
        s = subsystems.get(key, {})
        if "status" in s:
            armed = f"[red]unavailable[/red]"
            anchor = s.get("error", "")[:60]
        else:
            armed_bool = s.get("armed", False)
            armed = (
                f"[green]ARMED[/green]" if armed_bool
                else f"[yellow]ready (env-gated)[/yellow]"
            )
            anchor = s.get("anchor", "")
        table.add_row(key, armed, anchor[:80])
    console.print(table)

    summary = status["summary"]
    console.print(
        f"\nSummary: {summary['subsystems_available']}/"
        f"{summary['subsystems_total']} subsystems available, "
        f"{summary['subsystems_armed_when_mode_on']} armed."
    )
    if not is_on:
        console.print(
            "\n[dim]Run `graq compliance switch on` to enable EU AI Act mode "
            "for this shell session.[/dim]"
        )


@switch_app.command(name="on")
def switch_on_command(
    eval_format: str = typer.Option(
        "posix",
        "--shell",
        help="Shell dialect for the eval snippet: posix (bash/zsh) | powershell | cmd.",
    ),
) -> None:
    """Print a shell snippet that turns EU AI Act mode ON for this session.

    The mode is controlled by the ``GRAQLE_EU_AI_ACT_MODE`` environment
    variable. This command does NOT modify your shell directly (that
    requires ``eval`` / ``source``) — it emits a snippet for you to
    apply, then verifies what the snippet *would* set.

    Usage:

        eval "$(graq compliance switch on)"           # bash/zsh
        graq compliance switch on --shell powershell | Out-String | Invoke-Expression   # PowerShell
    """
    dialect = eval_format.strip().lower()
    if dialect == "posix":
        sys.stdout.write(f'export {_SWITCH_ENV_VAR}=on\n')
    elif dialect == "powershell":
        sys.stdout.write(f'$env:{_SWITCH_ENV_VAR} = "on"\n')
    elif dialect == "cmd":
        sys.stdout.write(f'set {_SWITCH_ENV_VAR}=on\n')
    else:
        console.print(
            f"[red]Unknown --shell {eval_format!r}; "
            f"expected posix | powershell | cmd.[/red]"
        )
        raise typer.Exit(2)
    console.print(
        f"[dim]# Apply with: eval \"$(graq compliance switch on)\" (bash/zsh) "
        f"or pipe to Invoke-Expression (PowerShell).[/dim]",
    )


@switch_app.command(name="off")
def switch_off_command(
    eval_format: str = typer.Option(
        "posix",
        "--shell",
        help="Shell dialect for the eval snippet: posix (bash/zsh) | powershell | cmd.",
    ),
) -> None:
    """Print a shell snippet that turns EU AI Act mode OFF for this session.

    Symmetric to ``graq compliance switch on``.
    """
    dialect = eval_format.strip().lower()
    if dialect == "posix":
        sys.stdout.write(f'unset {_SWITCH_ENV_VAR}\n')
    elif dialect == "powershell":
        sys.stdout.write(f'Remove-Item Env:{_SWITCH_ENV_VAR} -ErrorAction SilentlyContinue\n')
    elif dialect == "cmd":
        sys.stdout.write(f'set {_SWITCH_ENV_VAR}=\n')
    else:
        console.print(
            f"[red]Unknown --shell {eval_format!r}; "
            f"expected posix | powershell | cmd.[/red]"
        )
        raise typer.Exit(2)


@compliance_app.command(name="eur-lex-refresh")
def eur_lex_refresh_command(
    docs_dir: str = typer.Option(
        "docs/compliance",
        "--docs-dir",
        help="Root directory to scan for EUR-Lex URLs.",
    ),
    baseline: str = typer.Option(
        ".graqle/eur-lex-baseline.json",
        "--baseline",
        help="Path to write the refreshed baseline JSON.",
    ),
    offline: bool = typer.Option(
        False,
        "--offline",
        help="Skip network fetches and write an empty baseline.",
    ),
) -> None:
    """Refresh the EUR-Lex baseline (operator review then commit).

    Per CG-MKT-06. Run this after a human has reviewed the drift report
    from ``eur-lex-check`` and confirmed that the regulator-side change
    is acceptable (or that the docs have been updated to track it).
    Bakes the new content hashes into the baseline file.
    """
    from graqle.compliance.eur_lex_guard import refresh_baseline

    entries, errors = refresh_baseline(
        search_roots=[Path(docs_dir).expanduser()],
        baseline_path=Path(baseline).expanduser(),
        offline=offline,
    )
    if errors:
        for url, err in errors:
            console.print(f"[yellow]fetch failed: {url} → {err}[/yellow]")
    console.print(
        f"[green]EUR-Lex baseline written: "
        f"{len(entries)} URL(s) hashed, "
        f"{len(errors)} fetch error(s).[/green]"
    )
