"""Tests for graqle.intelligence.verify — Quality Gate verification."""

# ── graqle:intelligence ──
# module: tests.test_intelligence.test_verify
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, json, pathlib, pytest, verify
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graqle.intelligence.verify import verify_changes


def _setup_intelligence(root: Path) -> None:
    """Create minimal intelligence for verification tests."""
    intel_dir = root / ".graqle" / "intelligence" / "modules"
    intel_dir.mkdir(parents=True, exist_ok=True)

    # High-risk module
    (intel_dir / "core__graph.json").write_text(json.dumps({
        "module": "core.graph",
        "files": ["core/graph.py"],
        "risk_level": "CRITICAL",
        "risk_score": 0.9,
        "impact_radius": 14,
        "consumers": [{"module": f"client_{i}"} for i in range(14)],
        "dependencies": [],
        "function_count": 42,
        "constraints": ["DO NOT break Graph.add_node signature"],
        "incidents": ["v0.22: broke graph serialization"],
    }), encoding="utf-8")

    # Low-risk module
    (intel_dir / "utils__helpers.json").write_text(json.dumps({
        "module": "utils.helpers",
        "files": ["utils/helpers.py"],
        "risk_level": "LOW",
        "risk_score": 0.1,
        "impact_radius": 0,
        "consumers": [],
        "dependencies": [],
        "function_count": 3,
        "constraints": [],
        "incidents": [],
    }), encoding="utf-8")

    # Module index
    (root / ".graqle" / "intelligence" / "module_index.json").write_text(json.dumps({
        "total_modules": 2,
    }), encoding="utf-8")

    # Scorecard
    (root / ".graqle" / "scorecard.json").write_text(json.dumps({
        "health": "HEALTHY",
    }), encoding="utf-8")


class TestVerifyChanges:
    """Tests for verify_changes."""

    def test_no_intelligence(self, tmp_path: Path) -> None:
        result = verify_changes(tmp_path, files=["some_file.py"])
        assert result["verdict"] == "SKIP"

    def test_no_changes(self, tmp_path: Path) -> None:
        _setup_intelligence(tmp_path)
        result = verify_changes(tmp_path, files=[])
        assert result["verdict"] == "PASS"

    def test_low_risk_change(self, tmp_path: Path) -> None:
        _setup_intelligence(tmp_path)
        result = verify_changes(tmp_path, files=["utils/helpers.py"])
        assert result["verdict"] == "PASS"
        assert result["max_risk"] == "LOW"

    def test_high_risk_change_warns(self, tmp_path: Path) -> None:
        _setup_intelligence(tmp_path)
        result = verify_changes(tmp_path, files=["core/graph.py"])
        assert result["verdict"] == "WARN"
        assert result["max_risk"] == "CRITICAL"
        assert result["total_consumers"] >= 14

    def test_strict_blocks_critical(self, tmp_path: Path) -> None:
        _setup_intelligence(tmp_path)
        result = verify_changes(tmp_path, files=["core/graph.py"], strict=True)
        assert result["verdict"] == "BLOCK"

    def test_strict_passes_low_risk(self, tmp_path: Path) -> None:
        _setup_intelligence(tmp_path)
        result = verify_changes(tmp_path, files=["utils/helpers.py"], strict=True)
        assert result["verdict"] == "PASS"

    def test_reports_constraints(self, tmp_path: Path) -> None:
        _setup_intelligence(tmp_path)
        result = verify_changes(tmp_path, files=["core/graph.py"])
        assert len(result["constraints"]) >= 1
        assert "Graph.add_node" in result["constraints"][0]["constraint"]

    def test_mixed_changes(self, tmp_path: Path) -> None:
        _setup_intelligence(tmp_path)
        result = verify_changes(tmp_path, files=["core/graph.py", "utils/helpers.py"])
        # Should report the highest risk
        assert result["max_risk"] == "CRITICAL"
        assert result["affected_modules"] == 2

    def test_unknown_file_graceful(self, tmp_path: Path) -> None:
        _setup_intelligence(tmp_path)
        result = verify_changes(tmp_path, files=["unknown/file.py"])
        # Should pass (no intelligence = no risk detected)
        assert result["verdict"] == "PASS"
