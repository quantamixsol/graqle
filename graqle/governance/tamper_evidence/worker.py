"""The anchoring worker — productionise the shipped Layer 5 commit pipeline (ADR-221 §4.4 / R2).

`AnchoringWorker` is a long-lived service loop around the **shipped** :class:`Committer`.
It adds no cryptography and owns no batch logic; it is the *scheduler* that a deployed
``graqle govern serve`` process runs so that the durable governed-trace trail is
continuously sealed and **publicly anchored** out of band:

* **flush on the time ceiling.** The batcher seals a batch when ``batch_max_records`` are
  pending (inline, on enqueue) *or* ``batch_max_seconds`` elapse. The size ceiling fires
  on its own, but the *time* ceiling only fires when something calls ``flush()`` — so a
  long-lived service must tick. Each tick calls :meth:`Committer.flush`, which seals →
  Merkle-roots → anchors (or replay-queues) the pending batch.
* **drain the replay queue when Rekor recovers.** A batch committed while Rekor was
  unreachable is durably queued (never dropped). Each tick calls
  :meth:`LocalReplayQueue.drain`, which respects the circuit-breaker and re-anchors queued
  roots once Rekor is back — moving records COMMITTED → ANCHORED with no operator action.
* **fail-closed on anchoring.** The worker refuses to start if the config has
  ``fail_open_on_anchor_error=True`` (that would let an unreachable Rekor silently skip
  anchoring — the one thing Layer 5 must never do). The default is fail-closed; the worker
  enforces it as a precondition so the misconfiguration surfaces at startup, not silently
  at the first outage.
* **health for post-market monitoring (Article 72).** :meth:`health` returns queue depth,
  last-anchor age, a running anchored/backfill count, and the committer's status census —
  the signals an operator (or the R3 ``graqle govern serve`` health endpoint) watches.

The loop is synchronous and driven by a :class:`threading.Event`, so :meth:`stop` is a
clean cooperative shutdown: it flushes in-flight work, then returns. No event loop is
required, which keeps the worker embeddable in any process (CLI, container entrypoint,
test).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from graqle.config.attestation_config import AttestationConfig
    from graqle.governance.tamper_evidence.committer import Committer
    from graqle.governance.tamper_evidence.local_replay_queue import LocalReplayQueue

logger = logging.getLogger("graqle.governance.tamper_evidence.worker")

__all__ = [
    "AnchoringWorker",
    "WorkerHealth",
    "WorkerError",
]


class WorkerError(RuntimeError):
    """The anchoring worker was constructed or started in an unsafe configuration."""


@dataclass(frozen=True)
class WorkerHealth:
    """A point-in-time health snapshot of the anchoring worker (ADR-221 §4.4).

    Plain data so it serialises trivially for the R3 health endpoint / Article 72
    post-market monitoring. All counters are cumulative since worker construction except
    ``replay_queue_depth`` (instantaneous) and ``seconds_since_last_anchor`` (derived).
    """

    running: bool
    ticks: int
    records_committed: int
    records_anchored: int
    backfill_count: int
    replay_queue_depth: int
    seconds_since_last_anchor: float | None
    last_error_type: str | None
    status_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable view (the shape the R3 health endpoint will emit)."""
        return {
            "running": self.running,
            "ticks": self.ticks,
            "records_committed": self.records_committed,
            "records_anchored": self.records_anchored,
            "backfill_count": self.backfill_count,
            "replay_queue_depth": self.replay_queue_depth,
            "seconds_since_last_anchor": self.seconds_since_last_anchor,
            "last_error_type": self.last_error_type,
            "status_counts": dict(self.status_counts),
        }


