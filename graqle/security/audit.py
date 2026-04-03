"""Security audit logging — Content security audit logging.

Append-only JSONL audit trail for all content-security events
(redactions, sensitivity classifications, provider routing decisions).
Integrates with the existing GovernanceAuditLog format.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from graqle.security.content_gate import ContentAuditRecord

__all__ = [
    "ContentAuditRecord",
    "RedactionEvent",
    "SecurityAuditor",
]

logger = logging.getLogger("graqle.security.audit")

_DEFAULT_LOG_PATH = Path.home() / ".graqle" / "security_audit.jsonl"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RedactionEvent:
    """Immutable record of a single redaction action.

    Attributes:
        timestamp:       ISO-8601 UTC timestamp of the redaction.
        layer:           Security layer that triggered the redaction (L0-L4).
        pattern_matched: The pattern or rule name that matched.
        destination:     Where the content was headed (e.g. provider name).
    """

    timestamp: str
    layer: str  # L0 | L1 | L2 | L3 | L4
    pattern_matched: str
    destination: str


# ---------------------------------------------------------------------------
# SecurityAuditor
# ---------------------------------------------------------------------------


class SecurityAuditor:
    """Append-only JSONL audit log for content-security events.

    Thread-safe: all file writes are serialised through an internal
    threading.Lock so concurrent callers never interleave lines.
    """

    def __init__(self, log_path: str | Path | None = None) -> None:
        self._path = Path(log_path) if log_path is not None else _DEFAULT_LOG_PATH
        self._lock = threading.Lock()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("Cannot create audit log directory: %s", self._path.parent)

    # -- public API ---------------------------------------------------------

    def log_event(self, record: ContentAuditRecord) -> None:
        """Append record as a single JSON line (append-only, never truncate)."""
        try:
            data = self._serialise(record)
            data.setdefault("logged_at", datetime.now(timezone.utc).isoformat())
            line = json.dumps(data, default=str, ensure_ascii=False) + "\n"
            with self._lock:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(line)
        except Exception as exc:
            logger.error("Failed to write audit event: %s", exc)

    def get_recent(self, n: int = 10) -> list[dict[str, Any]]:
        """Return the last n records from the audit log."""
        if not self._path.exists():
            return []
        try:
            with self._lock:
                lines = self._path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            logger.warning("Cannot read audit log: %s", exc)
            return []

        records: list[dict[str, Any]] = []
        for raw in lines[-n:]:
            raw = raw.strip()
            if not raw:
                continue
            try:
                records.append(json.loads(raw))
            except json.JSONDecodeError:
                logger.warning("Skipping malformed audit line")
        return records

    def generate_report(self) -> dict[str, Any]:
        """Produce a summary report over the full audit log.

        Returns a dict with keys: total_events, by_destination,
        by_sensitivity, total_redactions.
        """
        if not self._path.exists():
            return {
                "total_events": 0,
                "by_destination": {},
                "by_sensitivity": {},
                "total_redactions": 0,
            }

        by_destination: Counter[str] = Counter()
        by_sensitivity: Counter[str] = Counter()
        total_redactions = 0
        total = 0

        with self._lock:
            try:
                with self._path.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        total += 1
                        by_destination[rec.get("destination", "unknown")] += 1
                        by_sensitivity[str(rec.get("sensitivity_level", "unknown"))] += 1
                        total_redactions += int(rec.get("redactions_applied", 0))
            except OSError as exc:
                logger.error("Failed to read audit log for report: %s", exc)

        return {
            "total_events": total,
            "by_destination": dict(by_destination),
            "by_sensitivity": dict(by_sensitivity),
            "total_redactions": total_redactions,
        }

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _serialise(record: ContentAuditRecord) -> dict[str, Any]:
        """Convert a ContentAuditRecord to a JSON-safe dict."""
        if hasattr(record, "__dataclass_fields__"):
            return asdict(record)
        if hasattr(record, "to_dict"):
            return record.to_dict()
        return {k: v for k, v in vars(record).items() if not k.startswith("_")}
