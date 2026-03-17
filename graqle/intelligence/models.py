"""Data models for the Graqle Intelligence Pipeline.

Every file scanned produces a FileIntelligenceUnit — an atomic, validated
package of nodes, edges, intelligence packet, and coverage report.
Nothing exits the pipeline without passing all 6 validation gates.

See ADR-105 §Architecture: Per-File Validation.
"""

# ── graqle:intelligence ──
# module: graqle.intelligence.models
# risk: HIGH (impact radius: 16 modules)
# consumers: claude_section, compile, emitter, headers, pipeline +11 more
# dependencies: __future__, datetime, enum, typing, pydantic
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ValidationStatus(str, Enum):
    """Outcome of validation gates for a single file."""

    PASS = "PASS"            # All gates passed without repair
    REPAIRED = "REPAIRED"    # Some gates failed, auto-repaired successfully
    DEGRADED = "DEGRADED"    # Auto-repair insufficient, partial intelligence


class InsightCategory(str, Enum):
    """Categories for curiosity-peak insights shown during streaming scan."""

    SUPERLATIVE = "superlative"    # "MOST imported", "LARGEST file"
    WARNING = "warning"            # "INCIDENT HISTORY", "HIGH RISK"
    SUGGESTION = "suggestion"      # "Consider splitting?"
    CONNECTION = "connection"      # "Bridges 4 isolated modules"
    HISTORY = "history"            # "Changed 12 times in 30 days"
    INVARIANT = "invariant"        # "Write-without-read", "format mismatch"


class ValidatedNode(BaseModel):
    """A node that has passed all validation gates.

    Guaranteed properties:
    - label is non-empty
    - entity_type is a registered node type
    - description length >= 30 chars
    - chunks list is non-empty with at least one meaningful chunk
    """

    id: str
    label: str
    entity_type: str
    description: str = Field(min_length=30)
    chunks: list[dict[str, Any]] = Field(min_length=1)
    properties: dict[str, Any] = Field(default_factory=dict)
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    @property
    def has_source(self) -> bool:
        return self.file_path is not None


class ValidatedEdge(BaseModel):
    """An edge that has passed integrity validation.

    Guaranteed properties:
    - source and target are non-empty strings
    - relationship is a registered edge type
    - no self-loops (source != target)
    """

    source: str
    target: str
    relationship: str
    properties: dict[str, Any] = Field(default_factory=dict)


class ValidationGateResult(BaseModel):
    """Result of a single validation gate."""

    gate: str                                      # e.g. "parse_integrity", "node_completeness"
    gate_number: int                               # 1-6
    passed: bool
    auto_repaired: int = 0                         # count of auto-repairs applied
    degraded: int = 0                              # count of items that couldn't be repaired
    warnings: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class CoverageReport(BaseModel):
    """Coverage metrics for a single file or the entire scan."""

    total_nodes: int = 0
    nodes_with_chunks: int = 0
    nodes_with_descriptions: int = 0
    total_edges: int = 0
    valid_edges: int = 0
    pending_edges: int = 0                         # edges deferred (target not yet scanned)
    dangling_edges: int = 0                        # edges that couldn't be resolved

    parse_success: bool = True
    auto_repairs: int = 0
    degraded_nodes: int = 0

    @property
    def chunk_coverage(self) -> float:
        if self.total_nodes == 0:
            return 100.0
        return round(self.nodes_with_chunks / self.total_nodes * 100, 1)

    @property
    def description_coverage(self) -> float:
        if self.total_nodes == 0:
            return 100.0
        return round(self.nodes_with_descriptions / self.total_nodes * 100, 1)

    @property
    def edge_integrity(self) -> float:
        if self.total_edges == 0:
            return 100.0
        return round(self.valid_edges / self.total_edges * 100, 1)

    @property
    def health(self) -> Literal["HEALTHY", "WARNING", "CRITICAL"]:
        if self.chunk_coverage >= 95 and self.edge_integrity >= 99:
            return "HEALTHY"
        if self.chunk_coverage >= 80 and self.edge_integrity >= 95:
            return "WARNING"
        return "CRITICAL"


class PublicInterface(BaseModel):
    """A public interface exposed by a module."""

    name: str
    type: str                                      # "Class", "Function", "Constant"
    line: int | None = None


class ModuleConsumer(BaseModel):
    """A module that imports/consumes this module."""

    module: str
    via: str = "IMPORTS"                           # edge type


class ModuleDependency(BaseModel):
    """A dependency this module imports."""

    module: str
    type: str = "internal"                         # "internal" or "external"


class ModulePacket(BaseModel):
    """Pre-compiled intelligence for one module.

    This is the core unit served by graq_gate. Contains everything
    an AI tool needs to understand a module's context, impact, and constraints —
    without reading a single source file.
    """

    module: str                                    # e.g. "graqle.activation.chunk_scorer"
    files: list[str]                               # source file paths
    node_count: int = 0
    function_count: int = 0
    class_count: int = 0
    line_count: int = 0

    public_interfaces: list[PublicInterface] = Field(default_factory=list)
    consumers: list[ModuleConsumer] = Field(default_factory=list)
    dependencies: list[ModuleDependency] = Field(default_factory=list)

    risk_score: float = 0.0                        # 0.0 - 1.0
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "LOW"
    impact_radius: int = 0                         # how many modules affected by changes

    chunk_coverage: float = 100.0
    description_coverage: float = 100.0

    constraints: list[str] = Field(default_factory=list)
    incidents: list[str] = Field(default_factory=list)

    last_compiled: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def consumer_count(self) -> int:
        return len(self.consumers)

    @property
    def dependency_count(self) -> int:
        return len(self.dependencies)


class CuriosityInsight(BaseModel):
    """A curiosity-peak insight surfaced during streaming scan.

    Each insight reveals something interesting about the scanned file
    that the developer likely didn't know. Designed for dopamine-loop
    engagement during the scan wait time.
    """

    category: InsightCategory
    module: str                                    # which module this is about
    message: str                                   # the insight text
    metric: str | None = None                      # e.g. "14 consumers", "66 functions"
    severity: Literal["info", "warn", "critical"] = "info"


class FileIntelligenceUnit(BaseModel):
    """Atomic output: one file's complete, validated intelligence.

    A file either produces a VALID FileIntelligenceUnit with all
    validation gates passed, or it surfaces errors that are immediately
    auto-repaired. Nothing passes through half-built.
    """

    file_path: str
    nodes: list[ValidatedNode]
    edges: list[ValidatedEdge]
    module_packet: ModulePacket
    coverage: CoverageReport
    validation_status: ValidationStatus
    gate_results: list[ValidationGateResult] = Field(default_factory=list)
    insights: list[CuriosityInsight] = Field(default_factory=list)
    scan_duration_ms: float = 0.0

    @property
    def is_healthy(self) -> bool:
        return self.validation_status != ValidationStatus.DEGRADED

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)
