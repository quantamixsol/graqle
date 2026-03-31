"""Tests for graqle.core.profiler — NodeProfilingTrace + ProfileSummary.

# ── graqle:intelligence ──
# module: tests.test_generation.test_profiler
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, pytest, graqle.core.profiler
# constraints: none
# ── /graqle:intelligence ──
"""
from __future__ import annotations

import time

import pytest

from graqle.core.profiler import (
    NodeProfilingTrace,
    ProfileConfig,
    ProfileSummary,
    Profiler,
    StepRecord,
)


# ---------------------------------------------------------------------------
# ProfileConfig Tests
# ---------------------------------------------------------------------------

class TestProfileConfig:
    def test_defaults(self) -> None:
        cfg = ProfileConfig()
        assert cfg.enabled is True
        assert cfg.slow_step_threshold_ms == 2000.0
        assert cfg.expensive_step_threshold_tokens == 4000
        assert cfg.write_kg_nodes is True
        assert cfg.include_step_breakdown is True
        assert cfg.max_steps == 50

    def test_custom_config(self) -> None:
        cfg = ProfileConfig(slow_step_threshold_ms=500.0, max_steps=10)
        assert cfg.slow_step_threshold_ms == 500.0
        assert cfg.max_steps == 10


# ---------------------------------------------------------------------------
# StepRecord Tests
# ---------------------------------------------------------------------------

class TestStepRecord:
    def test_step_record_fields(self) -> None:
        rec = StepRecord(
            step_name="ANCHOR",
            latency_ms=150.5,
            tokens_used=1200,
            confidence=0.82,
            model="claude-sonnet-4-6",
        )
        assert rec.step_name == "ANCHOR"
        assert rec.latency_ms == 150.5
        assert rec.tokens_used == 1200
        assert rec.confidence == 0.82
        assert rec.model == "claude-sonnet-4-6"

    def test_step_record_timestamp_auto_set(self) -> None:
        rec = StepRecord("GENERATE", latency_ms=300.0)
        assert rec.timestamp  # non-empty

    def test_step_record_is_slow(self) -> None:
        rec = StepRecord("GENERATE", latency_ms=2500.0)
        assert rec.is_slow(2000.0) is True
        assert rec.is_slow(3000.0) is False

    def test_step_record_is_expensive(self) -> None:
        rec = StepRecord("GENERATE", latency_ms=100.0, tokens_used=5000)
        assert rec.is_expensive(4000) is True
        assert rec.is_expensive(6000) is False

    def test_step_record_to_dict(self) -> None:
        rec = StepRecord("VALIDATE", latency_ms=50.0, tokens_used=100, confidence=0.9)
        d = rec.to_dict()
        assert d["step_name"] == "VALIDATE"
        assert d["latency_ms"] == 50.0
        assert d["tokens_used"] == 100
        assert "timestamp" in d


# ---------------------------------------------------------------------------
# NodeProfilingTrace Tests
# ---------------------------------------------------------------------------

class TestNodeProfilingTrace:
    def test_trace_creation(self) -> None:
        trace = NodeProfilingTrace(
            trace_id="profile_abc123",
            session_label="test",
            start_time="2026-03-27T00:00:00Z",
        )
        assert trace.trace_id == "profile_abc123"
        assert trace.session_label == "test"
        assert trace.steps == []

    def test_record_step_appends(self) -> None:
        trace = NodeProfilingTrace("id1", "test", "2026-03-27T00:00:00Z")
        rec = trace.record_step("ANCHOR", latency_ms=100.0, confidence=0.7)
        assert len(trace.steps) == 1
        assert isinstance(rec, StepRecord)
        assert rec.step_name == "ANCHOR"

    def test_record_multiple_steps(self) -> None:
        trace = NodeProfilingTrace("id2", "test", "2026-03-27T00:00:00Z")
        trace.record_step("ANCHOR", 100.0)
        trace.record_step("GENERATE", 500.0)
        trace.record_step("VALIDATE", 80.0)
        assert len(trace.steps) == 3

    def test_to_dict_fields(self) -> None:
        trace = NodeProfilingTrace("id3", "profile:test", "2026-03-27T00:00:00Z", query="q")
        trace.record_step("REASON", 200.0, tokens_used=800, confidence=0.85)
        d = trace.to_dict()
        assert d["trace_id"] == "id3"
        assert d["query"] == "q"
        assert len(d["steps"]) == 1
        assert "total_latency_ms" in d

    def test_to_node_metadata(self) -> None:
        trace = NodeProfilingTrace("id4", "test", "2026-03-27T00:00:00Z")
        trace.record_step("REASON", 300.0)
        meta = trace.to_node_metadata()
        assert meta["entity_type"] == "CodeMetric"
        assert meta["metric_type"] == "performance_profile"
        assert "trace_id" in meta
        assert "step_count" in meta

    def test_query_truncated_in_metadata(self) -> None:
        long_query = "x" * 300
        trace = NodeProfilingTrace("id5", "test", "2026-03-27T00:00:00Z", query=long_query)
        meta = trace.to_node_metadata()
        assert len(meta["query"]) <= 200


