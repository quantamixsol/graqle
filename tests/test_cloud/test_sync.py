"""Tests for graqle.cloud.sync — delta computation and sync state."""

# ── graqle:intelligence ──
# module: tests.test_cloud.test_sync
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, json, pytest, pathlib, sync
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from graqle.cloud.sync import (
    SyncConflict,
    SyncDelta,
    SyncState,
    auto_resolve_conflicts,
    compute_delta,
    compute_graph_hash,
    detect_conflicts,
    load_sync_snapshot,
    load_sync_state,
    save_sync_snapshot,
    save_sync_state,
)

# ---------------------------------------------------------------------------
# SyncDelta
# ---------------------------------------------------------------------------

class TestSyncDelta:
    def test_empty_delta(self):
        delta = SyncDelta()
        assert delta.is_empty
        assert delta.summary == "no changes"

    def test_non_empty_delta(self):
        delta = SyncDelta(
            nodes_added=[{"id": "n1"}],
            edges_added=[{"id": "e1"}, {"id": "e2"}],
        )
        assert not delta.is_empty
        assert "+1 nodes" in delta.summary
        assert "+2 edges" in delta.summary

    def test_delta_all_types(self):
        delta = SyncDelta(
            nodes_added=[{"id": "n1"}],
            nodes_modified=[{"id": "n2"}],
            nodes_deleted=["n3"],
            edges_added=[{"id": "e1"}],
            edges_modified=[{"id": "e2"}],
            edges_deleted=["e3"],
        )
        assert "+1 nodes" in delta.summary
        assert "~1 nodes" in delta.summary
        assert "-1 nodes" in delta.summary

    def test_delta_roundtrip(self):
        delta = SyncDelta(nodes_added=[{"id": "n1", "label": "test"}])
        d = delta.to_dict()
        restored = SyncDelta.from_dict(d)
        assert restored.nodes_added == [{"id": "n1", "label": "test"}]


# ---------------------------------------------------------------------------
# SyncState
# ---------------------------------------------------------------------------

class TestSyncState:
    def test_default_state(self):
        state = SyncState()
        assert state.status == "not_configured"
        assert state.local_version == 0

    def test_state_persistence(self, tmp_path):
        state = SyncState(
            team_id="team-test",
            local_version=5,
            remote_version=3,
            status="ahead",
        )
        save_sync_state(state, tmp_path)

        loaded = load_sync_state(tmp_path)
        assert loaded.team_id == "team-test"
        assert loaded.local_version == 5
        assert loaded.remote_version == 3
        assert loaded.status == "ahead"

    def test_load_missing_state(self, tmp_path):
        state = load_sync_state(tmp_path)
        assert state.status == "not_configured"

    def test_load_corrupt_state(self, tmp_path):
        state_path = tmp_path / ".graqle" / "sync-state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text("not json", encoding="utf-8")
        state = load_sync_state(tmp_path)
        assert state.status == "not_configured"


# ---------------------------------------------------------------------------
# Delta computation
# ---------------------------------------------------------------------------

class TestComputeDelta:
    def test_first_sync_all_new(self):
        local = {
            "nodes": [{"id": "n1"}, {"id": "n2"}],
            "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
        }
        delta = compute_delta(local, None)
        assert len(delta.nodes_added) == 2
        assert len(delta.edges_added) == 1
        assert not delta.nodes_modified
        assert not delta.nodes_deleted

    def test_no_changes(self):
        graph = {
            "nodes": [{"id": "n1", "label": "test"}],
            "edges": [],
        }
        delta = compute_delta(graph, graph)
        assert delta.is_empty

    def test_node_added(self):
        baseline = {"nodes": [{"id": "n1"}], "edges": []}
        local = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []}
        delta = compute_delta(local, baseline)
        assert len(delta.nodes_added) == 1
        assert delta.nodes_added[0]["id"] == "n2"

    def test_node_modified(self):
        baseline = {"nodes": [{"id": "n1", "label": "old"}], "edges": []}
        local = {"nodes": [{"id": "n1", "label": "new"}], "edges": []}
        delta = compute_delta(local, baseline)
        assert len(delta.nodes_modified) == 1
        assert delta.nodes_modified[0]["label"] == "new"

    def test_node_deleted(self):
        baseline = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []}
        local = {"nodes": [{"id": "n1"}], "edges": []}
        delta = compute_delta(local, baseline)
        assert delta.nodes_deleted == ["n2"]

    def test_edge_changes(self):
        baseline = {
            "nodes": [{"id": "n1"}, {"id": "n2"}],
            "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
        }
        local = {
            "nodes": [{"id": "n1"}, {"id": "n2"}],
            "edges": [
                {"id": "e1", "source": "n1", "target": "n2", "weight": 0.9},
                {"id": "e2", "source": "n2", "target": "n1"},
            ],
        }
        delta = compute_delta(local, baseline)
        assert len(delta.edges_added) == 1
        assert len(delta.edges_modified) == 1

    def test_links_key_fallback(self):
        """Test that 'links' key works as fallback for 'edges'."""
        local = {
            "nodes": [{"id": "n1"}],
            "links": [{"id": "e1", "source": "n1", "target": "n1"}],
        }
        delta = compute_delta(local, None)
        assert len(delta.edges_added) == 1


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

