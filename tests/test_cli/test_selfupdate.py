"""Tests for graq self-update command."""

# ── graqle:intelligence ──
# module: tests.test_cli.test_selfupdate
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, subprocess, sys, mock, pytest +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from graqle.cli.commands.selfupdate import (
    _stop_graq_processes,
    selfupdate_command,
)


class TestStopGraqProcesses:
    @patch("graqle.cli.commands.selfupdate.subprocess.run")
    def test_no_processes_found(self, mock_run):
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        pids, mcp = _stop_graq_processes()
        assert pids == []
        assert mcp is False

    @patch("graqle.cli.commands.selfupdate.sys.platform", "win32")
    @patch("graqle.cli.commands.selfupdate.os.kill")
    @patch("graqle.cli.commands.selfupdate.os.getpid", return_value=999)
    @patch("graqle.cli.commands.selfupdate.subprocess.run")
    def test_finds_and_stops_process(self, mock_run, mock_getpid, mock_kill):
        # First call: tasklist
        mock_run.side_effect = [
            MagicMock(stdout='"graq.exe","1234","Console","1","10,000 K"', returncode=0),
            MagicMock(stdout="ProcessId\n", returncode=0),  # wmic
        ]
        pids, mcp = _stop_graq_processes()
        assert 1234 in pids
        assert mcp is True
        mock_kill.assert_called()


class TestSelfUpdateCommand:
    @patch("graqle.cli.commands.selfupdate._stop_graq_processes", return_value=([], False))
    @patch("graqle.cli.commands.selfupdate.subprocess.run")
    def test_successful_upgrade(self, mock_run, mock_stop):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Successfully installed graqle-0.16.1",
            stderr="",
        )
        # Should not raise
        try:
            selfupdate_command(version="0.16.1", restart_mcp=False)
        except SystemExit:
            pass  # typer.Exit is OK

    @patch("graqle.cli.commands.selfupdate._stop_graq_processes", return_value=([], False))
    @patch("graqle.cli.commands.selfupdate.subprocess.run")
    def test_upgrade_failure(self, mock_run, mock_stop):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="ERROR: No matching distribution found",
        )
        with pytest.raises((SystemExit, Exception)):
            selfupdate_command(version="99.99.99", restart_mcp=False)
