"""Tests for graqle.intelligence.gate — Pre-compiled Intelligence Gate."""

# ── graqle:intelligence ──
# module: tests.test_intelligence.test_gate
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, json, pathlib, pytest, gate
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graqle.intelligence.gate import IntelligenceGate, _fuzzy_match_module


def _setup_intelligence(root: Path) -> None:
    """Create a minimal .graqle/intelligence/ structure."""
    intel_dir = root / ".graqle" / "intelligence" / "modules"
    intel_dir.mkdir(parents=True, exist_ok=True)

    # Module packets
    for mod_name in ("graqle.core.graph", "graqle.intelligence.pipeline", "graqle.cli.main"):
        safe = mod_name.replace(".", "__")
        (intel_dir / f"{safe}.json").write_text(json.dumps({
            "module": mod_name,
            "files": [mod_name.replace(".", "/") + ".py"],
            "risk_level": "HIGH" if "graph" in mod_name else "LOW",
            "risk_score": 0.7 if "graph" in mod_name else 0.2,
            "impact_radius": 14 if "graph" in mod_name else 1,
            "consumer_count": 14 if "graph" in mod_name else 1,
            "consumers": [{"module": f"consumer_{i}"} for i in range(14)] if "graph" in mod_name else [],
            "dependencies": [],
            "function_count": 42 if "graph" in mod_name else 5,
            "constraints": ["DO NOT break backward compat"] if "graph" in mod_name else [],
            "incidents": ["v0.25.0: regression in chunk coverage"] if "graph" in mod_name else [],
            "public_interfaces": [{"name": "Graph", "type": "Class", "line": 10}],
        }), encoding="utf-8")

    # Module index
    (root / ".graqle" / "intelligence" / "module_index.json").write_text(json.dumps({
        "total_modules": 3,
        "modules": [
            {"module": "graqle.core.graph", "risk_level": "HIGH"},
            {"module": "graqle.intelligence.pipeline", "risk_level": "LOW"},
            {"module": "graqle.cli.main", "risk_level": "LOW"},
        ],
    }), encoding="utf-8")

    # Impact matrix
    (root / ".graqle" / "intelligence" / "impact_matrix.json").write_text(json.dumps({
        "graqle.core.graph": {
            "consumers": ["consumer_0", "consumer_1", "consumer_2"],
            "consumer_count": 14,
            "risk_level": "HIGH",
            "impact_radius": 14,
        },
    }), encoding="utf-8")

    # Scorecard
    (root / ".graqle" / "scorecard.json").write_text(json.dumps({
        "chunk_coverage": 100.0,
        "description_coverage": 100.0,
        "edge_integrity": 100.0,
        "health": "HEALTHY",
    }), encoding="utf-8")


class TestIntelligenceGate:
    """Tests for IntelligenceGate."""

    def test_not_compiled(self, tmp_path: Path) -> None:
        gate = IntelligenceGate(tmp_path)
        assert gate.is_compiled is False
        result = gate.get_context("anything")
        assert "error" in result

    def test_get_context_exact_match(self, tmp_path: Path) -> None:
        _setup_intelligence(tmp_path)
        gate = IntelligenceGate(tmp_path)

        result = gate.get_context("graqle.core.graph")
        assert result["module"] == "graqle.core.graph"
        assert result["risk_level"] == "HIGH"
        assert result["function_count"] == 42

    def test_get_context_fuzzy_match(self, tmp_path: Path) -> None:
        _setup_intelligence(tmp_path)
        gate = IntelligenceGate(tmp_path)

        # Just "graph" should match
        result = gate.get_context("graph")
        assert result["module"] == "graqle.core.graph"

    def test_get_context_file_path(self, tmp_path: Path) -> None:
        _setup_intelligence(tmp_path)
        gate = IntelligenceGate(tmp_path)

        # File path with .py should work
        result = gate.get_context("graqle/core/graph.py")
        assert "error" not in result

    def test_get_context_not_found(self, tmp_path: Path) -> None:
        _setup_intelligence(tmp_path)
        gate = IntelligenceGate(tmp_path)

        result = gate.get_context("nonexistent_module")
        assert "error" in result
        assert "available_modules" in result

    def test_get_impact_high(self, tmp_path: Path) -> None:
        _setup_intelligence(tmp_path)
        gate = IntelligenceGate(tmp_path)

        result = gate.get_impact("graqle.core.graph")
        assert result["consumer_count"] == 14
        assert result["risk_level"] == "HIGH"
        assert result["safe_to_modify"] is False
        assert result["warning"] is not None

    def test_get_impact_low(self, tmp_path: Path) -> None:
        _setup_intelligence(tmp_path)
        gate = IntelligenceGate(tmp_path)

        result = gate.get_impact("graqle.intelligence.pipeline")
        assert result["safe_to_modify"] is True
        assert result["consumer_count"] == 0

    def test_get_scorecard(self, tmp_path: Path) -> None:
        _setup_intelligence(tmp_path)
        gate = IntelligenceGate(tmp_path)

        result = gate.get_scorecard()
        assert result["health"] == "HEALTHY"
        assert result["chunk_coverage"] == 100.0

    def test_list_modules(self, tmp_path: Path) -> None:
        _setup_intelligence(tmp_path)
        gate = IntelligenceGate(tmp_path)

        modules = gate._list_modules()
        assert len(modules) == 3
        assert "graqle.core.graph" in modules

    def test_response_under_100ms(self, tmp_path: Path) -> None:
        """Gate responses should be <100ms (reading pre-compiled JSON)."""
        import time
        _setup_intelligence(tmp_path)
        gate = IntelligenceGate(tmp_path)

        start = time.perf_counter()
        gate.get_context("graqle.core.graph")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 100, f"Gate response took {elapsed_ms:.1f}ms (>100ms)"


class TestFuzzyMatchModule:
    """Tests for _fuzzy_match_module."""

    def test_exact_match(self) -> None:
        names = ["graqle.core.graph", "graqle.cli.main"]
        assert _fuzzy_match_module("graqle.core.graph", names) == "graqle.core.graph"

    def test_last_component(self) -> None:
        names = ["graqle.core.graph", "graqle.cli.main"]
        assert _fuzzy_match_module("graph", names) == "graqle.core.graph"

    def test_file_path_normalization(self) -> None:
        names = ["graqle.core.graph"]
        assert _fuzzy_match_module("graqle/core/graph.py", names) == "graqle.core.graph"

    def test_no_match(self) -> None:
        names = ["graqle.core.graph"]
        assert _fuzzy_match_module("nonexistent", names) is None


class TestDogfoodGate:
    """Dogfooding: test gate on real SDK intelligence (if compiled)."""

    def test_gate_reads_real_intelligence(self) -> None:
        """If SDK has been compiled, gate should serve real packets."""
        gate = IntelligenceGate(Path("c:/Users/haris/Graqle/graqle-sdk"))
        if not gate.is_compiled:
            pytest.skip("SDK not compiled yet — run graq compile first")

        result = gate.get_context("pipeline")
        assert "error" not in result or "not found" in result.get("error", "")

        scorecard = gate.get_scorecard()
        # OT-070: is_compiled can return True (intelligence dir exists) while
        # scorecard.json is absent — they're produced by different commands.
        # Skip the scorecard assertion when the scorecard hasn't been generated
        # yet rather than failing dogfood on environment drift.
        if "error" in scorecard and "No scorecard found" in scorecard.get("error", ""):
            pytest.skip("Scorecard not generated — run graq compile first")
        assert "error" not in scorecard
        assert scorecard.get("health") in ("HEALTHY", "WARNING", "CRITICAL")
