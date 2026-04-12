"""graq_apply â deterministic insertion engine .

A first-class governed alternative to graq_edit for files where LLM-generated
diffs are unreliable: CRITICAL hub modules, large files (>1500 lines), files
with multiple lookalike methods (e.g. from_json/from_neo4j/to_neo4j sharing
similar docstring-close + import-line patterns).

The engine eliminates the LLM from the diff loop. The caller provides exact
byte-string anchors and replacements; the engine performs Python's
deterministic ``bytes.replace()`` and atomic write. Unchanged regions of the
file are byte-copied verbatim â there is no LLM regeneration, so the only
risk surface is the caller's anchor strings.

Implementation of the Deterministic Insertion Pattern documented in
.gcc/RUNBOOK-LARGE-FILE-EDITS.md and the spec in
.gcc/OPEN-TRACKER-CAPABILITY-GAPS.md.

Public API
----------
apply_insertions(file_path, insertions, *, expected_input_sha256=None,
                 expected_byte_delta_band=None, expected_markers=None,
                 dry_run=True) -> ApplyResult

ApplyResult â dataclass with structured fields for the MCP tool layer.

Error codes (machine-readable):
    GRAQ_APPLY_FILE_NOT_FOUND
    GRAQ_APPLY_SHA_MISMATCH
    GRAQ_APPLY_ANCHOR_NOT_FOUND
    GRAQ_APPLY_ANCHOR_NOT_UNIQUE
    GRAQ_APPLY_BYTE_DELTA_OUT_OF_BAND
    GRAQ_APPLY_MARKER_COUNT_MISMATCH
    GRAQ_APPLY_POST_WRITE_VERIFY
    GRAQ_APPLY_INVALID_INSERTION
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ApplyResult:
    """Structured result of a graq_apply call.

    Mirrors graq_edit's result shape for consistent MCP tool responses.
    """

    success: bool = False
    file_path: str = ""
    dry_run: bool = True
    bytes_before: int = 0
    bytes_after: int = 0
    byte_delta: int = 0
    insertions_applied: int = 0
    sha256_before: str = ""
    sha256_after: str = ""
    backup_path: str = ""
    error: str = ""
    error_code: str = ""
    marker_counts: dict = field(default_factory=dict)
    anchor_check: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# Stable, machine-readable error codes
ERR_FILE_NOT_FOUND = "GRAQ_APPLY_FILE_NOT_FOUND"
ERR_SHA_MISMATCH = "GRAQ_APPLY_SHA_MISMATCH"
ERR_ANCHOR_NOT_FOUND = "GRAQ_APPLY_ANCHOR_NOT_FOUND"
ERR_ANCHOR_NOT_UNIQUE = "GRAQ_APPLY_ANCHOR_NOT_UNIQUE"
ERR_BYTE_DELTA_OUT_OF_BAND = "GRAQ_APPLY_BYTE_DELTA_OUT_OF_BAND"
ERR_MARKER_COUNT_MISMATCH = "GRAQ_APPLY_MARKER_COUNT_MISMATCH"
ERR_POST_WRITE_VERIFY = "GRAQ_APPLY_POST_WRITE_VERIFY"
ERR_INVALID_INSERTION = "GRAQ_APPLY_INVALID_INSERTION"


def _to_bytes(value: Any) -> bytes:
    """Coerce a string-or-bytes value to bytes (UTF-8 if string)."""
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    raise TypeError(
        f"graq_apply: anchor/replacement must be str or bytes, got {type(value).__name__}"
    )


def _normalize_insertions(insertions):
    """Validate and normalize the insertions list.

    Each entry must have:
      - anchor: str | bytes (required, non-empty)
      - replacement: str | bytes (required)
      - expected_count: int (optional, default 1)
    """
    if not isinstance(insertions, list):
        raise ValueError("insertions must be a list of dicts")
    if not insertions:
        raise ValueError("insertions list is empty")

    normalized = []
    for i, entry in enumerate(insertions):
        if not isinstance(entry, dict):
            raise ValueError(f"insertions[{i}] is not a dict")
        if "anchor" not in entry:
            raise ValueError(f"insertions[{i}] missing required anchor field")
        if "replacement" not in entry:
            raise ValueError(f"insertions[{i}] missing required replacement field")
        anchor_b = _to_bytes(entry["anchor"])
        replacement_b = _to_bytes(entry["replacement"])
        if len(anchor_b) == 0:
            raise ValueError(f"insertions[{i}] anchor is empty")
        expected_count = int(entry.get("expected_count", 1))
        if expected_count < 1:
            raise ValueError(
                f"insertions[{i}] expected_count must be >= 1, got {expected_count}"
            )
        normalized.append(
            {
                "index": i,
                "anchor": anchor_b,
                "replacement": replacement_b,
                "expected_count": expected_count,
            }
        )
    return normalized


def _atomic_write(target: Path, content: bytes) -> None:
    """Write content to target atomically via tempfile + fsync + os.replace."""
    target_dir = str(target.parent.resolve()) if str(target.parent) else "."
    if not target_dir:
        target_dir = "."
    fd, tmp_path = tempfile.mkstemp(dir=target_dir, prefix=".graq_apply_", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp_path, str(target))
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


def _backup(target: Path) -> str:
    """Save a backup copy of target to .graqle/edit-backup/ and return the path."""
    backup_dir = Path(".graqle") / "edit-backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    backup_path = backup_dir / f"{ts}_{target.name}.bak"
    backup_path.write_bytes(target.read_bytes())
    return str(backup_path)


def apply_insertions(
    file_path,
    insertions,
    *,
    expected_input_sha256=None,
    expected_byte_delta_band=None,
    expected_markers=None,
    dry_run=True,
):
    """Apply deterministic exact-string insertions to a file.

    Parameters
    ----------
    file_path:
        Target file path (relative to cwd or absolute).
    insertions:
        List of insertion dicts. Each dict has keys:
          - anchor: str | bytes â the existing content to replace
          - replacement: str | bytes â the new content
          - expected_count: int â anchor uniqueness requirement (default 1)
    expected_input_sha256:
        Optional SHA-256 of the expected input file. If actual differs,
        abort with SHA_MISMATCH. Use to pin against a known baseline.
    expected_byte_delta_band:
        Optional (min, max) tuple. Post-apply byte delta must fall within
        this range or abort. Sanity check against runaway diffs.
    expected_markers:
        Optional dict mapping marker bytes/strings to their expected count
        in the post-apply file. Verifies the apply landed in the right place.
    dry_run:
        If True (default), validate everything but do NOT write to disk.

    Returns
    -------
    ApplyResult dataclass with structured outcome fields.
    """
    target = Path(file_path)
    result = ApplyResult(file_path=str(target), dry_run=dry_run)

    # Step 1: existence check
    if not target.exists():
        result.error_code = ERR_FILE_NOT_FOUND
        result.error = f"File not found: {target}"
        return result

    # Step 2: input validation
    try:
        normalized = _normalize_insertions(insertions)
    except (ValueError, TypeError) as exc:
        result.error_code = ERR_INVALID_INSERTION
        result.error = str(exc)
        return result

    # Step 3: read + hash baseline
    original = target.read_bytes()
    result.bytes_before = len(original)
    result.sha256_before = hashlib.sha256(original).hexdigest()

    # Step 4: optional baseline pin
    if expected_input_sha256 is not None and result.sha256_before != expected_input_sha256:
        result.error_code = ERR_SHA_MISMATCH
        result.error = (
            f"Input SHA mismatch. Expected {expected_input_sha256}, "
            f"got {result.sha256_before}. File has changed since baseline was captured."
        )
        return result

    # Step 5: apply each insertion sequentially with uniqueness checks
    current = original
    for entry in normalized:
        anchor = entry["anchor"]
        replacement = entry["replacement"]
        expected_count = entry["expected_count"]
        actual_count = current.count(anchor)
        result.anchor_check.append(
            {
                "index": entry["index"],
                "expected_count": expected_count,
                "actual_count": actual_count,
                "anchor_preview": anchor[:80].decode("utf-8", errors="replace"),
            }
        )

        if actual_count == 0:
            result.error_code = ERR_ANCHOR_NOT_FOUND
            result.error = (
                f"Insertion #{entry['index']} anchor not found in file. "
                f"Anchor preview: {anchor[:80]!r}"
            )
            return result
        if actual_count != expected_count:
            result.error_code = ERR_ANCHOR_NOT_UNIQUE
            result.error = (
                f"Insertion #{entry['index']} anchor count mismatch: "
                f"expected {expected_count}, got {actual_count}. "
                f"Pick a more unique anchor (longer or with surrounding context)."
            )
            return result

        current = current.replace(anchor, replacement, expected_count)
        result.insertions_applied += 1

    # Step 6: post-apply byte delta sanity check
    result.bytes_after = len(current)
    result.byte_delta = result.bytes_after - result.bytes_before
    if expected_byte_delta_band is not None:
        min_delta, max_delta = expected_byte_delta_band
        if result.byte_delta < min_delta or result.byte_delta > max_delta:
            result.error_code = ERR_BYTE_DELTA_OUT_OF_BAND
            result.error = (
                f"Byte delta {result.byte_delta} outside expected band "
                f"[{min_delta}, {max_delta}]."
            )
            return result

    # Step 7: marker count assertions
    if expected_markers is not None:
        for marker_str, expected_count in expected_markers.items():
            marker_b = _to_bytes(marker_str)
            actual_count = current.count(marker_b)
            key = (
                marker_str
                if isinstance(marker_str, str)
                else marker_str.decode("utf-8", "replace")
            )
            result.marker_counts[key] = actual_count
            if actual_count != expected_count:
                result.error_code = ERR_MARKER_COUNT_MISMATCH
                result.error = (
                    f"Marker count mismatch for {marker_str!r}: "
                    f"expected {expected_count}, got {actual_count}."
                )
                return result

    # Step 8: dry-run early exit
    if dry_run:
        result.success = True
        result.sha256_after = hashlib.sha256(current).hexdigest()
        return result

    # Step 9: backup + atomic write + post-write verification
    try:
        result.backup_path = _backup(target)
    except OSError as exc:
        result.error_code = ERR_FILE_NOT_FOUND
        result.error = f"Backup write failed: {exc}"
        return result

    try:
        _atomic_write(target, current)
    except OSError as exc:
        result.error_code = ERR_POST_WRITE_VERIFY
        result.error = f"Atomic write failed: {exc}"
        return result

    # Re-read and verify
    verify = target.read_bytes()
    if verify != current:
        result.error_code = ERR_POST_WRITE_VERIFY
        result.error = (
            "Post-write verification failed: file on disk does not match "
            "expected content. The original has been preserved in the backup."
        )
        return result

    result.success = True
    result.sha256_after = hashlib.sha256(verify).hexdigest()
    return result
