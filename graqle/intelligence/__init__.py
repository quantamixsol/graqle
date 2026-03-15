"""Graqle Intelligence — streaming intelligence pipeline with per-file validation.

The Q in Graqle: Quality Gate for development.
Every file passes through 6 validation gates, producing guaranteed-complete
intelligence packets that AI tools consume naturally.

See ADR-105 for the full architectural design.
"""

# ── graqle:intelligence ──
# module: graqle.intelligence.__init__
# risk: LOW (impact radius: 0 modules)
# dependencies: models, compile, emitter, headers, claude_section
# constraints: none
# ── /graqle:intelligence ──

from graqle.intelligence.claude_section import eject_section, generate_section, inject_section
from graqle.intelligence.compile import compile_intelligence
from graqle.intelligence.emitter import IntelligenceEmitter
from graqle.intelligence.headers import eject_header, generate_header, inject_header
from graqle.intelligence.models import (
    CoverageReport,
    CuriosityInsight,
    FileIntelligenceUnit,
    ModulePacket,
    ValidatedEdge,
    ValidatedNode,
    ValidationGateResult,
)

__all__ = [
    "CoverageReport",
    "CuriosityInsight",
    "FileIntelligenceUnit",
    "ModulePacket",
    "ValidationGateResult",
    "ValidatedEdge",
    "ValidatedNode",
    "compile_intelligence",
    "IntelligenceEmitter",
    "generate_header",
    "inject_header",
    "eject_header",
    "generate_section",
    "inject_section",
    "eject_section",
]
