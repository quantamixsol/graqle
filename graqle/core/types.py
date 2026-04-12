"""Core type definitions, enums, and protocols for Graqle."""

# ── graqle:intelligence ──
# module: graqle.core.types
# risk: HIGH (impact radius: 27 modules)
# consumers: __init__, base_agent, slm_agent, registry, benchmark_runner +22 more
# dependencies: __future__, dataclasses, datetime, enum, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import warnings
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


class CalibrationMethod(str, Enum):
    """Confidence calibration method applied to reasoning results."""

    NONE = "none"
    TEMPERATURE = "temperature"
    PLATT = "platt"
    ISOTONIC = "isotonic"


class CalibrationOutcome(str, Enum):
    """Outcome of a calibration/prediction operation.

    SKIPPED_LOW_CONFIDENCE does NOT match DRY_RUN in accuracy calculations.
    This distinction prevents accuracy inflation (S0 Bug B5).
    """

    WRITTEN = "written"
    DRY_RUN = "dry_run"
    SKIPPED_LOW_CONFIDENCE = "skipped_low_confidence"
    SKIPPED_DUPLICATE = "skipped_duplicate"
    SKIPPED_GENERATION_ERROR = "skipped_generation_error"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


@runtime_checkable
class ModelBackend(Protocol):
    """Protocol for any model that can generate text from a prompt.

    Implementations: LocalModel, AnthropicBackend, OpenAIBackend,
    OllamaBackend, BedrockBackend, CustomBackend. /030: Backends now return GenerateResult (str-compatible).
    Protocol keeps -> str annotation to avoid circular import
    (types.py cannot import backends.base). runtime_checkable only
    checks method existence, not return types, so this is safe.
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


@runtime_checkable
class AgentProtocol(Protocol):
    """Minimum interface for specialist agents in the reasoning roster.

    Note: ``isinstance()`` checks verify attribute presence only, not that
    ``generate()`` is a coroutine.  Use ``asyncio.iscoroutinefunction``
    to confirm async compliance at registration time.

    Return type: ``generate()`` returns ``str`` in this Phase 2 skeleton.
    Phase 3 will align to ``ReasoningResult`` when the coordinator's
    synthesis pipeline consumes structured metadata (confidence, cost,
    latency).  See for the parallel ``ModelBackend`` alignment.
    """

    @property
    def name(self) -> str:
        """Unique agent identifier used for dispatch and audit logging."""
        ...

    @property
    def model_id(self) -> str:
        """LLM model identifier this agent uses for generation."""
        ...

    async def generate(self, prompt: str, **kwargs: Any) -> str:  # TODO -> ReasoningResult in Phase 3
        """Generate a response for the given prompt.

        Returns plain ``str`` in Phase 2.  Will return ``ReasoningResult``
        in Phase 3 when coordinator synthesis requires structured metadata.

        Expected kwargs: ``temperature`` (float), ``max_tokens`` (int),
        ``stop_sequences`` (list[str]).  A ``GenerateOptions`` TypedDict
        will replace ``**kwargs`` in Phase 3.
        """
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
    # v0.24.1: Backend status fields (Issue 1+3 from the regulatory product feedback)
    backend_status: str = "ok"  # "ok", "unavailable", "fallback", "not_configured"
    backend_error: str | None = None  # Error message if backend failed
    reasoning_mode: str = "full"  # "full", "fallback_traversal", "keyword"
    raw_confidence: float | None = None  # Pre-calibration confidence for audit trail
    calibration_method: str | None = None  # CalibrationMethod value applied

    def __post_init__(self) -> None:
        if self.confidence is None:  # type: ignore[comparison-overlap]
            raise ValueError(
                "ReasoningResult.confidence must not be None (expected float). "
                "Fix the upstream data source that produced this result."
            )
        if self.cost_usd is None:  # type: ignore[comparison-overlap]
            raise ValueError(
                "ReasoningResult.cost_usd must not be None (expected float). "
                "Fix the upstream data source that produced this result."
            )
        if self.confidence == 0.0:
            warnings.warn(
                "ReasoningResult.confidence is exactly 0.0 — valid but may "
                "indicate a missing calibration step",
                stacklevel=3,
            )

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
# R5 Cross-Language MCP Linker types # ---------------------------------------------------------------------------


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

# ---------------------------------------------------------------------------
# R15 Multi-Backend Debate types # ---------------------------------------------------------------------------


@dataclass
class DebateTurn:
    """Single turn in a multi-panelist debate round."""

    round_number: int
    panelist: str  # backend name
    position: str  # propose / challenge / synthesize
    argument: str
    evidence_refs: list[str]  # KG node IDs
    confidence: float  # 0-1
    cost_usd: float
    latency_ms: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DebateTrace:
    """Full trace of a multi-panelist debate session."""

    query: str
    turns: list[DebateTurn]
    synthesis: str
    final_confidence: float
    total_cost_usd: float
    total_latency_ms: float
    consensus_reached: bool
    rounds_completed: int
    panelist_names: list[str]
    max_clearance_seen: str = "public"  # highest clearance of any input context
    metadata: dict[str, Any] = field(default_factory=dict)


class ClearanceLevel(int, Enum):
    """Controls what KG context is sent to each debate panelist backend.

    Ordering is implicit via integer values — comparison operators
    work directly without an external hierarchy dict.
    """

    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3


@dataclass
class DebateCostBudget:
    """Tracks and enforces a decaying cost budget across debate rounds."""

    initial_budget: float
    decay_factor: float | None = None  # Loaded from .graqle/debate_config.json at runtime
    _remaining: float = field(init=False)
    _round: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._remaining = self.initial_budget
        if self.decay_factor is None:
            from graqle.orchestration.debate_config import get as _debate_cfg
            self.decay_factor = float(_debate_cfg("decay_factor"))

    @property
    def exhausted(self) -> bool:
        """Return True when budget is fully spent."""
        return self._remaining <= 0.0

    def authorize_round(self, estimated_cost: float) -> bool:
        """Return False if exhausted or estimated cost exceeds remaining budget."""
        if self.exhausted or estimated_cost > self._remaining:
            return False
        return True

    def record_spend(self, actual_cost: float) -> float:
        """Deduct cost, apply decay, advance round, return remaining budget."""
        self._remaining -= actual_cost
        self._remaining *= self.decay_factor
        self._round += 1
        return self._remaining
