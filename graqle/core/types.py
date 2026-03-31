"""Core type definitions, enums, and protocols for Graqle."""

# ── graqle:intelligence ──
# module: graqle.core.types
# risk: HIGH (impact radius: 27 modules)
# consumers: __init__, base_agent, slm_agent, registry, benchmark_runner +22 more
# dependencies: __future__, dataclasses, datetime, enum, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class ReasoningType(str, Enum):
    """Type of reasoning content in a message."""

    ASSERTION = "assertion"
    QUESTION = "question"
    CONTRADICTION = "contradiction"
    SYNTHESIS = "synthesis"
    EVIDENCE = "evidence"
    HYPOTHESIS = "hypothesis"
    PROTOCOL_TRACE = "protocol_trace"


class NodeStatus(str, Enum):
    """Operational status of a CogniNode."""

    IDLE = "idle"
    ACTIVATED = "activated"
    REASONING = "reasoning"
    CONVERGED = "converged"
    ERROR = "error"


class AggregationStrategy(str, Enum):
    """Strategy for aggregating multi-node reasoning outputs."""

    WEIGHTED_SYNTHESIS = "weighted_synthesis"
    MAJORITY_VOTE = "majority_vote"
    RANK_FUSION = "rank_fusion"
    CONFIDENCE_WEIGHTED = "confidence_weighted"


class ActivationStrategy(str, Enum):
    """Strategy for selecting which nodes to activate."""

    PCST = "pcst"
    FULL = "full"
    TOP_K = "top_k"
    MANUAL = "manual"
    FEDERATED = "federated"  # R9: multi-KG federated activation


@runtime_checkable
class ModelBackend(Protocol):
    """Protocol for any model that can generate text from a prompt.

    Implementations: LocalModel, AnthropicBackend, OpenAIBackend,
    OllamaBackend, BedrockBackend, CustomBackend.
    """

    async def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def cost_per_1k_tokens(self) -> float: ...


@runtime_checkable
class GraphConnector(Protocol):
    """Protocol for loading graph data from any source."""

    def load(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return (nodes_dict, edges_dict) from graph source."""
        ...


@dataclass
class ReasoningResult:
    """Result of a GraQle reasoning query."""

    query: str
    answer: str
    confidence: float
    rounds_completed: int
    active_nodes: list[str]
    message_trace: list[Any]  # list[Message] — forward ref avoidance
    cost_usd: float
    latency_ms: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)
    # v0.24.1: Backend status fields (Issue 1+3 from CrawlQ feedback)
    backend_status: str = "ok"  # "ok", "unavailable", "fallback", "not_configured"
    backend_error: str | None = None  # Error message if backend failed
    reasoning_mode: str = "full"  # "full", "fallback_traversal", "keyword"

    @property
    def content(self) -> str:
        """Backward-compatible alias for .answer (renamed in v0.9.0)."""
        return self.answer

    @property
    def node_count(self) -> int:
        return len(self.active_nodes)


@dataclass
class ExplanationTrace:
    """Full provenance trace for a reasoning result."""

    result: ReasoningResult
    node_contributions: dict[str, float]  # node_id -> contribution weight
    reasoning_chain: list[dict[str, Any]]  # ordered reasoning steps
    evidence_sources: list[str]  # KG entity IDs
    conflict_pairs: list[tuple[str, str]]  # (node_a, node_b) conflicts found


@dataclass
class GraphStats:
    """Statistics about a GraQle instance."""

    total_nodes: int
    total_edges: int
    activated_nodes: int
    avg_degree: float
    density: float
    connected_components: int
    hub_nodes: list[str]  # highest-degree nodes


@dataclass
class NodeConfig:
    """Per-node configuration for model assignment and behavior."""

    backend: ModelBackend | None = None
    adapter_id: str | None = None
    max_tokens: int = 2048
    temperature: float = 0.3
    system_prompt: str | None = None


# ---------------------------------------------------------------------------
# R5 Cross-Language MCP Linker types (ADR-131)
# ---------------------------------------------------------------------------


@dataclass
class MCPCallSite:
    """A TypeScript callTool() invocation detected by the scanner."""

    tool_name: str | None       # None if dynamic
    params_raw: str | None
    file: str
    line: int
    enclosing_function: str
    is_dynamic: bool
    variable_hint: str | None   # for dynamic: the variable name


@dataclass
class MCPHandler:
    """A Python MCP handler function detected by the scanner."""

    tool_name: str              # bare name: "reason", "predict"
    function_name: str          # "_handle_reason"
    file: str
    line: int
    class_context: str | None
    registry_confirmed: bool    # True if found in TOOL_REGISTRY
