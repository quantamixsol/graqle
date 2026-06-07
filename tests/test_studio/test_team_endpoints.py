# V-TRACKB-NATIVE-005: new test file via native Write (S-010).
"""Tests for the Track B (B2.3) studio team endpoints.

GET /api/team/membership  — what team am I in (verified identity)?
POST /api/team/share      — publish my project graph as the shared team graph.

Identity is the A1b verified email; we patch verified_email_from_request to
simulate "a valid token resolved to this email" vs "unauthenticated".
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from graqle.studio.routes.api import router


def _make_app():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.studio_state = {"graph": None}
    return app


def _membership(team_id="team-acme", role="member", can_teach=True):
    m = MagicMock()
    m.team_id = team_id
    m.role = role
    m.can_teach = can_teach
    return m


# ----------------------------------------------------------- /team/membership

class TestMembership:
    def test_unauthenticated_is_401(self):
        client = TestClient(_make_app())
        with patch("graqle.studio.auth.verified_email_from_request", return_value=None):
            r = client.get("/api/team/membership")
        assert r.status_code == 401
        assert r.json()["team"] is None

    def test_member_returns_team(self):
        client = TestClient(_make_app())
        reg = MagicMock()
        reg.resolve_team_for_member.return_value = _membership()
        with patch("graqle.studio.auth.verified_email_from_request", return_value="dev@acme.com"), \
             patch("graqle.cloud.team_registry.TeamRegistry", return_value=reg):
            r = client.get("/api/team/membership")
        assert r.status_code == 200
        assert r.json()["team"]["team_id"] == "team-acme"
        assert r.json()["team"]["can_teach"] is True

    def test_non_member_returns_null_team(self):
        client = TestClient(_make_app())
        reg = MagicMock()
        reg.resolve_team_for_member.return_value = None
        with patch("graqle.studio.auth.verified_email_from_request", return_value="dev@acme.com"), \
             patch("graqle.cloud.team_registry.TeamRegistry", return_value=reg):
            r = client.get("/api/team/membership")
        assert r.status_code == 200
        assert r.json()["team"] is None

    def test_registry_error_fails_closed_to_no_team(self):
        client = TestClient(_make_app())
        reg = MagicMock()
        reg.resolve_team_for_member.side_effect = RuntimeError("ddb down")
        with patch("graqle.studio.auth.verified_email_from_request", return_value="dev@acme.com"), \
             patch("graqle.cloud.team_registry.TeamRegistry", return_value=reg):
            r = client.get("/api/team/membership")
        assert r.status_code == 200
        assert r.json()["team"] is None


# ----------------------------------------------------------------- /team/share

class TestShareEndpoint:
    def test_unauthenticated_is_401(self):
        client = TestClient(_make_app())
        with patch("graqle.studio.auth.verified_email_from_request", return_value=None):
            r = client.post("/api/team/share", json={"project": "proj"})
        assert r.status_code == 401

    def test_invalid_project_is_400(self):
        client = TestClient(_make_app())
        with patch("graqle.studio.auth.verified_email_from_request", return_value="dev@acme.com"):
            r = client.post("/api/team/share", json={"project": "../../etc"})
        assert r.status_code == 400

    def test_non_member_is_403(self):
        client = TestClient(_make_app())
        reg = MagicMock()
        reg.resolve_team_for_member.return_value = None
        with patch("graqle.studio.auth.verified_email_from_request", return_value="dev@acme.com"), \
             patch("graqle.cloud.team_registry.TeamRegistry", return_value=reg):
            r = client.post("/api/team/share", json={"project": "proj"})
        assert r.status_code == 403

    def test_member_shares_successfully(self):
        client = TestClient(_make_app())
        reg = MagicMock()
        reg.resolve_team_for_member.return_value = _membership()
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {"Body": MagicMock(read=lambda: b'{"nodes":[]}')}
        gw = MagicMock()
        gw.share_graph_to_team.return_value = {"status": "shared"}
        with patch("graqle.studio.auth.verified_email_from_request", return_value="dev@acme.com"), \
             patch("graqle.cloud.team_registry.TeamRegistry", return_value=reg), \
             patch("boto3.client", return_value=mock_s3), \
             patch("graqle.cloud.gateway.CloudGateway", return_value=gw):
            r = client.post("/api/team/share", json={"project": "proj"})
        assert r.status_code == 200
        assert r.json()["status"] == "shared"
        assert r.json()["team_id"] == "team-acme"
        # the verified member hash was passed to the gateway (64-hex)
        kw = gw.share_graph_to_team.call_args.kwargs
        assert len(kw["member_hash"]) == 64 and kw["team_id"] == "team-acme"

    def test_no_graph_to_share_is_404(self):
        client = TestClient(_make_app())
        reg = MagicMock()
        reg.resolve_team_for_member.return_value = _membership()
        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = Exception("NoSuchKey")
        with patch("graqle.studio.auth.verified_email_from_request", return_value="dev@acme.com"), \
             patch("graqle.cloud.team_registry.TeamRegistry", return_value=reg), \
             patch("boto3.client", return_value=mock_s3):
            r = client.post("/api/team/share", json={"project": "proj"})
        assert r.status_code == 404

    def test_gateway_forbidden_is_403(self):
        client = TestClient(_make_app())
        reg = MagicMock()
        reg.resolve_team_for_member.return_value = _membership(can_teach=False, role="viewer")
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {"Body": MagicMock(read=lambda: b'{"nodes":[]}')}
        gw = MagicMock()
        gw.share_graph_to_team.return_value = {"status": "forbidden", "code": "FORBIDDEN"}
        with patch("graqle.studio.auth.verified_email_from_request",
                   return_value="watch@acme.com"), \
             patch("graqle.cloud.team_registry.TeamRegistry", return_value=reg), \
             patch("boto3.client", return_value=mock_s3), \
             patch("graqle.cloud.gateway.CloudGateway", return_value=gw):
            r = client.post("/api/team/share", json={"project": "proj"})
        assert r.status_code == 403
