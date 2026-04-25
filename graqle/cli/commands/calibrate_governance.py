# ------------------------------------------------------------------
# PATENT NOTICE -- Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Application EP26166054.2 (Divisional, Claims F-J), owned by
# Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: support@quantamixsolutions.com
# ------------------------------------------------------------------

"""GraQle governance calibration CLI (R20 ADR-203).

Provides ``graq calibrate-governance`` commands for audit-grade
calibration of governance scores against real outcomes.

Subcommands:
    fit         Fit calibration model from (score, outcome) pairs
    status      Show current calibration model status and ECE
    predict     Predict calibrated risk for a given score
    diagram     Export reliability diagram as SVG
    versions    List all calibration versions

This is separate from ``graq calibrate`` (R11 reasoning calibration)
to avoid collision with existing CLI surface.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from graqle.governance.calibration import Calibrator, MIN_SAMPLES
from graqle.governance.calibration_store import CalibrationStore
from graqle.governance.reliability_diagram import generate_svg

calibrate_governance_app = typer.Typer(
    name="calibrate-governance",
    help="R20 AGGC: Audit-grade governance score calibration.",
    no_args_is_help=True,
)


@calibrate_governance_app.command("fit")
def fit_command(
    pairs_file: Path = typer.Argument(
        ...,
        help="JSONL file with {score, outcome} pairs (one per line).",
    ),
    method: str = typer.Option(
        "isotonic",
        help="Calibration method: platt or isotonic (default).",
    ),
    bootstrap_b: int = typer.Option(
        100,
        help="Bootstrap samples for confidence intervals (0 to skip).",
    ),
    output_dir: Path = typer.Option(
        Path(".graqle/calibration"),
        help="Directory to save calibration model.",
    ),
    seed: Optional[int] = typer.Option(None, help="Random seed."),
) -> None:
    """Fit a calibration model from (score, outcome) pairs."""
    if not pairs_file.exists():
        typer.secho(f"File not found: {pairs_file}", fg=typer.colors.RED)
        raise typer.Exit(1)

    pairs: list[tuple[float, int]] = []
    with open(pairs_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            score = float(data["score"])
            outcome = int(data["outcome"])
            pairs.append((score, outcome))

    typer.echo(f"Loaded {len(pairs)} (score, outcome) pairs")

    if len(pairs) < MIN_SAMPLES:
        typer.secho(
            f"Warning: only {len(pairs)} pairs provided, minimum is {MIN_SAMPLES}",
            fg=typer.colors.YELLOW,
        )

    cal = Calibrator()
    model = cal.fit(pairs, method=method, bootstrap_b=bootstrap_b, seed=seed)

    store = CalibrationStore(store_dir=output_dir)
    path = store.save(model)

    typer.echo(f"Status:  {model.status}")
    typer.echo(f"Method:  {model.method}")
    typer.echo(f"N:       {model.n_samples}")
    if model.ece is not None:
        typer.echo(f"ECE:     {model.ece:.4f}")
        color = typer.colors.GREEN if model.ece_passed else typer.colors.YELLOW
        typer.secho(
            f"Target:  < {model.target_ece} ({'PASS' if model.ece_passed else 'FAIL'})",
            fg=color,
        )
    typer.echo(f"Saved:   {path}")


@calibrate_governance_app.command("status")
def status_command(
    store_dir: Path = typer.Option(
        Path(".graqle/calibration"),
        help="Directory containing calibration models.",
    ),
) -> None:
    """Show current calibration model status."""
    store = CalibrationStore(store_dir=store_dir)
    current = store.load_current()
    if current is None:
        typer.secho("No active calibration model", fg=typer.colors.YELLOW)
        versions = store.list_versions()
        if versions:
            typer.echo(f"Available versions: {len(versions)}")
        raise typer.Exit(0)

    typer.echo(f"Version: {current.version}")
    typer.echo(f"Status:  {current.status}")
    typer.echo(f"Method:  {current.method}")
    typer.echo(f"N:       {current.n_samples}")
    if current.ece is not None:
        typer.echo(f"ECE:     {current.ece:.4f}")
    typer.echo(f"Created: {current.created_at}")


@calibrate_governance_app.command("predict")
def predict_command(
    score: float = typer.Argument(..., help="Governance score (0-100)."),
    store_dir: Path = typer.Option(
        Path(".graqle/calibration"),
        help="Directory containing calibration models.",
    ),
) -> None:
    """Predict calibrated risk for a governance score."""
    store = CalibrationStore(store_dir=store_dir)
    model = store.load_current()
    if model is None:
        typer.secho("No active calibration model", fg=typer.colors.RED)
        raise typer.Exit(1)

    cal = Calibrator()
    cal.load_model(model)
    prediction = cal.predict(score)

    typer.echo(f"Score:    {prediction.score}")
    typer.echo(f"Risk:     {prediction.risk:.4f}")
    if prediction.ci_lower is not None:
        typer.echo(f"CI:       [{prediction.ci_lower:.4f}, {prediction.ci_upper:.4f}]")
    typer.echo(f"Status:   {prediction.status}")


@calibrate_governance_app.command("diagram")
def diagram_command(
    output: Path = typer.Argument(..., help="Output SVG file path."),
    version: Optional[str] = typer.Option(
        None,
        help="Specific version to plot (default: current).",
    ),
    store_dir: Path = typer.Option(
        Path(".graqle/calibration"),
        help="Directory containing calibration models.",
    ),
) -> None:
    """Export reliability diagram as SVG."""
    store = CalibrationStore(store_dir=store_dir)
    if version:
        model = store.load(version)
    else:
        model = store.load_current()
    if model is None:
        typer.secho("No calibration model found", fg=typer.colors.RED)
        raise typer.Exit(1)

    svg = generate_svg(model)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg, encoding="utf-8")
    typer.secho(f"Reliability diagram written: {output}", fg=typer.colors.GREEN)


@calibrate_governance_app.command("versions")
def versions_command(
    store_dir: Path = typer.Option(
        Path(".graqle/calibration"),
        help="Directory containing calibration models.",
    ),
) -> None:
    """List all calibration versions."""
    store = CalibrationStore(store_dir=store_dir)
    versions = store.list_versions()
    if not versions:
        typer.echo("No calibration versions found")
        return

    typer.echo(f"{'Version':<20} {'Method':<10} {'Status':<15} {'N':<8} {'ECE':<8}")
    typer.echo("-" * 70)
    for v in versions:
        ece_str = f"{v.get('ece', 0):.4f}" if v.get("ece") is not None else "N/A"
        typer.echo(
            f"{v.get('version', '')[:18]:<20} "
            f"{v.get('method', ''):<10} "
            f"{v.get('status', ''):<15} "
            f"{v.get('n_samples', 0):<8} "
            f"{ece_str:<8}"
        )
