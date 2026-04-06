"""S5-13: Tests for ReasoningCoordinator Phase 1 skeleton (PR #12 review fixes).

Validates:
    - B1:  Constructor accepts llm_backend + agent_roster + CoordinatorConfig
    - B2:  Ephemeral lifecycle via context manager
    - M1:  Config key names aligned to R16 spec
    - M2:  GovernanceTopology Pydantic model validation
    - S5-1: Specialist dataclass
    - S5-12: Pydantic models (SubTask, TaskDecomposition, SynthesisResult)
    - Phase 1 stub methods raise NotImplementedError
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from graqle.core.types import AgentProtocol, ClearanceLevel
from graqle.reasoning.coordinator import (
    CoordinatorConfig,
    GovernanceEdge,
    GovernanceTopology,
    ReasoningCoordinator,
    Specialist,
    SubTask,
    SynthesisResult,
    TaskDecomposition,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


_VALID_CONFIG = CoordinatorConfig(
    COORDINATOR_DECOMPOSITION_PROMPT="decompose_v1",
    COORDINATOR_SYNTHESIS_PROMPT="synthesize_v1",
    max_specialists=4,
    specialist_timeout_seconds=30.0,
)


@pytest.fixture()
def mock_llm_backend() -> MagicMock:
    from unittest.mock import AsyncMock
    backend = MagicMock(name="llm_backend")
    # Phase 3: decompose() calls await self._llm_backend.generate()
    backend.generate = AsyncMock(return_value="[]")
    return backend


@pytest.fixture()
def mock_agent_roster() -> list[MagicMock]:
    from unittest.mock import AsyncMock
    agent = MagicMock(name="specialist")
    agent.name = "test-specialist"
    agent.model_id = "test-model"
    agent.generate = AsyncMock(return_value="")
    return [agent]


@pytest.fixture()
def coordinator(
    mock_llm_backend: MagicMock,
    mock_agent_roster: list[MagicMock],
) -> ReasoningCoordinator:
    return ReasoningCoordinator(
        mock_llm_backend,
        mock_agent_roster,
        _VALID_CONFIG,
    )


@pytest.fixture()
def sample_topology() -> GovernanceTopology:
    return GovernanceTopology(edges=[
        GovernanceEdge(source="a", target="b", relation="COMPLIES_WITH"),
        GovernanceEdge(source="c", target="d", relation="AMENDS"),
        GovernanceEdge(source="e", target="f", relation="GOVERNS"),
    ])


# ── B1: Constructor signature ────────────────────────────────────────────────


class TestConstructorB1:
    def test_accepts_llm_backend_and_roster(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        assert coordinator._llm_backend is not None
        assert len(coordinator._agent_roster) == 1

    def test_config_stored(self, coordinator: ReasoningCoordinator) -> None:
        assert coordinator._config is _VALID_CONFIG

    def test_sync_agent_rejected_at_init(self) -> None:
        """Async guard: sync generate() must raise TypeError at construction."""

        class SyncAgent:
            name = "sync-agent"
            model_id = "sync-model"

            def generate(self, prompt: str) -> str:
                return ""

        with pytest.raises(TypeError, match="must be a coroutine function"):
            ReasoningCoordinator(
                MagicMock(name="llm_backend"),
                [SyncAgent()],
                _VALID_CONFIG,
            )


# ── B2: Ephemeral lifecycle ──────────────────────────────────────────────────


class TestEphemeralB2:
    def test_not_active_by_default(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        assert coordinator._active is False

    def test_context_manager_activates(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        with coordinator:
            assert coordinator._active is True
        assert coordinator._active is False

    def test_methods_raise_outside_context(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        with pytest.raises(RuntimeError, match="context manager"):
            coordinator.register_specialist(Specialist(name="x", model_id="m"))

    def test_methods_work_inside_context(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        with coordinator:
            coordinator.register_specialist(Specialist(name="x", model_id="m"))
            assert len(coordinator.list_specialists()) == 1

    @pytest.mark.asyncio
    async def test_async_context_manager(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        async with coordinator:
            assert coordinator._active is True
        assert coordinator._active is False

    def test_specialists_cleared_on_exit(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        with coordinator:
            coordinator.register_specialist(Specialist(name="x", model_id="m"))
        # After exit, specialists should be cleared (ephemeral)
        with coordinator:
            assert coordinator.list_specialists() == []

    def test_duplicate_specialist_rejected(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        with coordinator:
            coordinator.register_specialist(Specialist(name="x", model_id="m"))
            with pytest.raises(ValueError, match="already registered"):
                coordinator.register_specialist(Specialist(name="x", model_id="m2"))

    def test_max_specialists_enforced(
        self, mock_llm_backend: MagicMock,
        mock_agent_roster: list[MagicMock],
    ) -> None:
        small_config = CoordinatorConfig(
            COORDINATOR_DECOMPOSITION_PROMPT="dp",
            COORDINATOR_SYNTHESIS_PROMPT="sp",
            max_specialists=1,
            specialist_timeout_seconds=10.0,
        )
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, small_config)
        with coord:
            coord.register_specialist(Specialist(name="a", model_id="m"))
            with pytest.raises(ValueError, match="Max specialists"):
                coord.register_specialist(Specialist(name="b", model_id="m"))


# ── M1: Config key names ────────────────────────────────────────────────────


class TestConfigM1:
    def test_spec_key_names(self) -> None:
        cfg = CoordinatorConfig(
            COORDINATOR_DECOMPOSITION_PROMPT="dp",
            COORDINATOR_SYNTHESIS_PROMPT="sp",
            max_specialists=2,
            specialist_timeout_seconds=10.0,
        )
        assert cfg.COORDINATOR_DECOMPOSITION_PROMPT == "dp"
        assert cfg.COORDINATOR_SYNTHESIS_PROMPT == "sp"

    def test_missing_key_raises(self) -> None:
        with pytest.raises(ValidationError):
            CoordinatorConfig(
                COORDINATOR_DECOMPOSITION_PROMPT="dp",
                # missing COORDINATOR_SYNTHESIS_PROMPT
                max_specialists=2,
                specialist_timeout_seconds=10.0,
            )

    def test_max_specialists_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            CoordinatorConfig(
                COORDINATOR_DECOMPOSITION_PROMPT="dp",
                COORDINATOR_SYNTHESIS_PROMPT="sp",
                max_specialists=0,
                specialist_timeout_seconds=10.0,
            )

    def test_timeout_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            CoordinatorConfig(
                COORDINATOR_DECOMPOSITION_PROMPT="dp",
                COORDINATOR_SYNTHESIS_PROMPT="sp",
                max_specialists=2,
                specialist_timeout_seconds=-1.0,
            )


# ── M2: GovernanceTopology ───────────────────────────────────────────────────


class TestGovernanceTopologyM2:
    def test_valid_topology(self, sample_topology: GovernanceTopology) -> None:
        assert len(sample_topology.edges) == 3
        assert len(sample_topology.complies_with) == 1
        assert len(sample_topology.amends) == 1
        assert len(sample_topology.governs) == 1

    def test_empty_topology(self) -> None:
        t = GovernanceTopology()
        assert t.edges == []

    def test_invalid_relation_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GovernanceEdge(source="a", target="b", relation="INVALID")

    def test_edge_properties_default_empty(self) -> None:
        e = GovernanceEdge(source="a", target="b", relation="GOVERNS")
        assert e.properties == {}


# ── S5-1: Specialist dataclass ───────────────────────────────────────────────


class TestSpecialist:
    def test_creation(self) -> None:
        s = Specialist(
            name="analyst",
            model_id="claude-sonnet-4-6",
            capability_tags=("summarization",),
            clearance_level=ClearanceLevel.PUBLIC,
        )
        assert s.name == "analyst"

    def test_defaults(self) -> None:
        s = Specialist(name="basic", model_id="m1")
        assert s.capability_tags == ()
        assert s.clearance_level == ClearanceLevel.PUBLIC

    def test_frozen(self) -> None:
        s = Specialist(name="x", model_id="m")
        with pytest.raises(AttributeError):
            s.name = "y"  # type: ignore[misc]

    def test_equality(self) -> None:
        kw: dict[str, Any] = {"name": "a", "model_id": "m"}
        assert Specialist(**kw) == Specialist(**kw)


# ── S5-12: Pydantic models ──────────────────────────────────────────────────


class TestPydanticModels:
    def test_subtask_valid(self) -> None:
        st = SubTask(description="Do X")
        assert st.clearance_required == ClearanceLevel.PUBLIC

    def test_subtask_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SubTask(description="")

    def test_decomposition_valid(self) -> None:
        td = TaskDecomposition(
            original_query="Q",
            subtasks=[SubTask(description="Do X")],
        )
        assert len(td.subtasks) == 1

    def test_decomposition_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaskDecomposition(original_query="Q", subtasks=[])

    def test_synthesis_valid(self) -> None:
        sr = SynthesisResult(
            merged_answer="42",
            clearance=ClearanceLevel.PUBLIC,
        )
        assert sr.taint == []

    def test_synthesis_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SynthesisResult(merged_answer="", clearance=ClearanceLevel.PUBLIC)


# ── Phase 1 stub methods ────────────────────────────────────────────────────


class TestStubMethods:
    @pytest.mark.asyncio
    async def test_decompose_returns_task_decomposition(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """decompose() now returns TaskDecomposition (Phase 3 implemented)."""
        with coordinator:
            # LLM returns garbage → fallback triggers → single subtask
            result = await coordinator.decompose("test query")
        assert isinstance(result, TaskDecomposition)
        assert len(result.subtasks) >= 1

    @pytest.mark.asyncio
    async def test_dispatch_returns_results(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """dispatch() now returns list of results (Phase 5 implemented)."""
        td = TaskDecomposition(
            original_query="Q",
            subtasks=[SubTask(description="Do X")],
        )
        with coordinator:
            results = await coordinator.dispatch(td)
        assert isinstance(results, list)
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_synthesize_empty_results(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """synthesize() with empty results returns PUBLIC default (Phase 4 implemented)."""
        with coordinator:
            result = await coordinator.synthesize([])
        assert isinstance(result, SynthesisResult)
        assert result.clearance == ClearanceLevel.PUBLIC
        assert result.taint == []

    @pytest.mark.asyncio
    async def test_execute_returns_synthesis_result(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """execute() now returns SynthesisResult (Phase 5 implemented)."""
        with coordinator:
            result = await coordinator.execute("test query")
        assert isinstance(result, SynthesisResult)


# ── Phase 2A: AgentProtocol conformance (N1) ──────────────────────────────


class TestAgentProtocolConformance:
    """MAJOR-1: AgentProtocol isinstance() conformance coverage.

    NOTE: @runtime_checkable checks attribute *presence* only —
    a sync generate() implementation silently passes isinstance().
    """

    def test_conforming_agent_passes_isinstance(self) -> None:
        class StubAgent:
            name = "stub-agent"
            model_id = "stub-model-v1"

            async def generate(self, prompt: str, **kwargs: Any) -> str:
                return ""

        assert isinstance(StubAgent(), AgentProtocol) is True

    def test_nonconforming_object_fails_isinstance(self) -> None:
        assert isinstance(object(), AgentProtocol) is False

    def test_missing_generate_fails_isinstance(self) -> None:
        class NoGenerate:
            name = "stub-agent"
            model_id = "stub-model-v1"

        assert isinstance(NoGenerate(), AgentProtocol) is False

    def test_specialist_dataclass_not_agent(self) -> None:
        """Specialist is a descriptor, not a runnable agent — lacks generate()."""
        s = Specialist(name="test-specialist", model_id="stub-model-v1")
        # Specialist has .name and .model_id but no .generate() method
        assert not hasattr(s, "generate")
        assert isinstance(s, AgentProtocol) is False

    def test_conforming_agent_with_property(self) -> None:
        """@property pattern (idiomatic production pattern) also satisfies Protocol."""

        class PropertyAgent:
            @property
            def name(self) -> str:
                return "prop-agent"

            @property
            def model_id(self) -> str:
                return "prop-model-v1"

            async def generate(self, prompt: str, **kwargs: Any) -> str:
                return ""

        assert isinstance(PropertyAgent(), AgentProtocol) is True

    def test_sync_generate_falsely_passes_isinstance(self) -> None:
        """@runtime_checkable can't detect sync vs async — document the trap."""
        import asyncio

        class SyncAgent:
            name = "sync-agent"
            model_id = "sync-model-v1"

            def generate(self, prompt: str, **kwargs: Any) -> str:
                return ""

        agent = SyncAgent()
        # isinstance passes (structural match) — THIS IS THE KNOWN TRAP
        assert isinstance(agent, AgentProtocol) is True
        # But iscoroutinefunction reveals the lie
        assert asyncio.iscoroutinefunction(agent.generate) is False

    def test_missing_name_fails_isinstance(self) -> None:
        class NoName:
            model_id = "stub-model-v1"

            async def generate(self, prompt: str, **kwargs: Any) -> str:
                return ""

        assert isinstance(NoName(), AgentProtocol) is False

    def test_missing_model_id_fails_isinstance(self) -> None:
        class NoModelId:
            name = "stub-agent"

            async def generate(self, prompt: str, **kwargs: Any) -> str:
                return ""

        assert isinstance(NoModelId(), AgentProtocol) is False


