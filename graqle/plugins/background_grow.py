# ──────────────────────────────────────────────────────────────────
# PATENT NOTICE — Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Applications EP26162901.8 and EP26166054.2, owned by
# Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: legal@quantamix.io
# ──────────────────────────────────────────────────────────────────

"""Background filesystem watcher that auto-runs `graq grow`.

v0.63.0 SPEC (.gsm/decisions/SPEC-v063-mcp-background-grow.md). Spawned by
KogniDevServer (graqle.plugins.mcp_dev_server) at startup. Subscribes to OS
file events via watchdog and debounces a batched `graq grow` invocation.

Layered defense (covers gaps of the git post-commit hook):
  - Git hook: fires ONLY on `git commit`. Misses IDE saves, AI agent writes,
    branch switches, generated code, manual edits.
  - This watcher: fires on EVERY filesystem event matching the watch pattern.

Subprocess-based grow invocation (not in-process):
  - Hung grow cannot deadlock the MCP server
  - Bedrock errors / Neo4j errors / venv errors are captured in stderr and logged
  - Subprocess gets its own Python interpreter (avoids re-entrant issues with
    pydantic validators / graqle state)

Configurable via env vars (all clamped to safe ranges at load time):
  - GRAQLE_DISABLE_BACKGROUND_GROW  — set to "1" to disable
  - GRAQLE_BG_GROW_DEBOUNCE         — debounce seconds, default 5.0, range [1, 300]
  - GRAQLE_BG_GROW_RATE_LIMIT       — chunks/hour cap, default 1000, range [1, 10000]

Security:
  - subprocess.run([fixed list], shell=False); file paths NEVER passed as
    subprocess args (watcher tracks them internally for telemetry only).
  - Circuit breaker: 5 consecutive failures -> 5min DISABLED state with WARN.
  - MAX_QUEUE_SIZE=10000 bounds memory under pathological burst loads.
"""

# ── graqle:intelligence ──
# module: graqle.plugins.background_grow
# risk: MEDIUM (new module, spawns daemon thread + subprocess from MCP server)
# consumers: graqle.plugins.mcp_dev_server (KogniDevServer startup)
# dependencies: __future__, logging, os, subprocess, sys, threading, time, collections, pathlib, typing
# optional dependency: watchdog>=3.0,<5.0 (graceful degradation if missing)
# constraints: subprocess shell=False (security); file paths never reach subprocess args (security); rate-limited Bedrock cost (cost); circuit-broken on persistent failure (reliability); queue-capped at 10000 events (memory)
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("graqle.plugins.background_grow")

# ─── Configuration (env vars, clamped at load) ─────────────────────────────


def _clamped_float(env: str, default: float, lo: float, hi: float) -> float:
    """Read env var as float, clamp to [lo, hi]. Log INFO if clamped."""
    raw = os.environ.get(env)
    if raw is None:
        return default
    try:
        val = float(raw)
    except ValueError:
        logger.info(
            "%s=%r is not a valid float; using default %s", env, raw, default
        )
        return default
    clamped = max(lo, min(hi, val))
    if clamped != val:
        logger.info(
            "%s=%s clamped to %s (valid range [%s, %s])",
            env, val, clamped, lo, hi,
        )
    return clamped


def _clamped_int(env: str, default: int, lo: int, hi: int) -> int:
    """Read env var as int, clamp to [lo, hi]. Log INFO if clamped."""
    raw = os.environ.get(env)
    if raw is None:
        return default
    try:
        val = int(raw)
    except ValueError:
        logger.info(
            "%s=%r is not a valid int; using default %d", env, raw, default
        )
        return default
    clamped = max(lo, min(hi, val))
    if clamped != val:
        logger.info(
            "%s=%d clamped to %d (valid range [%d, %d])",
            env, val, clamped, lo, hi,
        )
    return clamped