class AnchoringWorker:
    """Long-lived scheduler that continuously seals + anchors the governed-trace trail.

    Parameters
    ----------
    committer:
        The shipped :class:`Committer` (owns batcher → Merkle → anchor → KG-persist).
    config:
        Layer 5 :class:`AttestationConfig`. ``batch_max_seconds`` sets the default tick
        interval; ``fail_open_on_anchor_error`` MUST be ``False`` (enforced at construction).
    replay_queue:
        Optional :class:`LocalReplayQueue`. When present, each tick drains it so queued
        roots re-anchor once Rekor recovers. Without one, the worker only flushes batches.
    tick_seconds:
        Loop interval. Defaults to ``config.batch_max_seconds`` (the time ceiling the loop
        exists to honour). Must be > 0.
    drain_max_items:
        Cap on roots drained from the replay queue per tick (bounds tick latency / Rekor
        request burst). ``None`` drains all eligible entries.
    clock / sleep:
        Injectable time source + sleeper (deterministic tests). Default to ``time``.
    """

    def __init__(
        self,
        committer: Committer,
        config: AttestationConfig,
        *,
        replay_queue: LocalReplayQueue | None = None,
        tick_seconds: float | None = None,
        drain_max_items: int | None = None,
        shutdown_flush_timeout_seconds: float | None = 30.0,
        clock: Any = None,
        sleep: Any = None,
    ) -> None:
        # Fail-closed precondition: an anchoring worker that may silently skip anchoring
        # defeats the whole point of Layer 5. Refuse to start, loudly, at construction.
        if getattr(config, "fail_open_on_anchor_error", False):
            raise WorkerError(
                "AnchoringWorker requires fail_open_on_anchor_error=False "
                "(an unreachable Rekor must never silently skip anchoring); "
                "set attestation.fail_open_on_anchor_error=false"
            )
        interval = tick_seconds if tick_seconds is not None else float(
            getattr(config, "batch_max_seconds", 5)
        )
        if interval <= 0:
            raise WorkerError("tick_seconds must be > 0")

        if shutdown_flush_timeout_seconds is not None and shutdown_flush_timeout_seconds <= 0:
            raise WorkerError("shutdown_flush_timeout_seconds must be > 0 or None")

        self._committer = committer
        self._config = config
        self._replay_queue = replay_queue
        self._tick_seconds = interval
        self._drain_max_items = drain_max_items
        self._shutdown_flush_timeout = shutdown_flush_timeout_seconds
        self._clock = clock if clock is not None else time.monotonic
        self._sleep = sleep if sleep is not None else time.sleep

        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._running = False

        # Cumulative health counters (guarded by _lock).
        self._ticks = 0
        self._records_committed = 0
        self._records_anchored = 0  # via direct flush anchoring (committer-reported)
        self._backfill_count = 0  # via replay-queue drain (recovered after an outage)
        self._last_anchor_monotonic: float | None = None
        self._last_error_type: str | None = None

    # -- one unit of work -------------------------------------------------------

    def tick(self) -> int:
        """Run one scheduler cycle: flush the batcher, then drain the replay queue.

        Returns the number of records committed by the flush this tick. Never raises for
        an *anchoring* outage (that path is handled durably downstream — flush replay-queues
        and drain respects the breaker); it only propagates programmer/wiring errors.
        """
        committed = self._committer.flush()
        backfilled = 0
        if self._replay_queue is not None:
            try:
                backfilled = self._replay_queue.drain(max_items=self._drain_max_items)
            except Exception as exc:  # noqa: BLE001 - record + continue; never crash the loop
                # A drain failure is operationally surfaced (counter + log), not fatal:
                # the queued roots stay durable and the next tick retries them.
                self._record_error(exc)
                logger.error(
                    "graqle.anchoring.drain_failed",
                    extra={"error_type": type(exc).__name__},
                )
        with self._lock:
            self._ticks += 1
            self._records_committed += committed
            self._records_anchored += committed
            self._backfill_count += backfilled
            if committed or backfilled:
                self._last_anchor_monotonic = self._clock()
        return committed

    # -- run loop ---------------------------------------------------------------

    def run(self, max_ticks: int | None = None) -> None:
        """Run the scheduler loop until :meth:`stop` (or ``max_ticks``).

        Blocking. Each iteration runs one :meth:`tick`, then waits ``tick_seconds`` on the
        stop event (so a stop interrupts the wait immediately). ``max_ticks`` bounds the
        loop for tests / one-shot drains. On exit it performs a final flush so no
        acknowledged record is left unsealed at shutdown.
        """
        with self._lock:
            if self._running:
                raise WorkerError("worker already running")
            self._running = True
            # NB: do NOT clear the stop event here — a stop() signalled before run()
            # (or between runs) must be honoured so the loop exits promptly rather than
            # starting a fresh tick cycle. The event starts unset at construction; a
            # caller that wants to reuse a stopped worker constructs a new one.
        try:
            n = 0
            while not self._stop.is_set():
                self.tick()
                n += 1
                if max_ticks is not None and n >= max_ticks:
                    break
                # Interruptible wait: stop() wakes this immediately.
                self._stop.wait(self._tick_seconds)
        finally:
            # Graceful shutdown: seal anything still pending so a clean stop loses nothing.
            # The flush is bounded by ``shutdown_flush_timeout_seconds`` so a hung Rekor
            # at shutdown cannot block the process from exiting forever — operator visibility
            # via the timeout log is preferred over an indefinite hang.
            result: dict[str, Any] = {}

            def _do_flush() -> None:
                try:
                    result["final"] = self._committer.flush()
                except Exception as exc:  # noqa: BLE001 - captured, re-surfaced after join
                    result["error"] = exc

            flusher = threading.Thread(
                target=_do_flush, name="graqle-anchoring-shutdown-flush", daemon=True,
            )
            flusher.start()
            flusher.join(self._shutdown_flush_timeout)
            if flusher.is_alive():
                # Timed out: do not block exit. The underlying batch state is durable
                # (the WAL persists pending records); a future run() will re-seal it.
                self._record_error(TimeoutError("shutdown flush timed out"))
                logger.error(
                    "graqle.anchoring.shutdown_flush_timeout",
                    extra={"timeout_seconds": self._shutdown_flush_timeout},
                )
            elif "error" in result:
                self._record_error(result["error"])
                logger.error(
                    "graqle.anchoring.shutdown_flush_failed",
                    extra={"error_type": type(result["error"]).__name__},
                )
            else:
                final = result.get("final", 0) or 0
                if final:
                    with self._lock:
                        self._records_committed += final
                        self._records_anchored += final
                        self._last_anchor_monotonic = self._clock()
            with self._lock:
                self._running = False

    def stop(self) -> None:
        """Signal the run loop to exit after the current tick (cooperative, idempotent)."""
        self._stop.set()

    # -- health -----------------------------------------------------------------

    def _record_error(self, exc: Exception) -> None:
        with self._lock:
            self._last_error_type = type(exc).__name__

    def health(self) -> WorkerHealth:
        """A point-in-time :class:`WorkerHealth` snapshot for Article 72 monitoring."""
        depth = 0
        if self._replay_queue is not None:
            try:
                depth = self._replay_queue.depth
            except Exception:  # noqa: BLE001 - health must never raise
                depth = -1  # sentinel: depth unavailable (surfaced, not hidden)
        try:
            counts = self._committer.status_counts()
        except Exception:  # noqa: BLE001 - health must never raise
            counts = {}
        with self._lock:
            since = (
                None
                if self._last_anchor_monotonic is None
                else max(0.0, self._clock() - self._last_anchor_monotonic)
            )
            return WorkerHealth(
                running=self._running,
                ticks=self._ticks,
                records_committed=self._records_committed,
                records_anchored=self._records_anchored,
                backfill_count=self._backfill_count,
                replay_queue_depth=depth,
                seconds_since_last_anchor=since,
                last_error_type=self._last_error_type,
                status_counts=counts,
            )
