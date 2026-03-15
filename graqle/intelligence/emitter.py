"""Intelligence Emitter — writes compiled intelligence to all output targets.

Outputs:
- .graqle/intelligence/modules/   → per-module JSON packets
- .graqle/intelligence/impact_matrix.json
- .graqle/intelligence/module_index.json
- .graqle/scorecard.json

See ADR-105 §Intelligence Outputs.
"""

# ── graqle:intelligence ──
# module: graqle.intelligence.emitter
# risk: LOW (impact radius: 3 modules)
# consumers: compile, __init__, test_emitter
# dependencies: __future__, json, logging, pathlib, typing +2 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from graqle.intelligence.models import (
    FileIntelligenceUnit,
    ModulePacket,
)
from graqle.intelligence.scorecard import RunningScorecard

logger = logging.getLogger("graqle.intelligence.emitter")


class IntelligenceEmitter:
    """Writes intelligence artifacts to .graqle/intelligence/."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.intel_dir = root / ".graqle" / "intelligence"
        self.modules_dir = self.intel_dir / "modules"
        self._all_packets: list[ModulePacket] = []
        self._initialized = False

    def _ensure_dirs(self) -> None:
        if not self._initialized:
            self.modules_dir.mkdir(parents=True, exist_ok=True)
            self._initialized = True

    def emit_unit(self, unit: FileIntelligenceUnit) -> None:
        """Emit a single file's intelligence packet."""
        self._ensure_dirs()
        pkt = unit.module_packet

        # Write module packet JSON
        safe_name = pkt.module.replace(".", "__").replace("/", "__")
        packet_path = self.modules_dir / f"{safe_name}.json"
        packet_path.write_text(
            json.dumps(_packet_to_dict(pkt), indent=2, default=str),
            encoding="utf-8",
        )
        self._all_packets.append(pkt)

    def emit_index(self, scorecard: RunningScorecard) -> None:
        """Emit the master index and impact matrix after all files are processed."""
        self._ensure_dirs()

        # Module index
        index = {
            "modules": [
                {
                    "module": p.module,
                    "files": p.files,
                    "risk_level": p.risk_level,
                    "risk_score": p.risk_score,
                    "impact_radius": p.impact_radius,
                    "consumer_count": p.consumer_count,
                    "function_count": p.function_count,
                    "class_count": p.class_count,
                    "chunk_coverage": p.chunk_coverage,
                }
                for p in self._all_packets
            ],
            "total_modules": len(self._all_packets),
            "scorecard": scorecard.to_dict(),
        }
        (self.intel_dir / "module_index.json").write_text(
            json.dumps(index, indent=2, default=str), encoding="utf-8",
        )

        # Impact matrix: for each module, list what breaks if it changes
        impact: dict[str, Any] = {}
        for pkt in self._all_packets:
            if pkt.consumers:
                impact[pkt.module] = {
                    "consumers": [c.module for c in pkt.consumers],
                    "consumer_count": pkt.consumer_count,
                    "risk_level": pkt.risk_level,
                    "impact_radius": pkt.impact_radius,
                }
        (self.intel_dir / "impact_matrix.json").write_text(
            json.dumps(impact, indent=2, default=str), encoding="utf-8",
        )

        # Scorecard
        (self.root / ".graqle" / "scorecard.json").write_text(
            json.dumps(scorecard.to_dict(), indent=2, default=str), encoding="utf-8",
        )

        logger.info(
            "Intelligence emitted: %d modules, %d in impact matrix",
            len(self._all_packets), len(impact),
        )


def _packet_to_dict(pkt: ModulePacket) -> dict[str, Any]:
    """Serialize a ModulePacket to a clean JSON-friendly dict."""
    return {
        "module": pkt.module,
        "files": pkt.files,
        "node_count": pkt.node_count,
        "function_count": pkt.function_count,
        "class_count": pkt.class_count,
        "line_count": pkt.line_count,
        "public_interfaces": [
            {"name": pi.name, "type": pi.type, "line": pi.line}
            for pi in pkt.public_interfaces
        ],
        "consumers": [
            {"module": c.module, "via": c.via}
            for c in pkt.consumers
        ],
        "dependencies": [
            {"module": d.module, "type": d.type}
            for d in pkt.dependencies
        ],
        "risk_score": pkt.risk_score,
        "risk_level": pkt.risk_level,
        "impact_radius": pkt.impact_radius,
        "chunk_coverage": pkt.chunk_coverage,
        "description_coverage": pkt.description_coverage,
        "constraints": pkt.constraints,
        "incidents": pkt.incidents,
        "last_compiled": pkt.last_compiled,
    }