class TestConflictDetection:
    def test_no_conflicts(self):
        local = SyncDelta(nodes_modified=[{"id": "n1"}])
        remote = SyncDelta(nodes_modified=[{"id": "n2"}])
        conflicts = detect_conflicts(local, remote)
        assert len(conflicts) == 0

    def test_same_node_modified(self):
        local = SyncDelta(nodes_modified=[{"id": "n1", "label": "local"}])
        remote = SyncDelta(nodes_modified=[{"id": "n1", "label": "remote"}])
        conflicts = detect_conflicts(local, remote)
        assert len(conflicts) == 1
        assert conflicts[0].entity_id == "n1"

    def test_modified_vs_deleted(self):
        local = SyncDelta(nodes_modified=[{"id": "n1", "label": "local"}])
        remote = SyncDelta(nodes_deleted=["n1"])
        conflicts = detect_conflicts(local, remote)
        assert len(conflicts) == 1
        assert conflicts[0].remote_source == "deleted"


class TestAutoResolveConflicts:
    def test_code_beats_docs(self):
        conflicts = [SyncConflict(
            entity_id="n1",
            entity_type="node",
            local_value={"label": "local"},
            remote_value={"label": "remote"},
            local_source="code",
            remote_source="docs",
        )]
        unresolved = auto_resolve_conflicts(conflicts)
        assert len(unresolved) == 0
        assert conflicts[0].resolution == "local"

    def test_api_spec_beats_taught(self):
        conflicts = [SyncConflict(
            entity_id="n1",
            entity_type="node",
            local_value={},
            remote_value={},
            local_source="taught",
            remote_source="api_spec",
        )]
        unresolved = auto_resolve_conflicts(conflicts)
        assert conflicts[0].resolution == "remote"

    def test_same_priority_timestamp(self):
        conflicts = [SyncConflict(
            entity_id="n1",
            entity_type="node",
            local_value={"updated_at": "2026-03-14T10:00:00Z"},
            remote_value={"updated_at": "2026-03-14T09:00:00Z"},
            local_source="code",
            remote_source="code",
        )]
        unresolved = auto_resolve_conflicts(conflicts)
        assert len(unresolved) == 0
        assert conflicts[0].resolution == "local"

    def test_same_priority_same_timestamp_unresolved(self):
        conflicts = [SyncConflict(
            entity_id="n1",
            entity_type="node",
            local_value={"updated_at": "2026-03-14T10:00:00Z"},
            remote_value={"updated_at": "2026-03-14T10:00:00Z"},
            local_source="code",
            remote_source="code",
        )]
        unresolved = auto_resolve_conflicts(conflicts)
        assert len(unresolved) == 1


# ---------------------------------------------------------------------------
# Snapshot management
# ---------------------------------------------------------------------------

class TestSnapshots:
    def test_save_and_load_snapshot(self, tmp_path):
        graph = {"nodes": [{"id": "n1"}], "edges": []}
        graph_hash = save_sync_snapshot(graph, tmp_path)
        assert graph_hash

        loaded = load_sync_snapshot(tmp_path)
        assert loaded is not None
        assert loaded["nodes"] == [{"id": "n1"}]

    def test_load_missing_snapshot(self, tmp_path):
        result = load_sync_snapshot(tmp_path)
        assert result is None

    def test_graph_hash_deterministic(self):
        graph = {"nodes": [{"id": "n1"}], "edges": []}
        h1 = compute_graph_hash(graph)
        h2 = compute_graph_hash(graph)
        assert h1 == h2

    def test_graph_hash_changes(self):
        g1 = {"nodes": [{"id": "n1"}], "edges": []}
        g2 = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []}
        assert compute_graph_hash(g1) != compute_graph_hash(g2)
