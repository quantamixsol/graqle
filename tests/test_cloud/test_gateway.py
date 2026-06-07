"""Tests for graqle.cloud.gateway — cloud gateway client and upsell triggers."""

# ── graqle:intelligence ──
# module: tests.test_cloud.test_gateway
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, pytest, gateway
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from graqle.cloud.gateway import (
    CLOUD_VALUE_PROPS,
    CloudGateway,
    check_upsell_triggers,
)


class TestCloudGateway:
    def test_not_connected(self):
        gw = CloudGateway()
        assert not gw.is_connected

    def test_connected_with_key(self):
        gw = CloudGateway(api_key="grq_test123")
        assert gw.is_connected

    def test_status_not_connected(self):
        gw = CloudGateway()
        status = gw.get_status()
        assert not status.available
        assert "graq login" in status.message

    def test_status_connected(self):
        gw = CloudGateway(api_key="grq_test123")
        status = gw.get_status()
        assert status.available
        assert "foundation" in status.message

    def test_push_delta_not_connected(self):
        gw = CloudGateway()
        result = gw.push_delta({}, "team-test")
        assert result.get("code") == "NOT_CONNECTED"

    def test_push_delta_foundation(self):
        gw = CloudGateway(api_key="grq_test123")
        delta = {"nodes_added": [{"id": "n1"}], "nodes_modified": []}
        result = gw.push_delta(delta, "team-test")
        assert result.get("phase") == "foundation"
        assert result.get("status") == "queued"

    def test_pull_delta_foundation(self):
        gw = CloudGateway(api_key="grq_test123")
        result = gw.pull_delta("team-test", 5)
        assert result.get("phase") == "foundation"
        assert "delta" in result

    def test_register_team_foundation(self):
        gw = CloudGateway(api_key="grq_test123")
        result = gw.register_team("My Team", "owner@test.com")
        assert result.get("phase") == "foundation"
        assert "team-my-team" in result.get("team_id", "")

    def test_observability_foundation(self):
        gw = CloudGateway(api_key="grq_test123")
        result = gw.get_observability("team-test")
        assert result.get("local_metrics")
        assert not result.get("cloud_metrics")


class TestUpsellTriggers:
    def test_no_triggers_team_plan(self):
        triggers = check_upsell_triggers("team", node_count=10000)
        assert len(triggers) == 0

    def test_graph_size_trigger_free(self):
        triggers = check_upsell_triggers("free", node_count=450)
        assert any(t.trigger_type == "graph_size" for t in triggers)

    def test_no_trigger_small_graph(self):
        triggers = check_upsell_triggers("free", node_count=100)
        assert not any(t.trigger_type == "graph_size" for t in triggers)

    def test_multi_developer_trigger(self):
        triggers = check_upsell_triggers("free", developer_count=3)
        assert any(t.trigger_type == "multi_developer" for t in triggers)

    def test_high_usage_trigger(self):
        triggers = check_upsell_triggers("free", query_count=100)
        assert any(t.trigger_type == "high_usage" for t in triggers)

    def test_cross_repo_trigger(self):
        triggers = check_upsell_triggers("pro", has_multiple_repos=True)
        assert any(t.trigger_type == "cross_repo" for t in triggers)

    def test_pro_graph_size_trigger(self):
        triggers = check_upsell_triggers("pro", node_count=4500)
        assert any(t.trigger_type == "graph_size" for t in triggers)

    def test_trigger_has_value_prop(self):
        triggers = check_upsell_triggers("free", node_count=450)
        for t in triggers:
            assert t.value_prop  # should have associated cloud value prop


class TestCloudValueProps:
    def test_all_value_props_have_features(self):
        for key, prop in CLOUD_VALUE_PROPS.items():
            assert "title" in prop
            assert "description" in prop
            assert "features" in prop
            assert len(prop["features"]) > 0
            assert "min_plan" in prop
            assert "price" in prop


# ───────────────────────────── Track B (B2.1) ──────────────────────────────
# Team-aware upload_graph + the explicit share_graph_to_team RBAC gate.

import hashlib
from unittest.mock import MagicMock, patch

from graqle.cloud.team_registry import ForbiddenError


def _put_keys(mock_s3):
    """Return the list of S3 Keys that were put_object'd."""
    return [c.kwargs["Key"] for c in mock_s3.put_object.call_args_list]


