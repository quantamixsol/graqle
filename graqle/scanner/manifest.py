"""Incremental scan manifest — tracks which documents have been scanned.

The :class:`ScanManifest` persists a JSON file mapping document paths to
their last-known state (mtime, size, content hash, resulting node IDs).
Before scanning a file the caller checks :meth:`needs_scan`; after a
successful scan it calls :meth:`update`.  When a previously scanned file
is deleted, :meth:`remove_stale` returns the orphaned node IDs so the
caller can clean up the graph.

File: ``.graqle-doc-manifest.json`` (next to the graph file).
"""

# ── graqle:intelligence ──
# module: graqle.scanner.manifest
# risk: MEDIUM (impact radius: 3 modules)
# consumers: docs, test_doc_chain, test_manifest
# dependencies: __future__, hashlib, json, logging, os +4 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.scanner.manifest")

_DEFAULT_MANIFEST_NAME = ".graqle-doc-manifest.json"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class FileEntry:
    """Metadata snapshot for one scanned document file.

    Attributes
    ----------
    mtime:
        Last modification time at scan time (``os.path.getmtime``).
    size:
        File size in bytes at scan time.
    sha256:
        SHA-256 hex digest of the file content at scan time.
    scanned_at:
        Unix timestamp of when the scan was performed.
    node_ids:
        List of graph node IDs that were created from this file.
    format:
        Canonical format name (``"pdf"``, ``"markdown"``, etc.).
    parse_errors:
        Any non-fatal warnings from parsing (empty if clean).
    """

    mtime: float
    size: int
    sha256: str
    scanned_at: float
    node_ids: list[str] = field(default_factory=list)
    format: str = ""
    parse_errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


class ScanManifest:
    """Persistent incremental-scan manifest backed by a JSON file.

    Parameters
    ----------
    manifest_path:
        Absolute path to the manifest JSON file.  Created on first
        :meth:`save` if it does not already exist.
    """

    def __init__(self, manifest_path: str | Path) -> None:
        self._path = Path(manifest_path)
        self._entries: dict[str, FileEntry] = {}
        if self._path.is_file():
            self._load()

    # -- persistence --------------------------------------------------------

    def _load(self) -> None:
        """Load entries from the manifest file on disk."""
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for key, val in raw.items():
                self._entries[key] = FileEntry(**val)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning("Corrupt manifest %s — resetting: %s", self._path, exc)
            self._entries = {}

    def save(self) -> None:
        """Persist the current manifest to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: asdict(v) for k, v in self._entries.items()}
        self._path.write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8"
        )

    # -- query API ----------------------------------------------------------

    @property
    def entries(self) -> dict[str, FileEntry]:
        """Return a copy of all entries."""
        return dict(self._entries)

    def has_entry(self, rel_path: str) -> bool:
        """Return ``True`` if *rel_path* has been scanned before."""
        return rel_path in self._entries

    def get_entry(self, rel_path: str) -> FileEntry | None:
        """Return the :class:`FileEntry` for *rel_path* or ``None``."""
        return self._entries.get(rel_path)

    def needs_scan(self, rel_path: str, file_path: Path) -> bool:
        """Decide whether *file_path* needs (re-)scanning.

        A file needs scanning when:
        * It has never been scanned.
        * Its mtime or size differs from the last scan.

        Note: A full SHA-256 check is *not* performed here for speed.
        The hash is recorded at scan time for deduplication, not for the
        needs-scan decision.

        Parameters
        ----------
        rel_path:
            Relative (normalised) path used as the manifest key.
        file_path:
            Absolute path to the actual file on disk.
        """
        entry = self._entries.get(rel_path)
        if entry is None:
            return True
        try:
            stat = file_path.stat()
        except OSError:
            return True
        return stat.st_mtime != entry.mtime or stat.st_size != entry.size

    # -- mutation API -------------------------------------------------------

    def update(
        self,
        rel_path: str,
        file_path: Path,
        node_ids: list[str],
        fmt: str = "",
        parse_errors: list[str] | None = None,
    ) -> FileEntry:
        """Record a successful scan of *file_path*.

        Parameters
        ----------
        rel_path:
            Normalised manifest key.
        file_path:
            Absolute path on disk (used for stat + hash).
        node_ids:
            Graph node IDs created from this file.
        fmt:
            Format tag (``"pdf"``, ``"markdown"``, etc.).
        parse_errors:
            Non-fatal parse warnings.

        Returns
        -------
        FileEntry
            The newly created / updated entry.
        """
        stat = file_path.stat()
        sha = _sha256_file(file_path)
        entry = FileEntry(
            mtime=stat.st_mtime,
            size=stat.st_size,
            sha256=sha,
            scanned_at=time.time(),
            node_ids=list(node_ids),
            format=fmt,
            parse_errors=list(parse_errors or []),
        )
        self._entries[rel_path] = entry
        return entry

    def remove(self, rel_path: str) -> FileEntry | None:
        """Remove a single entry and return it (or ``None``)."""
        return self._entries.pop(rel_path, None)

    def remove_stale(self, base_dir: Path) -> dict[str, list[str]]:
        """Find entries whose files no longer exist on disk.

        Returns a mapping ``{rel_path: [node_id, ...]}`` of orphaned
        entries.  The entries are **removed** from the manifest (caller
        should :meth:`save` afterward).

        Parameters
        ----------
        base_dir:
            The root directory used to resolve *rel_path* to an absolute
            path.
        """
        stale: dict[str, list[str]] = {}
        keys_to_remove: list[str] = []

        for rel_path, entry in self._entries.items():
            abs_path = base_dir / rel_path
            if not abs_path.is_file():
                stale[rel_path] = list(entry.node_ids)
                keys_to_remove.append(rel_path)

        for key in keys_to_remove:
            del self._entries[key]

        return stale

    def file_count(self) -> int:
        """Return the number of tracked files."""
        return len(self._entries)

    def total_nodes(self) -> int:
        """Return total node count across all tracked files."""
        return sum(len(e.node_ids) for e in self._entries.values())

    def clear(self) -> None:
        """Remove all entries (does **not** delete the file)."""
        self._entries.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: Path, chunk_size: int = 65536) -> str:
    """Return the SHA-256 hex digest of a file, reading in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
