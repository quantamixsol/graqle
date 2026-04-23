"""CG-14 Config Drift Auditor — hash-based fingerprint detection.

Detects unauthorized edits to protected config files (graqle.yaml,
pyproject.toml, .mcp.json, .claude/settings.json) via SHA-256
fingerprinting against a versioned baseline at
``.graqle/config_baseline.json``.

Shared primitive consumed by CG-15 (KG-write gate) and G4
(protected_paths policy) in Wave 2 Phase 4.

CONCURRENCY CONTRACT:
  - Single-process thread safety via module-level RLock.
  - Multi-process: NOT supported. Users must serialize externally.
  - Lock scope: entire ``audit()`` and ``accept()`` methods
    (load-modify-save is atomic under the lock).
  - Lock is acquired ONCE at the public-method entry point. All
    private helpers (``_first_run``, ``_compare_with_baseline``,
    ``_load_baseline``, ``_save_baseline``) assume the caller holds
    the lock. They NEVER reacquire it, avoiding deadlock.
  - RLock allows a future caller to reenter safely, but no code path
    currently does.
  - try/finally around all lock-held mutations guarantees release.

FAIL-CLOSED BEHAVIOR:
  - Corrupted baseline → all protected files reported as drifted,
    never auto-repaired. User must manually delete ``.graqle/
    config_baseline.json`` to trigger fresh creation.
  - Permission denied reading protected file → drift record with
    drift_type="permission_denied", severity="high".
  - Missing protected file → drift_type="missing", severity="high".

BASELINE SCHEMA (versioned):
  {
    "schema_version": 1,
    "created_at": "2026-04-22T12:34:56Z",
    "entries": {
      "graqle.yaml": {
        "sha256": "<64-char hex>",
        "approver": "<str or null>",
        "approved_at": "<ISO-8601 UTC or null>"
      },
      ...
    }
  }
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger("graqle.governance.config_drift")


# ─────────────────────────────────────────────────────────────────────────
# Module-level constants + lock
# ─────────────────────────────────────────────────────────────────────────

DEFAULT_PROTECTED_FILES: tuple[str, ...] = (
    "graqle.yaml",
    "pyproject.toml",
    ".mcp.json",
    ".claude/settings.json",
)

# Relative path — authoritative absolute resolution happens in __init__.
DEFAULT_BASELINE_RELATIVE: Path = Path(".graqle") / "config_baseline.json"

BASELINE_SCHEMA_VERSION: int = 1
_SHA256_HEX_LEN: int = 64
_SHA256_HEX_CHARS: frozenset[str] = frozenset("0123456789abcdef")

# RLock: single-process thread safety, reentrancy-tolerant for future use.
_BASELINE_LOCK = threading.RLock()


# ─────────────────────────────────────────────────────────────────────────
# Typed exceptions
# ─────────────────────────────────────────────────────────────────────────


class BaselineCorruptedError(Exception):
    """Raised when the baseline JSON is unparseable or fails schema validation.

    Never auto-recovered: the auditor reports every protected file as
    drifted (drift_type="baseline_corrupted") and the user must manually
    delete the baseline file.
    """


class FileReadError(Exception):
    """Raised when a protected file exists but cannot be read.

    Distinct from ``FileNotFoundError``: the latter means the file is
    absent; this one means it's present but the process lacks permission
    or hit another OSError subclass (IsADirectoryError, BlockingIOError,
    etc.). The auditor maps this to drift_type="permission_denied".
    """


# ─────────────────────────────────────────────────────────────────────────
# DriftRecord
# ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DriftRecord:
    """Single drift detection result.

    Serializable to JSON via ``dataclasses.asdict``.

    Attributes:
        file_path: Relative path of protected file (from repo root).
        drift_type: One of: "modified", "missing", "permission_denied",
            "baseline_missing", "baseline_corrupted", "new_protected".
        requires_review: True when a human reviewer must explicitly
            accept this drift before the file is considered clean.
        approver: Identifier of last reviewer, or None if never accepted.
        diff_summary: Short human-readable description (≤200 chars).
        severity: "low" | "medium" | "high".
    """

    file_path: str
    drift_type: str
    requires_review: bool
    approver: str | None
    diff_summary: str
    severity: str


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


def _utc_now_iso() -> str:
    """Return current UTC time as ISO-8601 with trailing 'Z'."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _sanitize(s: str, max_len: int = 200) -> str:
    """Strip absolute paths and truncate error messages for user-facing envelopes.

    Replaces Windows drive paths, POSIX user/system paths, and UNC paths
    with ``<path>``. Preserves error codes. Truncates at ``max_len``.
    """
    if not isinstance(s, str):
        s = str(s)
    # Windows drive paths: C:\Users\foo or C:/Users/foo
    s = re.sub(r"[A-Za-z]:[\\/][\S]+", "<path>", s)
    # Windows UNC paths: \\server\share\path
    s = re.sub(r"\\\\[^\s\\]+\\[\S]+", "<path>", s)
    # POSIX common absolute paths
    s = re.sub(r"/(?:home|Users|var|tmp|root|opt|etc)/[\S]+", "<path>", s)
    return s[:max_len]