DEBOUNCE_SECONDS = _clamped_float("GRAQLE_BG_GROW_DEBOUNCE", 5.0, 1.0, 300.0)
MAX_CHUNKS_PER_HOUR = _clamped_int("GRAQLE_BG_GROW_RATE_LIMIT", 1000, 1, 10_000)
DISABLED_ENV = "GRAQLE_DISABLE_BACKGROUND_GROW"

# Hardcoded safety constants (not env-configurable — these are correctness, not knobs)
MAX_QUEUE_SIZE = 10_000               # bounds memory under burst loads
SUBPROCESS_TIMEOUT_SECONDS = 120.0    # kill hung grow processes
CIRCUIT_BREAKER_THRESHOLD = 5         # consecutive failures before disable
CIRCUIT_BREAKER_COOLDOWN = 300.0      # 5 minutes disabled after threshold
DROP_WARN_INTERVAL = 60.0             # one drop-warning per minute (not per drop)
COOLDOWN_WARN_INTERVAL = 60.0         # warn once per minute during cool-down

# Watch only source files. Skip caches/builds/git internals to avoid event storm.
WATCH_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java",
    ".md", ".yaml", ".yml", ".json",
}
IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".graqle", ".gcc", ".gsm", "dist", "build", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "target",  # rust
}


# ─── Watcher class ─────────────────────────────────────────────────────────


