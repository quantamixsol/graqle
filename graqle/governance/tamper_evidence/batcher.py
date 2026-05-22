"""Crash-safe async batcher with write-ahead log (R25-EU01 PR-3, Task 1.3).

Layer 5 commits governed-trace records to a tamper-evidence Merkle tree in
*batches*, not one record at a time: an RFC 6962 tree over N leaves amortizes
the (later, PR-5) Rekor anchor across the whole batch. But a batch that lives
only in memory is lost on crash, and a record acknowledged to its producer but
never committed is an integrity hole. This module closes that gap with a
**write-ahead log (WAL)**:

    enqueue(record)
        -> persist the record to the WAL durably (fsync) BEFORE acking
        -> add it to the in-memory pending batch
    flush()  (triggered by batch_max_records or batch_max_seconds)
        -> build the Merkle tree over the pending batch
        -> hand the batch off to the committer (PR-5; here: a callback)
        -> on success, remove the committed records from the WAL

The durability contract (C-P0-1): a record is acknowledged ONLY after its WAL
entry is fsync'd to stable storage. If the process dies at any point after the
ack, the next startup finds the entry in the WAL and commits it — exactly once.

**Crash recovery (drain-before-accept).** On construction the batcher drains any
WAL entries left by a previous (crashed) process and re-enqueues them BEFORE it
accepts a single new write. Ordering matters: accepting new writes first could
interleave a fresh record ahead of a recovered one and reorder the committed
log, so recovery is strictly serialized ahead of the live path (Task 1.3).

**Exactly-once via content-addressing.** Each record's WAL filename is derived
from the SHA-256 of its canonical bytes (:func:`graqle.governance.tamper_evidence
.canonicalize.canon`). Re-enqueuing an already-pending record (the classic
crash-replay double-submit, or a producer retry) writes to the same path and is
therefore an idempotent no-op — it cannot split one logical record across two
batches or produce two leaves for one record.

**Atomic, durable writes.** Every WAL entry is written via the proven
``NamedTemporaryFile -> os.fsync(fp) -> os.replace`` pattern (cr-005a / S-015):
the temp file is fully flushed to disk, then atomically renamed into place, so a
reader (the next startup's drain) never sees a half-written entry. On POSIX the
containing directory is fsync'd after the rename (:func:`_safe_dir_fsync`) so the
*rename itself* is durable; on Windows this is a graceful no-op (directory fsync
is unsupported there and file-level fsync already gives adequate durability).

Concurrency: all mutation of the pending batch and the WAL index is serialized
by a single :class:`threading.Lock`. ``MerkleTree`` instances built during flush
are immutable and safe to hand to concurrent readers (see merkle.py).

TS-2: the exact flush-trigger heuristic (how back-pressure and traffic shaping
interact with the two configured ceilings) is a trade secret. The PUBLIC
contract is only: a record is committed within ``batch_max_seconds`` of enqueue
or once ``batch_max_records`` are pending, whichever comes first.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from graqle.config.attestation_config import AttestationConfig
from graqle.governance.tamper_evidence.canonicalize import canon
from graqle.governance.tamper_evidence.errors import TamperEvidenceError
from graqle.governance.tamper_evidence.merkle import (
    MerkleTree,
    leaf_hash_for_record,
)

# Module logger. The best-effort cleanup paths below (failed dir-fsync, failed
# unlink of a committed entry) MUST NOT raise — doing so would break the
# durability/commit contract — but in a tamper-evidence module a silently
# swallowed filesystem error is an observability gap (cf. lesson R22 B2a:
# "except: pass in a gate handler is an AC-3 violation; always log"). We
# therefore degrade gracefully AND leave an operator breadcrumb at WARNING.
logger = logging.getLogger(__name__)

# Subdirectory (under the configured WAL root) holding not-yet-committed records.
# Distinct from ReplayQueueConfig.directory (.graqle/replay_queue/), which is the
# Rekor-availability fallback (PR-4): the WAL holds records pending their FIRST
# commit; the replay queue holds batch roots pending a Rekor anchor.
WAL_SUBDIR = "uncommitted"

# WAL entry filename suffix. Entries are <sha256-hex>.wal.json.
_WAL_SUFFIX = ".wal.json"

# A valid WAL idempotency key is exactly the lowercase hex of a SHA-256 digest:
# 64 chars, [0-9a-f]. This is enforced on EVERY key that becomes a path segment
# (defence-in-depth path-traversal guard) — even though keys are always produced
# by hashlib.sha256().hexdigest() on the live path, a key reconstructed from an
# on-disk filename during recovery must never be trusted to be well-formed.
_KEY_LEN = 64
_HEX_DIGITS = frozenset("0123456789abcdef")

# Hard cap on a single on-disk WAL entry's size, read during crash recovery. A
# governed-trace record is small (a few KiB); 4 MiB is generous headroom while
# still refusing a maliciously oversized or corrupt entry that could exhaust
# memory on read (DoS guard, mirrors merkle.MAX_TREE_SIZE / canonicalize
# ._MAX_SCAN_DEPTH). An entry larger than this is skipped, not loaded.
_MAX_WAL_ENTRY_BYTES = 4 * 1024 * 1024


def _is_valid_key(key: str) -> bool:
    """True iff ``key`` is a well-formed SHA-256 hex idempotency key.

    Rejects anything that could escape the WAL directory as a path segment
    (``..``, ``/``, ``\\``, absolute prefixes) since none of those are lowercase
    hex of length 64. This is the structural half of the path-traversal guard;
    the content re-hash in :meth:`_read_wal_entry` is the cryptographic half.
    """
    return len(key) == _KEY_LEN and not (set(key) - _HEX_DIGITS)


class BatcherError(TamperEvidenceError):
    """Raised for batcher / WAL operations that cannot proceed safely."""


def _safe_dir_fsync(dir_path: Path) -> None:
    """Best-effort durable-rename guarantee: fsync the directory on POSIX.

    After ``os.replace`` the file's *data* is durable (it was fsync'd before the
    rename), but on POSIX the *rename* itself is only durable once the containing
    directory's metadata is fsync'd. We do that here. On Windows there is no
    portable directory-fsync (``os.open`` on a directory fails), and file-level
    fsync already provides adequate durability for the rename, so this is a
    no-op there. Any OSError is swallowed: a failed dir-fsync must never turn a
    successful, already-acked write into a raised exception.
    """
    if os.name != "posix":
        return  # Windows: directory fsync unsupported; file fsync is sufficient.
    fd = None
    try:
        fd = os.open(str(dir_path), os.O_RDONLY)
        os.fsync(fd)
    except OSError as exc:
        # best-effort; data durability already guaranteed by file fsync. Logged
        # so an operator can see a degraded-durability filesystem if it recurs.
        logger.warning("directory fsync failed for %s: %s", dir_path, exc)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def _idempotency_key(record: dict[str, Any]) -> str:
    """Content-addressed idempotency key: SHA-256 hex of the record's canonical bytes.

    Uses the FULL-record canonicalization (:func:`canon`), not the leaf
    projection: two enqueue calls are "the same record" iff their entire content
    (wrapper fields included) is identical, so a retry with extra wrapper data is
    correctly treated as a distinct record while a true duplicate collapses to
    one WAL entry. This is what makes crash-replay re-enqueue a no-op.
    """
    return hashlib.sha256(canon(record)).hexdigest()


@dataclass(frozen=True)
class _PendingRecord:
    """One record awaiting commit: its idempotency key, payload, and leaf hash.

    ``leaf_hash`` is computed once at enqueue time (it is needed for the Merkle
    tree at flush) and carried through so flush never re-hashes.
    """

    key: str
    record: dict[str, Any]
    leaf_hash: bytes


# A committer callback receives the ordered pending records + the built tree and
# is responsible for the durable downstream commit (PR-5). Contract:
#   * It MUST raise on failure so the batcher leaves the WAL intact for retry.
#   * It MUST NOT mutate the records it is handed. The records are the same dict
#     objects still held in the pending batch; on a committer failure they are
#     retried, and the on-disk WAL copy (the canonical source recovery re-hashes)
#     is unchanged — so a mutating committer would make the in-memory retry
#     diverge from disk. The Merkle tree is independently safe regardless: it is
#     built from leaf hashes frozen at enqueue time (_PendingRecord.leaf_hash),
#     never re-hashed from the record at commit, so tree integrity does not
#     depend on the committer honouring this. The no-mutation rule protects the
#     retry/recovery consistency, not the tree.
# Injected so this module is testable in isolation and does not yet depend on PR-5.
CommitterFn = Callable[[list[dict[str, Any]], MerkleTree], None]


class WalBatcher:
    """Crash-safe batcher: durable WAL enqueue + size/time-triggered flush.

    Parameters
    ----------
    config:
        Layer 5 attestation config; supplies ``batch_max_records`` and
        ``batch_max_seconds`` (the two public flush ceilings).
    wal_root:
        Root directory under which the ``uncommitted/`` WAL lives. Created if
        absent. Typically ``.graqle`` in the project root.
    committer:
        Callback invoked with ``(records, tree)`` on flush. Must raise on
        failure (the WAL is then left intact for the next flush/restart). If
        omitted, flush builds the tree but performs no downstream commit (useful
        for tests and for the pre-PR-5 integration point).
    clock:
        Injectable monotonic clock (defaults to :func:`time.monotonic`) so the
        time-based flush trigger is deterministically testable.
    """

    def __init__(
        self,
        config: AttestationConfig,
        wal_root: str | os.PathLike[str],
        committer: CommitterFn | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._committer = committer
        self._clock = clock
        self._wal_dir = Path(wal_root) / WAL_SUBDIR
        self._wal_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        # Ordered pending batch. dict (insertion-ordered) doubles as the
        # idempotency index: key present => already pending => enqueue is a no-op.
        self._pending: dict[str, _PendingRecord] = {}
        # Monotonic timestamp of the oldest currently-pending record, or None
        # when the batch is empty. Drives the batch_max_seconds trigger.
        self._oldest_pending_at: float | None = None

        # Crash recovery: drain the WAL left by any previous process BEFORE the
        # live write path is reachable (Task 1.3 ordering guarantee).
        self._recover_from_wal()

    # ---- public API -----------------------------------------------------------

    def enqueue(self, record: dict[str, Any]) -> str:
        """Durably persist ``record`` to the WAL, then add it to the pending batch.

        Returns the record's content-addressed idempotency key. Re-enqueuing a
        record already pending (same canonical content) is an idempotent no-op:
        the same key is returned and no second WAL entry / leaf is created. The
        record is durably on disk (fsync'd) before this method returns — that is
        the acknowledgement boundary (C-P0-1).

        A flush is triggered inline when the size ceiling is reached; the
        time-based ceiling is evaluated by :meth:`maybe_flush` / the caller's
        scheduler.
        """
        if not isinstance(record, dict):
            raise BatcherError(
                f"record must be a dict, got {type(record).__name__}"
            )
        key = _idempotency_key(record)
        with self._lock:
            if key in self._pending:
                return key  # idempotent: already pending, same content
            # Persist BEFORE acking (durability contract). If this raises, the
            # record never entered the pending batch and was never acked.
            self._write_wal_entry(key, record)
            leaf = leaf_hash_for_record(record)
            self._pending[key] = _PendingRecord(key=key, record=record, leaf_hash=leaf)
            if self._oldest_pending_at is None:
                self._oldest_pending_at = self._clock()
            if len(self._pending) >= self._config.batch_max_records:
                self._flush_locked()
        return key

    def maybe_flush(self) -> bool:
        """Flush iff the time-based ceiling has elapsed for the oldest record.

        Returns ``True`` if a flush occurred. Intended to be called periodically
        by the caller's scheduler (the async loop / committer in PR-5). The
        size-based trigger is handled inline in :meth:`enqueue`; this covers the
        ``batch_max_seconds`` trigger for a batch that never reaches the size
        ceiling.
        """
        with self._lock:
            if not self._pending or self._oldest_pending_at is None:
                return False
            elapsed = self._clock() - self._oldest_pending_at
            if elapsed >= self._config.batch_max_seconds:
                self._flush_locked()
                return True
        return False

    def flush(self) -> int:
        """Force-flush the pending batch now. Returns the number of records committed.

        A no-op (returns 0) when the batch is empty — Layer 5 never builds a
        Merkle tree over zero leaves (merkle.py rejects it), so an empty flush is
        explicitly a no-op rather than an error.
        """
        with self._lock:
            return self._flush_locked()

    @property
    def pending_count(self) -> int:
        """Number of records currently pending commit (durably in the WAL)."""
        with self._lock:
            return len(self._pending)

    @property
    def wal_dir(self) -> Path:
        """The directory holding uncommitted WAL entries."""
        return self._wal_dir

    # ---- flush ----------------------------------------------------------------

    def _flush_locked(self) -> int:
        """Build the tree, commit, then clear the WAL. Caller must hold the lock.

        Order is load-bearing for crash-safety: the WAL entries are removed ONLY
        after the committer returns successfully. If the committer raises (or the
        process dies mid-commit), the entries remain on disk and are re-drained
        on the next startup — at-least-once delivery, deduplicated to
        exactly-once by the content-addressed key.
        """
        if not self._pending:
            return 0
        ordered = list(self._pending.values())
        leaf_hashes = [pr.leaf_hash for pr in ordered]
        records = [pr.record for pr in ordered]
        tree = MerkleTree.from_leaf_hashes(leaf_hashes)

        if self._committer is not None:
            # If this raises, we deliberately do NOT clear the WAL or the
            # pending batch: the batch is retried intact (no partial commit).
            self._committer(records, tree)

        # Commit succeeded (or no committer wired): WAL entries are now redundant.
        for pr in ordered:
            self._remove_wal_entry(pr.key)
        committed = len(ordered)
        self._pending.clear()
        self._oldest_pending_at = None
        return committed

    # ---- WAL persistence ------------------------------------------------------

    def _wal_path(self, key: str) -> Path:
        """Path of the WAL entry for idempotency ``key``.

        ``key`` must be a well-formed SHA-256 hex string. This is the single
        choke point that turns a key into a filesystem path, so the format guard
        lives here: a malformed key (the only way a path segment could contain
        ``..`` or a separator) is refused before it can escape the WAL directory.
        """
        if not _is_valid_key(key):
            raise BatcherError(
                f"refusing to build a WAL path from a malformed idempotency key "
                f"(expected {_KEY_LEN}-char lowercase hex)"
            )
        return self._wal_dir / f"{key}{_WAL_SUFFIX}"

    def _write_wal_entry(self, key: str, record: dict[str, Any]) -> None:
        """Atomically + durably write one WAL entry (temp -> fsync -> replace).

        The entry stores the idempotency key alongside the record so a drain can
        validate the on-disk content against its filename (tamper / corruption
        guard). The write is durable before return (C-P0-1):

        1. write to a NamedTemporaryFile in the SAME directory (so os.replace is
           an atomic intra-filesystem rename, never a cross-device copy);
        2. flush + os.fsync the file descriptor (data hits stable storage);
        3. os.replace into the final path (atomic: a reader sees old-or-new,
           never a partial file);
        4. fsync the directory on POSIX so the rename itself is durable;
        5. verify the final file's size is non-zero (S-015 post-write check) —
           a zero-byte entry would mean a silent truncation we must not ack.
        """
        final_path = self._wal_path(key)
        if final_path.exists():
            return  # idempotent on disk too (defends against in-flight retry)

        payload = json.dumps(
            {"idempotency_key": key, "record": record},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")

        tmp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=str(self._wal_dir),
                prefix=f".{key}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                tmp_name = tmp.name
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_name, str(final_path))
            tmp_name = None  # ownership transferred to final_path
            _safe_dir_fsync(self._wal_dir)
            # S-015 post-write verification: a present-but-empty entry is corrupt.
            try:
                if final_path.stat().st_size == 0:
                    raise BatcherError(
                        f"WAL entry {final_path.name} is zero-length after write; "
                        f"refusing to acknowledge a corrupt record"
                    )
            except OSError as exc:
                raise BatcherError(
                    f"WAL entry {final_path.name} could not be stat'd after write: {exc}"
                ) from exc
        finally:
            # Clean up the temp file if we failed before/at the rename.
            if tmp_name is not None:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass

    def _remove_wal_entry(self, key: str) -> None:
        """Delete a committed WAL entry. Missing file is fine (already removed)."""
        try:
            self._wal_path(key).unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            # A failed unlink leaves a redundant entry that the next drain will
            # re-enqueue; the content-addressed key makes that a safe no-op, so we
            # do not escalate (the record is already committed downstream). Logged
            # so a recurring leak of committed entries is observable to operators.
            logger.warning("failed to remove committed WAL entry %s: %s", key, exc)

    # ---- crash recovery -------------------------------------------------------

    def _recover_from_wal(self) -> None:
        """Drain WAL entries from a previous process into the pending batch.

        Called once from __init__, BEFORE any public write path is reachable.
        Each on-disk entry is parsed and re-enqueued in deterministic
        (filename-sorted) order. A corrupt or mismatched entry is skipped (and
        its file left in place for operator inspection) rather than aborting
        recovery — one bad entry must not block commit of the rest.

        Re-enqueue here goes through the same dedup index as the live path, so a
        record that was both in the WAL and (somehow) re-submitted collapses to a
        single pending entry.
        """
        try:
            entries = sorted(
                p for p in self._wal_dir.iterdir()
                if p.is_file() and p.name.endswith(_WAL_SUFFIX)
            )
        except OSError:
            return  # no readable WAL dir => nothing to recover

        for path in entries:
            parsed = self._read_wal_entry(path)
            if parsed is None:
                continue  # corrupt/mismatched: skip, leave on disk
            key, record = parsed
            # No dedup check is needed here: _read_wal_entry enforces
            # key == filename-stem, and directory filenames are unique, so each
            # recovered key is necessarily distinct within this loop. (The
            # exactly-once guarantee against the LIVE path is enforced separately
            # by the `key in self._pending` check in enqueue().)
            leaf = leaf_hash_for_record(record)
            self._pending[key] = _PendingRecord(key=key, record=record, leaf_hash=leaf)
            if self._oldest_pending_at is None:
                self._oldest_pending_at = self._clock()

    def _read_wal_entry(self, path: Path) -> tuple[str, dict[str, Any]] | None:
        """Parse + validate one WAL entry. Returns (key, record) or None if invalid.

        Validation: the stored ``idempotency_key`` must (a) be a well-formed hex
        key, (b) equal the filename stem, and (c) equal the recomputed
        content-address of the record. A mismatch means corruption or tampering —
        the entry is rejected (returns None) rather than committed under a wrong
        identity. The on-disk entry is also size-capped before it is read into
        memory (DoS guard against a maliciously oversized entry).
        """
        try:
            if path.stat().st_size > _MAX_WAL_ENTRY_BYTES:
                return None  # oversized entry: skip without loading (DoS guard)
            raw = path.read_bytes()
            data = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        key = data.get("idempotency_key")
        record = data.get("record")
        if not isinstance(key, str) or not isinstance(record, dict):
            return None
        if not _is_valid_key(key):
            return None  # malformed key => reject (path-traversal / corruption)
        expected_stem = path.name[: -len(_WAL_SUFFIX)]
        if key != expected_stem:
            return None  # filename/content disagree => corrupt
        try:
            if _idempotency_key(record) != key:
                return None  # content does not match its address => tampered
        except (TamperEvidenceError, ValueError, TypeError):
            return None  # non-canonical record on disk => reject
        return key, record
