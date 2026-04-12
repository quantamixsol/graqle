"""graq_gate — Pre-compiled Intelligence Gate.

Serves pre-compiled module intelligence from .graqle/intelligence/ in <100ms.
No graph loading. No scanning. Just reads JSON files from disk.

This is the core of Layer A (Deep Reasoning) — making intelligence instantly
available to any AI tool via MCP or direct API.

See §Layer A: Deep Reasoning.
"""

# ── graqle:intelligence ──
# module: graqle.intelligence.gate
# risk: MEDIUM (impact radius: 12 modules)
# consumers: run_multigov_v3, verify, __init__, ontology_generator, __init__ +7 more
# dependencies: __future__, json, logging, pathlib, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.intelligence.gate")


class IntelligenceGate:
    """Serves pre-compiled intelligence from .graqle/intelligence/.

    Thread-safe, stateless (reads from disk every call).
    Designed for <100ms response times.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(".")
        self.intel_dir = self.root / ".graqle" / "intelligence"

    @property
    def is_compiled(self) -> bool:
        """Check if intelligence has been compiled."""
        return self.intel_dir.exists() and (self.intel_dir / "module_index.json").exists()

    def get_context(self, module_query: str) -> dict[str, Any]:
        """Get pre-compiled context for a module (<100ms).

        Returns the full module packet: risk, consumers, dependencies,
        public interfaces, constraints, incidents.
        """
        if not self.is_compiled:
            return {
                "error": "No intelligence compiled yet. Run 'graq compile' first.",
                "hint": "graq compile scans your codebase and pre-compiles intelligence packets.",
            }

        packet = self._find_module_packet(module_query)
        if packet is None:
            return {
                "error": f"Module '{module_query}' not found in compiled intelligence.",
                "hint": "Check module name or run 'graq compile' to refresh.",
                "available_modules": self._list_modules()[:10],
            }

        return packet

    def get_impact(self, module_query: str) -> dict[str, Any]:
        """Get impact analysis for a module — what breaks if it changes."""
        impact_path = self.intel_dir / "impact_matrix.json"

        if not impact_path.exists():
            return {"error": "No impact matrix found. Run 'graq compile' first."}

        impact_data = json.loads(impact_path.read_text(encoding="utf-8"))

        matched_key = _fuzzy_match_module(module_query, list(impact_data.keys()))
        if matched_key is None:
            # Module exists but has no consumers
            packet = self._find_module_packet(module_query)
            if packet:
                return {
                    "module": module_query,
                    "impact": "LOW — no other modules import this directly.",
                    "consumers": [],
                    "consumer_count": 0,
                    "safe_to_modify": True,
                }
            return {"error": f"Module '{module_query}' not found."}

        entry = impact_data[matched_key]
        consumer_count = entry.get("consumer_count", 0)
        return {
            "module": matched_key,
            "consumers": entry.get("consumers", []),
            "consumer_count": consumer_count,
            "risk_level": entry.get("risk_level", "UNKNOWN"),
            "impact_radius": entry.get("impact_radius", 0),
            "safe_to_modify": consumer_count == 0,
            "warning": (
                f"HIGH IMPACT — {consumer_count} modules depend on this. "
                "Review consumers before making breaking changes."
            ) if consumer_count >= 5 else None,
        }

    def get_scorecard(self) -> dict[str, Any]:
        """Get project-wide quality gate scorecard."""
        scorecard_path = self.root / ".graqle" / "scorecard.json"
        if not scorecard_path.exists():
            return {"error": "No scorecard found. Run 'graq compile' first."}

        return json.loads(scorecard_path.read_text(encoding="utf-8"))

    def _find_module_packet(self, query: str) -> dict[str, Any] | None:
        """Find a module packet by fuzzy name match."""
        modules_dir = self.intel_dir / "modules"
        if not modules_dir.exists():
            return None

        # Exact match (dots → __)
        safe_name = query.replace(".", "__").replace("/", "__")
        for suffix in ("", ".json"):
            candidate = modules_dir / f"{safe_name}{suffix}"
            if candidate.exists():
                return json.loads(candidate.read_text(encoding="utf-8"))

        # Strip file extension
        for ext in (".py", ".js", ".ts", ".jsx", ".tsx"):
            if query.endswith(ext):
                safe_name = query[:-len(ext)].replace(".", "__").replace("/", "__")
                candidate = modules_dir / f"{safe_name}.json"
                if candidate.exists():
                    return json.loads(candidate.read_text(encoding="utf-8"))

        # Fuzzy: last component match
        last_part = query.rsplit(".", 1)[-1].rsplit("/", 1)[-1]
        for fpath in modules_dir.glob("*.json"):
            if last_part in fpath.stem:
                return json.loads(fpath.read_text(encoding="utf-8"))

        return None

    def _list_modules(self) -> list[str]:
        """List available module names."""
        modules_dir = self.intel_dir / "modules"
        if not modules_dir.exists():
            return []
        return sorted(f.stem.replace("__", ".") for f in modules_dir.glob("*.json"))


def _fuzzy_match_module(query: str, module_names: list[str]) -> str | None:
    """Fuzzy match a module query against a list of names."""
    if query in module_names:
        return query

    normalized = query.replace("/", ".").replace("\\", ".")
    for ext in (".py", ".js", ".ts"):
        if normalized.endswith(ext):
            normalized = normalized[:-len(ext)]
            break

    if normalized in module_names:
        return normalized

    last_part = normalized.rsplit(".", 1)[-1]
    for name in module_names:
        if name.endswith(f".{last_part}") or name == last_part:
            return name

    for name in module_names:
        if last_part in name:
            return name

    return None
