"""LearningTracker — records graph learning events for dashboard visibility.

Every `graq learn` and auto-recompile event is logged here. The dashboard
reads this file to show learning counts, domain breakdown, and recompile history.

Storage: .graqle/learning_log.json
"""

# ── graqle:intelligence ──
# module: graqle.intelligence.learning_tracker
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, json, logging, datetime, pathlib +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.intelligence.learning_tracker")


class LearningTracker:
    """Tracks learning events and recompile history for dashboard."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(".")
        self._path = self.root / ".graqle" / "learning_log.json"

    def _load(self) -> dict[str, Any]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "total_learning_events": 0,
            "total_recompiles": 0,
            "domain_counts": {},
            "skill_activations": {},
            "events": [],
        }

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def record_learn_event(
        self,
        *,
        event_type: str = "node",
        node_id: str = "",
        entity_type: str = "",
        domain: str = "",
        edges_added: int = 0,
        description: str = "",
    ) -> None:
        """Record a graq learn event."""
        data = self._load()
        data["total_learning_events"] += 1

        # Classify domain from entity type if not provided
        if not domain:
            domain = self._classify_domain(entity_type)

        data["domain_counts"][domain] = data["domain_counts"].get(domain, 0) + 1

        # Keep last 200 events (rolling window)
        data["events"].append({
            "type": event_type,
            "node_id": node_id,
            "entity_type": entity_type,
            "domain": domain,
            "edges_added": edges_added,
            "description": description[:200],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if len(data["events"]) > 200:
            data["events"] = data["events"][-200:]

        self._save(data)
        logger.debug("Learning event recorded: %s %s (%s)", event_type, node_id, domain)

    def record_recompile(
        self,
        *,
        trigger: str = "manual",
        modules_updated: int = 0,
        duration_seconds: float = 0.0,
    ) -> None:
        """Record a recompile event (manual or auto-staleness)."""
        data = self._load()
        data["total_recompiles"] += 1

        data["events"].append({
            "type": "recompile",
            "trigger": trigger,
            "modules_updated": modules_updated,
            "duration_seconds": round(duration_seconds, 1),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if len(data["events"]) > 200:
            data["events"] = data["events"][-200:]

        self._save(data)
        logger.debug("Recompile recorded: %s (%d modules)", trigger, modules_updated)

    def record_skill_activation(self, skill_name: str, domain: str = "") -> None:
        """Record that a skill was used during reasoning."""
        data = self._load()
        key = skill_name
        data["skill_activations"][key] = data["skill_activations"].get(key, 0) + 1
        self._save(data)

    def get_summary(self) -> dict[str, Any]:
        """Get learning summary for dashboard."""
        data = self._load()
        return {
            "total_learning_events": data.get("total_learning_events", 0),
            "total_recompiles": data.get("total_recompiles", 0),
            "domain_counts": data.get("domain_counts", {}),
            "skill_activations": data.get("skill_activations", {}),
            "recent_events": data.get("events", [])[-20:],
        }

    def get_skill_counts_by_domain(self) -> dict[str, int]:
        """Count skills activated per domain."""
        data = self._load()
        domain_skills: dict[str, int] = {}
        for skill, count in data.get("skill_activations", {}).items():
            domain = self._skill_domain(skill)
            domain_skills[domain] = domain_skills.get(domain, 0) + count
        return domain_skills

    @staticmethod
    def _classify_domain(entity_type: str) -> str:
        """Auto-classify entity type into a domain."""
        et = entity_type.upper()
        eng_types = {
            "MODULE", "CLASS", "FUNCTION", "COMPONENT", "LAMBDA", "CONTAINER",
            "DATABASE", "SCHEMA", "API", "ENDPOINT", "SERVICE", "TEST",
            "REACTCOMPONENT", "APIENDPOINT", "MIDDLEWARE",
        }
        gov_types = {
            "REGULATION", "POLICY", "GOV_FRAMEWORK", "GOV_REQUIREMENT",
            "GOV_CONTROL", "GOV_ENFORCEMENT", "GOV_EVIDENCE",
        }
        mkt_types = {"SEGMENT", "CHANNEL", "CAMPAIGN", "MESSAGE", "COHORT"}
        fin_types = {"INSTRUMENT", "PORTFOLIO", "TRANSACTION", "RISK_METRIC"}
        legal_types = {"CONTRACT", "CLAUSE", "OBLIGATION", "JURISDICTION"}

        if et in eng_types:
            return "engineering"
        if et in gov_types:
            return "governance"
        if et in mkt_types:
            return "marketing"
        if et in fin_types:
            return "financial"
        if et in legal_types:
            return "legal"
        return "general"

    @staticmethod
    def _skill_domain(skill_name: str) -> str:
        """Map skill name to domain."""
        sn = skill_name.lower()
        if any(k in sn for k in ("react", "css", "ui", "frontend", "component")):
            return "engineering"
        if any(k in sn for k in ("api", "endpoint", "middleware", "backend")):
            return "engineering"
        if any(k in sn for k in ("security", "injection", "auth", "secret")):
            return "security"
        if any(k in sn for k in ("test", "edge_case", "quality")):
            return "testing"
        if any(k in sn for k in ("gov", "drace", "audit", "compliance")):
            return "governance"
        if any(k in sn for k in ("market", "campaign", "segment")):
            return "marketing"
        return "general"
