"""User decision persistence — remember merge accept/reject decisions.

Stores decisions in ``.graqle/merge_decisions.yaml`` so the user is
never asked the same question twice on future scans.
"""

# ── graqle:intelligence ──
# module: graqle.scanner.dedup.decisions
# risk: LOW (impact radius: 1 modules)
# consumers: test_decisions
# dependencies: __future__, json, logging, dataclasses, pathlib +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.scanner.dedup.decisions")

_DEFAULT_PATH = ".graqle/merge_decisions.json"


@dataclass
class UserDecision:
    """A recorded merge decision."""

    node_a: str
    node_b: str
    accepted: bool
    timestamp: str = ""
    reason: str = ""


class DecisionStore:
    """Persistent store for user merge decisions.

    Parameters
    ----------
    path:
        Path to the decisions file (JSON).
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else Path(_DEFAULT_PATH)
        self._decisions: dict[str, UserDecision] = {}
        self._load()

    def _key(self, node_a: str, node_b: str) -> str:
        return "::".join(sorted([node_a, node_b]))

    def has_decision(self, node_a: str, node_b: str) -> bool:
        """Check if a decision exists for this pair."""
        return self._key(node_a, node_b) in self._decisions

    def get_decision(self, node_a: str, node_b: str) -> UserDecision | None:
        """Get the stored decision for this pair."""
        return self._decisions.get(self._key(node_a, node_b))

    def record(
        self,
        node_a: str,
        node_b: str,
        accepted: bool,
        reason: str = "",
    ) -> None:
        """Record a user's merge decision."""
        from datetime import datetime, timezone

        key = self._key(node_a, node_b)
        self._decisions[key] = UserDecision(
            node_a=node_a,
            node_b=node_b,
            accepted=accepted,
            timestamp=datetime.now(timezone.utc).isoformat(),
            reason=reason,
        )
        self._save()

    def all_decisions(self) -> list[UserDecision]:
        """Return all stored decisions."""
        return list(self._decisions.values())

    def clear(self) -> None:
        """Clear all stored decisions."""
        self._decisions.clear()
        self._save()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for key, entry in data.items():
                self._decisions[key] = UserDecision(
                    node_a=entry.get("node_a", ""),
                    node_b=entry.get("node_b", ""),
                    accepted=entry.get("accepted", False),
                    timestamp=entry.get("timestamp", ""),
                    reason=entry.get("reason", ""),
                )
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load decisions: %s", exc)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for key, dec in self._decisions.items():
            data[key] = {
                "node_a": dec.node_a,
                "node_b": dec.node_b,
                "accepted": dec.accepted,
                "timestamp": dec.timestamp,
                "reason": dec.reason,
            }
        self._path.write_text(
            json.dumps(data, indent=2), encoding="utf-8",
        )
