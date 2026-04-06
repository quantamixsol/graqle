"""Reasoning coordinator — multi-specialist orchestration skeleton (S5 Phase 1, PR #12).

Decomposes complex queries into specialist subtasks, dispatches them
under governance constraints, and synthesises a clearance-aware result.

B1: Constructor accepts llm_backend + agent_roster per R16 spec.
B2: Ephemeral lifecycle — memory/governance_topology passed per-call, not stored.
M1: Config keys aligned to COORDINATOR_DECOMPOSITION_PROMPT / COORDINATOR_SYNTHESIS_PROMPT.
M2: GovernanceTopology Pydantic model with typed GovernanceEdge edges.
"""

# ── graqle:intelligence ──
# module: graqle.reasoning.coordinator
# risk: HIGH (impact radius: 8 modules)
# consumers: test_coordinator, reasoning.__init__, governance_tasks
# dependencies: __future__, dataclasses, logging, typing, pydantic, core.types
# constraints: PR-12 (B1, B2, M1, M2)
# ── /graqle:intelligence ──

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal, Sequence

from pydantic import BaseModel, Field

from graqle.core.types import AgentProtocol, ClearanceLevel, ModelBackend
from graqle.reasoning.governance_tasks import create_governance_gates

logger = logging.getLogger("graqle.reasoning.coordinator")

# Compiled separator pattern for edge path tokenization (S5-3)
_EDGE_SEP_RE = re.compile(r'[\s/\\._-]+')


# ── M1: CoordinatorConfig ────────────────────────────────────────────────────


class CoordinatorConfig(BaseModel):
    """Configuration with R16 spec-aligned key names (M1 fix)."""

    COORDINATOR_DECOMPOSITION_PROMPT: str
    COORDINATOR_SYNTHESIS_PROMPT: str
    max_specialists: int = Field(..., ge=1)
    specialist_timeout_seconds: float = Field(..., gt=0.0)


# ── M2: GovernanceEdge / GovernanceTopology ──────────────────────────────────


class GovernanceEdge(BaseModel):
    """A typed edge in the governance topology graph (M2)."""

    source: str
    target: str
    relation: Literal["COMPLIES_WITH", "AMENDS", "GOVERNS"]
    properties: dict[str, Any] = Field(default_factory=dict)


class GovernanceTopology(BaseModel):
    """Governance graph expressed as typed edges (M2)."""

    edges: list[GovernanceEdge] = Field(default_factory=list)

    @property
    def complies_with(self) -> list[GovernanceEdge]:
        return [e for e in self.edges if e.relation == "COMPLIES_WITH"]

    @property
    def amends(self) -> list[GovernanceEdge]:
        return [e for e in self.edges if e.relation == "AMENDS"]

    @property
    def governs(self) -> list[GovernanceEdge]:
        return [e for e in self.edges if e.relation == "GOVERNS"]


# ── S5-1: Specialist dataclass ───────────────────────────────────────────────


@dataclass(frozen=True)
class Specialist:
    """A reasoning specialist agent descriptor."""

    name: str
    model_id: str
    capability_tags: tuple[str, ...] = ()
    clearance_level: ClearanceLevel = ClearanceLevel.PUBLIC


# ── S5-12: Pydantic validation models ───────────────────────────────────────


class SubTask(BaseModel):
    """A single decomposed subtask."""

    description: str = Field(..., min_length=1)
    required_capabilities: list[str] = Field(default_factory=list)
    clearance_required: ClearanceLevel = Field(default=ClearanceLevel.PUBLIC)


class TaskDecomposition(BaseModel):
    """Validated decomposition of a complex query into subtasks."""

    original_query: str = Field(..., min_length=1)
    subtasks: list[SubTask] = Field(..., min_length=1)


class SynthesisResult(BaseModel):
    """Validated synthesis of specialist outputs."""

    merged_answer: str = Field(..., min_length=1)
    clearance: ClearanceLevel
    taint: list[str] = Field(default_factory=list)


# ── S5-2 / S5-10: ReasoningCoordinator ──────────────────────────────────────