class BackgroundGrowWatcher:
    """Filesystem watcher that triggers `graq grow` on debounced batches.

    Lifecycle:
        watcher = BackgroundGrowWatcher(Path("."))
        if watcher.start():
            ...  # MCP server lifetime
            watcher.stop()  # optional; daemon=True dies with process anyway

    Thread-safe: register/resolve operations are guarded by ``_lock``.
    The debounce loop is a daemon thread (dies with the MCP server).
    """

    def __init__(
        self,
        project_root: Path,
        python_executable: Optional[str] = None,
    ) -> None:
        self._root = Path(project_root).resolve()
        self._py = python_executable or sys.executable
        self._pending_events: deque = deque()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._observer: Any = None  # watchdog Observer, created in start()

        # Telemetry
        self._growths_completed: int = 0
        self._chunks_this_hour: int = 0
        self._hour_start: float = time.monotonic()
        self._last_drop_warn_ts: float = 0.0

        # Circuit breaker state
        self._consecutive_failures: int = 0
        self._circuit_broken_until: float = 0.0  # monotonic timestamp
        self._last_cooldown_warn_ts: float = 0.0

    # ── lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Start the watcher. Returns False if disabled or watchdog missing.

        Never raises — graceful degradation on every failure path. The MCP
        server can call this unconditionally at startup.
        """
        if os.environ.get(DISABLED_ENV, "0") == "1":
            logger.info(
                "Background grow watcher disabled via %s=1", DISABLED_ENV
            )
            return False

        try:
            from watchdog.observers import Observer  # type: ignore[import-not-found]
            from watchdog.events import FileSystemEventHandler  # type: ignore[import-not-found]
        except ImportError:
            logger.warning(
                "Background grow watcher unavailable: watchdog not installed. "
                "Install with: pip install 'graqle[watch]'  "
                "(or: pip install watchdog>=3.0,<5.0)"
            )
            return False

        class _Handler(FileSystemEventHandler):  # noqa: D106 - small inner class
            def __init__(self, owner: "BackgroundGrowWatcher") -> None:
                self._owner = owner

            def on_any_event(self, event: Any) -> None:
                if event.is_directory:
                    return
                try:
                    p = Path(event.src_path)
                except (TypeError, ValueError):
                    return
                if p.suffix not in WATCH_EXTENSIONS:
                    return
                if any(part in IGNORE_DIRS for part in p.parts):
                    return
                self._owner._enqueue(p)

        try:
            self._observer = Observer()
            self._observer.schedule(_Handler(self), str(self._root), recursive=True)
            self._observer.daemon = True
            self._observer.start()
        except Exception as exc:
            logger.warning(
                "Background grow watcher failed to start observer: %s: %s",
                type(exc).__name__, exc,
            )
            return False

        self._thread = threading.Thread(
            target=self._debounce_loop_guarded,
            name="graqle-bg-grow",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Background grow watcher started on %s "
            "(debounce=%.1fs, rate_limit=%d chunks/h, queue_cap=%d, "
            "circuit_breaker=%d failures/%ds cooldown)",
            self._root, DEBOUNCE_SECONDS, MAX_CHUNKS_PER_HOUR,
            MAX_QUEUE_SIZE, CIRCUIT_BREAKER_THRESHOLD, CIRCUIT_BREAKER_COOLDOWN,
        )
        return True

    def stop(self) -> None:
        """Signal the thread to stop. Best-effort; daemon=True dies anyway."""
        self._stop_event.set()
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=2.0)
            except Exception:
                pass  # nothing useful to do on stop failure
        if self._thread is not None:
            self._thread.join(timeout=DEBOUNCE_SECONDS + 1.0)

    # ── queue management ───────────────────────────────────────────────────

    def _enqueue(self, path: Path) -> None:
        """Add a file event to the queue. Drops oldest if at MAX_QUEUE_SIZE."""
        with self._lock:
            if len(self._pending_events) >= MAX_QUEUE_SIZE:
                now = time.monotonic()
                if now - self._last_drop_warn_ts > DROP_WARN_INTERVAL:
                    logger.warning(
                        "Background grow queue full (%d events); dropping oldest. "
                        "Consider increasing GRAQLE_BG_GROW_DEBOUNCE or "
                        "investigating bulk file changes.",
                        MAX_QUEUE_SIZE,
                    )
                    self._last_drop_warn_ts = now
                self._pending_events.popleft()
            self._pending_events.append((time.monotonic(), path))

    def _drain_batch(self) -> list[Path]:
        """Pop and dedupe everything in the queue. Returns sorted unique paths."""
        with self._lock:
            paths = {p for _ts, p in self._pending_events}
            self._pending_events.clear()
        return sorted(paths)

    # ── rate limit ──────────────────────────────────────────────────────────

    def _check_rate_limit(self, batch_size: int) -> bool:
        """Hourly rate-limit gate. Returns True if OK to proceed."""
        now = time.monotonic()
        if now - self._hour_start >= 3600:
            self._chunks_this_hour = 0
            self._hour_start = now
        if self._chunks_this_hour + batch_size > MAX_CHUNKS_PER_HOUR:
            logger.warning(
                "Background grow rate-limited: would exceed %d chunks/hour "
                "(current=%d, batch=%d). Deferring this batch.",
                MAX_CHUNKS_PER_HOUR, self._chunks_this_hour, batch_size,
            )
            return False
        self._chunks_this_hour += batch_size
        return True

    # ── circuit breaker ────────────────────────────────────────────────────

    def _circuit_open(self) -> bool:
        """True iff circuit is currently OPEN (watcher should NOT call grow)."""
        if self._consecutive_failures < CIRCUIT_BREAKER_THRESHOLD:
            return False
        now = time.monotonic()
        if now < self._circuit_broken_until:
            if now - self._last_cooldown_warn_ts > COOLDOWN_WARN_INTERVAL:
                remaining = int(self._circuit_broken_until - now)
                logger.warning(
                    "Background grow circuit OPEN: %d consecutive failures, "
                    "cooling down for %d more seconds.",
                    self._consecutive_failures, remaining,
                )
                self._last_cooldown_warn_ts = now
            return True
        # Cooldown elapsed — close circuit and retry
        logger.info(
            "Background grow circuit cooldown elapsed; retrying after %d failures",
            self._consecutive_failures,
        )
        return False

    def _record_grow_outcome(self, success: bool) -> None:
        if success:
            if self._consecutive_failures > 0:
                logger.info(
                    "Background grow recovered after %d consecutive failures",
                    self._consecutive_failures,
                )
            self._consecutive_failures = 0
            self._circuit_broken_until = 0.0
            return
        self._consecutive_failures += 1
        if self._consecutive_failures == CIRCUIT_BREAKER_THRESHOLD:
            self._circuit_broken_until = time.monotonic() + CIRCUIT_BREAKER_COOLDOWN
            logger.warning(
                "Background grow circuit BREAKING: %d consecutive failures, "
                "watcher disabled for %d seconds.",
                CIRCUIT_BREAKER_THRESHOLD, int(CIRCUIT_BREAKER_COOLDOWN),
            )

    # ── debounce loop ──────────────────────────────────────────────────────

    def _debounce_loop_guarded(self) -> None:
        """Outer try/except wrapper so a thread crash is logged, not silent."""
        try:
            self._debounce_loop()
        except Exception:
            logger.exception(
                "Background grow watcher thread crashed unexpectedly. "
                "Watcher disabled until MCP server restarts."
            )

    def _debounce_loop(self) -> None:
        """Pop the batch every DEBOUNCE_SECONDS and call `graq grow`."""
        while not self._stop_event.wait(DEBOUNCE_SECONDS):
            if self._circuit_open():
                continue

            batch = self._drain_batch()
            if not batch:
                continue

            if not self._check_rate_limit(len(batch)):
                # Put them back for next interval (within queue cap)
                with self._lock:
                    for p in batch:
                        if len(self._pending_events) < MAX_QUEUE_SIZE:
                            self._pending_events.append((time.monotonic(), p))
                continue

            logger.info(
                "Background grow: %d file change(s) detected, running grow...",
                len(batch),
            )

            success = self._run_grow_subprocess()
            self._record_grow_outcome(success)

    def _run_grow_subprocess(self) -> bool:
        """Invoke `graq grow` in subprocess. Returns True on exit 0.

        SECURITY: subprocess is invoked with a fixed argv list, shell=False.
        File paths from the watcher are tracked internally for telemetry but
        NEVER passed as subprocess arguments. ``graq grow`` does its own
        change detection from the working directory.
        """
        try:
            result = subprocess.run(  # noqa: S603 - safe: fixed argv, shell=False
                # v0.63.0: --embed so background-grown nodes are queryable by
                # reasoning (incremental embed; the end-to-end auto-grow fix).
                [self._py, "-m", "graqle.cli.main", "grow", "--embed"],
                cwd=str(self._root),
                capture_output=True,
                text=True,
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
                shell=False,
            )
            self._growths_completed += 1
            if result.returncode == 0:
                logger.info(
                    "Background grow OK: %s",
                    (result.stdout or "").strip() or "(no output)",
                )
                return True
            logger.error(
                "Background grow FAILED (exit %d): %s",
                result.returncode,
                ((result.stderr or result.stdout) or "(no output)").strip(),
            )
            return False
        except subprocess.TimeoutExpired:
            logger.error(
                "Background grow TIMEOUT after %.0fs", SUBPROCESS_TIMEOUT_SECONDS
            )
            return False
        except FileNotFoundError as exc:
            logger.error(
                "Background grow EXEC FAILED: %s. Check python_executable=%r",
                exc, self._py,
            )
            return False
        except Exception as exc:
            logger.error(
                "Background grow EXCEPTION: %s: %s", type(exc).__name__, exc
            )
            return False

    # ── telemetry ──────────────────────────────────────────────────────────

    @property
    def stats(self) -> dict:
        """For graq_inspect / debug: return current watcher state."""
        return {
            "root": str(self._root),
            "growths_completed": self._growths_completed,
            "chunks_this_hour": self._chunks_this_hour,
            "pending_events": len(self._pending_events),
            "alive": self._thread is not None and self._thread.is_alive(),
            "consecutive_failures": self._consecutive_failures,
            "circuit_open": (
                self._consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD
                and time.monotonic() < self._circuit_broken_until
            ),
        }
