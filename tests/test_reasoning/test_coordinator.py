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
    return MagicMock(name="llm_backend")


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
    async def test_decompose_raises(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        with coordinator:
            with pytest.raises(NotImplementedError):
                await coordinator.decompose("query")

    @pytest.mark.asyncio
    async def test_dispatch_raises(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        td = TaskDecomposition(
            original_query="Q",
            subtasks=[SubTask(description="Do X")],
        )
        with coordinator:
            with pytest.raises(NotImplementedError):
                await coordinator.dispatch(td)

    @pytest.mark.asyncio
    async def test_synthesize_raises(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        with coordinator:
            with pytest.raises(NotImplementedError):
                await coordinator.synthesize([])

    @pytest.mark.asyncio
    async def test_execute_raises(
        self, coordinator: ReasoningCoordinator,
    ) -> None:
        with coordinator:
            with pytest.raises(NotImplementedError):
                await coordinator.execute("query")


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
