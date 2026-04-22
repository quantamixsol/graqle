"""CG-15 KG-write gate + G4 protected_paths policy (Wave 2 Phase 4).

Two SEPARATE helpers with no coupling:

  check_kg_block(file_path) -> (allowed, envelope)
    CG-15: hard fail-fast block on KG files (graqle.json, graqle.json.*.bak,
    graqle_*.json). ZERO bypass. No approval. No auth context. Pure function
    of the path alone. Only graq_learn and graq_grow legitimately write these
    (they use separate handlers and naturally bypass this gate).

  check_protected_path(file_path, *, config, approved_by, auditor) -> (allowed, envelope)
    G4: approval-gated block on user-configured protected paths. Approval via
    either (a) non-empty caller-asserted approved_by (advisory trust model,
    MCP transport auth is the enforcement layer) OR (b) CG-14 ConfigDriftAuditor
    reports baseline-clean (no drift) for the file.

Precedence when called sequentially from a handler:
  1. check_kg_block first (stricter, no bypass)
  2. check_protected_path second (approval-aware)

Path normalization:
  All paths normalized to PurePosixPath with forward slashes for matching.
  CG-15 matches on BASENAME only (case-sensitive on POSIX, case-insensitive
  on Windows via lowercase folding).
  G4 matches on FULL RELATIVE PATH via fnmatch for glob support.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from graqle.config.settings import GraqleConfig
    from graqle.governance.config_drift import ConfigDriftAuditor

from graqle.governance.config_drift import build_error_envelope

logger = logging.getLogger("graqle.governance.kg_write_gate")


# ─────────────────────────────────────────────────────────────────────────
# CG-15: KG file matcher
# ─────────────────────────────────────────────────────────────────────────

_KG_FILENAME = "graqle.json"
_APPROVER_MIN_LEN = 3


def _normalize_basename(file_path: str | os.PathLike) -> str:
    """Extract lowercased basename from any path form.

    Handles: POSIX ("/foo/bar.json"), Windows ("C:\\foo\\bar.json"),
    UNC ("\\\\server\\share\\bar.json"), mixed separators, PathLike objects.

    Raises:
        TypeError: non-string, non-PathLike input
        ValueError: empty string
    """
    if isinstance(file_path, (str, os.PathLike)):
        s = os.fspath(file_path)
    else:
        raise TypeError(f"file_path must be str or PathLike, got {type(file_path).__name__}")
    if not s or not s.strip():
        raise ValueError("file_path must be non-empty")
    # Normalize separators to forward slash
    normalized = s.replace("\\", "/")
    # Take last segment after final /
    basename = normalized.rsplit("/", 1)[-1]
    if not basename:
        raise ValueError(f"file_path yielded empty basename: {file_path!r}")
    return basename.lower()


def _is_kg_file(file_path: str | os.PathLike) -> bool:
    """True if the basename matches a KG file pattern.

    Matches (case-insensitive basename):
      - "graqle.json" (exact)
      - "graqle.json.<anything>.bak" (backups)
      - "graqle_<anything>.json" (corrupt/snapshot variants)

    Explicit non-matches:
      - "mygraqle.json" (prefix mismatch)
      - "graqle.yaml" (extension mismatch)
      - "graqle.json.keep" (non-.bak suffix)
    """
    try:
        name = _normalize_basename(file_path)
    except (TypeError, ValueError):
        return False
    if name == _KG_FILENAME:
        return True
    # Backup variants: starts with "graqle.json." AND ends with ".bak"
    if name.startswith(_KG_FILENAME + ".") and name.endswith(".bak"):
        return True
    # Corrupt/snapshot: starts with "graqle_" AND ends with ".json"
    if name.startswith("graqle_") and name.endswith(".json"):
        return True
    return False


def check_kg_block(file_path: str | os.PathLike) -> tuple[bool, dict | None]:
    """CG-15: Check if a write target is a KG file (hard block, no bypass).

    Pure function. Takes ONLY the path. No auth context, no approval, no
    auditor. This decoupling is deliberate: CG-15 is an absolute policy.

    Returns:
        (True, None) if the write is NOT a KG file — caller may proceed.
        (False, envelope) if the write IS a KG file — blocked.

    Never raises on valid input; invalid types/empty strings return allowed
    (downstream validation will catch those).
    """
    try:
        if not _is_kg_file(file_path):
            return (True, None)
    except Exception as exc:
        # Defensive: if matcher itself fails, let the downstream handler
        # surface the real error (don't block on our own bug)
        logger.debug("CG-15 matcher raised %s, allowing pass-through", exc)
        return (True, None)

    # BLOCKED
    envelope = build_error_envelope(
        "CG-15_KG_WRITE_BLOCKED",
        "Direct writes to KG files are blocked. "
        "Use graq_learn or graq_grow for knowledge graph mutations.",
        file_path=str(file_path),
        suggestion=(
            "graq_learn(mode='outcome'|'entity'|'knowledge') or graq_grow "
            "are the governed writers for graqle.json and its backups."
        ),
    )
    return (False, envelope)


# ─────────────────────────────────────────────────────────────────────────
# G4: Protected paths policy
# ─────────────────────────────────────────────────────────────────────────

# Default CG-14 protected files are also G4 defaults; merged at runtime.
_CG_14_DEFAULT_PROTECTED_PATHS: tuple[str, ...] = (
    "graqle.yaml",
    "pyproject.toml",
    ".mcp.json",
    ".claude/settings.json",
)


def _merged_protected_patterns(config: "GraqleConfig | None") -> list[str]:
    """Deterministic merge of CG-14 defaults + user's config.protected_paths.

    Order:
      1. CG-14 defaults in declaration order
      2. User patterns from config.protected_paths in declaration order
    Duplicates removed preserving first occurrence.
    Non-string, empty, whitespace-only entries skipped with debug log.

    All non-empty strings are accepted as patterns (fnmatch syntax).
    """
    user_patterns: list[Any] = []
    if config is not None:
        user_patterns = list(getattr(config, "protected_paths", []) or [])

    seen: set[str] = set()
    merged: list[str] = []
    for raw in list(_CG_14_DEFAULT_PROTECTED_PATHS) + user_patterns:
        if not isinstance(raw, str):
            logger.debug("G4: skipping non-string protected_path %r", raw)
            continue
        p = raw.strip()
        if not p:
            logger.debug("G4: skipping empty protected_path")
            continue
        if p not in seen:
            seen.add(p)
            merged.append(p)
    return merged


def _normalize_relative_path(file_path: str | os.PathLike) -> str | None:
    """Normalize a path to forward-slash form for pattern matching.

    Returns the path as a POSIX-style string (e.g. "deploy/prod/app.yml").
    Absolute paths are converted to basenames (can't match relative patterns).

    Returns None on invalid input — caller should then allow (no match).
    """
    try:
        s = os.fspath(file_path)
    except TypeError:
        return None
    if not s or not s.strip():
        return None
    normalized = s.strip().replace("\\", "/")
    # Strip leading slash — treat as relative
    while normalized.startswith("/"):
        normalized = normalized[1:]
    # Strip Windows drive letter (e.g. "c:/foo/bar" -> "foo/bar")
    if len(normalized) >= 2 and normalized[1] == ":":
        normalized = normalized[2:]
        while normalized.startswith("/"):
            normalized = normalized[1:]
    return normalized or None


def _path_matches_pattern(normalized_path: str, pattern: str) -> bool:
    """Match a normalized forward-slash path against an fnmatch-style pattern.

    Uses PurePosixPath.match for platform-independent glob semantics.
    Supports `*`, `?`, `[seq]`, and path segments. For `**` recursive
    matching, Path.match handles the standard pathlib semantics.
    """
    try:
        # PurePosixPath.match is consistent across platforms
        return PurePosixPath(normalized_path).match(pattern) or PurePosixPath(
            normalized_path
        ).match("**/" + pattern) or PurePosixPath(normalized_path).match(
            pattern + "/**"
        )
    except Exception as exc:
        logger.debug("G4: match failed for pattern %r vs %r: %s", pattern, normalized_path, exc)
        return False


def _approval_is_valid(approved_by: Any) -> bool:
    """Caller-asserted approval validation (advisory trust model).

    Requires:
      - type is str
      - stripped length >= _APPROVER_MIN_LEN (default 3)

    Authentication of the approver identity happens at the MCP transport
    layer. This helper only rejects trivially invalid values.
    """
    if not isinstance(approved_by, str):
        return False
    stripped = approved_by.strip()
    return len(stripped) >= _APPROVER_MIN_LEN


def _auditor_reports_clean(
    auditor: "ConfigDriftAuditor | None",
    file_path: str,
) -> bool:
    """True if the ConfigDriftAuditor reports no drift for this file.

    Fail-closed: if auditor is None or raises, returns False (no auto-allow).
    """
    if auditor is None:
        return False
    try:
        records = auditor.audit()
    except Exception as exc:
        logger.debug("G4: auditor.audit() raised %s, treating as drifted", exc)
        return False
    # Clean = no drift records referencing this path
    for r in records:
        if r.file_path == file_path:
            return False
    return True


def check_protected_path(
    file_path: str | os.PathLike,
    *,
    config: "GraqleConfig | None" = None,
    approved_by: str | None = None,
    auditor: "ConfigDriftAuditor | None" = None,
) -> tuple[bool, dict | None]:
    """G4: Check if a write requires approval under protected_paths policy.

    Approval granted if ANY of:
      - File does not match any protected pattern (no policy applies)
      - Caller-asserted approved_by is valid (advisory)
      - CG-14 ConfigDriftAuditor reports the file as clean (baseline-accepted)

    Returns:
        (True, None) if allowed.
        (False, envelope) if blocked.
    """
    normalized = _normalize_relative_path(file_path)
    if normalized is None:
        # Invalid path — let downstream handler surface the real error
        return (True, None)

    patterns = _merged_protected_patterns(config)
    matched_pattern: str | None = None
    for p in patterns:
        if _path_matches_pattern(normalized, p) or normalized == p:
            matched_pattern = p
            break

    if matched_pattern is None:
        return (True, None)  # no policy applies

    # Match found — check approval paths
    if _approval_is_valid(approved_by):
        return (True, None)
    if _auditor_reports_clean(auditor, normalized):
        return (True, None)

    # BLOCKED
    envelope = build_error_envelope(
        "G4_PROTECTED_PATH",
        "Write to a protected path requires reviewer approval.",
        file_path=str(file_path),
        suggestion=(
            "Provide approved_by='<reviewer-id>' (length >= 3) OR run "
            "graq_config_audit(action='accept', file='<path>', approver='<id>') "
            "to record a CG-14 baseline acceptance first."
        ),
        matched_pattern=matched_pattern,
    )
    return (False, envelope)
