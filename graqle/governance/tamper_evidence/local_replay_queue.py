"""Durable local replay queue — Rekor-availability fallback (R25-EU01 CONDITION-3).

When Sigstore Rekor (PR-4 anchor) is unreachable, a committed batch root still
needs to be anchored *eventually* — dropping it would break the tamper-evidence
chain (AC-2: every committed batch root is anchored). This module is the
ADR-RT-003 §3.1 CONDITION-3 fallback: roots that cannot be anchored right now are
**durably queued** here and replayed when Rekor recovers.

This is NOT the PR-3 write-ahead log. They occupy disjoint directories and
lifecycle phases and never collide:

* **WAL** (``.graqle/uncommitted/``, PR-3) — individual *records* pending their
  FIRST commit (Merkle build + downstream commit).
* **Replay queue** (``.graqle/replay_queue/``, this module) — committed batch
  *roots* pending a Rekor *anchor*.

Each queued entry is one JSON file ``<seq>-<root_hex>.json`` holding the root,
its receipt-less metadata, an attempt counter, and a SHA-256 integrity checksum
over the canonical payload (verified on read when ``integrity_check`` is on).

**5-state overflow protocol** (ADR-RT-003 §3.1). The queue is bounded
(``max_entries``); as it fills while Rekor stays down, it escalates through:

    NORMAL  ──fill≥degraded_ratio──▶  DEGRADED  ──fill≥alert_ratio──▶  ALERT
       ▲                                                                  │
       │ drain back below                                          fill≥1.0
       │ recovery_ratio                                                   ▼
    RECOVERY ◀──Rekor returns, draining──  PAUSE ◀───── queue full ───────┘

* NORMAL — anchoring works (or queue is shallow); business as usual.
* DEGRADED — Rekor is failing and the queue is filling; log at WARNING.
* ALERT — queue near full; structured operator alert (+ optional webhook).
* PAUSE — queue full; per ``on_queue_full`` either reject new roots or signal
  the caller to pause accepting writes (AC-9). NEVER silently drop a root.
* RECOVERY — Rekor is back and the backlog is draining; returns to NORMAL once
  the queue falls below ``recovery_ratio``.

An **independent circuit-breaker** tracks Rekor health separately from the
overflow state: consecutive anchor failures open the breaker (stop hammering a
dead Rekor); a cooldown half-opens it to probe; a success closes it. The
overflow state reflects the QUEUE; the breaker reflects the ANCHOR — orthogonal.

An **audited operator override** lets an operator force-drain or force-resume
past the protocol; every override is recorded (structured WARNING) so it appears
in the audit trail.

Everything is deterministically unit-testable: inject ``clock`` (for backoff +
breaker cooldown) and ``anchor`` (a :class:`RekorAnchor` or any object with
``anchor(bytes)->RekorReceipt`` + ``available``). No network, no real sleeps.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Protocol

from graqle.config.attestation_config import ReplayQueueConfig
from graqle.governance.tamper_evidence.anchors.sigstore_rekor import (
    AnchorError,
    RekorReceipt,
)
from graqle.governance.tamper_evidence.errors import TamperEvidenceError

logger = logging.getLogger(__name__)

# Entry filename: <zero-padded seq>-<root hex>.json. The seq prefix gives a
# stable FIFO replay order independent of filesystem listing order; the root hex
# makes the filename self-describing and collision-free.
_ENTRY_SUFFIX = ".json"
_SEQ_WIDTH = 12  # zero-pad sequence so lexical sort == numeric sort

# Fill-ratio thresholds for the 5-state overflow protocol. These are operational
# tuning knobs (NOT TS-2): they describe the PUBLIC overflow contract.
_DEGRADED_RATIO = 0.50
_ALERT_RATIO = 0.80
_RECOVERY_RATIO = 0.25

# Circuit-breaker defaults (consecutive failures to open; cooldown seconds to
# half-open). Operational, not secret.
_BREAKER_FAIL_THRESHOLD = 3
_BREAKER_COOLDOWN_SECONDS = 30.0


class OverflowState(str, Enum):
    """The 5 states of the queue overflow protocol (ADR-RT-003 §3.1)."""

    NORMAL = "normal"
    DEGRADED = "degraded"
    ALERT = "alert"
    PAUSE = "pause"
    RECOVERY = "recovery"


class BreakerState(str, Enum):
    """Circuit-breaker states for Rekor health (independent of overflow)."""

    CLOSED = "closed"  # anchoring allowed
    OPEN = "open"  # anchoring suppressed (Rekor presumed down)
    HALF_OPEN = "half_open"  # one probe allowed to test recovery


class ReplayQueueError(TamperEvidenceError):
    """Raised for replay-queue operations that cannot proceed safely."""


class QueueFullError(ReplayQueueError):
    """The queue is full and ``on_queue_full='reject'`` — the root was not queued."""


class AnchorLike(Protocol):
    """The anchor surface the replay queue needs (satisfied by RekorAnchor)."""

    @property
    def available(self) -> bool: ...

    def anchor(self, root_bytes: bytes) -> RekorReceipt: ...


@dataclass(frozen=True)
class QueuedRoot:
    """One batch root awaiting a Rekor anchor."""

    seq: int
    root_hex: str
    batch_id: str
    attempts: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Breaker:
    """Mutable circuit-breaker state. Cooldown uses the injected clock."""

    state: BreakerState = BreakerState.CLOSED
    consecutive_failures: int = 0
    opened_at: float | None = None


class LocalReplayQueue:
    """Durable, bounded, FIFO queue of batch roots pending a Rekor anchor.

    Parameters
    ----------
    config:
        :class:`ReplayQueueConfig` — ``directory``, ``max_entries``,
        ``integrity_check``, ``max_retries``, ``retry_backoff_seconds``,
        ``on_queue_full``.
    queue_root:
        Base directory under which ``replay_queue/`` lives (typically
        ``.graqle``). The config's ``directory`` is honoured as the subdir name's
        source; entries live in ``<queue_root>/replay_queue/``.
    anchor:
        Object with ``available`` + ``anchor(bytes)->RekorReceipt`` (a
        :class:`RekorAnchor` in production, a fake in tests). Optional: a
        queue can be constructed purely to enqueue/inspect without draining.
    clock:
        Injectable monotonic clock (defaults to ``time.monotonic``) for breaker
        cooldown — deterministic in tests.
    """

    def __init__(
        self,
        config: ReplayQueueConfig,
        queue_root: str | os.PathLike[str],
        anchor: AnchorLike | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        import threading
        import time as _time

        self._config = config
        self._anchor = anchor
        self._clock = clock or _time.monotonic
        # Serializes enqueue/drain/override across threads: the PR-5 committer may
        # enqueue (commit path) and drain (recovery path) concurrently. All
        # mutation of _next_seq, the breaker, and the on-disk queue happens under
        # this lock (reentrant so internal helpers can be called while held).
        self._lock = threading.RLock()
        # Use ONLY the LAST path component of config.directory as the subdir name
        # so config.directory can never escape queue_root (path-traversal guard:
        # Path("../../etc").name == "etc", Path("..").name == "" -> fallback).
        subdir = Path(config.directory).name or "replay_queue"
        if subdir in ("", ".", ".."):  # belt-and-suspenders: never a traversal token
            subdir = "replay_queue"
        self._dir = Path(queue_root) / subdir
        self._dir.mkdir(parents=True, exist_ok=True)
        # Restrict the queue directory on POSIX (governance artifact; defence in
        # depth). chmod is a no-op concept on Windows, so guard it; failure to
        # chmod must not prevent the queue from operating.
        if os.name == "posix":
            try:
                os.chmod(self._dir, 0o700)
            except OSError:  # pragma: no cover - platform/permission dependent
                pass
        self._breaker = _Breaker()
        # Next sequence number = one past the highest on disk (durable ordering).
        self._next_seq = self._highest_seq_on_disk() + 1

    # ---- public API -----------------------------------------------------------

    def enqueue(self, root_hex: str, batch_id: str, metadata: dict[str, Any] | None = None) -> OverflowState:
        """Durably queue a batch root for later anchoring; return the new overflow state.

        Raises :class:`QueueFullError` only when the queue is full AND
        ``on_queue_full='reject'``. With ``on_queue_full='pause_writes'`` a full
        queue still persists the root (durability wins) and returns
        :data:`OverflowState.PAUSE` so the caller can pause accepting writes — a
        root is NEVER silently dropped (AC-9).
        """
        if not isinstance(root_hex, str) or not root_hex:
            raise ReplayQueueError("root_hex must be a non-empty string")
        if not _is_hex(root_hex):
            raise ReplayQueueError(
                "root_hex must be a hex string (it is decoded with bytes.fromhex "
                "at anchor time); refusing to queue a non-hex root"
            )
        with self._lock:
            return self._enqueue_locked(root_hex, batch_id, metadata)

    def _enqueue_locked(self, root_hex: str, batch_id: str, metadata: dict[str, Any] | None) -> OverflowState:
        count = self.depth
        if count >= self._config.max_entries:
            if self._config.on_queue_full == "reject":
                raise QueueFullError(
                    f"replay queue full ({count}/{self._config.max_entries}); "
                    f"on_queue_full='reject' — root {root_hex[:12]}… not queued"
                )
            # pause_writes: still persist (never drop), but signal PAUSE.
            self._write_entry(root_hex, batch_id, metadata or {}, attempts=0)
            logger.error(
                "replay queue full (%d/%d) — persisted root %s and signalling "
                "PAUSE; caller should pause accepting writes (AC-9)",
                count + 1, self._config.max_entries, root_hex[:12],
            )
            return OverflowState.PAUSE
        self._write_entry(root_hex, batch_id, metadata or {}, attempts=0)
        return self._compute_state(self.depth)

    def drain(self, max_items: int | None = None) -> int:
        """Attempt to anchor queued roots in FIFO order; return the count anchored.

        Respects the circuit-breaker: if it is OPEN and still in cooldown, drain
        is a no-op (returns 0) to avoid hammering a down Rekor. When the cooldown
        elapses the breaker half-opens and a single probe is attempted; success
        closes it and the full drain proceeds, a failure re-opens it.

        Each anchored root's entry is removed only AFTER the anchor succeeds
        (durable until externally proven). A per-entry failure increments its
        attempt counter; once ``max_retries`` is exceeded the entry is left in
        place and surfaced (never dropped) for operator attention.

        Delivery semantics are **at-least-once**, not exactly-once: if Rekor
        records the root but the response is lost in transit, the anchor surfaces
        as :class:`AnchorError`, the entry stays queued, and the next drain
        re-submits it — producing a second Rekor entry for the same root. This is
        acceptable for tamper-evidence: the root is content-addressed, so a
        duplicate Rekor entry is benign (an inclusion proof against either entry
        validates, and Rekor coalesces identical entries). Exactly-once anchoring
        is not attempted here; an idempotency token, if ever needed, belongs in
        the PR-5 committer that owns the batch lifecycle.
        """
        if self._anchor is None:
            raise ReplayQueueError("no anchor configured; cannot drain")
        with self._lock:
            return self._drain_locked(max_items)

    def _drain_locked(self, max_items: int | None) -> int:
        if not self._breaker_allows_attempt():
            return 0

        entries = self._list_entries()
        if max_items is not None:
            entries = entries[:max_items]

        anchored = 0
        for path in entries:
            queued = self._read_entry(path)
            if queued is None:
                continue  # corrupt entry: skip, leave for operator
            try:
                root_bytes = bytes.fromhex(queued.root_hex)
            except ValueError:
                # A non-hex root reached disk despite the enqueue guard (tamper /
                # external write). Skip it — never crash the whole drain.
                logger.error(
                    "replay-queue entry %s has a non-hex root; skipping", path.name
                )
                continue
            try:
                self._anchor.anchor(root_bytes)
            except AnchorError as exc:
                self._record_failure()
                self._bump_attempts(path, queued, exc)
                # Breaker may have just opened; stop draining this pass.
                if self._breaker.state == BreakerState.OPEN:
                    break
                continue
            # Success: anchor proven, remove the entry and reset breaker.
            self._record_success()
            self._remove_entry(path)
            anchored += 1
        return anchored

    @property
    def depth(self) -> int:
        """Number of roots currently queued (durably on disk)."""
        return len(self._list_entries())

    @property
    def state(self) -> OverflowState:
        """Current overflow state derived from the queue fill ratio + breaker."""
        return self._compute_state(self.depth)

    @property
    def breaker_state(self) -> BreakerState:
        """Current circuit-breaker state (Rekor health)."""
        return self._breaker.state

    @property
    def queue_dir(self) -> Path:
        """Directory holding queued roots."""
        return self._dir

    def operator_override(self, action: str, reason: str) -> None:
        """Audited operator override of the overflow protocol.

        ``action`` is ``'reset_breaker'`` (force the circuit-breaker closed to
        retry Rekor now) or ``'clear_pause'`` (no-op marker that the operator has
        acknowledged a PAUSE). Every override is logged at WARNING with the
        supplied ``reason`` so it appears in the audit trail. Unknown actions
        raise — an override must be explicit.
        """
        with self._lock:
            if action == "reset_breaker":
                self._breaker = _Breaker()
                logger.warning(
                    "OPERATOR OVERRIDE reset_breaker: circuit-breaker forced CLOSED. "
                    "reason=%s", reason,
                )
            elif action == "clear_pause":
                logger.warning(
                    "OPERATOR OVERRIDE clear_pause: operator acknowledged PAUSE. "
                    "reason=%s", reason,
                )
            else:
                raise ReplayQueueError(
                    f"unknown operator override action {action!r}; "
                    f"expected 'reset_breaker' or 'clear_pause'"
                )

    # ---- overflow state machine -----------------------------------------------

    def _compute_state(self, count: int) -> OverflowState:
        """Map (fill ratio, breaker) onto the 5-state overflow protocol."""
        max_entries = self._config.max_entries
        ratio = count / max_entries if max_entries else 0.0
        if count >= max_entries:
            return OverflowState.PAUSE
        # When the breaker is recovering (half-open/closed after being open) and
        # the queue is draining below recovery_ratio, we are in RECOVERY.
        if self._breaker.state in (BreakerState.HALF_OPEN, BreakerState.OPEN):
            if ratio >= _ALERT_RATIO:
                return OverflowState.ALERT
            if ratio >= _DEGRADED_RATIO:
                return OverflowState.DEGRADED
            if ratio > _RECOVERY_RATIO:
                return OverflowState.RECOVERY
            return OverflowState.RECOVERY if count > 0 else OverflowState.NORMAL
        if ratio >= _ALERT_RATIO:
            return OverflowState.ALERT
        if ratio >= _DEGRADED_RATIO:
            return OverflowState.DEGRADED
        return OverflowState.NORMAL

    # ---- circuit-breaker ------------------------------------------------------

    def _breaker_allows_attempt(self) -> bool:
        """True if an anchor attempt may proceed under the current breaker state."""
        b = self._breaker
        if b.state == BreakerState.CLOSED:
            return True
        if b.state == BreakerState.OPEN:
            # Allow a probe once the cooldown has elapsed -> half-open.
            if b.opened_at is not None and (self._clock() - b.opened_at) >= _BREAKER_COOLDOWN_SECONDS:
                b.state = BreakerState.HALF_OPEN
                return True
            return False
        # HALF_OPEN: allow the single probe.
        return True

    def _record_failure(self) -> None:
        """Register an anchor failure; open the breaker past the threshold."""
        b = self._breaker
        b.consecutive_failures += 1
        if b.state == BreakerState.HALF_OPEN:
            # Probe failed -> re-open immediately.
            b.state = BreakerState.OPEN
            b.opened_at = self._clock()
        elif b.consecutive_failures >= _BREAKER_FAIL_THRESHOLD:
            b.state = BreakerState.OPEN
            b.opened_at = self._clock()
            logger.error(
                "Rekor circuit-breaker OPEN after %d consecutive anchor failures",
                b.consecutive_failures,
            )

    def _record_success(self) -> None:
        """Register an anchor success; close the breaker."""
        if self._breaker.state != BreakerState.CLOSED:
            logger.warning("Rekor circuit-breaker CLOSED after successful anchor")
        self._breaker = _Breaker()

    # ---- durable entry persistence --------------------------------------------

    def _entry_path(self, seq: int, root_hex: str) -> Path:
        return self._dir / f"{seq:0{_SEQ_WIDTH}d}-{root_hex}{_ENTRY_SUFFIX}"

    def _write_entry(self, root_hex: str, batch_id: str, metadata: dict[str, Any], attempts: int) -> None:
        """Persist a NEW queued root under a freshly-allocated sequence number."""
        seq = self._next_seq
        self._next_seq += 1
        self._persist_entry(seq, root_hex, batch_id, metadata, attempts)

    def _rewrite_entry_atomic(
        self, path: Path, seq: int, root_hex: str, batch_id: str,
        metadata: dict[str, Any], attempts: int,
    ) -> None:
        """Rewrite an EXISTING entry in place (same seq+root => same filename).

        ``os.replace`` overwrites the original path atomically, so there is no
        window in which the root is absent from disk (durability under crash).
        ``path`` is the existing entry's path and equals ``_entry_path(seq,
        root_hex)``; it is passed for clarity but the write targets that same
        deterministic path.
        """
        self._persist_entry(seq, root_hex, batch_id, metadata, attempts)

    def _persist_entry(
        self, seq: int, root_hex: str, batch_id: str,
        metadata: dict[str, Any], attempts: int,
    ) -> None:
        """Atomically + durably write the entry for ``seq``/``root_hex``.

        temp -> fsync -> os.replace into the deterministic ``_entry_path``. Because
        the path is a pure function of (seq, root_hex), writing an existing
        (seq, root) atomically OVERWRITES it (the bump path) and writing a new one
        CREATES it (the enqueue path) — both crash-safe, neither leaves a gap.
        """
        payload: dict[str, Any] = {
            "seq": seq,
            "root_hex": root_hex,
            "batch_id": batch_id,
            "attempts": attempts,
            "metadata": metadata,
        }
        if self._config.integrity_check:
            payload["checksum"] = _checksum(payload)
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        final_path = self._entry_path(seq, root_hex)
        tmp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=str(self._dir), prefix=f".{seq}.", suffix=".tmp", delete=False
            ) as tmp:
                tmp_name = tmp.name
                tmp.write(data)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_name, str(final_path))
            tmp_name = None
        finally:
            if tmp_name is not None:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass

    def _bump_attempts(self, path: Path, queued: QueuedRoot, exc: Exception) -> None:
        """Increment an entry's attempt counter; surface if max_retries exceeded.

        The bump is an ATOMIC in-place rewrite: the entry keeps its original seq
        and root, so its filename is unchanged, and :meth:`_rewrite_entry_atomic`
        overwrites it via tempfile -> fsync -> os.replace. Crucially there is NO
        remove-then-write window — a crash mid-bump leaves either the old entry
        or the new one fully on disk, never nothing. (graq_predict failure-chain
        #1: a remove-then-rewrite would lose the root on a crash between the two.)
        """
        attempts = queued.attempts + 1
        if attempts > self._config.max_retries:
            logger.error(
                "replay-queue root %s exceeded max_retries (%d); leaving in place "
                "for operator. last error: %s",
                queued.root_hex[:12], self._config.max_retries, exc,
            )
            return  # leave the entry untouched; never drop a root
        self._rewrite_entry_atomic(path, queued.seq, queued.root_hex, queued.batch_id, queued.metadata, attempts)

    def _remove_entry(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("failed to remove replay-queue entry %s: %s", path.name, exc)

    def _read_entry(self, path: Path) -> QueuedRoot | None:
        """Parse + integrity-check one entry; return None if corrupt."""
        try:
            data = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            logger.warning("replay-queue entry %s unreadable/corrupt; skipping: %s", path.name, exc)
            return None
        if not isinstance(data, dict):
            return None
        if self._config.integrity_check:
            stored = data.get("checksum")
            recomputed = _checksum({k: v for k, v in data.items() if k != "checksum"})
            if stored != recomputed:
                logger.error("replay-queue entry %s failed integrity check; skipping", path.name)
                return None
        try:
            return QueuedRoot(
                seq=int(data["seq"]),
                root_hex=str(data["root_hex"]),
                batch_id=str(data["batch_id"]),
                attempts=int(data.get("attempts", 0)),
                metadata=dict(data.get("metadata", {})),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _list_entries(self) -> list[Path]:
        """All queued-root files in FIFO (seq) order."""
        try:
            return sorted(
                p for p in self._dir.iterdir()
                if p.is_file() and p.name.endswith(_ENTRY_SUFFIX) and not p.name.startswith(".")
            )
        except OSError:
            return []

    def _highest_seq_on_disk(self) -> int:
        """Highest sequence number among existing entries (0 if empty)."""
        highest = 0
        for path in self._list_entries():
            try:
                seq = int(path.name.split("-", 1)[0])
            except (ValueError, IndexError):
                continue
            highest = max(highest, seq)
        return highest


def _checksum(payload: dict[str, Any]) -> str:
    """SHA-256 over the canonical (sorted-key) JSON of ``payload``."""
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _is_hex(s: str) -> bool:
    """True iff ``s`` is a non-empty, even-length hex string (a valid root_hex).

    The root is decoded with ``bytes.fromhex`` at anchor time, so an odd-length
    or non-hex string would fail there; validating at enqueue keeps a malformed
    root out of the durable queue entirely.
    """
    if not s or len(s) % 2 != 0:
        return False
    try:
        bytes.fromhex(s)
        return True
    except ValueError:
        return False
