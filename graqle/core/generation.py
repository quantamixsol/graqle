# ── graqle:intelligence ──
# module: graqle.core.generation
# risk: LOW (impact radius: new file, zero existing consumers)
# consumers: mcp_dev_server, cli.main, studio.routes.api
# constraints: NEVER import from types.py for new fields — extend here only
# ── /graqle:intelligence ──

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class DiffPatch:
    """A single file diff produced by graq_generate."""

    file_path: str
    unified_diff: str
    lines_added: int
    lines_removed: int
    preview: str  # first ~5 lines of the diff, safe to display in chat


@dataclass
class GenerationRequest:
    """Input to the graq_generate tool."""

    description: str
    file_path: str = ""       # empty = let the graph infer affected file(s)
    max_rounds: int = 2
    dry_run: bool = False
    backend: str = ""         # empty = use default backend from graqle.yaml


@dataclass
class CodeGenerationResult:
    """
    Result of a graq_generate or graq_edit operation.

    Extends the ReasoningResult pattern (same scalar fields) plus
    diff-specific output.  Does NOT inherit from ReasoningResult to avoid
    touching types.py (257-module blast radius).
    """

    # --- core reasoning fields (mirror ReasoningResult scalars) ---
    query: str
    answer: str                         # natural-language summary of changes
    confidence: float
    rounds_completed: int
    active_nodes: list[str]
    cost_usd: float
    latency_ms: float

    # --- code generation fields ---
    patches: list[DiffPatch] = field(default_factory=list)
    files_affected: list[str] = field(default_factory=list)

    # --- status ---
    timestamp: datetime = field(default_factory=datetime.utcnow)
    backend_status: str = "ok"          # "ok", "unavailable", "fallback"
    backend_error: str | None = None
    dry_run: bool = False

    # --- metadata ---
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def node_count(self) -> int:
        return len(self.active_nodes)

    @property
    def total_lines_added(self) -> int:
        return sum(p.lines_added for p in self.patches)

    @property
    def total_lines_removed(self) -> int:
        return sum(p.lines_removed for p in self.patches)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to MCP tool result dict."""
        return {
            "query": self.query,
            "answer": self.answer,
            "confidence": self.confidence,
            "rounds_completed": self.rounds_completed,
            "active_nodes": self.active_nodes,
            "node_count": self.node_count,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "patches": [
                {
                    "file_path": p.file_path,
                    "unified_diff": p.unified_diff,
                    "lines_added": p.lines_added,
                    "lines_removed": p.lines_removed,
                    "preview": p.preview,
                }
                for p in self.patches
            ],
            "files_affected": self.files_affected,
            "total_lines_added": self.total_lines_added,
            "total_lines_removed": self.total_lines_removed,
            "timestamp": self.timestamp.isoformat(),
            "backend_status": self.backend_status,
            "backend_error": self.backend_error,
            "dry_run": self.dry_run,
            "metadata": self.metadata,
        }
