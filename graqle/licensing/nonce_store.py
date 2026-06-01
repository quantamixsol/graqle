"""Licence nonce replay-protection store (WS-D D1c).

Each ed25519 licence carries a random ``nonce`` (see
:mod:`graqle.licensing.ed25519_license`). This store records the nonces that
have been *accepted*, so a licence token cannot be replayed after it has been
superseded/revoked: the first time a nonce is seen it is recorded and accepted;
a second presentation of the same nonce is rejected.

This deliberately mirrors the proven WAL discipline of
:class:`graqle.metering.dedupe.MeterDedupeStore` (temp → ``fsync`` → atomic
``os.replace`` → directory ``fsync`` → post-write zero-length check; integrity
digest + filename-stem validation on recovery; DoS size cap; corruption-skip).
It differs in one respect: a licence ``nonce`` is an arbitrary opaque string
(not a 64-hex digest), so the on-disk FILENAME is the SHA-256 of the nonce (a
safe, fixed-width hex stem) while the entry body stores the original nonce +
an integrity digest. Pure stdlib.

Replay semantics (single authoritative source): :meth:`accept_once` returns
``True`` exactly once per nonce (accept), ``False`` thereafter (replay). The
durable record is written BEFORE ``True`` is returned, and the in-memory set is
rebuilt from disk on startup, so a crash cannot cause a replay to be accepted
twice. (Mirrors metering's persist-before-ack + recover-on-startup.)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
from pathlib import Path

__all__ = ["NonceStoreError", "LicenseNonceStore"]

logger = logging.getLogger(__name__)

_ENTRY_SUFFIX = ".nonce.json"
# The filename stem is sha256(nonce) hex: 64 lowercase hex chars. Same structural
# path-traversal guard as the metering store (the stem is always a digest we
# computed, never attacker-controlled bytes).
_STEM_LEN = 64
_HEX_DIGITS = frozenset("0123456789abcdef")
_MAX_ENTRY_BYTES = 1 * 1024 * 1024
# A nonce longer than this is refused before hashing (defence against an absurd
# input; a real licence nonce is a short random token).
_MAX_NONCE_LEN = 4096


class NonceStoreError(Exception):
    """Raised for nonce-store operations that cannot proceed safely."""


def _stem_for(nonce: str) -> str:
    """SHA-256 hex of the nonce — the safe fixed-width filename stem."""
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def _is_valid_stem(stem: str) -> bool:
    return len(stem) == _STEM_LEN and not (set(stem) - _HEX_DIGITS)


def _safe_dir_fsync(dir_path: Path) -> None:
    """fsync the directory on POSIX so the rename is durable; no-op on Windows."""
    if os.name != "posix":
        return
    fd = None
    try:
        fd = os.open(str(dir_path), os.O_RDONLY)
        os.fsync(fd)
    except OSError as exc:
        logger.warning("nonce-store directory fsync failed for %s: %s", dir_path, exc)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


class LicenseNonceStore:
    """Durable, thread-safe, accept-once gate for licence nonces.

    Usage::

        store = LicenseNonceStore(directory)
        if not store.accept_once(license.nonce):
            raise LicenseError("licence nonce replayed")

    Parameters
    ----------
    directory:
        Where nonce records live (created if absent). One file per accepted nonce.
    """

    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._lock = threading.RLock()
        self._seen: set[str] = set()  # set of stems
        self._dir.mkdir(parents=True, exist_ok=True)
        self._recover()

    # ---- public API -----------------------------------------------------------

    def accept_once(self, nonce: str) -> bool:
        """Record ``nonce`` and report whether it was new.

        Returns ``True`` the first time a (well-formed, bounded) nonce is seen —
        the caller accepts the licence — and ``False`` on any subsequent
        presentation (a replay). A non-string or over-long nonce raises
        :class:`NonceStoreError` (a malformed nonce is a verification-layer bug,
        not a silently-accepted licence).
        """
        if not isinstance(nonce, str) or not nonce:
            raise NonceStoreError("nonce must be a non-empty string")
        if len(nonce) > _MAX_NONCE_LEN:
            raise NonceStoreError(
                f"nonce exceeds {_MAX_NONCE_LEN} chars; refusing (suspicious input)"
            )
        stem = _stem_for(nonce)
        with self._lock:
            if stem in self._seen:
                return False
            self._write_entry(stem, nonce)  # durable BEFORE acknowledging "new"
            self._seen.add(stem)
            return True

    def has_seen(self, nonce: str) -> bool:
        """True iff ``nonce`` has already been accepted (read-only)."""
        if not isinstance(nonce, str) or not nonce or len(nonce) > _MAX_NONCE_LEN:
            return False
        with self._lock:
            return _stem_for(nonce) in self._seen

    @property
    def count(self) -> int:
        """Number of distinct accepted nonces (observability)."""
        with self._lock:
            return len(self._seen)

    # ---- durable persistence --------------------------------------------------

    def _entry_path(self, stem: str) -> Path:
        if not _is_valid_stem(stem):
            raise NonceStoreError("refusing to build a path from a malformed stem")
        return self._dir / f"{stem}{_ENTRY_SUFFIX}"

    @staticmethod
    def _entry_digest(stem: str, nonce: str) -> str:
        """Integrity checksum binding the stem to the stored nonce."""
        return hashlib.sha256((stem + ":" + nonce).encode("utf-8")).hexdigest()

    def _write_entry(self, stem: str, nonce: str) -> None:
        """Atomically + durably write one nonce entry (temp → fsync → replace)."""
        final_path = self._entry_path(stem)
        if final_path.exists():
            return  # idempotent on disk (in-flight retry)
        payload = json.dumps(
            {"stem": stem, "nonce": nonce, "digest": self._entry_digest(stem, nonce)},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        tmp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=str(self._dir), prefix=f".{stem}.", suffix=".tmp", delete=False
            ) as tmp:
                tmp_name = tmp.name
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_name, str(final_path))
            tmp_name = None
            _safe_dir_fsync(self._dir)
            try:
                if final_path.stat().st_size == 0:
                    raise NonceStoreError(
                        f"nonce entry {final_path.name} is zero-length after write"
                    )
            except OSError as exc:
                raise NonceStoreError(
                    f"nonce entry {final_path.name} could not be stat'd after write: {exc}"
                ) from exc
        finally:
            if tmp_name is not None:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass

    # ---- crash recovery -------------------------------------------------------

    def _recover(self) -> None:
        """Rebuild the in-memory seen-set from on-disk entries (corrupt => skip)."""
        try:
            entries = [
                p for p in self._dir.iterdir()
                if p.is_file() and p.name.endswith(_ENTRY_SUFFIX)
            ]
        except OSError:
            return
        for path in entries:
            stem = self._read_entry(path)
            if stem is not None:
                self._seen.add(stem)

    def _read_entry(self, path: Path) -> str | None:
        """Parse + validate one entry. Returns the stem, or None if invalid."""
        try:
            if path.stat().st_size > _MAX_ENTRY_BYTES:
                return None
            data = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        stem = data.get("stem")
        nonce = data.get("nonce")
        digest = data.get("digest")
        if not (isinstance(stem, str) and isinstance(nonce, str) and isinstance(digest, str)):
            return None
        if not _is_valid_stem(stem):
            return None
        if stem != path.name[: -len(_ENTRY_SUFFIX)]:
            return None  # filename/content mismatch => corrupt
        if stem != _stem_for(nonce):
            return None  # stem must be sha256(nonce) — else tampered
        if digest != self._entry_digest(stem, nonce):
            return None  # integrity checksum mismatch => corrupt/tampered
        return stem
