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

__all__ = ["govern_app", "govern_serve", "govern_health"]

# Filenames under .graqle/ — co-located with mcp.pid / govern.pid for operator tooling.
HEALTH_FILE_NAME = "govern.health.json"
PID_FILE_NAME = "govern.pid"


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


def _write_health_snapshot(health_file: Path, snapshot: dict[str, Any]) -> None:
    """Atomically write a health snapshot (tempfile + os.replace).

    Used by the serve loop after each tick so the `health` sub-command (and any
    external monitoring tool) can read a consistent, never-partial JSON file.

    The snapshot carries no PII — only counts, ticks, queue depth, exception TYPE
    names (R2-PR1 PII-safety verified) — so it is safe to write to the local
    operator-readable file. Cross-platform atomic via tempfile.NamedTemporaryFile +
    os.replace; if the write fails (full disk, permission), we surface the error
    type but never raise out of the serve loop (a missing snapshot is preferable to
    a crashed worker — the next tick will retry).
    """
    import json
    import tempfile

    health_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: str | None = None
    try:
        # Same directory as the destination so os.replace is atomic on all platforms.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(health_file.parent),
            prefix=health_file.name + ".",
            suffix=".tmp",
            delete=False,
        ) as fh:
            json.dump(snapshot, fh, default=str, sort_keys=True)
            tmp_path = fh.name
        os.replace(tmp_path, health_file)
        tmp_path = None  # successfully renamed; nothing to clean up
    except Exception as exc:  # noqa: BLE001 - never crash the serve loop on a snapshot write
        logger.error(
            "graqle.govern.health_snapshot_write_failed",
            extra={"error_type": type(exc).__name__},
        )
        # Defence in depth: remove an orphaned tempfile so repeated failures cannot
        # fill .graqle/ over time (sentinel-flagged disk-exhaustion vector).
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass  # the original write error is what the operator needs to see


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


def _build_health_writing_worker(base_worker: Any, health_file: Path) -> Any:
    """Wrap ``base_worker`` so each tick writes its health snapshot to ``health_file``.

    Subclassing keeps the R2-PR1 ``AnchoringWorker`` untouched (no new public API on the
    shipped class) and gives a clean Liskov substitution — the serve loop, signal
    handlers, and tests all interact with the worker through its existing surface.
    """
    from graqle.governance.tamper_evidence.worker import AnchoringWorker

    class _HealthWritingWorker(AnchoringWorker):
        """AnchoringWorker that snapshots health to disk after every tick."""

        def tick(self) -> int:  # type: ignore[override]
            committed = super().tick()
            try:
                _write_health_snapshot(health_file, self.health().to_dict())
            except Exception as exc:  # noqa: BLE001 - never let snapshot write crash the loop
                logger.error(
                    "graqle.govern.health_snapshot_tick_failed",
                    extra={"error_type": type(exc).__name__},
                )
            return committed

    # Re-class the existing worker instance in place so all the configuration and state
    # from _build_worker (config, replay queue, sink, lock state, counters) carry over.
    # Guarded: only swap when the base is actually an AnchoringWorker (production path).
    # Tests with stub workers (and any future caller injecting a non-AnchoringWorker for
    # tracing/mocking) skip the swap and lose only the periodic snapshot — the serve
    # loop still runs and the operator can still call `graqle govern health` against the
    # previous snapshot. Surfaces the skip in the log for observability, never silently.
    if isinstance(base_worker, AnchoringWorker):
        base_worker.__class__ = _HealthWritingWorker
    else:
        logger.warning(
            "graqle.govern.health_writer_skipped_non_anchoring_worker",
            extra={"worker_type": type(base_worker).__name__},
        )
    return base_worker


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
    health_file = graqle_dir / HEALTH_FILE_NAME

    # Wrap the worker so every tick (including the --once tick) snapshots health to
    # .graqle/govern.health.json — the operator surface the `graqle govern health`
    # sub-command and any external monitor reads. The snapshot is PII-safe (counts +
    # exception type names only).
    worker = _build_health_writing_worker(worker, health_file)

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


def _read_health_snapshot(health_file: Path) -> dict[str, Any]:
    """Read + parse the health-snapshot JSON file. Raises ``typer.Exit`` on missing/corrupt."""
    import json

    if not health_file.is_file():
        console.print(
            f"[red]✗ Health snapshot not found:[/red] {health_file}\n"
            "  Is `graqle govern serve` running? Snapshots are written each tick."
        )
        raise typer.Exit(1)
    try:
        return json.loads(health_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        console.print(f"[red]✗ Corrupt health snapshot:[/red] {exc.msg}")
        raise typer.Exit(1)
    except OSError as exc:
        console.print(f"[red]✗ Cannot read health snapshot:[/red] {type(exc).__name__}")
        raise typer.Exit(1)


@govern_app.command("health")
def govern_health(
    health_file: str = typer.Option(
        f".graqle/{HEALTH_FILE_NAME}", "--health-file",
        help="Path to the health snapshot JSON file.",
    ),
    watch: float = typer.Option(
        0.0, "--watch",
        help="Re-read every N seconds (0 = single read). Bounded poll-style monitoring.",
    ),
    pretty: bool = typer.Option(
        True, "--pretty/--compact",
        help="Pretty-print the JSON (default) or emit a compact single-line form.",
    ),
) -> None:
    """Read + print the AnchoringWorker's last health snapshot (Article 72 monitoring).

    The shipped serve loop writes ``.graqle/govern.health.json`` after every tick.
    This command reads + prints that snapshot as JSON, which an operator (or any
    external monitor / cron / curl pipeline) can consume.

    Fields (from ``WorkerHealth.to_dict``):

    * ``running`` — whether the worker loop is active
    * ``ticks`` — cumulative tick count since process start
    * ``records_committed`` / ``records_anchored`` — cumulative successful seal counts
    * ``backfill_count`` — replay-queue drains since process start
    * ``replay_queue_depth`` — current durable backlog (instantaneous; -1 = unavailable)
    * ``seconds_since_last_anchor`` — operator latency signal (None until first anchor)
    * ``last_error_type`` — exception type name only (PII-safe; never a payload value)
    * ``status_counts`` — Committer's CommitStatus census (PENDING/COMMITTED/ANCHORED/…)
    """
    import json
    import time

    if watch < 0:
        console.print("[red]✗ --watch must be >= 0[/red]")
        raise typer.Exit(1)

    path = Path(health_file)

    def _emit_once() -> None:
        snapshot = _read_health_snapshot(path)
        if pretty:
            console.print_json(json.dumps(snapshot, default=str, sort_keys=True))
        else:
            console.print(json.dumps(snapshot, default=str, sort_keys=True))

    if watch == 0:
        _emit_once()
        return

    # Poll-style mode: emit + wait + repeat. Exit cleanly on Ctrl-C.
    try:
        while True:
            _emit_once()
            time.sleep(watch)
    except KeyboardInterrupt:
        return