class TestTeamAwareUpload:
    def test_user_path_is_byte_identical_when_no_team(self):
        gw = CloudGateway(api_key="grq_test123")
        mock_s3 = MagicMock()
        with patch("boto3.client", return_value=mock_s3):
            res = gw.upload_graph('{"nodes":[]}', "dev@acme.com", "proj")
        assert res["status"] == "uploaded"
        eh = hashlib.sha256(b"dev@acme.com").hexdigest()
        assert res["s3_prefix"] == f"graphs/{eh}/proj"
        assert _put_keys(mock_s3) == [f"graphs/{eh}/proj/graqle.json"]

    def test_team_id_routes_to_team_prefix(self):
        gw = CloudGateway(api_key="grq_test123")
        mock_s3 = MagicMock()
        with patch("boto3.client", return_value=mock_s3):
            res = gw.upload_graph('{"nodes":[]}', "dev@acme.com", "proj",
                                  team_id="team-acme")
        assert res["status"] == "uploaded"
        assert res["s3_prefix"] == "graphs/team-acme/proj"
        # email is NOT in the key on the team path
        assert _put_keys(mock_s3) == ["graphs/team-acme/proj/graqle.json"]

    def test_invalid_team_id_is_rejected_before_any_write(self):
        gw = CloudGateway(api_key="grq_test123")
        mock_s3 = MagicMock()
        with patch("boto3.client", return_value=mock_s3):
            res = gw.upload_graph('{"nodes":[]}', "dev@acme.com", "proj",
                                  team_id="../../etc")
        assert res["status"] == "failed"
        mock_s3.put_object.assert_not_called()

    def test_upload_not_connected(self):
        gw = CloudGateway()  # no key
        res = gw.upload_graph("{}", "a@b.co", "proj", team_id="team-acme")
        assert res.get("code") == "NOT_CONNECTED"


class _FakeReg:
    """Registry double that grants/denies a single member_hash."""

    def __init__(self, allow_hash=None):
        self.allow = allow_hash

    def assert_can_write(self, mh, team_id):
        if mh != self.allow:
            raise ForbiddenError("not permitted")
        return MagicMock(can_teach=True)


class TestShareGraphToTeam:
    def test_member_can_share_routes_to_team_prefix(self):
        gw = CloudGateway(api_key="grq_test123")
        mh = hashlib.sha256(b"dev@acme.com").hexdigest()
        mock_s3 = MagicMock()
        with patch("boto3.client", return_value=mock_s3):
            res = gw.share_graph_to_team('{"nodes":[]}', mh, "team-acme", "proj",
                                         registry=_FakeReg(allow_hash=mh))
        assert res["status"] == "shared"
        assert res["team_id"] == "team-acme"
        assert _put_keys(mock_s3) == ["graphs/team-acme/proj/graqle.json"]

    def test_viewer_or_outsider_is_forbidden_and_writes_nothing(self):
        gw = CloudGateway(api_key="grq_test123")
        outsider = hashlib.sha256(b"evil@x.com").hexdigest()
        mock_s3 = MagicMock()
        with patch("boto3.client", return_value=mock_s3):
            res = gw.share_graph_to_team('{"nodes":[]}', outsider, "team-acme",
                                         "proj", registry=_FakeReg(allow_hash="someoneelse"))
        assert res["status"] == "forbidden" and res["code"] == "FORBIDDEN"
        mock_s3.put_object.assert_not_called()

    def test_share_not_connected(self):
        gw = CloudGateway()
        res = gw.share_graph_to_team("{}", "h" * 64, "team-acme", "proj",
                                     registry=_FakeReg(allow_hash="h" * 64))
        assert res.get("code") == "NOT_CONNECTED"

    def test_registry_error_fails_closed(self):
        from graqle.cloud.team_registry import TeamRegistryError
        gw = CloudGateway(api_key="grq_test123")

        class _BoomReg:
            def assert_can_write(self, mh, team_id):
                raise TeamRegistryError("registry down")

        mock_s3 = MagicMock()
        with patch("boto3.client", return_value=mock_s3):
            res = gw.share_graph_to_team("{}", "h" * 64, "team-acme", "proj",
                                         registry=_BoomReg())
        assert res["status"] == "failed"
        mock_s3.put_object.assert_not_called()


class TestUploadBranches:
    def test_scorecard_is_also_uploaded(self):
        gw = CloudGateway(api_key="grq_test123")
        mock_s3 = MagicMock()
        with patch("boto3.client", return_value=mock_s3):
            res = gw.upload_graph('{"nodes":[]}', "dev@acme.com", "proj",
                                  scorecard_data='{"score":1}', team_id="team-acme")
        assert res["status"] == "uploaded"
        keys = _put_keys(mock_s3)
        assert "graphs/team-acme/proj/graqle.json" in keys
        assert "graphs/team-acme/proj/scorecard.json" in keys

    def test_upload_s3_failure_returns_failed(self):
        gw = CloudGateway(api_key="grq_test123")
        mock_s3 = MagicMock()
        mock_s3.put_object.side_effect = RuntimeError("s3 boom")
        with patch("boto3.client", return_value=mock_s3):
            res = gw.upload_graph('{"nodes":[]}', "dev@acme.com", "proj")
        assert res["status"] == "failed" and "s3 boom" in res["error"]