# ── Phase 2B: _read_governance_topology (S5-3) ────────────────────────────


class TestReadGovernanceTopology:
    """S5-3: Governance topology filtering — fail-closed, case-insensitive, Windows-safe."""

    def test_inactive_coordinator_raises(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        with pytest.raises(RuntimeError):
            coordinator._read_governance_topology(GovernanceTopology())

    def test_none_topology_returns_empty(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        with coordinator:
            result = coordinator._read_governance_topology(None)
        assert result.edges == []

    def test_empty_edges_returns_empty(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        with coordinator:
            result = coordinator._read_governance_topology(GovernanceTopology(edges=[]))
        assert result.edges == []

    def test_empty_context_returns_all_edges(
        self, coordinator: ReasoningCoordinator, sample_topology: GovernanceTopology,
    ) -> None:
        with coordinator:
            result = coordinator._read_governance_topology(sample_topology, task_context="")
        assert result.edges == sample_topology.edges

    def test_filters_by_source_word(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        topo = GovernanceTopology(edges=[
            GovernanceEdge(source="auth/login", target="policy", relation="GOVERNS"),
            GovernanceEdge(source="billing/pay", target="audit", relation="COMPLIES_WITH"),
        ])
        with coordinator:
            result = coordinator._read_governance_topology(topo, task_context="auth")
        assert len(result.edges) == 1
        assert result.edges[0].source == "auth/login"

    def test_filters_by_target_word(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        topo = GovernanceTopology(edges=[
            GovernanceEdge(source="x", target="auth/verify", relation="AMENDS"),
            GovernanceEdge(source="y", target="billing/pay", relation="GOVERNS"),
        ])
        with coordinator:
            result = coordinator._read_governance_topology(topo, task_context="auth")
        assert len(result.edges) == 1

    def test_case_insensitive_match(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        topo = GovernanceTopology(edges=[
            GovernanceEdge(source="Auth/Login", target="policy", relation="GOVERNS"),
        ])
        with coordinator:
            r_lower = coordinator._read_governance_topology(topo, task_context="auth")
            r_upper = coordinator._read_governance_topology(topo, task_context="AUTH")
        assert len(r_lower.edges) == 1
        assert r_lower.edges == r_upper.edges

    def test_multiword_context_union(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        topo = GovernanceTopology(edges=[
            GovernanceEdge(source="auth/login", target="p", relation="GOVERNS"),
            GovernanceEdge(source="billing/pay", target="q", relation="COMPLIES_WITH"),
            GovernanceEdge(source="unrelated", target="r", relation="AMENDS"),
        ])
        with coordinator:
            result = coordinator._read_governance_topology(topo, task_context="auth billing")
        assert len(result.edges) == 2

    def test_no_match_returns_empty(
        self, coordinator: ReasoningCoordinator, sample_topology: GovernanceTopology,
    ) -> None:
        with coordinator:
            result = coordinator._read_governance_topology(
                sample_topology, task_context="zzznomatch"
            )
        assert result.edges == []

    def test_windows_path_normalization(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        edge = GovernanceEdge(
            source="graqle\\auth\\login", target="policy", relation="GOVERNS"
        )
        topo = GovernanceTopology(edges=[edge])
        with coordinator:
            result = coordinator._read_governance_topology(topo, task_context="auth")
        assert len(result.edges) == 1

    def test_returns_governance_topology_instance(
        self, coordinator: ReasoningCoordinator, sample_topology: GovernanceTopology,
    ) -> None:
        with coordinator:
            result = coordinator._read_governance_topology(sample_topology, task_context="a")
        assert isinstance(result, GovernanceTopology)

    def test_fail_closed_none_with_context(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """Fail-closed even when task_context is provided."""
        with coordinator:
            result = coordinator._read_governance_topology(None, task_context="auth")
        assert result.edges == []

    def test_whitespace_only_context_returns_all(
        self, coordinator: ReasoningCoordinator, sample_topology: GovernanceTopology,
    ) -> None:
        """Whitespace-only context treated as no context → return all edges."""
        with coordinator:
            result = coordinator._read_governance_topology(sample_topology, task_context="   ")
        assert len(result.edges) == len(sample_topology.edges)

    def test_dotted_module_path(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        edge = GovernanceEdge(
            source="graqle.backends.api", target="policy", relation="GOVERNS"
        )
        topo = GovernanceTopology(edges=[edge])
        with coordinator:
            result = coordinator._read_governance_topology(topo, task_context="backends")
        assert len(result.edges) == 1

    def test_underscore_joined_segment(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        edge = GovernanceEdge(
            source="auth_service/login", target="policy", relation="GOVERNS"
        )
        topo = GovernanceTopology(edges=[edge])
        with coordinator:
            result = coordinator._read_governance_topology(topo, task_context="auth")
        assert len(result.edges) == 1

    def test_empty_context_returns_defensive_copy(
        self, coordinator: ReasoningCoordinator, sample_topology: GovernanceTopology,
    ) -> None:
        """Empty context returns a copy, not the original object."""
        with coordinator:
            result = coordinator._read_governance_topology(sample_topology, task_context="")
        assert result is not sample_topology
        assert result.edges == sample_topology.edges


# ── Phase 3: TestDecompose ────────────────────────────────────────────────


class TestDecompose:
    """Phase 3: Tests for ReasoningCoordinator.decompose()."""

    @pytest.mark.asyncio
    async def test_happy_path_json_subtasks(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """LLM returns valid JSON array → TaskDecomposition with correct subtasks."""
        from unittest.mock import AsyncMock
        valid_json = (
            '[{"description": "Fetch data", "required_capabilities": []},'
            ' {"description": "Analyse data", "required_capabilities": []}]'
        )
        mock_llm_backend.generate = AsyncMock(return_value=valid_json)
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        with coord:
            result = await coord.decompose("test query")
        assert isinstance(result, TaskDecomposition)
        assert len(result.subtasks) == 2
        assert result.subtasks[0].description == "Fetch data"
        assert result.subtasks[1].description == "Analyse data"

    @pytest.mark.asyncio
    async def test_empty_json_triggers_fallback(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """LLM returns '[]' → fallback returns single subtask."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="[]")
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        with coord:
            result = await coord.decompose("empty json query")
        assert isinstance(result, TaskDecomposition)
        assert len(result.subtasks) == 1
        assert result.subtasks[0].description == "empty json query"

    @pytest.mark.asyncio
    async def test_garbage_response_triggers_fallback(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """LLM returns 'hello world' → fallback returns single subtask."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="hello world")
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        with coord:
            result = await coord.decompose("garbage response query")
        assert isinstance(result, TaskDecomposition)
        assert len(result.subtasks) == 1
        assert result.subtasks[0].description == "garbage response query"

    @pytest.mark.asyncio
    async def test_inactive_raises(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """Without context manager, decompose raises RuntimeError."""
        with pytest.raises(RuntimeError, match="context manager"):
            await coordinator.decompose("should raise")


# ── Phase 3: TestParseTaskSpecs ───────────────────────────────────────────


class TestParseTaskSpecs:
    """Phase 3: Tests for ReasoningCoordinator._parse_task_specs()."""

    def test_valid_json_array(self, coordinator: ReasoningCoordinator) -> None:
        raw = '[{"description": "task1", "required_capabilities": []}]'
        with coordinator:
            result = coordinator._parse_task_specs(raw)
        assert result is not None
        assert len(result) == 1
        assert result[0].description == "task1"

    def test_json_in_markdown_fences(self, coordinator: ReasoningCoordinator) -> None:
        raw = '```json\n[{"description": "fenced task", "required_capabilities": []}]\n```'
        with coordinator:
            result = coordinator._parse_task_specs(raw)
        assert result is not None
        assert len(result) == 1
        assert result[0].description == "fenced task"

    def test_no_brackets_returns_none(self, coordinator: ReasoningCoordinator) -> None:
        with coordinator:
            result = coordinator._parse_task_specs("no json here")
        assert result is None

    def test_invalid_json_returns_none(self, coordinator: ReasoningCoordinator) -> None:
        with coordinator:
            result = coordinator._parse_task_specs("[{broken")
        assert result is None

    def test_partial_valid_items(self, coordinator: ReasoningCoordinator) -> None:
        """2 items, 1 valid 1 invalid → returns list with 1 SubTask."""
        raw = '[{"description": "valid task", "required_capabilities": []}, {"bad_key": "no description"}]'
        with coordinator:
            result = coordinator._parse_task_specs(raw)
        assert result is not None
        assert len(result) == 1
        assert result[0].description == "valid task"


# ── Phase 3: TestFallbackTasks ────────────────────────────────────────────


class TestFallbackTasks:
    """Phase 3: Tests for ReasoningCoordinator._fallback_tasks()."""

    def test_returns_single_subtask(self, coordinator: ReasoningCoordinator) -> None:
        with coordinator:
            result = coordinator._fallback_tasks("my fallback query")
        assert isinstance(result, TaskDecomposition)
        assert len(result.subtasks) == 1
        assert result.subtasks[0].description == "my fallback query"

    def test_clearance_is_public(self, coordinator: ReasoningCoordinator) -> None:
        with coordinator:
            result = coordinator._fallback_tasks("clearance check")
        assert result.subtasks[0].clearance_required == ClearanceLevel.PUBLIC

    def test_original_query_preserved(self, coordinator: ReasoningCoordinator) -> None:
        query = "preserve this query"
        with coordinator:
            result = coordinator._fallback_tasks(query)
        assert result.original_query == query


# ── Phase 2C: _check_memory_for_gates (S5-5) ──────────────────────────────


class TestCheckMemoryForGates:
    """Tests for ReasoningCoordinator._check_memory_for_gates."""

    def test_returns_none_when_memory_is_none(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        with coordinator:
            result = coordinator._check_memory_for_gates("key", memory=None)
        assert result is None

    def test_returns_none_when_key_missing(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        with coordinator:
            result = coordinator._check_memory_for_gates("key", memory={})
        assert result is None

    def test_returns_cached_result_when_valid(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        entry: dict[str, Any] = {"gate": "PASS", "_expired": False}
        with coordinator:
            result = coordinator._check_memory_for_gates("k", memory={"k": entry})
        assert result == entry

    def test_expired_entry_returns_none(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        entry: dict[str, Any] = {"gate": "PASS", "_expired": True}
        with coordinator:
            result = coordinator._check_memory_for_gates("k", memory={"k": entry})
        assert result is None

    def test_read_only_does_not_mutate_memory(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        entry: dict[str, Any] = {"gate": "PASS", "_expired": False}
        memory = {"k": entry}
        memory_before = {"k": {"gate": "PASS", "_expired": False}}
        with coordinator:
            coordinator._check_memory_for_gates("k", memory=memory)
        assert memory == memory_before

    def test_inactive_coordinator_raises(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        with pytest.raises(RuntimeError, match="context manager"):
            coordinator._check_memory_for_gates("key", memory={})


# ── Phase 2D: _compose_governance_gates (S5-4, DGC) ───────────────────────


class TestComposeGovernanceGates:
    """Tests for ReasoningCoordinator._compose_governance_gates."""

    def test_inactive_raises(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        with pytest.raises(RuntimeError):
            coordinator._compose_governance_gates()

    def test_returns_three_standard_gates(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        with coordinator:
            results = coordinator._compose_governance_gates()
        assert len(results) == 3
        ids = {r["id"] for r in results}
        assert ids == {
            "gate_git_governance",
            "gate_ip_trade_secret",
            "gate_clearance_verification",
        }

    def test_gate_result_has_required_keys(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        with coordinator:
            results = coordinator._compose_governance_gates()
        required_keys = {"id", "node_id", "task_type", "clearance", "topology_edges_count"}
        for gate in results:
            assert required_keys.issubset(gate.keys())

    def test_topology_edges_count_matches(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        topology = GovernanceTopology(edges=[
            GovernanceEdge(source="a", target="b", relation="COMPLIES_WITH"),
            GovernanceEdge(source="c", target="d", relation="GOVERNS"),
        ])
        with coordinator:
            results = coordinator._compose_governance_gates(governance_topology=topology)
        for gate in results:
            assert gate["topology_edges_count"] == 2

    def test_writes_to_memory_when_provided(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        memory: dict[str, Any] = {}
        with coordinator:
            coordinator._compose_governance_gates(memory=memory)
        assert "gate:gate_git_governance" in memory
        assert "gate:gate_ip_trade_secret" in memory
        assert "gate:gate_clearance_verification" in memory

    def test_no_memory_write_when_none(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        with coordinator:
            results = coordinator._compose_governance_gates(memory=None)
        assert len(results) == 3

    def test_filters_topology_by_context(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        topology = GovernanceTopology(edges=[
            GovernanceEdge(source="auth/login", target="policy", relation="GOVERNS"),
            GovernanceEdge(source="billing/pay", target="audit", relation="COMPLIES_WITH"),
            GovernanceEdge(source="auth/verify", target="rules", relation="AMENDS"),
        ])
        with coordinator:
            results = coordinator._compose_governance_gates(
                governance_topology=topology,
                task_context="auth",
            )
        for gate in results:
            assert gate["topology_edges_count"] == 2

    def test_empty_topology_returns_gates(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        with coordinator:
            results = coordinator._compose_governance_gates(governance_topology=None)
        assert len(results) == 3
        for gate in results:
            assert gate["topology_edges_count"] == 0


# ── Phase 2E: Integration tests (S5-3 → S5-5 → S5-4 chain) ───────────────


class TestGovernanceIntegration:
    """Integration tests exercising the full S5-3→S5-5→S5-4 governance chain."""

    def test_full_governance_chain(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """read_topology → check_memory (miss) → compose (write) → check_memory (hit)."""
        topology = GovernanceTopology(edges=[
            GovernanceEdge(source="auth/login", target="policy", relation="GOVERNS"),
        ])
        memory: dict[str, Any] = {}
        context_key = "gate:gate_git_governance"

        with coordinator:
            filtered = coordinator._read_governance_topology(topology, task_context="auth")
            assert len(filtered.edges) == 1

            miss = coordinator._check_memory_for_gates(context_key, memory=memory)
            assert miss is None

            coordinator._compose_governance_gates(
                governance_topology=filtered, memory=memory, task_context="auth",
            )
            assert context_key in memory

            hit = coordinator._check_memory_for_gates(context_key, memory=memory)
            assert hit is not None
            assert hit == memory[context_key]

    def test_memory_roundtrip(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """Compose writes to memory; check reads back; values match."""
        memory: dict[str, Any] = {}
        with coordinator:
            results = coordinator._compose_governance_gates(memory=memory)
            for gate in results:
                key = f"gate:{gate['id']}"
                cached = coordinator._check_memory_for_gates(key, memory=memory)
                assert cached is not None
                assert cached["id"] == gate["id"]
                assert cached["topology_edges_count"] == gate["topology_edges_count"]

    def test_expired_gate_triggers_recompose(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """Expired entry → miss → recompose overwrites with fresh result."""
        memory: dict[str, Any] = {
            "gate:gate_git_governance": {"id": "gate_git_governance", "_expired": True},
        }
        with coordinator:
            miss = coordinator._check_memory_for_gates("gate:gate_git_governance", memory=memory)
            assert miss is None

            coordinator._compose_governance_gates(memory=memory)
            fresh = coordinator._check_memory_for_gates("gate:gate_git_governance", memory=memory)
            assert fresh is not None
            assert fresh.get("_expired") is not True

    def test_topology_flows_through_chain(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """Topology with auth edges filters correctly through compose."""
        topology = GovernanceTopology(edges=[
            GovernanceEdge(source="auth/login", target="policy", relation="GOVERNS"),
            GovernanceEdge(source="auth/verify", target="rules", relation="AMENDS"),
            GovernanceEdge(source="billing/pay", target="audit", relation="COMPLIES_WITH"),
        ])
        with coordinator:
            results = coordinator._compose_governance_gates(
                governance_topology=topology, memory={}, task_context="auth",
            )
            for gate in results:
                assert gate["topology_edges_count"] == 2

    def test_context_manager_required_for_all(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """All 3 governance methods raise RuntimeError outside context manager."""
        with pytest.raises(RuntimeError, match="context manager"):
            coordinator._read_governance_topology(GovernanceTopology())
        with pytest.raises(RuntimeError, match="context manager"):
            coordinator._check_memory_for_gates("key", memory={})
        with pytest.raises(RuntimeError, match="context manager"):
            coordinator._compose_governance_gates(memory={})


# ── Phase 3: TestDecomposeComprehensive ──────────────────────────────────────


class TestDecomposeComprehensive:
    """Comprehensive edge-case tests for ReasoningCoordinator.decompose()."""

    @pytest.mark.asyncio
    async def test_clearance_internal_parsed(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """clearance_required=INTERNAL is parsed and stored correctly."""
        from unittest.mock import AsyncMock
        valid_json = (
            '[{"description": "Internal task", "required_capabilities": [],'
            ' "clearance_required": "INTERNAL"}]'
        )
        mock_llm_backend.generate = AsyncMock(return_value=valid_json)
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        with coord:
            result = await coord.decompose("internal clearance query")
        assert isinstance(result, TaskDecomposition)
        assert len(result.subtasks) == 1
        assert result.subtasks[0].clearance_required == ClearanceLevel.INTERNAL

    @pytest.mark.asyncio
    async def test_clearance_confidential_parsed(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """clearance_required=CONFIDENTIAL is parsed and stored correctly."""
        from unittest.mock import AsyncMock
        valid_json = (
            '[{"description": "Confidential task", "required_capabilities": [],'
            ' "clearance_required": "CONFIDENTIAL"}]'
        )
        mock_llm_backend.generate = AsyncMock(return_value=valid_json)
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        with coord:
            result = await coord.decompose("confidential clearance query")
        assert isinstance(result, TaskDecomposition)
        assert result.subtasks[0].clearance_required == ClearanceLevel.CONFIDENTIAL

    @pytest.mark.asyncio
    async def test_clearance_restricted_parsed(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """clearance_required=RESTRICTED is parsed and stored correctly."""
        from unittest.mock import AsyncMock
        valid_json = (
            '[{"description": "Restricted task", "required_capabilities": [],'
            ' "clearance_required": "RESTRICTED"}]'
        )
        mock_llm_backend.generate = AsyncMock(return_value=valid_json)
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        with coord:
            result = await coord.decompose("restricted clearance query")
        assert isinstance(result, TaskDecomposition)
        assert result.subtasks[0].clearance_required == ClearanceLevel.RESTRICTED

    @pytest.mark.asyncio
    async def test_llm_exception_triggers_fallback(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """generate() raises recoverable exception → fallback TaskDecomposition returned."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        with coord:
            result = await coord.decompose("exception query")
        assert isinstance(result, TaskDecomposition)
        assert len(result.subtasks) == 1
        assert result.subtasks[0].description == "exception query"
        assert result.subtasks[0].clearance_required == ClearanceLevel.PUBLIC

    @pytest.mark.asyncio
    async def test_memory_cache_hit_skips_llm(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Cached decomposition in memory returns without calling LLM."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="[]")
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        query = "cached query"
        cache_key = f"decompose:{query[:100]}"
        cached_subtasks = [{"description": "Cached subtask", "required_capabilities": []}]
        memory: dict[str, Any] = {cache_key: {"subtasks": cached_subtasks, "_expired": False}}
        with coord:
            result = await coord.decompose(query, memory=memory)
        # LLM should not have been called
        mock_llm_backend.generate.assert_not_called()
        assert isinstance(result, TaskDecomposition)
        assert result.subtasks[0].description == "Cached subtask"

    @pytest.mark.asyncio
    async def test_expired_cache_calls_llm(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Expired cache entry causes LLM to be called (cache miss)."""
        from unittest.mock import AsyncMock
        valid_json = '[{"description": "Fresh task", "required_capabilities": []}]'
        mock_llm_backend.generate = AsyncMock(return_value=valid_json)
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        query = "expired cache query"
        cache_key = f"decompose:{query[:100]}"
        memory: dict[str, Any] = {cache_key: {"subtasks": [], "_expired": True}}
        with coord:
            result = await coord.decompose(query, memory=memory)
        mock_llm_backend.generate.assert_called_once()
        assert result.subtasks[0].description == "Fresh task"

    @pytest.mark.asyncio
    async def test_unicode_query(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Unicode characters in query are handled without error."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="[]")
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        unicode_query = "分析データ 🔍 résumé naïve café"
        with coord:
            result = await coord.decompose(unicode_query)
        assert isinstance(result, TaskDecomposition)
        assert result.original_query == unicode_query
        assert len(result.subtasks) >= 1

    @pytest.mark.asyncio
    async def test_very_long_query(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Query longer than 5000 chars is handled without error."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="[]")
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        long_query = "x" * 5001
        with coord:
            result = await coord.decompose(long_query)
        assert isinstance(result, TaskDecomposition)
        assert result.original_query == long_query

    @pytest.mark.asyncio
    async def test_empty_specialist_list_in_prompt(
        self, mock_llm_backend: MagicMock,
    ) -> None:
        """Empty agent roster does not crash decompose(); fallback still works."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="[]")
        coord = ReasoningCoordinator(mock_llm_backend, [], _VALID_CONFIG)
        with coord:
            result = await coord.decompose("no specialists query")
        assert isinstance(result, TaskDecomposition)
        assert len(result.subtasks) >= 1

    @pytest.mark.asyncio
    async def test_governance_topology_passed_to_compose_gates(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """GovernanceTopology passed to decompose() flows to _compose_governance_gates."""
        from unittest.mock import AsyncMock, patch
        mock_llm_backend.generate = AsyncMock(return_value="[]")
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        topology = GovernanceTopology(edges=[
            GovernanceEdge(source="auth/login", target="policy", relation="GOVERNS"),
        ])
        with coord:
            with patch.object(
                coord,
                "_compose_governance_gates",
                wraps=coord._compose_governance_gates,
            ) as mock_compose:
                await coord.decompose("topology query", governance_topology=topology)
        mock_compose.assert_called_once()
        call_kwargs = mock_compose.call_args.kwargs
        assert call_kwargs["governance_topology"] is topology

    @pytest.mark.asyncio
    async def test_async_context_manager_decompose(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """decompose() works correctly inside async context manager."""
        from unittest.mock import AsyncMock
        valid_json = '[{"description": "Async task", "required_capabilities": []}]'
        mock_llm_backend.generate = AsyncMock(return_value=valid_json)
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        async with coord:
            result = await coord.decompose("async context query")
        assert isinstance(result, TaskDecomposition)
        assert result.subtasks[0].description == "Async task"

    @pytest.mark.asyncio
    async def test_memory_written_by_compose_gates(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """decompose() writes governance gate results to memory via _compose_governance_gates."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="[]")
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        memory: dict[str, Any] = {}
        with coord:
            await coord.decompose("memory write test", memory=memory)
        # Gate keys should have been written (on cache miss path)
        assert "gate:gate_git_governance" in memory
        assert "gate:gate_ip_trade_secret" in memory
        assert "gate:gate_clearance_verification" in memory

    @pytest.mark.asyncio
    async def test_cache_writeback_on_successful_parse(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """decompose() writes parsed subtasks to memory for future SIG reads."""
        from unittest.mock import AsyncMock
        valid_json = '[{"description": "Cached task", "required_capabilities": []}]'
        mock_llm_backend.generate = AsyncMock(return_value=valid_json)
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        memory: dict[str, Any] = {}
        query = "cache writeback test"
        with coord:
            await coord.decompose(query, memory=memory)
        cache_key = f"decompose:{query[:100]}"
        assert cache_key in memory
        assert "subtasks" in memory[cache_key]
        assert len(memory[cache_key]["subtasks"]) == 1


# ── Phase 3: TestParseTaskSpecsComprehensive ─────────────────────────────────


class TestParseTaskSpecsComprehensive:
    """Comprehensive edge-case tests for ReasoningCoordinator._parse_task_specs()."""

    def test_clearance_internal_value(self, coordinator: ReasoningCoordinator) -> None:
        """INTERNAL clearance string is parsed to ClearanceLevel.INTERNAL."""
        raw = '[{"description": "task", "required_capabilities": [], "clearance_required": "INTERNAL"}]'
        with coordinator:
            result = coordinator._parse_task_specs(raw)
        assert result is not None
        assert len(result) == 1
        assert result[0].clearance_required == ClearanceLevel.INTERNAL

    def test_clearance_confidential_value(self, coordinator: ReasoningCoordinator) -> None:
        """CONFIDENTIAL clearance string is parsed to ClearanceLevel.CONFIDENTIAL."""
        raw = '[{"description": "task", "required_capabilities": [], "clearance_required": "CONFIDENTIAL"}]'
        with coordinator:
            result = coordinator._parse_task_specs(raw)
        assert result is not None
        assert result[0].clearance_required == ClearanceLevel.CONFIDENTIAL

    def test_clearance_restricted_value(self, coordinator: ReasoningCoordinator) -> None:
        """RESTRICTED clearance string is parsed to ClearanceLevel.RESTRICTED."""
        raw = '[{"description": "task", "required_capabilities": [], "clearance_required": "RESTRICTED"}]'
        with coordinator:
            result = coordinator._parse_task_specs(raw)
        assert result is not None
        assert result[0].clearance_required == ClearanceLevel.RESTRICTED

    def test_unknown_clearance_enum_rejected(self, coordinator: ReasoningCoordinator) -> None:
        """Unknown clearance string causes item to be rejected (invalid SubTask)."""
        raw = '[{"description": "task", "required_capabilities": [], "clearance_required": "ULTRA_SECRET"}]'
        with coordinator:
            result = coordinator._parse_task_specs(raw)
        assert result is None

    def test_missing_clearance_key_defaults_to_public(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """Missing clearance_required key defaults to ClearanceLevel.PUBLIC."""
        raw = '[{"description": "task without clearance", "required_capabilities": []}]'
        with coordinator:
            result = coordinator._parse_task_specs(raw)
        assert result is not None
        assert len(result) == 1
        assert result[0].clearance_required == ClearanceLevel.PUBLIC

    def test_multiple_json_arrays_invalid_span(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """Two separate JSON arrays: find('[') + rfind(']') spans both → invalid JSON → None."""
        raw = (
            '[{"description": "first", "required_capabilities": []}]'
            ' text '
            '[{"description": "second", "required_capabilities": []}]'
        )
        with coordinator:
            result = coordinator._parse_task_specs(raw)
        # The span from first [ to last ] is invalid JSON
        assert result is None

    def test_nested_array_of_arrays(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """[[{...}]] — inner items are lists not dicts, all skipped → None."""
        raw = '[[{"description": "nested task", "required_capabilities": []}]]'
        with coordinator:
            result = coordinator._parse_task_specs(raw)
        assert result is None

    def test_dict_wrapper_extracts_inner_array(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """{"tasks": [{...}]} — find('[') finds inner array, parsed correctly."""
        raw = '{"tasks": [{"description": "wrapped task", "required_capabilities": []}]}'
        with coordinator:
            result = coordinator._parse_task_specs(raw)
        assert result is not None
        assert len(result) == 1
        assert result[0].description == "wrapped task"

    def test_extra_unknown_fields_ignored(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """Extra unknown fields in JSON do not cause rejection of valid items."""
        raw = (
            '[{"description": "task with extras", "required_capabilities": [],'
            ' "unknown_field": "some_value", "another_extra": 42}]'
        )
        with coordinator:
            result = coordinator._parse_task_specs(raw)
        assert result is not None
        assert len(result) == 1
        assert result[0].description == "task with extras"

    def test_all_items_invalid_returns_none(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """All items fail SubTask validation → returns None."""
        raw = '[{"wrong_key": "no description"}, {"also_wrong": true}]'
        with coordinator:
            result = coordinator._parse_task_specs(raw)
        assert result is None

    def test_non_list_json_returns_none(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """Top-level dict (no inner array) → returns None."""
        raw = '{"description": "not an array"}'
        with coordinator:
            result = coordinator._parse_task_specs(raw)
        assert result is None

    def test_empty_string_returns_none(self, coordinator: ReasoningCoordinator) -> None:
        """Empty string → no brackets → returns None."""
        with coordinator:
            result = coordinator._parse_task_specs("")
        assert result is None

    def test_list_of_strings_returns_none(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """List of strings instead of dicts → all items skipped → None."""
        raw = '["task1", "task2", "task3"]'
        with coordinator:
            result = coordinator._parse_task_specs(raw)
        assert result is None

    def test_mixed_valid_and_clearance_levels(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """Multiple subtasks with different clearance levels all parsed correctly."""
        raw = (
            '['
            '{"description": "pub task", "required_capabilities": [], "clearance_required": "PUBLIC"},'
            '{"description": "int task", "required_capabilities": [], "clearance_required": "INTERNAL"},'
            '{"description": "conf task", "required_capabilities": [], "clearance_required": "CONFIDENTIAL"}'
            ']'
        )
        with coordinator:
            result = coordinator._parse_task_specs(raw)
        assert result is not None
        assert len(result) == 3
        assert result[0].clearance_required == ClearanceLevel.PUBLIC
        assert result[1].clearance_required == ClearanceLevel.INTERNAL
        assert result[2].clearance_required == ClearanceLevel.CONFIDENTIAL

    def test_unicode_in_description(self, coordinator: ReasoningCoordinator) -> None:
        """Unicode characters in description are preserved."""
        raw = '[{"description": "分析データ résumé 🔍", "required_capabilities": []}]'
        with coordinator:
            result = coordinator._parse_task_specs(raw)
        assert result is not None
        assert result[0].description == "分析データ résumé 🔍"

    def test_required_capabilities_preserved(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """required_capabilities list is preserved through parsing."""
        raw = '[{"description": "task", "required_capabilities": ["summarization", "code_review"]}]'
        with coordinator:
            result = coordinator._parse_task_specs(raw)
        assert result is not None
        assert result[0].required_capabilities == ["summarization", "code_review"]


# ── Phase 3: TestFallbackTasksComprehensive ──────────────────────────────────


class TestFallbackTasksComprehensive:
    """Comprehensive edge-case tests for ReasoningCoordinator._fallback_tasks()."""

    def test_empty_string_query(self, coordinator: ReasoningCoordinator) -> None:
        """Empty string query — SubTask requires min_length=1, so this should raise."""
        with coordinator:
            with pytest.raises(Exception):
                coordinator._fallback_tasks("")

    def test_whitespace_only_query(self, coordinator: ReasoningCoordinator) -> None:
        """Whitespace-only query is valid (length > 0) and preserved."""
        with coordinator:
            result = coordinator._fallback_tasks("   ")
        assert isinstance(result, TaskDecomposition)
        assert result.subtasks[0].description == "   "
        assert result.original_query == "   "

    def test_very_long_query_preserved(self, coordinator: ReasoningCoordinator) -> None:
        """Very long query (5000+ chars) is preserved in fallback."""
        long_query = "z" * 5001
        with coordinator:
            result = coordinator._fallback_tasks(long_query)
        assert result.original_query == long_query
        assert result.subtasks[0].description == long_query

    def test_unicode_query_preserved(self, coordinator: ReasoningCoordinator) -> None:
        """Unicode query is preserved in fallback."""
        unicode_query = "分析 🔍 café"
        with coordinator:
            result = coordinator._fallback_tasks(unicode_query)
        assert result.subtasks[0].description == unicode_query

    def test_capabilities_empty(self, coordinator: ReasoningCoordinator) -> None:
        """Fallback subtask has empty required_capabilities."""
        with coordinator:
            result = coordinator._fallback_tasks("any query")
        assert result.subtasks[0].required_capabilities == []

    def test_inactive_coordinator_raises(self, coordinator: ReasoningCoordinator) -> None:
        """_fallback_tasks does not require context manager (no _check_active)."""
        # _fallback_tasks does NOT call _check_active — verify it works outside CM
        result = coordinator._fallback_tasks("outside context")
        assert isinstance(result, TaskDecomposition)


# ── Phase 4: TestSynthesize ──────────────────────────────────────────────────


class TestSynthesize:
    """Phase 4: Tests for ReasoningCoordinator.synthesize()."""

    @pytest.mark.asyncio
    async def test_all_public_results_public_output(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """All PUBLIC results → PUBLIC output clearance."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="Merged answer")
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        results = [
            {"answer": "Answer A", "clearance": ClearanceLevel.PUBLIC, "taint": []},
            {"answer": "Answer B", "clearance": ClearanceLevel.PUBLIC, "taint": []},
        ]
        with coord:
            result = await coord.synthesize(results)
        assert isinstance(result, SynthesisResult)
        assert result.clearance == ClearanceLevel.PUBLIC

    @pytest.mark.asyncio
    async def test_mixed_public_internal_yields_internal(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Mixed PUBLIC + INTERNAL → INTERNAL output clearance."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="Merged answer")
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        results = [
            {"answer": "Answer A", "clearance": ClearanceLevel.PUBLIC, "taint": []},
            {"answer": "Answer B", "clearance": ClearanceLevel.INTERNAL, "taint": []},
        ]
        with coord:
            result = await coord.synthesize(results)
        assert result.clearance == ClearanceLevel.INTERNAL

    @pytest.mark.asyncio
    async def test_mixed_public_restricted_yields_restricted(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Mixed PUBLIC + RESTRICTED → RESTRICTED output clearance."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="Merged answer")
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        results = [
            {"answer": "Answer A", "clearance": ClearanceLevel.PUBLIC, "taint": []},
            {"answer": "Answer B", "clearance": ClearanceLevel.RESTRICTED, "taint": []},
        ]
        with coord:
            result = await coord.synthesize(results)
        assert result.clearance == ClearanceLevel.RESTRICTED

    @pytest.mark.asyncio
    async def test_single_specialist_passthrough(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Single specialist result passes through with correct clearance and taint."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="Merged answer")
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        results = [
            {"answer": "Solo answer", "clearance": ClearanceLevel.INTERNAL, "taint": ["source:internal"]},
        ]
        with coord:
            result = await coord.synthesize(results)
        assert result.clearance == ClearanceLevel.INTERNAL
        assert "source:internal" in result.taint

    @pytest.mark.asyncio
    async def test_missing_clearance_key_fails_closed_to_restricted(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Missing clearance key in result dict → fails closed to RESTRICTED."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="Merged answer")
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        results = [
            {"answer": "Answer without clearance", "taint": []},
        ]
        with coord:
            result = await coord.synthesize(results)
        assert result.clearance == ClearanceLevel.RESTRICTED

    @pytest.mark.asyncio
    async def test_duplicate_taints_deduplicated(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Duplicate taint strings are deduplicated in the output."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="Merged answer")
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        results = [
            {"answer": "A", "clearance": ClearanceLevel.PUBLIC, "taint": ["pii", "gdpr"]},
            {"answer": "B", "clearance": ClearanceLevel.PUBLIC, "taint": ["pii", "sox"]},
        ]
        with coord:
            result = await coord.synthesize(results)
        assert result.taint.count("pii") == 1
        assert "gdpr" in result.taint
        assert "sox" in result.taint

    @pytest.mark.asyncio
    async def test_taint_ordering_preserved(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Taint insertion order is preserved (first-seen ordering)."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="Merged answer")
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        results = [
            {"answer": "A", "clearance": ClearanceLevel.PUBLIC, "taint": ["alpha", "beta"]},
            {"answer": "B", "clearance": ClearanceLevel.PUBLIC, "taint": ["beta", "gamma"]},
        ]
        with coord:
            result = await coord.synthesize(results)
        assert result.taint.index("alpha") < result.taint.index("beta")
        assert result.taint.index("beta") < result.taint.index("gamma")

    @pytest.mark.asyncio
    async def test_missing_answer_key_no_crash(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Missing answer key in result dict → empty string fallback (no crash)."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="Merged answer")
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        results = [{"clearance": ClearanceLevel.PUBLIC, "taint": []}]
        with coord:
            result = await coord.synthesize(results)
        assert isinstance(result, SynthesisResult)

    @pytest.mark.asyncio
    async def test_llm_failure_manual_concatenation(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """LLM generate() raises → fallback to manual concatenation of answers."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        results = [
            {"answer": "Part one", "clearance": ClearanceLevel.PUBLIC, "taint": []},
            {"answer": "Part two", "clearance": ClearanceLevel.PUBLIC, "taint": []},
        ]
        with coord:
            result = await coord.synthesize(results)
        assert "Part one" in result.merged_answer
        assert "Part two" in result.merged_answer

    @pytest.mark.asyncio
    async def test_memory_written_with_synthesis_result(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """synthesize() writes result to memory under 'synthesis:result' key."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="Merged answer")
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        results = [{"answer": "A", "clearance": ClearanceLevel.PUBLIC, "taint": []}]
        memory: dict[str, Any] = {}
        with coord:
            await coord.synthesize(results, memory=memory)
        assert "synthesis:result" in memory

    @pytest.mark.asyncio
    async def test_no_memory_write_when_none(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """synthesize() with memory=None does not raise and returns valid result."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="Merged answer")
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        results = [{"answer": "A", "clearance": ClearanceLevel.PUBLIC, "taint": []}]
        with coord:
            result = await coord.synthesize(results, memory=None)
        assert isinstance(result, SynthesisResult)

    @pytest.mark.asyncio
    async def test_inactive_coordinator_raises(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """synthesize() outside context manager raises RuntimeError."""
        with pytest.raises(RuntimeError, match="context manager"):
            await coordinator.synthesize([])

    @pytest.mark.asyncio
    async def test_async_context_manager_works(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """synthesize() works correctly inside async context manager."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="Merged answer")
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        results = [{"answer": "Async answer", "clearance": ClearanceLevel.PUBLIC, "taint": []}]
        async with coord:
            result = await coord.synthesize(results)
        assert isinstance(result, SynthesisResult)
        assert result.clearance == ClearanceLevel.PUBLIC

    @pytest.mark.asyncio
    async def test_all_answers_empty_no_answer_available(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """All answers empty strings → merged_answer is 'No answer available.'"""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        results = [
            {"answer": "", "clearance": ClearanceLevel.PUBLIC, "taint": []},
            {"answer": "", "clearance": ClearanceLevel.PUBLIC, "taint": []},
        ]
        with coord:
            result = await coord.synthesize(results)
        assert result.merged_answer == "No answer available."

    @pytest.mark.asyncio
    async def test_clearance_escalation_chain(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED — max wins."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="Merged answer")
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        results = [
            {"answer": "A", "clearance": ClearanceLevel.PUBLIC, "taint": []},
            {"answer": "B", "clearance": ClearanceLevel.INTERNAL, "taint": []},
            {"answer": "C", "clearance": ClearanceLevel.CONFIDENTIAL, "taint": []},
            {"answer": "D", "clearance": ClearanceLevel.RESTRICTED, "taint": []},
        ]
        with coord:
            result = await coord.synthesize(results)
        assert result.clearance == ClearanceLevel.RESTRICTED

    @pytest.mark.asyncio
    async def test_memory_synthesis_result_structure(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Memory synthesis:result contains merged_answer, clearance, taint keys."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="Merged answer")
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        results = [{"answer": "A", "clearance": ClearanceLevel.INTERNAL, "taint": ["pii"]}]
        memory: dict[str, Any] = {}
        with coord:
            await coord.synthesize(results, memory=memory)
        entry = memory["synthesis:result"]
        assert "merged_answer" in entry
        assert "clearance" in entry
        assert "taint" in entry
        assert entry["clearance"] == ClearanceLevel.INTERNAL
        assert entry["taint"] == ["pii"]

    @pytest.mark.asyncio
    async def test_no_taint_returns_empty_list(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """No taints across all results → empty taint list."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="Merged answer")
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        results = [
            {"answer": "A", "clearance": ClearanceLevel.PUBLIC, "taint": []},
            {"answer": "B", "clearance": ClearanceLevel.PUBLIC, "taint": []},
        ]
        with coord:
            result = await coord.synthesize(results)
        assert result.taint == []


# ── Phase 5: TestDispatch ────────────────────────────────────────────────────


class TestDispatch:
    """Phase 5: Tests for ReasoningCoordinator.dispatch()."""

    @pytest.mark.asyncio
    async def test_routes_to_agent_in_roster(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Subtask is routed to agent in roster (clearance PUBLIC matches)."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="llm fallback")
        mock_agent_roster[0].generate = AsyncMock(return_value="agent answer")
        mock_agent_roster[0].clearance_level = ClearanceLevel.PUBLIC
        mock_agent_roster[0].capability_tags = ()
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        td = TaskDecomposition(
            original_query="Q", subtasks=[SubTask(description="Do X")],
        )
        with coord:
            results = await coord.dispatch(td)
        assert len(results) == 1
        assert results[0]["answer"] == "agent answer"
        mock_agent_roster[0].generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_to_llm_when_no_agent_qualifies(
        self, mock_llm_backend: MagicMock,
    ) -> None:
        """No agent qualifies (empty roster) → falls back to llm_backend."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="llm fallback answer")
        coord = ReasoningCoordinator(mock_llm_backend, [], _VALID_CONFIG)
        td = TaskDecomposition(
            original_query="Q", subtasks=[SubTask(description="Do X")],
        )
        with coord:
            results = await coord.dispatch(td)
        assert len(results) == 1
        assert results[0]["answer"] == "llm fallback answer"
        mock_llm_backend.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_clearance_gate_filters_agent(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Agent with PUBLIC clearance can't handle RESTRICTED subtask → falls back to LLM."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="llm restricted answer")
        mock_agent_roster[0].clearance_level = ClearanceLevel.PUBLIC
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        td = TaskDecomposition(
            original_query="Q",
            subtasks=[SubTask(description="restricted task", clearance_required=ClearanceLevel.RESTRICTED)],
        )
        with coord:
            results = await coord.dispatch(td)
        assert len(results) == 1
        # Should have gone to LLM, not the agent
        mock_llm_backend.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_agent_timeout_returns_error(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Agent times out → error result returned."""
        import asyncio as aio
        from unittest.mock import AsyncMock

        async def slow_generate(*args: Any, **kwargs: Any) -> str:
            await aio.sleep(100)
            return "never"

        mock_agent_roster[0].generate = slow_generate
        mock_agent_roster[0].clearance_level = ClearanceLevel.PUBLIC
        mock_agent_roster[0].capability_tags = ()
        small_config = CoordinatorConfig(
            COORDINATOR_DECOMPOSITION_PROMPT="dp",
            COORDINATOR_SYNTHESIS_PROMPT="sp",
            max_specialists=4,
            specialist_timeout_seconds=0.01,
        )
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, small_config)
        td = TaskDecomposition(
            original_query="Q", subtasks=[SubTask(description="Do X")],
        )
        with coord:
            results = await coord.dispatch(td)
        assert len(results) == 1
        assert "timeout" in results[0]["answer"].lower() or "Error" in results[0]["answer"]

    @pytest.mark.asyncio
    async def test_agent_error_returns_error_result(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Agent raises RuntimeError → error result returned."""
        from unittest.mock import AsyncMock
        mock_agent_roster[0].generate = AsyncMock(side_effect=RuntimeError("agent failure"))
        mock_agent_roster[0].clearance_level = ClearanceLevel.PUBLIC
        mock_agent_roster[0].capability_tags = ()
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        td = TaskDecomposition(
            original_query="Q", subtasks=[SubTask(description="Do X")],
        )
        with coord:
            results = await coord.dispatch(td)
        assert len(results) == 1
        assert "agent failure" in results[0]["answer"]

    @pytest.mark.asyncio
    async def test_multiple_subtasks_dispatched(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Multiple subtasks each produce a result."""
        from unittest.mock import AsyncMock
        mock_agent_roster[0].generate = AsyncMock(return_value="agent answer")
        mock_agent_roster[0].clearance_level = ClearanceLevel.PUBLIC
        mock_agent_roster[0].capability_tags = ()
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        td = TaskDecomposition(
            original_query="Q",
            subtasks=[SubTask(description="A"), SubTask(description="B"), SubTask(description="C")],
        )
        with coord:
            results = await coord.dispatch(td)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_result_clearance_matches_subtask(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Result clearance matches the subtask's clearance_required."""
        from unittest.mock import AsyncMock
        mock_agent_roster[0].generate = AsyncMock(return_value="answer")
        mock_agent_roster[0].clearance_level = ClearanceLevel.CONFIDENTIAL
        mock_agent_roster[0].capability_tags = ()
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        td = TaskDecomposition(
            original_query="Q",
            subtasks=[SubTask(description="task", clearance_required=ClearanceLevel.CONFIDENTIAL)],
        )
        with coord:
            results = await coord.dispatch(td)
        assert results[0]["clearance"] == ClearanceLevel.CONFIDENTIAL

    @pytest.mark.asyncio
    async def test_inactive_coordinator_raises(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """dispatch() outside context manager raises RuntimeError."""
        td = TaskDecomposition(
            original_query="Q", subtasks=[SubTask(description="Do X")],
        )
        with pytest.raises(RuntimeError, match="context manager"):
            await coordinator.dispatch(td)


# ── Phase 5: TestExecute ────────────────────────────────────────────────────


class TestExecute:
    """Phase 5: Tests for ReasoningCoordinator.execute() full pipeline."""

    @pytest.mark.asyncio
    async def test_execute_returns_synthesis_result(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """execute() returns SynthesisResult via full pipeline."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="synthesized answer")
        mock_agent_roster[0].clearance_level = ClearanceLevel.PUBLIC
        mock_agent_roster[0].capability_tags = ()
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        with coord:
            result = await coord.execute("test query")
        assert isinstance(result, SynthesisResult)
        assert len(result.merged_answer) > 0

    @pytest.mark.asyncio
    async def test_execute_passes_governance_topology(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """GovernanceTopology is passed through the full pipeline."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="answer")
        mock_agent_roster[0].clearance_level = ClearanceLevel.PUBLIC
        mock_agent_roster[0].capability_tags = ()
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        topology = GovernanceTopology(edges=[
            GovernanceEdge(source="auth", target="policy", relation="GOVERNS"),
        ])
        with coord:
            result = await coord.execute("topology test", governance_topology=topology)
        assert isinstance(result, SynthesisResult)

    @pytest.mark.asyncio
    async def test_execute_writes_to_memory(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """execute() writes gate results and synthesis to memory."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="answer")
        mock_agent_roster[0].clearance_level = ClearanceLevel.PUBLIC
        mock_agent_roster[0].capability_tags = ()
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        memory: dict[str, Any] = {}
        with coord:
            await coord.execute("memory test", memory=memory)
        assert "synthesis:result" in memory
        assert "gate:gate_git_governance" in memory

    @pytest.mark.asyncio
    async def test_execute_inactive_raises(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        """execute() outside context manager raises RuntimeError."""
        with pytest.raises(RuntimeError, match="context manager"):
            await coordinator.execute("should fail")

    @pytest.mark.asyncio
    async def test_execute_async_context_manager(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """execute() works inside async context manager."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="answer")
        mock_agent_roster[0].clearance_level = ClearanceLevel.PUBLIC
        mock_agent_roster[0].capability_tags = ()
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        async with coord:
            result = await coord.execute("async query")
        assert isinstance(result, SynthesisResult)


# ── Phase 6: End-to-end integration tests ────────────────────────────────────


class TestEndToEndIntegration:
    """Phase 6: End-to-end integration tests exercising the full coordinator pipeline."""

    @pytest.mark.asyncio
    async def test_full_pipeline_with_valid_decomposition(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Full pipeline: LLM decomposes → agents dispatch → LLM synthesizes."""
        from unittest.mock import AsyncMock

        # LLM returns valid decomposition, then synthesis
        decompose_json = '[{"description": "Fetch data", "required_capabilities": []}]'
        call_count = 0

        async def multi_response(*args: Any, **kwargs: Any) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return decompose_json
            return "Synthesized final answer"

        mock_llm_backend.generate = multi_response
        mock_agent_roster[0].generate = AsyncMock(return_value="Agent fetched data")
        mock_agent_roster[0].clearance_level = ClearanceLevel.PUBLIC
        mock_agent_roster[0].capability_tags = ()

        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        with coord:
            result = await coord.execute("analyse dependencies")
        assert isinstance(result, SynthesisResult)
        assert result.clearance == ClearanceLevel.PUBLIC
        assert len(result.merged_answer) > 0

    @pytest.mark.asyncio
    async def test_pipeline_with_memory_roundtrip(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Memory accumulates gate results + synthesis through full pipeline."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="answer")
        mock_agent_roster[0].clearance_level = ClearanceLevel.PUBLIC
        mock_agent_roster[0].capability_tags = ()
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        memory: dict[str, Any] = {}
        with coord:
            await coord.execute("memory roundtrip test", memory=memory)
        # Gates written by decompose's _compose_governance_gates
        assert "gate:gate_git_governance" in memory
        assert "gate:gate_ip_trade_secret" in memory
        assert "gate:gate_clearance_verification" in memory
        # Synthesis result written by synthesize
        assert "synthesis:result" in memory
        assert "merged_answer" in memory["synthesis:result"]

    @pytest.mark.asyncio
    async def test_pipeline_clearance_propagation_end_to_end(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Clearance propagation: INTERNAL subtask → INTERNAL synthesis result."""
        from unittest.mock import AsyncMock

        decompose_json = (
            '[{"description": "Internal analysis", "required_capabilities": [],'
            ' "clearance_required": "INTERNAL"}]'
        )
        call_count = 0

        async def multi_response(*args: Any, **kwargs: Any) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return decompose_json
            return "Synthesized"

        mock_llm_backend.generate = multi_response
        mock_agent_roster[0].generate = AsyncMock(return_value="Internal analysis done")
        mock_agent_roster[0].clearance_level = ClearanceLevel.INTERNAL
        mock_agent_roster[0].capability_tags = ()

        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        with coord:
            result = await coord.execute("internal query")
        assert result.clearance == ClearanceLevel.INTERNAL

    @pytest.mark.asyncio
    async def test_pipeline_with_governance_topology(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """GovernanceTopology flows through all 3 phases of the pipeline."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="answer")
        mock_agent_roster[0].clearance_level = ClearanceLevel.PUBLIC
        mock_agent_roster[0].capability_tags = ()
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        topology = GovernanceTopology(edges=[
            GovernanceEdge(source="auth/login", target="policy", relation="GOVERNS"),
            GovernanceEdge(source="billing/pay", target="audit", relation="COMPLIES_WITH"),
        ])
        memory: dict[str, Any] = {}
        with coord:
            result = await coord.execute("auth query", governance_topology=topology, memory=memory)
        assert isinstance(result, SynthesisResult)
        # Gates should reflect filtered topology (auth edges only = 1)
        gate = memory.get("gate:gate_git_governance", {})
        assert gate.get("topology_edges_count", -1) == 1

    @pytest.mark.asyncio
    async def test_pipeline_llm_failure_graceful_degradation(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """LLM failure at every stage → graceful degradation through fallbacks."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(side_effect=RuntimeError("LLM down"))
        mock_agent_roster[0].clearance_level = ClearanceLevel.PUBLIC
        mock_agent_roster[0].capability_tags = ()
        # Agent also fails
        mock_agent_roster[0].generate = AsyncMock(side_effect=RuntimeError("Agent down"))
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        with coord:
            result = await coord.execute("failure test")
        # Should still return a SynthesisResult via fallbacks
        assert isinstance(result, SynthesisResult)
        assert result.clearance == ClearanceLevel.PUBLIC

    @pytest.mark.asyncio
    async def test_pipeline_multi_subtask_mixed_clearance(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Multiple subtasks with mixed clearances → highest clearance wins in synthesis."""
        from unittest.mock import AsyncMock

        decompose_json = (
            '['
            '{"description": "Public task", "required_capabilities": [], "clearance_required": "PUBLIC"},'
            '{"description": "Confidential task", "required_capabilities": [], "clearance_required": "CONFIDENTIAL"}'
            ']'
        )
        call_count = 0

        async def multi_response(*args: Any, **kwargs: Any) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return decompose_json
            return "Merged"

        mock_llm_backend.generate = multi_response
        mock_agent_roster[0].generate = AsyncMock(return_value="result")
        mock_agent_roster[0].clearance_level = ClearanceLevel.CONFIDENTIAL
        mock_agent_roster[0].capability_tags = ()

        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)
        with coord:
            result = await coord.execute("mixed clearance query")
        assert result.clearance == ClearanceLevel.CONFIDENTIAL

    @pytest.mark.asyncio
    async def test_pipeline_ephemeral_lifecycle(
        self, mock_llm_backend: MagicMock, mock_agent_roster: list[MagicMock],
    ) -> None:
        """Two consecutive pipeline runs — second run starts clean (ephemeral)."""
        from unittest.mock import AsyncMock
        mock_llm_backend.generate = AsyncMock(return_value="answer")
        mock_agent_roster[0].clearance_level = ClearanceLevel.PUBLIC
        mock_agent_roster[0].capability_tags = ()
        coord = ReasoningCoordinator(mock_llm_backend, mock_agent_roster, _VALID_CONFIG)

        # First run
        with coord:
            coord.register_specialist(Specialist(name="s1", model_id="m1"))
            result1 = await coord.execute("run 1")
        assert isinstance(result1, SynthesisResult)

        # Second run — specialists cleared
        with coord:
            assert coord.list_specialists() == []
            result2 = await coord.execute("run 2")
        assert isinstance(result2, SynthesisResult)

    @pytest.mark.asyncio
    async def test_pipeline_capability_tag_matching(
        self, mock_llm_backend: MagicMock,
    ) -> None:
        """Agent with matching capability_tags is preferred over agent without."""
        from unittest.mock import AsyncMock

        agent1 = MagicMock(name="generic-agent")
        agent1.name = "generic"
        agent1.model_id = "model"
        agent1.generate = AsyncMock(return_value="generic answer")
        agent1.clearance_level = ClearanceLevel.PUBLIC
        agent1.capability_tags = ()

        agent2 = MagicMock(name="specialist-agent")
        agent2.name = "code-reviewer"
        agent2.model_id = "model"
        agent2.generate = AsyncMock(return_value="specialist answer")
        agent2.clearance_level = ClearanceLevel.PUBLIC
        agent2.capability_tags = ("code_review",)

        mock_llm_backend.generate = AsyncMock(return_value="synthesized")
        coord = ReasoningCoordinator(mock_llm_backend, [agent1, agent2], _VALID_CONFIG)
        td = TaskDecomposition(
            original_query="Q",
            subtasks=[SubTask(description="review", required_capabilities=["code_review"])],
        )
        with coord:
            results = await coord.dispatch(td)
        assert len(results) == 1
        assert results[0]["answer"] == "specialist answer"
        agent2.generate.assert_called_once()
        agent1.generate.assert_not_called()