def _hash_file(path: Path) -> str:
    """Return SHA-256 hex digest of ``path`` contents.

    Raises:
        FileNotFoundError: file (or symlink target) is absent.
        FileReadError: file exists but cannot be read (wraps OSError).
    """
    # Broken symlink: .exists() follows, .is_symlink() identifies link
    if path.is_symlink() and not path.exists():
        raise FileNotFoundError(f"broken symlink: {path.name}")
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except FileNotFoundError:
        raise
    except OSError as exc:
        # PermissionError, IsADirectoryError, BlockingIOError, etc.
        raise FileReadError(f"{type(exc).__name__}: {exc}") from exc


def _validate_baseline(data: Any) -> dict:
    """Validate parsed baseline dict against the schema.

    Raises:
        BaselineCorruptedError: schema violation of any kind.

    Returns:
        The validated dict (same object, with normalized entries).
    """
    if not isinstance(data, dict):
        raise BaselineCorruptedError("baseline root is not a dict")
    if data.get("schema_version") != BASELINE_SCHEMA_VERSION:
        raise BaselineCorruptedError(
            f"unknown schema_version: {data.get('schema_version')!r}"
        )
    entries = data.get("entries")
    if not isinstance(entries, dict):
        raise BaselineCorruptedError("baseline 'entries' is not a dict")
    for file_path, entry in entries.items():
        if not isinstance(file_path, str) or not file_path:
            raise BaselineCorruptedError(f"invalid entry key: {file_path!r}")
        if not isinstance(entry, dict):
            raise BaselineCorruptedError(f"entry {file_path!r}: not a dict")
        sha = entry.get("sha256")
        if (
            not isinstance(sha, str)
            or len(sha) != _SHA256_HEX_LEN
            or not all(c in _SHA256_HEX_CHARS for c in sha.lower())
        ):
            raise BaselineCorruptedError(
                f"entry {file_path!r}: bad sha256"
            )
        approver = entry.get("approver")
        if approver is not None and not isinstance(approver, str):
            raise BaselineCorruptedError(
                f"entry {file_path!r}: approver must be str or null"
            )
        ts = entry.get("approved_at")
        if ts is not None:
            if not isinstance(ts, str):
                raise BaselineCorruptedError(
                    f"entry {file_path!r}: approved_at must be str or null"
                )
            try:
                datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError as exc:
                raise BaselineCorruptedError(
                    f"entry {file_path!r}: malformed ISO-8601 timestamp"
                ) from exc
    return data


# ─────────────────────────────────────────────────────────────────────────
# ConfigDriftAuditor
# ─────────────────────────────────────────────────────────────────────────