# ---------------------------------------------------------------------------
# Profiler Tests
# ---------------------------------------------------------------------------

class TestProfiler:
    def setup_method(self) -> None:
        self.profiler = Profiler()

    def test_new_trace_has_unique_id(self) -> None:
        t1 = self.profiler.new_trace("session_a")
        time.sleep(0.001)
        t2 = self.profiler.new_trace("session_b")
        assert t1.trace_id != t2.trace_id

    def test_new_trace_starts_with_prefix(self) -> None:
        trace = self.profiler.new_trace("test")
        assert trace.trace_id.startswith("profile_")

    def test_finish_computes_totals(self) -> None:
        trace = self.profiler.new_trace("test")
        trace.record_step("ANCHOR", 100.0, tokens_used=500, confidence=0.6)
        trace.record_step("GENERATE", 400.0, tokens_used=1200, confidence=0.85)
        trace.record_step("VALIDATE", 50.0, tokens_used=200, confidence=0.9)
        summary = self.profiler.finish(trace)
        assert summary.total_latency_ms == pytest.approx(550.0, abs=0.01)
        assert summary.total_tokens == 1900
        assert summary.final_confidence == pytest.approx(0.9, abs=0.001)

    def test_finish_identifies_bottleneck(self) -> None:
        trace = self.profiler.new_trace("test")
        trace.record_step("ANCHOR", 100.0)
        trace.record_step("GENERATE", 2000.0)  # slowest
        trace.record_step("VALIDATE", 50.0)
        summary = self.profiler.finish(trace)
        assert summary.bottleneck_step == "GENERATE"
        assert summary.bottleneck_latency_ms == 2000.0

    def test_finish_flags_slow_steps(self) -> None:
        cfg = ProfileConfig(slow_step_threshold_ms=500.0)
        profiler = Profiler(cfg)
        trace = profiler.new_trace("test")
        trace.record_step("ANCHOR", 100.0)
        trace.record_step("GENERATE", 1500.0)  # exceeds 500ms threshold
        summary = profiler.finish(trace)
        assert "GENERATE" in trace.slow_steps

    def test_finish_flags_expensive_steps(self) -> None:
        cfg = ProfileConfig(expensive_step_threshold_tokens=1000)
        profiler = Profiler(cfg)
        trace = profiler.new_trace("test")
        trace.record_step("REASON", 200.0, tokens_used=2000)  # exceeds 1000 threshold
        summary = profiler.finish(trace)
        assert "REASON" in trace.expensive_steps

    def test_finish_no_steps_gives_empty_bottleneck(self) -> None:
        trace = self.profiler.new_trace("empty")
        summary = self.profiler.finish(trace)
        assert summary.bottleneck_step == ""
        assert summary.bottleneck_latency_ms == 0.0
        assert summary.total_latency_ms == 0.0

    def test_finish_sets_end_time(self) -> None:
        trace = self.profiler.new_trace("test")
        trace.record_step("REASON", 100.0)
        self.profiler.finish(trace)
        assert trace.end_time  # non-empty

    def test_finish_recommendations_no_issues(self) -> None:
        trace = self.profiler.new_trace("test")
        trace.record_step("REASON", 100.0, tokens_used=100, confidence=0.85)
        summary = self.profiler.finish(trace)
        assert len(summary.recommendations) >= 1
        assert "No performance issues" in summary.recommendations[0]

    def test_finish_recommends_enrich_on_low_confidence(self) -> None:
        trace = self.profiler.new_trace("test")
        trace.record_step("REASON", 100.0, tokens_used=100, confidence=0.40)
        summary = self.profiler.finish(trace)
        recs_text = " ".join(summary.recommendations)
        assert "graq_learn" in recs_text or "confidence" in recs_text

    def test_finish_recommends_on_high_latency(self) -> None:
        trace = self.profiler.new_trace("test")
        trace.record_step("REASON", 15_000.0, tokens_used=100, confidence=0.8)
        summary = self.profiler.finish(trace)
        recs_text = " ".join(summary.recommendations)
        assert "latency" in recs_text or "10s" in recs_text or "dry_run" in recs_text

    def test_profile_summary_to_dict(self) -> None:
        trace = self.profiler.new_trace("test")
        trace.record_step("REASON", 200.0, confidence=0.75)
        summary = self.profiler.finish(trace)
        d = summary.to_dict()
        assert "trace_id" in d
        assert "total_latency_ms" in d
        assert "final_confidence" in d
        assert "bottleneck_step" in d
        assert "recommendations" in d
        assert isinstance(d["recommendations"], list)

    def test_record_timed_step_helper(self) -> None:
        import time as _time
        trace = self.profiler.new_trace("timed")
        start = _time.perf_counter_ns()
        _time.sleep(0.001)  # sleep 1ms
        rec = self.profiler.record_timed_step(trace, "TIMED_STEP", start, tokens_used=50)
        assert rec.latency_ms >= 1.0  # at least 1ms elapsed
        assert rec.step_name == "TIMED_STEP"
        assert len(trace.steps) == 1


