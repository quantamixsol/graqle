"""Exactly-once billing dedupe store, WAL-backed (WS-B B3).

The dedupe store is the **single authoritative source of billable events**: a
:class:`MeterEvent` is recorded to the downstream :class:`~graqle.metering.events.MeterSink`
**iff** its ``idempotency_key`` (the proof's Merkle ``leaf_hash`` hex) has not
been seen before. Because that key is identical at both count points (the
runtime ``AttestationSink`` path and the Layer-5 ``Committer`` batch path) and
stable across retries, this gives exactly-once billing under:

* **retry** — the same anchor re-emitted after a transient downstream failure;
* **dual-path** — a proof that flows through *both* count points;
* **crash-mid-write** — durability via the same WAL discipline the Layer-5
  batcher uses (temp → ``fsync`` → atomic ``os.replace`` → directory ``fsync`` →
  post-write zero-length check), with on-recovery content validation.

This module deliberately mirrors ``graqle.governance.tamper_evidence.batcher``'s
WAL implementation rather than inventing a new one: the key is already a 64-char
SHA-256 hex (a ``leaf_hash``), so the same path-traversal guard, DoS size cap,
and corruption-skip recovery apply unchanged. Pure stdlib — no proprietary or
network dependency, ships in Community.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

__all__ = ["MeterDedupeError", "MeterDedupeStore"]

logger = logging.getLogger(__name__)

# A ledger entry filename is ``<idempotency-key>.meter.json``. A distinct suffix
# from the batcher's ``.wal.json`` so the two stores can never collide even if an
# operator points them at the same directory by mistake.
_LEDGER_SUFFIX = ".meter.json"

# An idempotency key is the hex of a SHA-256 digest (a leaf_hash): exactly 64
# lowercase hex chars. Enforced on EVERY key that becomes a path segment — even
# one reconstructed from an on-disk filename during recovery, which must never be
# trusted to be well-formed (path-traversal defence-in-depth, mirrors batcher).
_KEY_LEN = 64
_HEX_DIGITS = frozenset("0123456789abcdef")

# Hard cap on a single on-disk ledger entry's size, read during crash recovery.
# A meter ledger entry is tiny (key + edition + a few metadata fields), so 1 MiB
# is generous headroom while still refusing a maliciously oversized or corrupt
# entry that could exhaust memory on read (DoS guard).
_MAX_LEDGER_ENTRY_BYTES = 1 * 1024 * 1024


class MeterDedupeError(Exception):
    """Raised for dedupe-store operations that cannot proceed safely."""


def _is_valid_key(key: str) -> bool:
    """True iff ``key`` is a well-formed SHA-256 hex idempotency key.

    Rejects anything that could escape the ledger directory as a path segment
    (``..``, ``/``, ``\\``, absolute prefixes) since none of those are lowercase
    hex of length 64. This is the structural half of the path-traversal guard.
    """
    return len(key) == _KEY_LEN and not (set(key) - _HEX_DIGITS)


def _safe_dir_fsync(dir_path: Path) -> None:
    """Best-effort durable-rename guarantee: fsync the directory on POSIX.

    After ``os.replace`` the file's *data* is durable (it was fsync'd before the
    rename), but on POSIX the *rename* itself is only durable once the containing
    directory's metadata is fsync'd. On Windows there is no portable
    directory-fsync, and file-level fsync already provides adequate durability
    for the rename, so this is a no-op there. A failed dir-fsync must never turn
    a successful, already-recorded dedupe entry into a raised exception.
    """
    if os.name != "posix":
        return
    fd = None
    try:
        fd = os.open(str(dir_path), os.O_RDONLY)
        os.fsync(fd)
    except OSError as exc:
        logger.warning("meter-dedupe directory fsync failed for %s: %s", dir_path, exc)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


class MeterDedupeStore:
    """Durable, thread-safe, exactly-once gate keyed on the proof ``leaf_hash``.

    Usage::

        store = MeterDedupeStore(directory)
        if store.mark_if_new(event.idempotency_key):
            sink.record(event)   # first time only

    :meth:`mark_if_new` returns ``True`` exactly once per key (the caller then
    bills), ``False`` on every subsequent call for the same key (no-op). The
    durable WAL entry is written *before* ``True`` is returned, so a crash after
    billing can never re-bill, and a crash before the entry is durable simply
    re-bills on retry — never silently drops a billable event.

    Parameters
    ----------
    directory:
        Where ledger entries live. Created if absent. One file per recorded key.
    digest:
        Optional integrity checksum carried inside each entry (sentinel MAJOR:
        "WAL carries integrity checksums + corruption recovery"). On recovery the
        stored digest is recomputed from the entry's own fields; a mismatch marks
        the entry corrupt and it is skipped (left on disk for inspection), never
        trusted as a recorded key.
    """

    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._lock = threading.RLock()
        # In-memory mirror of recorded keys for O(1) hot-path checks. Rebuilt from
        # disk on construction so exactly-once survives a process restart.
        self._seen: set[str] = set()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._recover()

    # ---- public API -----------------------------------------------------------

    def mark_if_new(self, key: str) -> bool:
        """Atomically record ``key`` and report whether it was new.

        Returns ``True`` the first time a well-formed ``key`` is presented (the
        caller should bill), ``False`` if it was already recorded (no-op). A
        malformed key is rejected with :class:`MeterDedupeError` rather than
        silently treated as new — a key that is not a valid leaf_hash hex is a
        programming error upstream, not a billable event.
        """
        if not _is_valid_key(key):
            raise MeterDedupeError(
                f"refusing to dedupe on a malformed idempotency key "
                f"(expected {_KEY_LEN}-char lowercase hex leaf_hash)"
            )
        with self._lock:
            if key in self._seen:
                return False
            # Durably record BEFORE acknowledging "new". Ordering rationale
            # (sentinel adversarial pass):
            #   * A crash AFTER _write_entry but BEFORE self._seen.add does NOT
            #     double-bill on restart: __init__ -> _recover() reads every
            #     on-disk entry back into _seen, so the key is remembered and the
            #     next mark_if_new returns False. (proven by
            #     test_recovery_remembers_across_restart.)
            #   * If the caller's sink.record() raises AFTER this returns True,
            #     the key is already persisted, so that one proof is billed-once
            #     -> recorded-as-seen but the emit was lost (a single under-bill).
            #     This is the deliberate, customer-favourable trade-off: the
            #     alternative (persist AFTER a successful emit) would re-bill on
            #     every retry — over-charging is worse than a rare single
            #     under-emit, and the sink (StudioMeter, S2) owns its own durable
            #     delivery queue downstream of this gate.
            self._write_entry(key)
            self._seen.add(key)
            return True

    def has(self, key: str) -> bool:
        """True iff ``key`` has already been recorded (read-only, no write)."""
        with self._lock:
            return key in self._seen

    @property
    def count(self) -> int:
        """Number of distinct billable keys recorded (observability)."""
        with self._lock:
            return len(self._seen)

    # ---- durable persistence --------------------------------------------------

    def _ledger_path(self, key: str) -> Path:
        """Path of the ledger entry for ``key`` — the single key→path choke point.

        ``key`` must be well-formed hex (the only way a path segment could carry
        ``..`` or a separator is a malformed key), so the format guard lives here.
        """
        if not _is_valid_key(key):
            raise MeterDedupeError(
                f"refusing to build a ledger path from a malformed idempotency key "
                f"(expected {_KEY_LEN}-char lowercase hex)"
            )
        return self._dir / f"{key}{_LEDGER_SUFFIX}"

    @staticmethod
    def _entry_digest(key: str) -> str:
        """Integrity checksum bound into each entry: SHA-256 of the key itself.

        The entry is content-addressed by its key (the filename), so the digest
        is over the key — on recovery we recompute it and reject any entry whose
        stored digest disagrees (corruption / tamper guard).
        """
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def _write_entry(self, key: str) -> None:
        """Atomically + durably write one ledger entry (temp → fsync → replace).

        Mirrors ``batcher._write_wal_entry``:

        1. write to a NamedTemporaryFile in the SAME directory (so os.replace is
           an atomic intra-filesystem rename, never a cross-device copy);
        2. flush + os.fsync the fd (data hits stable storage);
        3. os.replace into the final path (atomic: a reader sees old-or-new);
        4. fsync the directory on POSIX so the rename itself is durable;
        5. verify the final file's size is non-zero (a zero-byte entry would be a
           silent truncation we must not treat as recorded).
        """
        final_path = self._ledger_path(key)
        # The exists() short-circuit is an optimisation, NOT the correctness
        # mechanism: callers reach _write_entry under self._lock (RLock held
        # across the whole mark_if_new check-write-add), so there is no in-process
        # TOCTOU window. Even out-of-process, the entry is content-addressed
        # (filename == key, body derived from key), so two writers of the same key
        # write byte-identical content and the atomic os.replace below is
        # last-writer-wins with identical bytes — never a partial/corrupt entry.
        if final_path.exists():
            return  # idempotent on disk too (defends against an in-flight retry)

        payload = json.dumps(
            {"idempotency_key": key, "digest": self._entry_digest(key)},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")

        tmp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=str(self._dir),
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
            _safe_dir_fsync(self._dir)
            try:
                if final_path.stat().st_size == 0:
                    raise MeterDedupeError(
                        f"meter ledger entry {final_path.name} is zero-length after "
                        f"write; refusing to acknowledge a corrupt billable record"
                    )
            except OSError as exc:
                raise MeterDedupeError(
                    f"meter ledger entry {final_path.name} could not be stat'd "
                    f"after write: {exc}"
                ) from exc
        finally:
            if tmp_name is not None:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass

    # ---- crash recovery -------------------------------------------------------

    def _recover(self) -> None:
        """Rebuild the in-memory seen-set from on-disk ledger entries.

        Called once from ``__init__``. A corrupt or mismatched entry is skipped
        (and left on disk for operator inspection) rather than aborting recovery —
        one bad entry must not make the store forget every other billed key (which
        would re-bill them).
        """
        try:
            entries = [
                p for p in self._dir.iterdir()
                if p.is_file() and p.name.endswith(_LEDGER_SUFFIX)
            ]
        except OSError:
            return  # no readable ledger dir => nothing to recover
        for path in entries:
            key = self._read_entry(path)
            if key is not None:
                self._seen.add(key)

    def _read_entry(self, path: Path) -> str | None:
        """Parse + validate one ledger entry. Returns the key, or None if invalid.

        Validation (mirrors ``batcher._read_wal_entry``): the stored
        ``idempotency_key`` must (a) be well-formed hex, (b) equal the filename
        stem, and (c) carry a ``digest`` equal to the recomputed checksum. Any
        mismatch means corruption/tamper — the entry is rejected (returns None)
        rather than trusted as a recorded key. The on-disk entry is size-capped
        before being read into memory (DoS guard).
        """
        try:
            if path.stat().st_size > _MAX_LEDGER_ENTRY_BYTES:
                return None  # oversized entry: skip without loading (DoS guard)
            raw = path.read_bytes()
            data = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        key = data.get("idempotency_key")
        digest = data.get("digest")
        if not isinstance(key, str) or not isinstance(digest, str):
            return None
        if not _is_valid_key(key):
            return None  # malformed key => reject (path-traversal / corruption)
        expected_stem = path.name[: -len(_LEDGER_SUFFIX)]
        if key != expected_stem:
            return None  # filename/content disagree => corrupt
        if digest != self._entry_digest(key):
            return None  # integrity checksum mismatch => corrupt / tampered
        return key