class ConfigDriftAuditor:
    """Audit protected config files for drift against a baseline.

    The auditor is single-process thread-safe (see module docstring).
    Instances are cheap to create; callers may hold a long-lived
    auditor or instantiate per audit call.
    """

    def __init__(
        self,
        root: Path | None = None,
        baseline_path: Path | None = None,
        protected_files: Iterable[str] | None = None,
    ) -> None:
        self.root: Path = (root or Path.cwd()).resolve()
        if baseline_path is not None:
            self.baseline_path: Path = Path(baseline_path).resolve()
        else:
            self.baseline_path = (self.root / DEFAULT_BASELINE_RELATIVE).resolve()
        # Normalize: preserve order, dedupe, skip empty
        raw = protected_files if protected_files is not None else DEFAULT_PROTECTED_FILES
        seen: set[str] = set()
        normalized: list[str] = []
        for p in raw:
            if not isinstance(p, str) or not p.strip():
                continue
            p = p.strip()
            if p not in seen:
                seen.add(p)
                normalized.append(p)
        self._protected_files: tuple[str, ...] = tuple(normalized)

    # ── public API ─────────────────────────────────────────────────────

    def audit(self) -> list[DriftRecord]:
        """Audit all protected files against the baseline.

        Returns empty list when baseline matches current state.
        Holds the module RLock for the full method duration.
        """
        with _BASELINE_LOCK:
            try:
                baseline = self._load_baseline()
            except BaselineCorruptedError:
                return [
                    DriftRecord(
                        file_path=f,
                        drift_type="baseline_corrupted",
                        requires_review=True,
                        approver=None,
                        diff_summary=(
                            "baseline corrupted — delete manually to rebuild"
                        ),
                        severity="high",
                    )
                    for f in self._protected_files
                ]
            if baseline is None:
                return self._first_run()
            return self._compare_with_baseline(baseline)

    def accept(self, file: str, approver: str) -> None:
        """Mark ``file``'s current state as approved by ``approver``.

        Raises:
            ValueError: ``file`` is not in ``protected_files``.
            FileNotFoundError: ``file`` is absent or a broken symlink.
            FileReadError: ``file`` exists but cannot be read.
            BaselineCorruptedError: existing baseline is corrupted
                (must be manually deleted first).

        Holds the module RLock for the full method duration.
        """
        if file not in self._protected_files:
            raise ValueError(
                f"file {file!r} is not in protected_files {self._protected_files!r}"
            )
        if not isinstance(approver, str) or not approver.strip():
            raise ValueError("approver must be a non-empty string")
        approver = approver.strip()

        with _BASELINE_LOCK:
            # Hash the file FIRST (outside baseline load) so that a
            # FileNotFoundError or FileReadError propagates clearly without
            # also triggering a baseline load.
            abs_path = (self.root / file).resolve()
            sha = _hash_file(abs_path)  # raises if absent/unreadable

            # Load existing or start fresh
            try:
                baseline = self._load_baseline()
            except BaselineCorruptedError:
                # Do NOT auto-repair; surface to caller
                raise

            if baseline is None:
                baseline = {
                    "schema_version": BASELINE_SCHEMA_VERSION,
                    "created_at": _utc_now_iso(),
                    "entries": {},
                }

            baseline["entries"][file] = {
                "sha256": sha,
                "approver": approver,
                "approved_at": _utc_now_iso(),
            }
            self._save_baseline(baseline)

    @property
    def protected_files(self) -> tuple[str, ...]:
        """Normalized, deduplicated protected file list."""
        return self._protected_files

    # ── internal helpers (assume lock is held) ─────────────────────────

    def _first_run(self) -> list[DriftRecord]:
        """Create initial baseline from readable files; report the rest.

        Assumes caller holds ``_BASELINE_LOCK``.
        """
        records: list[DriftRecord] = []
        entries: dict[str, dict[str, Any]] = {}
        now = _utc_now_iso()

        for rel in self._protected_files:
            abs_path = (self.root / rel).resolve()
            try:
                sha = _hash_file(abs_path)
            except FileNotFoundError:
                records.append(DriftRecord(
                    file_path=rel,
                    drift_type="missing",
                    requires_review=True,
                    approver=None,
                    diff_summary="file absent from repo",
                    severity="high",
                ))
                continue
            except FileReadError as exc:
                records.append(DriftRecord(
                    file_path=rel,
                    drift_type="permission_denied",
                    requires_review=True,
                    approver=None,
                    diff_summary=_sanitize(str(exc)),
                    severity="high",
                ))
                continue
            entries[rel] = {
                "sha256": sha,
                "approver": None,
                "approved_at": None,
            }
            records.append(DriftRecord(
                file_path=rel,
                drift_type="baseline_missing",
                requires_review=True,
                approver=None,
                diff_summary=(
                    "first-run baseline created; review + accept to clean"
                ),
                severity="medium",
            ))

        baseline = {
            "schema_version": BASELINE_SCHEMA_VERSION,
            "created_at": now,
            "entries": entries,
        }
        self._save_baseline(baseline)
        return records

    def _compare_with_baseline(self, baseline: dict) -> list[DriftRecord]:
        """Diff current file states against baseline entries.

        Assumes caller holds ``_BASELINE_LOCK``.
        """
        records: list[DriftRecord] = []
        entries = baseline.get("entries", {})

        for rel in self._protected_files:
            abs_path = (self.root / rel).resolve()
            prior = entries.get(rel)

            if prior is None:
                # Protected file added to list after baseline existed
                try:
                    _hash_file(abs_path)
                    records.append(DriftRecord(
                        file_path=rel,
                        drift_type="new_protected",
                        requires_review=True,
                        approver=None,
                        diff_summary=(
                            "file added to protected_files after baseline"
                        ),
                        severity="medium",
                    ))
                except FileNotFoundError:
                    records.append(DriftRecord(
                        file_path=rel,
                        drift_type="missing",
                        requires_review=True,
                        approver=None,
                        diff_summary="file absent; not in baseline",
                        severity="high",
                    ))
                except FileReadError as exc:
                    records.append(DriftRecord(
                        file_path=rel,
                        drift_type="permission_denied",
                        requires_review=True,
                        approver=None,
                        diff_summary=_sanitize(str(exc)),
                        severity="high",
                    ))
                continue

            try:
                current_sha = _hash_file(abs_path)
            except FileNotFoundError:
                records.append(DriftRecord(
                    file_path=rel,
                    drift_type="missing",
                    requires_review=True,
                    approver=prior.get("approver"),
                    diff_summary="file absent; baseline had entry",
                    severity="high",
                ))
                continue
            except FileReadError as exc:
                records.append(DriftRecord(
                    file_path=rel,
                    drift_type="permission_denied",
                    requires_review=True,
                    approver=prior.get("approver"),
                    diff_summary=_sanitize(str(exc)),
                    severity="high",
                ))
                continue

            prior_sha = prior.get("sha256", "")
            if current_sha != prior_sha:
                records.append(DriftRecord(
                    file_path=rel,
                    drift_type="modified",
                    requires_review=True,
                    approver=prior.get("approver"),
                    diff_summary=(
                        f"hash changed: {prior_sha[:8]}... -> {current_sha[:8]}..."
                    ),
                    severity="medium",
                ))
            # else clean — no record emitted

        return records

    def _load_baseline(self) -> dict | None:
        """Load + validate baseline. None if missing; raises on corruption.

        Assumes caller holds ``_BASELINE_LOCK``.
        """
        if not self.baseline_path.exists():
            return None
        try:
            with open(self.baseline_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            raise BaselineCorruptedError(f"JSON parse error: {exc}") from exc
        except OSError as exc:
            # Treat baseline I/O errors as corruption for fail-closed
            raise BaselineCorruptedError(
                f"baseline read failed: {type(exc).__name__}"
            ) from exc
        return _validate_baseline(data)

    def _save_baseline(self, baseline: dict) -> None:
        """Atomic write via mkstemp + os.replace.

        Assumes caller holds ``_BASELINE_LOCK``. On any failure, the
        original baseline is unchanged and temp files are cleaned.
        """
        self.baseline_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(self.baseline_path.parent),
            prefix=".config_baseline.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(baseline, f, indent=2, sort_keys=True)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass  # fsync unsupported on some filesystems
            os.replace(tmp_path, self.baseline_path)
            tmp_path = None  # replaced successfully; do not clean
        finally:
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass  # best-effort cleanup


# ─────────────────────────────────────────────────────────────────────────
# MCP envelope builder (used by _handle_config_audit in mcp_dev_server.py)
# ─────────────────────────────────────────────────────────────────────────


def build_audit_response(records: list[DriftRecord]) -> dict[str, Any]:
    """Serialize audit records to the MCP response shape."""
    return {
        "action": "audit",
        "drift_records": [asdict(r) for r in records],
        "total_drift": len(records),
    }


def build_accept_response(file: str, approver: str) -> dict[str, Any]:
    """Serialize accept confirmation to the MCP response shape."""
    return {
        "action": "accept",
        "file": file,
        "approver": approver,
        "status": "accepted",
    }


_SANITIZE_EXTRA_FIELDS: tuple[str, ...] = (
    "file_path",
    "matched_pattern",
    "suggestion",
    "hint",
    "fix",
)


def build_error_envelope(
    error_code: str,
    message: str,
    **extra: Any,
) -> dict[str, Any]:
    """Single entry point for all user-facing error envelopes.

    Sanitizes the ``message`` field unconditionally. Additionally sanitizes
    the following allowlisted extra fields if present and string-valued:
    ``file_path``, ``matched_pattern``, ``suggestion``, ``hint``, ``fix``.

    Non-allowlisted extra fields pass through as-is; callers must
    sanitize those themselves if they may carry paths or exception text.
    """
    env: dict[str, Any] = {"error": error_code, "message": _sanitize(message)}
    for key, value in extra.items():
        if key in _SANITIZE_EXTRA_FIELDS and isinstance(value, str):
            env[key] = _sanitize(value)
        else:
            env[key] = value
    return env
