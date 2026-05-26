"""`graqle govern serve` — run the AnchoringWorker as a long-lived service (ADR-221 §4.4 / R2-PR2).

The CLI surface that turns the R2-PR1 :class:`AnchoringWorker` into a deployable process:

* loads :class:`AttestationConfig` from ``graqle.yaml`` (the existing loader),
* assembles the **shipped** Layer 5 parts (``Committer`` + ``WalBatcher`` + optional
  ``RekorAnchor`` + optional ``LocalReplayQueue``) per config,
* installs SIGINT/SIGTERM handlers that cooperatively stop the worker so the loop's
  bounded shutdown-flush runs (a hung Rekor at shutdown cannot block exit),
* writes PID + version files under ``.graqle/`` so other tooling can detect the process
  (mirrors ``graq mcp serve``),
* blocks on :meth:`AnchoringWorker.run` until ``stop()`` or fatal error.

``--once`` runs a single tick (one flush + one replay-drain) and exits — useful for
cron, healthchecks, or a one-shot manual catch-up after an outage.

No new cryptography; this module is pure assembly + lifecycle. The fail-closed
``fail_open_on_anchor_error`` invariant is enforced by ``AnchoringWorker.__init__``;
the CLI surfaces the message cleanly so a misconfig dies at startup, not silently
at the first outage.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

logger = logging.getLogger("graqle.cli.govern_serve")
console = Console()

govern_app = typer.Typer(
    name="govern",
    help="Runtime governance services — continuously anchor the Layer 5 audit trail.",
    no_args_is_help=True,
)

__all__ = ["govern_app", "govern_serve"]


def _build_worker(config_path: str) -> Any:
    """Load config + assemble Committer/queue/worker. Isolated so tests can patch it.

    Returns the :class:`AnchoringWorker`. Raises ``typer.Exit(1)`` on missing config or
    when the attestation block is disabled / misconfigured (the worker enforces the
    fail-closed precondition; we surface its message and exit cleanly).
    """
    # Local imports keep CLI startup cheap and let tests stub these without import-time work.
    from graqle.config.settings import GraqleConfig
    from graqle.governance.tamper_evidence.batcher import WalBatcher
    from graqle.governance.tamper_evidence.committer import Committer
    from graqle.governance.tamper_evidence.worker import AnchoringWorker, WorkerError

    cfg_path = Path(config_path)
    if not cfg_path.is_file():
        console.print(f"[red]✗ Config not found:[/red] {cfg_path}", style=None)
        raise typer.Exit(1)

    try:
        gcfg = GraqleConfig.from_yaml(cfg_path)
    except Exception as exc:  # noqa: BLE001 - surface the validation error cleanly
        console.print(f"[red]✗ Failed to load {cfg_path}:[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(1)

    att = gcfg.attestation
    if not att.enabled:
        console.print(
            "[yellow]⚠ attestation.enabled is false in graqle.yaml; "
            "the anchoring worker has nothing to do.[/yellow]\n"
            "  Enable Layer 5 first (set attestation.enabled: true)."
        )
        raise typer.Exit(2)

    # WAL lives under .graqle/attestation alongside the existing service files
    # (mcp.pid / govern.pid). Directory is created by WalBatcher.__init__.
    wal_root = Path(".graqle") / "attestation"
    batcher = WalBatcher(config=att, wal_root=wal_root)
    committer = Committer(config=att, batcher=batcher)

    # The worker's fail-closed precondition reads ``config.fail_open_on_anchor_error``
    # via getattr-with-default. On the real AttestationConfig that field lives under
    # ``.security``, so we surface it at the top level via a lightweight proxy so the
    # precondition fires correctly (refusing to start under a fail-open misconfig).
    worker_config = _WorkerConfigView(att)

    try:
        worker = AnchoringWorker(committer, worker_config)
    except WorkerError as exc:
        # Most likely the fail-closed precondition.
        console.print(f"[red]✗ AnchoringWorker refused to start:[/red] {exc}")
        raise typer.Exit(1)

    return worker


class _WorkerConfigView:
    """Flatten ``AttestationConfig`` for the AnchoringWorker's precondition.

    The worker reads ``config.fail_open_on_anchor_error`` and ``config.batch_max_seconds``
    via attribute access. On the shipped :class:`AttestationConfig` the first field lives
    nested under ``.security``; this view exposes both at the top level so the
    fail-closed startup invariant fires correctly in the deployed service.
    """

    __slots__ = ("_att",)

    def __init__(self, att: Any) -> None:
        self._att = att

    @property
    def batch_max_seconds(self) -> int:
        return int(self._att.batch_max_seconds)

    @property
    def fail_open_on_anchor_error(self) -> bool:
        sec = getattr(self._att, "security", None)
        if sec is None:
            return False
        return bool(getattr(sec, "fail_open_on_anchor_error", False))


def _write_pid_files(graqle_dir: Path) -> tuple[Path, Path]:
    """Write .graqle/govern.pid + .graqle/govern.version. Returns the two paths."""
    from graqle.__version__ import __version__

    graqle_dir.mkdir(exist_ok=True)
    pid_file = graqle_dir / "govern.pid"
    version_file = graqle_dir / "govern.version"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    version_file.write_text(__version__, encoding="utf-8")
    return pid_file, version_file


def _cleanup_pid_file(pid_file: Path) -> None:
    """Best-effort PID-file removal (atexit hook).

    A failure here should NEVER raise out of interpreter shutdown — at worst the file
    is left behind for the next start to overwrite. Hoisted to module scope so it is
    unit-testable (the atexit-registered inline closure is hard to exercise otherwise).
    """
    try:
        pid_file.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001 - shutdown path, never propagate
        pass


def _install_signal_handlers(worker: Any) -> None:
    """Install SIGINT (always) + SIGTERM (POSIX) handlers that cooperatively stop the worker.

    Each handler just calls ``worker.stop()`` — the run loop honours the stop event after
    the current tick, then runs the bounded shutdown-flush. Idempotent: a second signal
    is a no-op (stop() is idempotent).
    """

    def _handler(signum: int, _frame: Any) -> None:
        logger.info(
            "graqle.govern.signal_received",
            extra={"signum": int(signum)},
        )
        worker.stop()

    signal.signal(signal.SIGINT, _handler)
    # SIGTERM is POSIX-only — skip on Windows (no AttributeError, but the signal is unused).
    if hasattr(signal, "SIGTERM") and sys.platform != "win32":
        signal.signal(signal.SIGTERM, _handler)


@govern_app.command("serve")
def govern_serve(
    config: str = typer.Option(
        "graqle.yaml", "--config", "-c", help="Config file path (graqle.yaml)."
    ),
    once: bool = typer.Option(
        False, "--once", help="Run a single tick (one flush + one replay-drain) and exit."
    ),
    tick_seconds: float | None = typer.Option(
        None, "--tick-seconds",
        help="Override the loop interval (default: attestation.batch_max_seconds).",
    ),
) -> None:
    """Run the AnchoringWorker as a long-lived service.

    Reads ``graqle.yaml``, assembles the Layer 5 commit pipeline (Committer + Batcher
    over the shipped tamper_evidence module), and runs the AnchoringWorker until
    SIGINT/SIGTERM. The fail-closed ``fail_open_on_anchor_error`` invariant is
    enforced at startup — a misconfig refuses to run.

    Use ``--once`` for cron-style one-shot catch-ups (runs a single tick and exits).
    """
    worker = _build_worker(config)

    # Optional tick override (constructor default came from config; allow CLI override
    # for ops use where a tighter loop is wanted, e.g. catch-up after extended outage).
    if tick_seconds is not None:
        if tick_seconds <= 0:
            console.print("[red]✗ --tick-seconds must be > 0[/red]")
            raise typer.Exit(1)
        worker._tick_seconds = tick_seconds  # noqa: SLF001 - documented override path

    graqle_dir = Path(".graqle")
    pid_file, _ = _write_pid_files(graqle_dir)

    import atexit

    atexit.register(_cleanup_pid_file, pid_file)

    if once:
        # One-shot mode: run a single tick. No signal handlers (the process exits
        # immediately after) and no run-loop lifecycle.
        committed = worker.tick()
        h = worker.health()
        console.print(
            f"[green]✓ once: committed={committed} backfill={h.backfill_count} "
            f"queue_depth={h.replay_queue_depth}[/green]"
        )
        return

    _install_signal_handlers(worker)
    console.print(
        f"[bold]graqle govern serve[/bold] — tick_seconds={worker._tick_seconds}, "
        f"PID={os.getpid()} — Ctrl-C to stop"
    )
    try:
        worker.run()
    except KeyboardInterrupt:
        # Belt-and-braces: SIGINT handler should have called stop() already, but a
        # Windows console Ctrl-C delivery can race the signal handler.
        worker.stop()
    except Exception as exc:  # noqa: BLE001 - structured exit
        console.print(
            f"[red]✗ govern serve crashed:[/red] {type(exc).__name__}: {exc}",
            style=None,
        )
        raise typer.Exit(1)
    finally:
        h = worker.health()
        console.print(
            f"[dim]stopped — ticks={h.ticks} committed={h.records_committed} "
            f"backfill={h.backfill_count}[/dim]"
        )
