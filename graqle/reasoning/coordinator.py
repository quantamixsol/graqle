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
import json
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

# ClearanceLevel name→enum map for LLM string coercion (case-insensitive)
_CLEARANCE_MAP: dict[str, ClearanceLevel] = {
    level.name.upper(): level for level in ClearanceLevel
}


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

        logger.debug("decompose: starting for query %r", query[:80])

        cache_key = f"decompose:{query[:100]}"

        # Check memory for cached decomposition BEFORE gates (SIG read-first)
        cached = self._check_memory_for_gates(cache_key, memory=memory)
        if cached and isinstance(cached, dict) and "subtasks" in cached:
            cached_subtasks = cached["subtasks"]
            if isinstance(cached_subtasks, list) and cached_subtasks:
                try:
                    subtask_list = [SubTask.model_validate(s) for s in cached_subtasks]
                    logger.debug("decompose: cache hit — returning cached decomposition")
                    return TaskDecomposition(
                        original_query=query,
                        subtasks=subtask_list,
                    )
                except Exception as exc:
                    logger.warning(
                        "decompose: cached subtask validation failed (%s) — falling through to LLM",
                        exc,
                    )

        # Compose governance gates (only on cache miss)
        gates = self._compose_governance_gates(
            governance_topology=governance_topology,
            memory=memory,
            task_context=query,
        )
        logger.debug("decompose: composed %d governance gate(s)", len(gates))

        # Build prompt
        specialist_names = [s.name for s in self._specialists]
        prompt = (
            f"{self._config.COORDINATOR_DECOMPOSITION_PROMPT}\n\n"
            f"Query: {query}\n\n"
            f"Registered specialists: {specialist_names}\n\n"
            f"Decompose into JSON array of subtasks. Each subtask: "
            f"{{'description': '...', 'required_capabilities': [...], "
            f"'clearance_required': 'PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED'}}"
        )
        logger.debug("decompose: built prompt (%d chars)", len(prompt))

        # Call LLM with timeout — fail-closed to fallback on recoverable exceptions
        try:
            result = await asyncio.wait_for(
                self._llm_backend.generate(
                    prompt, max_tokens=2048, temperature=0.2
                ),
                timeout=self._config.specialist_timeout_seconds,
            )
        except (OSError, TimeoutError, asyncio.TimeoutError, RuntimeError, ValueError) as exc:
            logger.warning(
                "decompose: LLM call failed (%s) — using fallback", exc, exc_info=True,
            )
            return self._fallback_tasks(query)

        # Guard against None result
        if result is None:
            logger.debug("decompose: LLM returned None — using fallback")
            return self._fallback_tasks(query)
        logger.debug("decompose: LLM returned %d chars", len(str(result)))

        # Parse
        raw = str(result)
        subtasks = self._parse_task_specs(raw)

        # Fallback if parsing failed or returned empty
        if not subtasks:
            logger.debug("decompose: parse failed or empty — using fallback")
            return self._fallback_tasks(query)

        # Write cache for future SIG reads
        if memory is not None:
            memory[cache_key] = {
                "subtasks": [s.model_dump() for s in subtasks],
            }

        # Build and return TaskDecomposition
        decomposition = TaskDecomposition(
            original_query=query,
            subtasks=subtasks,
        )
        logger.debug(
            "decompose: returning %d subtask(s)", len(decomposition.subtasks)
        )
        return decomposition

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

        results: list[dict[str, Any]] = []

        for subtask in decomposition.subtasks:
            # Find best specialist: clearance_level >= clearance_required,
            # then maximise capability_tags overlap with required_capabilities.
            best_agent: AgentProtocol | None = None
            best_score: int = -1

            for agent in self._agent_roster:
                raw_clearance = getattr(agent, "clearance_level", None)
                agent_clearance: ClearanceLevel = (
                    raw_clearance if isinstance(raw_clearance, ClearanceLevel)
                    else ClearanceLevel.PUBLIC
                )

                # Clearance gate: agent must meet or exceed required clearance
                if agent_clearance < subtask.clearance_required:
                    continue

                # Score by capability_tags overlap
                agent_tags: tuple[str, ...] = getattr(agent, "capability_tags", ())
                score = len(set(agent_tags) & set(subtask.required_capabilities))

                if score > best_score:
                    best_score = score
                    best_agent = agent

            # Fallback to llm_backend when no agent qualifies
            if best_agent is None:
                logger.debug(
                    "dispatch: no specialist matched subtask %r (clearance=%s) — using llm_backend",
                    subtask.description[:60],
                    subtask.clearance_required,
                )
                try:
                    raw = await asyncio.wait_for(
                        self._llm_backend.generate(
                            subtask.description, max_tokens=2048, temperature=0.2
                        ),
                        timeout=self._config.specialist_timeout_seconds,
                    )
                    results.append({
                        "answer": str(raw),
                        "clearance": subtask.clearance_required,
                        "taint": [],
                    })
                except asyncio.TimeoutError:
                    logger.warning(
                        "dispatch: llm_backend timed out for subtask %r",
                        subtask.description[:60],
                        exc_info=True,
                    )
                    results.append({
                        "answer": f"Error: timeout processing subtask: {subtask.description}",
                        "clearance": subtask.clearance_required,
                        "taint": [],
                    })
                except (OSError, TimeoutError, RuntimeError, ValueError) as exc:
                    logger.warning(
                        "dispatch: llm_backend error for subtask %r: %s",
                        subtask.description[:60],
                        exc,
                        exc_info=True,
                    )
                    results.append({
                        "answer": f"Error: {exc}",
                        "clearance": subtask.clearance_required,
                        "taint": [],
                    })
                continue

            # Dispatch to best_agent with timeout
            agent_name: str = getattr(best_agent, "name", repr(best_agent))
            logger.debug(
                "dispatch: routing subtask %r to agent %r (clearance=%s, score=%d)",
                subtask.description[:60],
                agent_name,
                subtask.clearance_required,
                best_score,
            )
            try:
                raw = await asyncio.wait_for(
                    best_agent.generate(
                        subtask.description, max_tokens=2048, temperature=0.2
                    ),
                    timeout=self._config.specialist_timeout_seconds,
                )
                results.append({
                    "answer": str(raw),
                    "clearance": subtask.clearance_required,
                    "taint": [],
                })
            except asyncio.TimeoutError:
                logger.warning(
                    "dispatch: agent %r timed out for subtask %r",
                    agent_name,
                    subtask.description[:60],
                    exc_info=True,
                )
                results.append({
                    "answer": f"Error: timeout processing subtask: {subtask.description}",
                    "clearance": subtask.clearance_required,
                    "taint": [],
                })
            except (OSError, TimeoutError, RuntimeError, ValueError) as exc:
                logger.warning(
                    "dispatch: agent %r error for subtask %r: %s",
                    agent_name,
                    subtask.description[:60],
                    exc,
                    exc_info=True,
                )
                results.append({
                    "answer": f"Error: {exc}",
                    "clearance": subtask.clearance_required,
                    "taint": [],
                })

        logger.debug("dispatch: returning %d result(s)", len(results))
        return results

    # ── S5-7/8: Decomposition helpers ───────────────────────────────────

    def _parse_task_specs(self, raw: str) -> list[SubTask] | None:
        """Extract a JSON array of subtask dicts from raw LLM output.

        Returns a non-empty list of SubTask instances on success, or
        None if no valid array can be found/parsed.
        """
        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1 or end <= start:
            logger.debug("_parse_task_specs: no JSON array brackets found")
            return None

        candidate = raw[start : end + 1]
        try:
            items = json.loads(candidate)
        except json.JSONDecodeError as exc:
            logger.debug("_parse_task_specs: JSON decode error: %s", exc)
            return None

        if not isinstance(items, list) or not items:
            logger.debug("_parse_task_specs: parsed value is not a non-empty list")
            return None

        subtasks: list[SubTask] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            # Coerce clearance_required from string name to ClearanceLevel enum
            cr = item.get("clearance_required")
            if isinstance(cr, str):
                normalised = cr.upper()
                if normalised in _CLEARANCE_MAP:
                    coerced_item = {**item, "clearance_required": _CLEARANCE_MAP[normalised]}
                else:
                    logger.warning(
                        "_parse_task_specs: unrecognised clearance_required %r, skipping item", cr,
                    )
                    continue
            else:
                coerced_item = item
            try:
                subtasks.append(SubTask(**coerced_item))
            except Exception as exc:  # noqa: BLE001
                logger.debug("_parse_task_specs: SubTask validation error: %s", exc)
                continue

        if not subtasks:
            logger.debug("_parse_task_specs: no valid SubTask objects constructed")
            return None

        return subtasks

    def _fallback_tasks(self, query: str) -> TaskDecomposition:
        """Return a single-subtask decomposition when LLM parsing fails."""
        logger.debug("_fallback_tasks: constructing fallback for query %r", query[:80])
        fallback_subtask = SubTask(
            description=query,
            required_capabilities=[],
            clearance_required=ClearanceLevel.PUBLIC,
        )
        return TaskDecomposition(
            original_query=query,
            subtasks=[fallback_subtask],
        )

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

        # Handle empty results list with default PUBLIC clearance
        if not results:
            logger.debug("synthesize: empty results list — returning PUBLIC default")
            return SynthesisResult(
                merged_answer="No specialist results available.",
                clearance=ClearanceLevel.PUBLIC,
                taint=[],
            )

        # Propagate clearance using highest-clearance-wins
        # Missing 'clearance' key → fail-closed to highest available
        clearances: list[ClearanceLevel] = []
        for r in results:
            if "clearance" in r:
                clearances.append(r["clearance"])
            else:
                logger.warning(
                    "synthesize: result missing 'clearance' key — failing closed to highest available",
                )
                clearances.append(max(ClearanceLevel))

        merged_clearance: ClearanceLevel = max(clearances)

        # Accumulate deduplicated taint from all specialist results
        seen_taint: set[str] = set()
        merged_taint: list[str] = []
        for r in results:
            for tag in r.get("taint", []):
                if tag not in seen_taint:
                    seen_taint.add(tag)
                    merged_taint.append(tag)

        # Handle missing 'answer' key with empty string fallback
        answers: list[str] = [r.get("answer", "") for r in results]

        # Call LLM with COORDINATOR_SYNTHESIS_PROMPT to merge specialist answers
        answers_block = "\n\n".join(
            f"Specialist {i + 1}: {a}" for i, a in enumerate(answers) if a
        )
        prompt = (
            f"{self._config.COORDINATOR_SYNTHESIS_PROMPT}\n\n"
            f"Specialist answers to merge:\n\n{answers_block}"
        )

        merged_answer: str
        try:
            llm_result = await self._llm_backend.generate(
                prompt, max_tokens=2048, temperature=0.2
            )
            merged_answer = str(llm_result)
        except (OSError, TimeoutError, RuntimeError, ValueError) as exc:
            # On LLM failure, concatenate answers manually
            logger.warning(
                "synthesize: LLM call failed (%s) — falling back to concatenation",
                exc,
                exc_info=True,
            )
            merged_answer = "\n\n".join(a for a in answers if a) or "No answer available."

        # Write synthesis gate to memory if provided
        if memory is not None:
            memory["synthesis:result"] = {
                "merged_answer": merged_answer,
                "clearance": merged_clearance,
                "taint": merged_taint,
            }

        logger.debug(
            "synthesize: clearance=%s taint_count=%d answer_len=%d",
            merged_clearance,
            len(merged_taint),
            len(merged_answer),
        )

        return SynthesisResult(
            merged_answer=merged_answer,
            clearance=merged_clearance,
            taint=merged_taint,
        )

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

        logger.debug("execute: starting pipeline for query %r", query[:80])

        decomposition = await self.decompose(
            query,
            governance_topology=governance_topology,
            memory=memory,
        )
        logger.debug("execute: decomposed into %d subtask(s)", len(decomposition.subtasks))

        dispatch_results = await self.dispatch(
            decomposition,
            governance_topology=governance_topology,
            memory=memory,
        )
        logger.debug("execute: dispatched, got %d result(s)", len(dispatch_results))

        synthesis = await self.synthesize(
            dispatch_results,
            governance_topology=governance_topology,
            memory=memory,
        )
        logger.debug(
            "execute: synthesis complete (clearance=%s, taint_count=%d)",
            synthesis.clearance,
            len(synthesis.taint),
        )
        return synthesis
