"""GraQle calibration CLI — fit calibrators against benchmarks and inspect state.

Provides ``graq calibrate run`` and ``graq calibrate status`` subcommands.
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.calibrate
# risk: MEDIUM (impact radius: 3 modules)
# consumers: graqle.cli.main
# dependencies: __future__, collections, json, pathlib, pickle, re, typing, numpy, typer
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import pickle
import re
from collections import Counter
from pathlib import Path
from typing import Any, Optional

import numpy as np
import typer

from graqle.calibration.benchmark import load_benchmark
from graqle.calibration.methods import create_calibrator
from graqle.calibration.metrics import compute_brier_score, compute_ece, compute_mce
from graqle.config.settings import CalibrationConfig

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_METHODS: set[str] = {"platt", "isotonic", "temperature"}

# ---------------------------------------------------------------------------
# Typer app
# ---------------------------------------------------------------------------

calibrate_app = typer.Typer(
    name="calibrate",
    help="Confidence calibration — fit, evaluate, and inspect calibrators.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitize_benchmark_name(raw: str) -> str:
    """Return a filesystem-safe benchmark name derived from *raw*."""
    sanitized = re.sub(r"[^a-zA-Z0-9_\-]", "_", raw)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized[:80] or "unnamed"


def _band_distribution_table(questions: list[Any]) -> str:
    """Build a compact ASCII table of expected-band counts."""
    counts: Counter[int] = Counter()
    for q in questions:
        counts[q.expected_band] += 1

    total = len(questions) or 1
    lines: list[str] = []
    lines.append("Band | Count |   Pct")
    lines.append("-----|-------|------")
    for band in sorted(counts):
        count = counts[band]
        pct = count / total * 100
        lines.append(f"  {band}  | {count:>5} | {pct:5.1f}%")
    lines.append(f"Total| {len(questions):>5} |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------


@calibrate_app.command("run")
def run(
    benchmark_path: str = typer.Argument(
        ...,
        help="Path to the calibration benchmark file (YAML).",
    ),
    method: str = typer.Option(
        "temperature",
        "--method",
        "-m",
        help=f"Calibration method. Valid: {', '.join(sorted(VALID_METHODS))}.",
    ),
    n_bins: int = typer.Option(
        7,
        "--bins",
        "-b",
        help="Number of bins for ECE / MCE computation.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Load benchmark and show stats without fitting.",
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="Path to write the JSON report.",
    ),
) -> None:
    """Fit a calibrator on a benchmark and produce a calibration report."""

    # ── Validate method ──
    if method not in VALID_METHODS:
        typer.echo(
            f"Error: Invalid method '{method}'. "
            f"Valid methods: {', '.join(sorted(VALID_METHODS))}",
            err=True,
        )
        raise typer.Exit(code=1)

    if n_bins < 2:
        typer.echo("Error: --bins must be >= 2", err=True)
        raise typer.Exit(code=1)

    # ── Load benchmark ──
    bp = Path(benchmark_path)
    if not bp.exists():
        typer.echo(f"Error: Benchmark file not found: {bp}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Loading benchmark from {bp} …")
    try:
        benchmark = load_benchmark(str(bp))
    except Exception as exc:
        typer.echo(f"Error: Failed to load benchmark: {exc}", err=True)
        raise typer.Exit(code=1)
    questions = benchmark.questions

    # ── Empty guard ──
    if not questions:
        typer.echo("Error: Benchmark contains no questions.", err=True)
        raise typer.Exit(code=1)

    sanitized_name = _sanitize_benchmark_name(bp.stem)
    typer.echo(f"Benchmark: {sanitized_name}  ({len(questions)} questions)")

    # ── Band distribution ──
    typer.echo("")
    typer.echo(_band_distribution_table(questions))
    typer.echo("")

    # ── Dry-run exits here ──
    if dry_run:
        typer.echo("[dry-run] Validation complete — no calibration performed.")
        raise typer.Exit(code=0)

    # ── Synthetic placeholder ──
    typer.echo(
        "WARNING: No live reasoning backend — using synthetic placeholder scores.",
    )

    rng = np.random.default_rng(42)
    n = len(questions)
    raw_confidences: np.ndarray = rng.uniform(0.1, 0.95, size=n).astype(np.float64)
    correctness: np.ndarray = np.array(
        [1.0 if q.is_answerable else 0.0 for q in questions],
        dtype=np.float64,
    )

    # ── Fit calibrator ──
    typer.echo(f"Fitting calibrator: {method} …")
    calibrator = create_calibrator(method)
    calibrator.fit(raw_confidences, correctness)

    # ── Calibrate each confidence ──
    calibrated: np.ndarray = np.array(
        [calibrator.calibrate(float(c)) for c in raw_confidences],
        dtype=np.float64,
    )

    # ── Metrics ──
    ece_value, reliability = compute_ece(calibrated, correctness, n_bins)
    mce_value = compute_mce(calibrated, correctness, n_bins)
    brier_value = compute_brier_score(calibrated, correctness)

    typer.echo("")
    typer.echo("── Calibration Metrics ──")
    typer.echo(f"  ECE  : {ece_value:.6f}")
    typer.echo(f"  MCE  : {mce_value:.6f}")
    typer.echo(f"  Brier: {brier_value:.6f}")
    typer.echo("")

    # ── Build report ──
    report: dict[str, Any] = {
        "synthetic": True,
        "benchmark": sanitized_name,
        "method": method,
        "n_questions": n,
        "n_bins": n_bins,
        "ece": float(ece_value),
        "mce": float(mce_value),
        "brier": float(brier_value),
        "band_distribution": dict(Counter(q.expected_band for q in questions)),
        "reliability": {
            str(k): {"accuracy": v[0], "confidence": v[1], "count": v[2]}
            for k, v in reliability.items()
        },
    }

    # ── Persist state ──
    config = CalibrationConfig()
    persist_path = Path(config.persist_path)
    persist_path.parent.mkdir(parents=True, exist_ok=True)

    state: dict[str, Any] = {
        "method": method,
        "benchmark": sanitized_name,
        "n_questions": n,
        "ece": float(ece_value),
        "mce": float(mce_value),
        "brier": float(brier_value),
        "synthetic": True,
    }
    with open(persist_path, "wb") as fh:
        pickle.dump(state, fh)
    typer.echo(f"Calibration state persisted to {persist_path}")

    # ── Optional JSON output ──
    if output is not None:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, default=str))
        typer.echo(f"Report written to {out_path}")

    # ── Synthetic → non-zero exit ──
    raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------


@calibrate_app.command("status")
def status(
    state_path: Optional[str] = typer.Option(
        None,
        "--state",
        "-s",
        help="Path to persisted calibration state (pickle). "
        "Defaults to CalibrationConfig.persist_path.",
    ),
) -> None:
    """Show the current calibration status from persisted state."""
    config = CalibrationConfig()
    path = Path(state_path) if state_path else Path(config.persist_path)

    if not path.exists():
        typer.echo(f"No calibration state found at {path}")
        raise typer.Exit(code=0)

    try:
        with open(path, "rb") as fh:
            state: dict[str, Any] = pickle.load(fh)  # noqa: S301
    except Exception as exc:
        typer.echo(f"Error reading calibration state: {exc}", err=True)
        raise typer.Exit(code=1)

    typer.echo("── Calibration State ──")
    typer.echo(f"  Method    : {state.get('method', 'unknown')}")
    typer.echo(f"  Benchmark : {state.get('benchmark', 'unknown')}")
    typer.echo(f"  Questions : {state.get('n_questions', 'N/A')}")
    typer.echo(f"  ECE       : {state.get('ece', 'N/A')}")
    typer.echo(f"  MCE       : {state.get('mce', 'N/A')}")
    typer.echo(f"  Brier     : {state.get('brier', 'N/A')}")
    typer.echo(f"  Synthetic : {state.get('synthetic', 'N/A')}")
    typer.echo(f"  State file: {path}")
