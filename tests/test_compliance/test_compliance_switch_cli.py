"""Tests for the new `graq compliance switch` CLI sub-typer (v0.57.0)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from graqle.cli.commands.compliance import compliance_app


runner = CliRunner()


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("GRAQLE_EU_AI_ACT_MODE", raising=False)
    monkeypatch.delenv("GRAQLE_AI_DISCLOSURE", raising=False)


class TestSwitchStatus:
    def test_default_text_format(self):
        result = runner.invoke(compliance_app, ["switch", "status"])
        assert result.exit_code == 0
        # Strip ANSI for substring checks
        import re
        plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "GRAQLE_EU_AI_ACT_MODE" in plain
        assert "OFF" in plain or "off" in plain

    def test_json_format(self):
        result = runner.invoke(
            compliance_app, ["switch", "status", "--format", "json"]
        )
        assert result.exit_code == 0
        # JSON output is on stdout — find the first { and parse from there
        idx = result.output.find("{")
        assert idx >= 0
        # Need to be careful — Rich console may also have written diagnostic
        # text. The bulk JSON should still be parseable from the first {.
        # Find matching closing brace via brace counting.
        text = result.output[idx:]
        # Trim anything after last }
        rlast = text.rfind("}")
        payload = json.loads(text[: rlast + 1])
        assert payload["schema_version"] == "1.0"
        assert "subsystems" in payload

    def test_invalid_format_exit_2(self):
        result = runner.invoke(
            compliance_app, ["switch", "status", "--format", "xml"]
        )
        assert result.exit_code == 2

    def test_status_reflects_master_switch_on(self, monkeypatch):
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")
        result = runner.invoke(
            compliance_app, ["switch", "status", "--format", "json"]
        )
        assert result.exit_code == 0
        idx = result.output.find("{")
        text = result.output[idx:]
        rlast = text.rfind("}")
        payload = json.loads(text[: rlast + 1])
        assert payload["master_switch"]["is_on"] is True


class TestSwitchOn:
    def test_posix_snippet_default(self):
        result = runner.invoke(compliance_app, ["switch", "on"])
        assert result.exit_code == 0
        assert "export GRAQLE_EU_AI_ACT_MODE=on" in result.output

    def test_powershell_snippet(self):
        result = runner.invoke(
            compliance_app, ["switch", "on", "--shell", "powershell"]
        )
        assert result.exit_code == 0
        assert '$env:GRAQLE_EU_AI_ACT_MODE = "on"' in result.output

    def test_cmd_snippet(self):
        result = runner.invoke(
            compliance_app, ["switch", "on", "--shell", "cmd"]
        )
        assert result.exit_code == 0
        assert "set GRAQLE_EU_AI_ACT_MODE=on" in result.output

    def test_unknown_shell_exit_2(self):
        result = runner.invoke(
            compliance_app, ["switch", "on", "--shell", "fish"]
        )
        assert result.exit_code == 2


class TestSwitchOff:
    def test_posix_unset(self):
        result = runner.invoke(compliance_app, ["switch", "off"])
        assert result.exit_code == 0
        assert "unset GRAQLE_EU_AI_ACT_MODE" in result.output

    def test_powershell_remove_item(self):
        result = runner.invoke(
            compliance_app, ["switch", "off", "--shell", "powershell"]
        )
        assert result.exit_code == 0
        assert "Remove-Item Env:GRAQLE_EU_AI_ACT_MODE" in result.output

    def test_cmd_empty_set(self):
        result = runner.invoke(
            compliance_app, ["switch", "off", "--shell", "cmd"]
        )
        assert result.exit_code == 0
        assert "set GRAQLE_EU_AI_ACT_MODE=" in result.output


class TestExistingStatusBackwardCompat:
    """The existing `graq compliance status` must stay schema v1 compatible."""

    def test_legacy_eu_ai_act_mode_field_still_present(self):
        result = runner.invoke(
            compliance_app, ["status", "--format", "json"]
        )
        assert result.exit_code == 0
        # Find the JSON
        idx = result.output.find("{")
        text = result.output[idx:]
        rlast = text.rfind("}")
        payload = json.loads(text[: rlast + 1])
        # Schema version stays at 1 (additive change only)
        assert payload["schema_version"] == "1"
        # Existing boolean still there
        assert "eu_ai_act_mode" in payload
        assert isinstance(payload["eu_ai_act_mode"], bool)
        # New field added (additive)
        assert "eu_ai_act_subsystems" in payload
        assert "schema_version" in payload["eu_ai_act_subsystems"]