class ReasoningCoordinator:
    """Ephemeral per-query reasoning coordinator (PR #12 fixes).

    B1: accepts ``llm_backend`` and ``agent_roster`` per R16 spec.
    B2: ephemeral — use as context manager. ``memory`` and
        ``governance_topology`` passed per-call, never stored on self.
    """

    def __init__(
        self,
        llm_backend: ModelBackend,
        agent_roster: Sequence[AgentProtocol],
        config: CoordinatorConfig,
    ) -> None:
        # Validate async compliance — @runtime_checkable can't check this
        for agent in agent_roster:
            if hasattr(agent, "generate") and not asyncio.iscoroutinefunction(agent.generate):
                raise TypeError(
                    f"Agent {getattr(agent, 'name', '?')!r}.generate must be a coroutine function"
                )

        self._llm_backend = llm_backend
        self._agent_roster = list(agent_roster)
        self._config = config
        self._specialists: list[Specialist] = []
        self._active: bool = False

        logger.info(
            "ReasoningCoordinator initialised (llm_backend=%s, roster=%d)",
            type(llm_backend).__name__,
            len(self._agent_roster),
        )

    # ── B2: sync + async context manager ───────────────────────────────

    def __enter__(self) -> ReasoningCoordinator:
        if self._active:
            raise RuntimeError("ReasoningCoordinator is not re-entrant")
        self._active = True
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self._active = False
        self._specialists = []  # ephemeral — clear on exit

    async def __aenter__(self) -> ReasoningCoordinator:
        if self._active:
            raise RuntimeError("ReasoningCoordinator is not re-entrant")
        self._active = True
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self._active = False
        self._specialists = []  # ephemeral — clear on exit

    def _check_active(self) -> None:
        if not self._active:
            raise RuntimeError(
                "ReasoningCoordinator must be used inside a context manager."
            )

    # ── Specialist management ────────────────────────────────────────────

    def register_specialist(self, specialist: Specialist) -> None:
        """Register a specialist for subtask dispatch."""
        self._check_active()
        if any(s.name == specialist.name for s in self._specialists):
            raise ValueError(f"Specialist {specialist.name!r} already registered")
        if len(self._specialists) >= self._config.max_specialists:
            raise ValueError(
                f"Max specialists ({self._config.max_specialists}) reached"
            )
        self._specialists.append(specialist)

    def list_specialists(self) -> list[Specialist]:
        """Return currently registered specialists."""
        self._check_active()
        return list(self._specialists)

    # ── S5-3: Governance topology reading ───────────────────────────────

    def _read_governance_topology(
        self,
        topology: GovernanceTopology | None,
        *,
        task_context: str = "",
    ) -> GovernanceTopology:
        """Filter GovernanceTopology to edges relevant to task_context.

        Fail-closed: missing or empty topology returns empty GovernanceTopology,
        never permissive. Normalizes paths during matching only; returned edges
        retain their original path strings.
        """
        self._check_active()

        # Fail-closed: None → programming error / missing input
        if topology is None:
            logger.debug("_read_governance_topology: topology is None — returning empty (fail-closed)")
            return GovernanceTopology()

        # Fail-closed: empty edges → valid but vacuous
        if not topology.edges:
            logger.debug("_read_governance_topology: topology.edges is empty — returning empty")
            return GovernanceTopology()

        # No context (including whitespace-only) → all edges relevant, defensive copy
        if not task_context or not task_context.strip():
            logger.debug(
                "_read_governance_topology: no context — returning all %d edges",
                len(topology.edges),
            )
            return GovernanceTopology(edges=list(topology.edges))

        # Tokenize on whitespace + path separators (/, \, ., _, -)
        words = {w.casefold() for w in _EDGE_SEP_RE.split(task_context) if w}
        if not words:
            return GovernanceTopology(edges=list(topology.edges))

        # Pre-compute normalized token sets per edge, then filter
        filtered = []
        for e in topology.edges:
            src_tokens = {w.casefold() for w in _EDGE_SEP_RE.split(e.source) if w}
            tgt_tokens = {w.casefold() for w in _EDGE_SEP_RE.split(e.target) if w}
            if (words & src_tokens) or (words & tgt_tokens):
                filtered.append(e)

        logger.debug(
            "_read_governance_topology: %d/%d edges retained for context %r",
            len(filtered),
            len(topology.edges),
            task_context,
        )
        return GovernanceTopology(edges=filtered)

    # ── S5-5: Memory gate cache (READ-ONLY SIG query) ──────────────────

    def _check_memory_for_gates(
        self,
        context_key: str,
        *,
        memory: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """READ-ONLY SIG query of memory for prior gate decisions.

        Checks whether a prior governance-gate decision for *context_key* is
        cached in *memory* and still valid (not decay-expired).  Returns the
        cached entry on a hit so the caller can short-circuit recomputation.

        Writes to memory (S5-4) are performed exclusively by
        ``_compose_governance_gates``; this method never mutates *memory*.

        Returns:
            The cached gate-decision ``dict`` on a cache hit, or ``None`` when
            memory is absent, the key is missing, or the entry has expired.
        """
        self._check_active()

        if memory is None:
            logger.debug(
                "_check_memory_for_gates: memory is None — skipping lookup for key %r",
                context_key,
            )
            return None

        entry = memory.get(context_key)

        if entry is None:
            logger.debug(
                "_check_memory_for_gates: no cache entry for key %r",
                context_key,
            )
            return None

        if not isinstance(entry, dict):
            logger.warning(
                "_check_memory_for_gates: non-dict entry for key %r — treating as miss",
                context_key,
            )
            return None

        if entry.get("_expired", False):
            logger.debug(
                "_check_memory_for_gates: entry for key %r is expired — treating as miss",
                context_key,
            )
            return None

        logger.debug(
            "_check_memory_for_gates: cache hit for key %r",
            context_key,
        )
        return entry

    # ── S5-4 / V10: DGC — Dynamic Gate Composition (WRITE side of SIG) ─

    def _compose_governance_gates(
        self,
        *,
        governance_topology: GovernanceTopology | None = None,
        memory: dict[str, Any] | None = None,
        task_context: str = "",
    ) -> list[dict[str, Any]]:
        """Compose governance gates from topology and standard gate tasks (DGC).

        This is the WRITE side of the SIG loop (V10).  The READ side is
        ``_check_memory_for_gates``.  Together they form the complete loop.
        """
        self._check_active()

        # Filter topology to task-relevant edges
        filtered_topology = self._read_governance_topology(
            governance_topology, task_context=task_context
        )

        # Standard gate tasks — no parameters (per governance_tasks.py contract)
        gate_tasks = create_governance_gates()

        # Build gate results
        topology_edges_count = len(filtered_topology.edges)
        gate_results: list[dict[str, Any]] = []
        for task in gate_tasks:
            gate_result: dict[str, Any] = {
                "id": task.id,
                "node_id": task.node_id,
                "task_type": task.task_type,
                "clearance": task.clearance,
                "topology_edges_count": topology_edges_count,
            }
            gate_results.append(gate_result)

        # SIG write-side (V10) — persist each gate result to memory (namespaced)
        if memory is not None:
            for gate_result in gate_results:
                key = f"gate:{gate_result['id']}"
                if key in memory:
                    logger.warning(
                        "_compose_governance_gates: overwriting existing key %r",
                        key,
                    )
                memory[key] = gate_result

        logger.debug(
            "_compose_governance_gates: composed %d gate(s) from %d topology edge(s) "
            "for context %r (memory_write=%s)",
            len(gate_results),
            topology_edges_count,
            task_context,
            memory is not None,
        )

        return gate_results

    # ── Decomposition ────────────────────────────────────────────────────

    async def decompose(
        self,
        query: str,
        *,
        governance_topology: GovernanceTopology | None = None,
        memory: dict[str, Any] | None = None,
    ) -> TaskDecomposition:
        """Decompose a complex query into specialist subtasks."""
        self._check_active()
        raise NotImplementedError("Phase 1 stub — implementation in Phase 3")

    # ── Dispatch ─────────────────────────────────────────────────────────

    async def dispatch(
        self,
        decomposition: TaskDecomposition,
        *,
        governance_topology: GovernanceTopology | None = None,
        memory: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Assign subtasks to specialists and collect results."""
        self._check_active()
        raise NotImplementedError("Phase 1 stub — implementation in Phase 3")

    # ── Synthesis ────────────────────────────────────────────────────────

    async def synthesize(
        self,
        results: list[dict[str, Any]],
        *,
        governance_topology: GovernanceTopology | None = None,
        memory: dict[str, Any] | None = None,
    ) -> SynthesisResult:
        """Merge specialist outputs with clearance propagation and taint."""
        self._check_active()
        raise NotImplementedError("Phase 1 stub — implementation in Phase 4")

    # ── Full pipeline ────────────────────────────────────────────────────

    async def execute(
        self,
        query: str,
        *,
        governance_topology: GovernanceTopology | None = None,
        memory: dict[str, Any] | None = None,
    ) -> SynthesisResult:
        """Full pipeline: decompose → dispatch → synthesize."""
        self._check_active()
        raise NotImplementedError("Phase 1 stub — implementation in Phase 5")
