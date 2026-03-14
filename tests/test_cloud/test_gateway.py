"""Tests for graqle.cloud.gateway — cloud gateway client and upsell triggers."""

from __future__ import annotations

import pytest

from graqle.cloud.gateway import (
    CLOUD_VALUE_PROPS,
    CloudGateway,
    CloudServiceStatus,
    UpsellTrigger,
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
