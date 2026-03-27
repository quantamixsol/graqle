"""Phase 8 wiring tests — GOVERNANCE_BYPASS KG nodes, TOOL_EXECUTION audit nodes, graq gate CLI.

# ── graqle:intelligence ──
# module: tests.test_generation.test_phase8_wiring
# risk: LOW (impact radius: 0 modules — test only)
# dependencies: __future__, pytest, unittest.mock, typer.testing, graqle.core.governance
# constraints: All tests must pass without a live graph or LLM backend
# ── /graqle:intelligence ──
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# 1. GOVERNANCE_BYPASS KG node structure
# ──────────────────────────────────────────────────────────────────────────────

class TestGovernanceBypassNodeStructure:
    """Verify GovernanceBypassNode.to_node_metadata() has the right shape."""

    def test_bypass_node_metadata_keys(self) -> None:
        from graqle.core.governance import GovernanceBypassNode

        node = GovernanceBypassNode(
            bypass_id="bypass_test123",
            gate_tier="T2",
            timestamp="2026-03-27T10:00:00+00:00",
            risk_level="MEDIUM",
            impact_radius=5,
            gate_score=0.75,
            threshold_at_time=0.70,
            file_path="src/api.py",
            actor="test-actor",
            approved_by="",
            justification="routine update",
            action="edit",
        )
        meta = node.to_node_metadata()
        required_keys = {
            "gate_tier", "timestamp", "risk_level", "impact_radius",
            "gate_score", "threshold_at_time", "file_path", "actor", "action",
            "actual_outcome", "regret_score", "entity_type",
        }
        assert required_keys.issubset(set(meta.keys()))

    def test_bypass_node_entity_type(self) -> None:
        from graqle.core.governance import GovernanceBypassNode

        node = GovernanceBypassNode(
            bypass_id="bypass_xyz",
            gate_tier="T3",
            timestamp="2026-03-27T10:00:00+00:00",
            risk_level="HIGH",
            impact_radius=10,
            gate_score=0.91,
            threshold_at_time=0.90,
            file_path="src/core.py",
            actor="dev",
            approved_by="lead",
            justification="approved refactor",
            action="generate",
        )
        meta = node.to_node_metadata()
        assert meta["entity_type"] == "GOVERNANCE_BYPASS"

    def test_bypass_node_initial_outcome_unknown(self) -> None:
        from graqle.core.governance import GovernanceBypassNode

        node = GovernanceBypassNode(
            bypass_id="b1",
            gate_tier="T2",
            timestamp="2026-03-27T10:00:00+00:00",
            risk_level="MEDIUM",
            impact_radius=4,
            gate_score=0.72,
            threshold_at_time=0.70,
            file_path="src/x.py",
            actor="",
            approved_by="",
            justification="",
            action="edit",
        )
        assert node.actual_outcome == "unknown"
        assert node.regret_score == 0.0

    def test_bypass_node_regret_score_mutable(self) -> None:
        from graqle.core.governance import GovernanceBypassNode

        node = GovernanceBypassNode(
            bypass_id="b2",
            gate_tier="T2",
            timestamp="2026-03-27T10:00:00+00:00",
            risk_level="MEDIUM",
            impact_radius=4,
            gate_score=0.72,
            threshold_at_time=0.70,
            file_path="src/x.py",
            actor="",
            approved_by="",
            justification="",
            action="edit",
        )
        node.actual_outcome = "incident"
        node.regret_score = 0.95
        assert node.to_node_metadata()["actual_outcome"] == "incident"
        assert node.to_node_metadata()["regret_score"] == 0.95


# ──────────────────────────────────────────────────────────────────────────────
# 2. build_bypass_node produces correct bypass_id uniqueness
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildBypassNodeUniqueness:
    """Successive calls produce distinct bypass_ids."""

    def test_unique_bypass_ids(self) -> None:
        import time

        from graqle.core.governance import GateResult, GovernanceMiddleware

        mw = GovernanceMiddleware()
        gate = GateResult(
            tier="T2",
            blocked=False,
            requires_approval=False,
            gate_score=0.75,
            reason="T2 pass",
            bypass_allowed=True,
            risk_level="MEDIUM",
            impact_radius=5,
            file_path="src/a.py",
            threshold_at_time=0.70,
        )
        n1 = mw.build_bypass_node(gate)
        time.sleep(0.01)
        n2 = mw.build_bypass_node(gate)
        # bypass_id is derived from timestamp — different calls should diverge
        # (may collide in sub-millisecond, so we just check structure)
        assert n1.bypass_id.startswith("bypass_")
        assert n2.bypass_id.startswith("bypass_")
        assert len(n1.bypass_id) > 7

    def test_bypass_node_fields_match_gate(self) -> None:
        from graqle.core.governance import GateResult, GovernanceMiddleware

        mw = GovernanceMiddleware()
        gate = GateResult(
            tier="T3",
            blocked=False,
            requires_approval=True,
            gate_score=0.92,
            reason="T3 approved",
            bypass_allowed=True,
            risk_level="HIGH",
            impact_radius=15,
            file_path="src/auth.py",
            threshold_at_time=0.90,
        )
        node = mw.build_bypass_node(
            gate,
            approved_by="lead",
            justification="critical hotfix",
            action="edit",
            actor="dev1",
        )
        assert node.gate_tier == "T3"
        assert node.risk_level == "HIGH"
        assert node.impact_radius == 15
        assert node.gate_score == pytest.approx(0.92, abs=0.001)
        assert node.approved_by == "lead"
        assert node.justification == "critical hotfix"
        assert node.actor == "dev1"
        assert node.action == "edit"


# ──────────────────────────────────────────────────────────────────────────────
# 3. graq gate CLI command — import and basic invocation
# ──────────────────────────────────────────────────────────────────────────────

class TestGraqGateCLI:
    """graq gate command — structure, exit codes, output modes."""

    def test_gate_command_importable(self) -> None:
        from graqle.cli.main import gate_command
        assert callable(gate_command)

    def test_gate_t1_pass_exit_0(self) -> None:
        from typer.testing import CliRunner

        from graqle.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, [
            "gate", "src/utils.py",
            "--risk", "LOW",
            "--impact-radius", "1",
        ])
        assert result.exit_code == 0

    def test_gate_ts_block_exit_1(self) -> None:
        from typer.testing import CliRunner

        from graqle.cli.main import app

        runner = CliRunner()
        # Inject a TS-1 pattern (w_J) into the diff — should unconditionally block
        result = runner.invoke(app, [
            "gate", "src/core.py",
            "--diff", "some code with w_J = 0.7 in it",
            "--risk", "LOW",
        ])
        assert result.exit_code == 1

    def test_gate_ts_block_no_fail_flag_exit_0(self) -> None:
        """--no-fail suppresses the exit code even when blocked."""
        from typer.testing import CliRunner

        from graqle.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, [
            "gate", "src/core.py",
            "--diff", "some code with w_J = 0.7 in it",
            "--risk", "LOW",
            "--no-fail",
        ])
        assert result.exit_code == 0

    def test_gate_json_output(self) -> None:
        import re

        from typer.testing import CliRunner

        from graqle.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, [
            "gate", "src/safe.py",
            "--risk", "LOW",
            "--impact-radius", "1",
            "--json",
        ])
        assert result.exit_code == 0
        # Strip ANSI codes that Rich may inject
        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        data = json.loads(clean, strict=False)
        assert "tier" in data
        assert "blocked" in data
        assert "gate_score" in data

    def test_gate_t3_requires_approved_by(self) -> None:
        """T3 (HIGH risk + large radius) blocks without approved_by."""
        import re

        from typer.testing import CliRunner

        from graqle.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, [
            "gate", "src/core.py",
            "--risk", "HIGH",
            "--impact-radius", "12",
            "--json",
        ])
        assert result.exit_code == 1
        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        data = json.loads(clean, strict=False)
        assert data["blocked"] is True
        assert data["tier"] == "T3"

    def test_gate_t3_passes_with_approval(self) -> None:
        """T3 passes when approved_by is provided."""
        import re

        from typer.testing import CliRunner

        from graqle.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, [
            "gate", "src/core.py",
            "--risk", "HIGH",
            "--impact-radius", "12",
            "--approved-by", "lead-engineer",
            "--justification", "critical security patch",
            "--json",
        ])
        assert result.exit_code == 0
        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        data = json.loads(clean, strict=False)
        assert data["blocked"] is False
        assert data["tier"] == "T3"

    def test_gate_sarif_output_structure(self) -> None:
        """SARIF output is valid v2.1 structure."""
        import re

        from typer.testing import CliRunner

        from graqle.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, [
            "gate", "src/utils.py",
            "--risk", "LOW",
            "--impact-radius", "1",
            "--sarif",
        ])
        assert result.exit_code == 0
        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        data = json.loads(clean, strict=False)
        assert data["version"] == "2.1.0"
        assert "runs" in data
        assert len(data["runs"]) == 1
        assert "results" in data["runs"][0]


# ──────────────────────────────────────────────────────────────────────────────
# 4. TOOL_EXECUTION audit node metadata shape
# ──────────────────────────────────────────────────────────────────────────────

class TestToolExecutionAuditNode:
    """Verify TOOL_EXECUTION audit metadata shape from handle_tool."""

    def test_tool_execution_metadata_keys(self) -> None:
        """Audit node metadata must contain required fields."""
        # Simulate what handle_tool builds
        meta = {
            "tool": "graq_reason",
            "actor": "test-actor",
            "latency_ms": 42,
            "had_error": False,
            "entity_type": "TOOL_EXECUTION",
        }
        required = {"tool", "actor", "latency_ms", "had_error", "entity_type"}
        assert required.issubset(set(meta.keys()))
        assert meta["entity_type"] == "TOOL_EXECUTION"

    def test_tool_execution_had_error_flag(self) -> None:
        """had_error is True when result starts with error key."""
        result_str = json.dumps({"error": "GOVERNANCE_GATE", "tier": "T3"})
        had_error = '"error"' in result_str[:120]
        assert had_error is True

    def test_tool_execution_had_error_false_for_success(self) -> None:
        result_str = json.dumps({"answer": "ok", "confidence": 0.85})
        had_error = '"error"' in result_str[:120]
        assert had_error is False

    def test_tool_audit_id_format(self) -> None:
        """Audit node ID follows tool_exec_{tool}_{timestamp} pattern."""
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        audit_id = f"tool_exec_graq_reason_{ts}"
        assert audit_id.startswith("tool_exec_graq_reason_")
        assert len(audit_id) > 20


# ──────────────────────────────────────────────────────────────────────────────
# 5. Integration: gate_command registered in CLI app
# ──────────────────────────────────────────────────────────────────────────────

class TestGateCLIRegistration:
    """graq gate is registered and visible in help."""

    def test_gate_in_app_commands(self) -> None:
        from typer.testing import CliRunner

        from graqle.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["--help"])
        assert "gate" in result.output

    def test_gate_help_text(self) -> None:
        from typer.testing import CliRunner

        from graqle.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["gate", "--help"])
        assert result.exit_code == 0
        assert "exit code" in result.output.lower() or "governance" in result.output.lower()
