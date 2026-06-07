# V-TRACKB-NATIVE-004: new test file via native Write (S-010).
"""Tests for `graq team share` (Track B B1.3) — publish local graph to the team."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from graqle.cli.commands.team import team_app

runner = CliRunner()


@pytest.fixture
def repo_with_graph(tmp_path: Path) -> Path:
    (tmp_path / "graqle.json").write_text('{"nodes":[{"id":"n1"}],"links":[]}', encoding="utf-8")
    return tmp_path


def _creds(email="dev@acme.com", api_key="grq_test"):
    c = MagicMock()
    c.email = email
    c.api_key = api_key
    return c


def _team(configured=True, team_id="team-acme", team_name="Acme"):
    cfg = MagicMock()
    cfg.is_configured = configured
    cfg.team_id = team_id
    cfg.team_name = team_name
    return cfg


def _patch(gate=True, creds=None, team=None, gateway_result=None):
    """Patch the share command's collaborators."""
    creds = creds if creds is not None else _creds()
    team = team if team is not None else _team()
    gw = MagicMock()
    gw.share_graph_to_team.return_value = gateway_result or {
        "status": "shared", "team_id": team.team_id
    }
    return (
        patch("graqle.cli.commands.team._check_team_gate", return_value=gate),
        patch("graqle.cloud.credentials.load_credentials", return_value=creds),
        patch("graqle.cloud.team.load_team_config", return_value=team),
        patch("graqle.cloud.gateway.CloudGateway", return_value=gw),
        gw,
    )


def test_share_success(repo_with_graph):
    p_gate, p_creds, p_team, p_gw, gw = _patch()
    with p_gate, p_creds, p_team, p_gw:
        res = runner.invoke(
            team_app, ["share", "--root", str(repo_with_graph), "--project", "Brand"]
        )
    assert res.exit_code == 0
    assert "shared with your team" in res.stdout.lower()
    # the gateway was called with the team id + project + a member hash (64 hex)
    kwargs = gw.share_graph_to_team.call_args.kwargs
    assert kwargs["team_id"] == "team-acme"
    assert kwargs["project"] == "Brand"
    assert len(kwargs["member_hash"]) == 64


def test_share_defaults_project_to_repo_folder(repo_with_graph):
    p_gate, p_creds, p_team, p_gw, gw = _patch()
    with p_gate, p_creds, p_team, p_gw:
        res = runner.invoke(team_app, ["share", "--root", str(repo_with_graph)])
    assert res.exit_code == 0
    assert gw.share_graph_to_team.call_args.kwargs["project"] == repo_with_graph.name


def test_share_blocked_by_plan_gate(repo_with_graph):
    p_gate, p_creds, p_team, p_gw, _ = _patch(gate=False)
    with p_gate, p_creds, p_team, p_gw:
        res = runner.invoke(team_app, ["share", "--root", str(repo_with_graph)])
    assert res.exit_code == 1


def test_share_no_team_configured(repo_with_graph):
    p_gate, p_creds, p_team, p_gw, _ = _patch(team=_team(configured=False))
    with p_gate, p_creds, p_team, p_gw:
        res = runner.invoke(team_app, ["share", "--root", str(repo_with_graph)])
    assert res.exit_code == 1
    assert "no team configured" in res.stdout.lower()


def test_share_not_logged_in(repo_with_graph):
    p_gate, p_creds, p_team, p_gw, _ = _patch(creds=_creds(email=""))
    with p_gate, p_creds, p_team, p_gw:
        res = runner.invoke(team_app, ["share", "--root", str(repo_with_graph)])
    assert res.exit_code == 1
    assert "not logged in" in res.stdout.lower()


def test_share_no_graph_file(tmp_path: Path):
    p_gate, p_creds, p_team, p_gw, _ = _patch()
    with p_gate, p_creds, p_team, p_gw:
        res = runner.invoke(team_app, ["share", "--root", str(tmp_path)])
    assert res.exit_code == 1
    assert "no graqle.json" in res.stdout.lower()


def test_share_forbidden(repo_with_graph):
    p_gate, p_creds, p_team, p_gw, _ = _patch(
        gateway_result={"status": "forbidden", "code": "FORBIDDEN", "error": "not permitted"}
    )
    with p_gate, p_creds, p_team, p_gw:
        res = runner.invoke(team_app, ["share", "--root", str(repo_with_graph)])
    assert res.exit_code == 1
    assert "not permitted to share" in res.stdout.lower()


def test_share_not_connected(repo_with_graph):
    p_gate, p_creds, p_team, p_gw, _ = _patch(
        gateway_result={"status": "error", "code": "NOT_CONNECTED"}
    )
    with p_gate, p_creds, p_team, p_gw:
        res = runner.invoke(team_app, ["share", "--root", str(repo_with_graph)])
    assert res.exit_code == 1
    assert "not connected" in res.stdout.lower()


def test_share_generic_failure(repo_with_graph):
    p_gate, p_creds, p_team, p_gw, _ = _patch(
        gateway_result={"status": "failed", "error": "s3 exploded"}
    )
    with p_gate, p_creds, p_team, p_gw:
        res = runner.invoke(team_app, ["share", "--root", str(repo_with_graph)])
    assert res.exit_code == 1
    assert "share failed" in res.stdout.lower()
