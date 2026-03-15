"""Tests for graqle.intelligence.emitter — Intelligence Emitter."""

# ── graqle:intelligence ──
# module: tests.test_intelligence.test_emitter
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, json, pathlib, pytest, emitter +2 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graqle.intelligence.emitter import IntelligenceEmitter, _packet_to_dict
from graqle.intelligence.models import (
    CoverageReport,
    FileIntelligenceUnit,
    ModulePacket,
    ModuleConsumer,
    ValidatedEdge,
    ValidatedNode,
    ValidationGateResult,
    ValidationStatus,
)
from graqle.intelligence.scorecard import RunningScorecard


def _make_packet(module: str = "test_mod", risk_score: float = 0.5) -> ModulePacket:
    return ModulePacket(
        module=module,
        files=["test_mod.py"],
        node_count=3,
        function_count=2,
        class_count=1,
        line_count=50,
        public_interfaces=[],
        consumers=[],
        dependencies=[],
        risk_score=risk_score,
        risk_level="MEDIUM",
        impact_radius=2,
        chunk_coverage=95.0,
        description_coverage=90.0,
        constraints=[],
        incidents=[],
    )


def _make_unit(module: str = "test_mod", risk_score: float = 0.5) -> FileIntelligenceUnit:
    pkt = _make_packet(module, risk_score)
    return FileIntelligenceUnit(
        file_path="test_mod.py",
        module_packet=pkt,
        nodes=[
            ValidatedNode(
                id="n1",
                label="func_a",
                entity_type="function",
                description="A test function that does something useful and more",
                chunks=[{"content": "def func_a(): pass", "type": "source"}],
            )
        ],
        edges=[
            ValidatedEdge(source="n1", target="n2", relationship="CALLS")
        ],
        gate_results=[
            ValidationGateResult(gate="parse_integrity", gate_number=1, passed=True),
        ],
        coverage=CoverageReport(
            total_nodes=3,
            nodes_with_chunks=3,
            nodes_with_descriptions=3,
            total_edges=2,
            valid_edges=2,
        ),
        validation_status=ValidationStatus.PASS,
    )


class TestIntelligenceEmitter:
    """Tests for IntelligenceEmitter."""

    def test_emit_unit_creates_module_json(self, tmp_path: Path) -> None:
        emitter = IntelligenceEmitter(tmp_path)
        unit = _make_unit()
        emitter.emit_unit(unit)

        packet_file = tmp_path / ".graqle" / "intelligence" / "modules" / "test_mod.json"
        assert packet_file.exists()
        data = json.loads(packet_file.read_text(encoding="utf-8"))
        assert data["module"] == "test_mod"
        assert data["risk_level"] == "MEDIUM"

    def test_emit_unit_sanitizes_module_name(self, tmp_path: Path) -> None:
        emitter = IntelligenceEmitter(tmp_path)
        unit = _make_unit(module="graqle.core.graph")
        emitter.emit_unit(unit)

        packet_file = tmp_path / ".graqle" / "intelligence" / "modules" / "graqle__core__graph.json"
        assert packet_file.exists()

    def test_emit_index_creates_all_files(self, tmp_path: Path) -> None:
        emitter = IntelligenceEmitter(tmp_path)
        unit = _make_unit()
        emitter.emit_unit(unit)

        scorecard = RunningScorecard()
        scorecard.ingest(unit)
        emitter.emit_index(scorecard)

        intel_dir = tmp_path / ".graqle" / "intelligence"
        assert (intel_dir / "module_index.json").exists()
        assert (intel_dir / "impact_matrix.json").exists()
        assert (tmp_path / ".graqle" / "scorecard.json").exists()

    def test_module_index_content(self, tmp_path: Path) -> None:
        emitter = IntelligenceEmitter(tmp_path)
        for name in ("mod_a", "mod_b"):
            emitter.emit_unit(_make_unit(module=name))

        scorecard = RunningScorecard()
        emitter.emit_index(scorecard)

        index = json.loads(
            (tmp_path / ".graqle" / "intelligence" / "module_index.json").read_text(encoding="utf-8")
        )
        assert index["total_modules"] == 2
        assert len(index["modules"]) == 2

    def test_impact_matrix_tracks_consumers(self, tmp_path: Path) -> None:
        emitter = IntelligenceEmitter(tmp_path)
        pkt = _make_packet("hub_mod")
        pkt.consumers = [
            ModuleConsumer(module="client_a", via="import"),
            ModuleConsumer(module="client_b", via="import"),
        ]
        unit = _make_unit(module="hub_mod")
        unit.module_packet = pkt
        emitter.emit_unit(unit)

        scorecard = RunningScorecard()
        emitter.emit_index(scorecard)

        impact = json.loads(
            (tmp_path / ".graqle" / "intelligence" / "impact_matrix.json").read_text(encoding="utf-8")
        )
        assert "hub_mod" in impact
        assert impact["hub_mod"]["consumer_count"] == 2

    def test_emit_multiple_units(self, tmp_path: Path) -> None:
        emitter = IntelligenceEmitter(tmp_path)
        for i in range(5):
            emitter.emit_unit(_make_unit(module=f"mod_{i}"))

        modules_dir = tmp_path / ".graqle" / "intelligence" / "modules"
        json_files = list(modules_dir.glob("*.json"))
        assert len(json_files) == 5


class TestPacketToDict:
    """Tests for _packet_to_dict serialization."""

    def test_basic_serialization(self) -> None:
        pkt = _make_packet()
        d = _packet_to_dict(pkt)
        assert d["module"] == "test_mod"
        assert d["function_count"] == 2
        assert d["risk_level"] == "MEDIUM"
        assert isinstance(d["public_interfaces"], list)
        assert isinstance(d["consumers"], list)
        assert isinstance(d["dependencies"], list)

    def test_json_serializable(self) -> None:
        pkt = _make_packet()
        d = _packet_to_dict(pkt)
        json.dumps(d, default=str)


class TestDogfoodEmitter:
    """Dogfooding: test emitter on real SDK structure."""

    def test_emitter_creates_clean_directory_structure(self, tmp_path: Path) -> None:
        emitter = IntelligenceEmitter(tmp_path)
        for name in ("pipeline", "validators", "scorecard", "models"):
            emitter.emit_unit(_make_unit(module=f"graqle.intelligence.{name}"))

        scorecard = RunningScorecard()
        emitter.emit_index(scorecard)

        intel_dir = tmp_path / ".graqle" / "intelligence"
        assert intel_dir.is_dir()
        assert (intel_dir / "modules").is_dir()
        assert len(list((intel_dir / "modules").glob("*.json"))) == 4
        assert (intel_dir / "module_index.json").exists()
        assert (intel_dir / "impact_matrix.json").exists()
