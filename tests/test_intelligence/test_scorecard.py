"""Tests for the Running Scorecard with curiosity-peak insights."""

# ── graqle:intelligence ──
# module: tests.test_intelligence.test_scorecard
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, scorecard, models
# constraints: none
# ── /graqle:intelligence ──

import pytest
from graqle.intelligence.scorecard import RunningScorecard
from graqle.intelligence.models import (
    CoverageReport,
    FileIntelligenceUnit,
    InsightCategory,
    ModulePacket,
    ModuleConsumer,
    ModuleDependency,
    ValidationStatus,
    ValidatedNode,
)


def _make_unit(
    module: str,
    function_count: int = 5,
    class_count: int = 1,
    consumer_count: int = 0,
    dependency_count: int = 0,
    risk_level: str = "LOW",
    risk_score: float = 0.2,
    impact_radius: int = 1,
    incidents: list[str] | None = None,
    nodes_count: int = 5,
    chunks_ok: int = 5,
) -> FileIntelligenceUnit:
    """Helper to create a FileIntelligenceUnit for testing."""
    node = ValidatedNode(
        id=f"{module}::main",
        label="main",
        entity_type="Function",
        description=f"Main function in {module} for testing scorecard.",
        chunks=[{"text": f"def main(): pass  # {module}", "type": "function"}],
    )
    pkt = ModulePacket(
        module=module,
        files=[f"{module.replace('.', '/')}.py"],
        function_count=function_count,
        class_count=class_count,
        node_count=nodes_count,
        consumers=[ModuleConsumer(module=f"consumer_{i}") for i in range(consumer_count)],
        dependencies=[ModuleDependency(module=f"dep_{i}") for i in range(dependency_count)],
        risk_level=risk_level,
        risk_score=risk_score,
        impact_radius=impact_radius,
        incidents=incidents or [],
    )
    cov = CoverageReport(
        total_nodes=nodes_count,
        nodes_with_chunks=chunks_ok,
        nodes_with_descriptions=nodes_count,
        total_edges=nodes_count * 2,
        valid_edges=nodes_count * 2,
    )
    return FileIntelligenceUnit(
        file_path=f"{module.replace('.', '/')}.py",
        nodes=[node],
        edges=[],
        module_packet=pkt,
        coverage=cov,
        validation_status=ValidationStatus.PASS,
    )


class TestRunningScorecard:
    def test_empty_scorecard(self):
        sc = RunningScorecard()
        assert sc.files_scanned == 0
        assert sc.coverage.health == "HEALTHY"
        assert sc.progress_pct == 0.0

    def test_ingest_single_file(self):
        sc = RunningScorecard()
        sc.total_files = 10
        unit = _make_unit("graqle.core.graph")
        insights = sc.ingest(unit)
        assert sc.files_scanned == 1
        assert sc.total_nodes == 5
        assert sc.progress_pct == 10.0

    def test_coverage_accumulates(self):
        sc = RunningScorecard()
        sc.total_files = 3
        sc.ingest(_make_unit("mod_a", nodes_count=10, chunks_ok=10))
        sc.ingest(_make_unit("mod_b", nodes_count=10, chunks_ok=8))
        sc.ingest(_make_unit("mod_c", nodes_count=10, chunks_ok=10))

        assert sc.total_nodes == 30
        assert sc.nodes_with_chunks == 28
        assert sc.coverage.chunk_coverage == pytest.approx(93.3, abs=0.1)

    def test_to_dict(self):
        sc = RunningScorecard()
        sc.total_files = 5
        sc.ingest(_make_unit("test_mod"))
        d = sc.to_dict()
        assert d["files_scanned"] == 1
        assert d["total_files"] == 5
        assert "health" in d
        assert "chunk_coverage" in d


class TestCuriosityInsights:
    def test_superlative_most_imported(self):
        sc = RunningScorecard()
        sc.total_files = 10
        # First file: small, no consumers
        sc.ingest(_make_unit("small_mod", consumer_count=1))
        # Second file: heavily imported
        insights = sc.ingest(_make_unit("hub_mod", consumer_count=15))

        superlatives = [i for i in insights if i.category == InsightCategory.SUPERLATIVE]
        assert any("MOST IMPORTED" in i.message for i in superlatives)

    def test_superlative_largest_module(self):
        sc = RunningScorecard()
        sc.total_files = 10
        sc.ingest(_make_unit("small", function_count=5))
        insights = sc.ingest(_make_unit("giant", function_count=66))

        superlatives = [i for i in insights if i.category == InsightCategory.SUPERLATIVE]
        assert any("LARGEST" in i.message for i in superlatives)

    def test_warning_high_risk(self):
        sc = RunningScorecard()
        sc.total_files = 10
        insights = sc.ingest(_make_unit(
            "risky", risk_level="HIGH", risk_score=0.85, impact_radius=12
        ))

        warnings = [i for i in insights if i.category == InsightCategory.WARNING]
        assert any("HIGH RISK" in i.message for i in warnings)

    def test_warning_incident_history(self):
        sc = RunningScorecard()
        sc.total_files = 10
        insights = sc.ingest(_make_unit(
            "buggy", incidents=["v0.25.0: chunk coverage regression (27.3%)"]
        ))

        history = [i for i in insights if i.category == InsightCategory.HISTORY]
        assert any("INCIDENT HISTORY" in i.message for i in history)

    def test_suggestion_large_file(self):
        sc = RunningScorecard()
        sc.total_files = 10
        insights = sc.ingest(_make_unit("bloated", function_count=45))

        suggestions = [i for i in insights if i.category == InsightCategory.SUGGESTION]
        assert any("Consider splitting" in i.message for i in suggestions)

    def test_connection_hub_module(self):
        sc = RunningScorecard()
        sc.total_files = 10
        insights = sc.ingest(_make_unit(
            "central", consumer_count=5, dependency_count=4
        ))

        connections = [i for i in insights if i.category == InsightCategory.CONNECTION]
        assert any("HUB MODULE" in i.message for i in connections)

    def test_no_insights_for_boring_module(self):
        sc = RunningScorecard()
        sc.total_files = 10
        # First module needed to establish baselines
        sc.ingest(_make_unit("baseline", function_count=5, consumer_count=1))
        # Second module is small and boring
        insights = sc.ingest(_make_unit(
            "boring", function_count=3, consumer_count=0,
            dependency_count=1, risk_level="LOW",
        ))
        assert len(insights) == 0

    def test_insights_accumulate(self):
        sc = RunningScorecard()
        sc.total_files = 10
        sc.ingest(_make_unit("small", function_count=5))
        sc.ingest(_make_unit("large", function_count=50, consumer_count=10))
        sc.ingest(_make_unit("risky", risk_level="CRITICAL", impact_radius=20))

        assert len(sc.insights) >= 3  # multiple insights across files