# ---------------------------------------------------------------------------
# Ontology Phase 7 Tests (PERFORMANCE_PROFILING skill + validate_profile_output gate)
# ---------------------------------------------------------------------------

class TestCodingOntologyPhase7:
    def test_performance_profiling_skill_exists(self) -> None:
        from graqle.ontology.domains.coding import CODING_SKILLS
        assert "PERFORMANCE_PROFILING" in CODING_SKILLS

    def test_skill_count_is_14(self) -> None:
        from graqle.ontology.domains.coding import CODING_SKILLS
        # Phase 7 adds PERFORMANCE_PROFILING: 13 → 14
        assert len(CODING_SKILLS) == 14

    def test_validate_profile_output_gate_exists(self) -> None:
        from graqle.ontology.domains.coding import CODING_OUTPUT_GATES
        assert "validate_profile_output" in CODING_OUTPUT_GATES
        gate = CODING_OUTPUT_GATES["validate_profile_output"]
        assert "trace_id" in gate["required"]
        assert "total_latency_ms" in gate["required"]

    def test_output_gate_count_is_12(self) -> None:
        from graqle.ontology.domains.coding import CODING_OUTPUT_GATES
        # Phase 7 adds validate_profile_output: 11 → 12
        assert len(CODING_OUTPUT_GATES) == 12

    def test_code_metric_has_performance_profiling_skill(self) -> None:
        from graqle.ontology.domains.coding import CODING_SKILL_MAP
        assert "CodeMetric" in CODING_SKILL_MAP
        assert "PERFORMANCE_PROFILING" in CODING_SKILL_MAP["CodeMetric"]


# ---------------------------------------------------------------------------
# graq_profile Tool Definition Tests
# ---------------------------------------------------------------------------

class TestGraqProfileToolDefinition:
    def test_graq_profile_in_tool_definitions(self) -> None:
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "graq_profile" in names
        assert "kogni_profile" in names

    def test_graq_profile_schema_requires_query(self) -> None:
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_profile")
        schema = tool["inputSchema"]
        assert "query" in schema["properties"]
        assert schema["required"] == ["query"]

    def test_graq_profile_schema_has_optional_params(self) -> None:
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_profile")
        props = tool["inputSchema"]["properties"]
        assert "max_rounds" in props
        assert "session_label" in props
        assert "write_kg_node" in props
        assert "include_step_breakdown" in props

    def test_tool_count_is_112(self) -> None:
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        # Phase 7 adds graq_profile + kogni_profile: 110 → 112
        assert len(TOOL_DEFINITIONS) == 116  # +2: graq_correct + kogni_correct (R6)


# ---------------------------------------------------------------------------
# graq_profile Routing Tests
# ---------------------------------------------------------------------------

class TestGraqProfileRouting:
    def test_graq_profile_maps_to_profile_task(self) -> None:
        from graqle.routing import MCP_TOOL_TO_TASK
        assert MCP_TOOL_TO_TASK.get("graq_profile") == "profile"
        assert MCP_TOOL_TO_TASK.get("kogni_profile") == "profile"

    def test_profile_task_in_recommendations(self) -> None:
        from graqle.routing import TASK_RECOMMENDATIONS
        assert "profile" in TASK_RECOMMENDATIONS
        rec = TASK_RECOMMENDATIONS["profile"]
        assert "description" in rec
        assert "suggested_providers" in rec

    def test_task_count_is_20(self) -> None:
        from graqle.routing import TASK_RECOMMENDATIONS
        # Phase 7 adds profile: 19 → 20
        assert len(TASK_RECOMMENDATIONS) == 20
