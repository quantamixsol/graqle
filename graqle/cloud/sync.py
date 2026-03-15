"""Graqle Cloud Sync — delta-based graph synchronization.

Computes deltas between local and remote graph versions for efficient
push/pull sync. Foundation for Team tier cloud sync via Neptune.

The sync protocol is delta-based (not full replication):
- Push: sends only changed nodes/edges since last sync
- Pull: receives only changes from team graph
- Resolve: interactive conflict resolution for ambiguous changes
"""

# ── graqle:intelligence ──
# module: graqle.cloud.sync
# risk: MEDIUM (impact radius: 2 modules)
# consumers: main, test_sync
# dependencies: __future__, hashlib, json, logging, time +3 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.cloud.sync")

SYNC_STATE_FILE = ".graqle/sync-state.json"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SyncDelta:
    """A set of changes to push or pull."""

    nodes_added: list[dict[str, Any]] = field(default_factory=list)
    nodes_modified: list[dict[str, Any]] = field(default_factory=list)
    nodes_deleted: list[str] = field(default_factory=list)
    edges_added: list[dict[str, Any]] = field(default_factory=list)
    edges_modified: list[dict[str, Any]] = field(default_factory=list)
    edges_deleted: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not any([
            self.nodes_added, self.nodes_modified, self.nodes_deleted,
            self.edges_added, self.edges_modified, self.edges_deleted,
        ])

    @property
    def summary(self) -> str:
        parts = []
        if self.nodes_added:
            parts.append(f"+{len(self.nodes_added)} nodes")
        if self.nodes_modified:
            parts.append(f"~{len(self.nodes_modified)} nodes")
        if self.nodes_deleted:
            parts.append(f"-{len(self.nodes_deleted)} nodes")
        if self.edges_added:
            parts.append(f"+{len(self.edges_added)} edges")
        if self.edges_modified:
            parts.append(f"~{len(self.edges_modified)} edges")
        if self.edges_deleted:
            parts.append(f"-{len(self.edges_deleted)} edges")
        return ", ".join(parts) if parts else "no changes"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SyncDelta:
        return cls(**{k: v for k, v in data.items()
                      if k in cls.__dataclass_fields__})


@dataclass
class SyncState:
    """Tracks sync state between local and remote graph."""

    team_id: str = ""
    last_push: str = ""
    last_pull: str = ""
    local_version: int = 0
    remote_version: int = 0
    status: str = "not_configured"  # not_configured, in_sync, ahead, behind, diverged
    last_snapshot_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SyncState:
        return cls(**{k: v for k, v in data.items()
                      if k in cls.__dataclass_fields__})


@dataclass
class SyncConflict:
    """A conflict between local and remote versions of the same entity."""

    entity_id: str
    entity_type: str  # "node" or "edge"
    local_value: dict[str, Any]
    remote_value: dict[str, Any]
    local_source: str = ""
    remote_source: str = ""
    resolution: str = ""  # "local", "remote", "manual", ""

    @property
    def source_priority(self) -> dict[str, int]:
        """Source type priority for auto-resolution."""
        return {
            "code": 5,
            "api_spec": 4,
            "config": 3,
            "taught": 2,
            "docs": 1,
            "unknown": 0,
        }


# ---------------------------------------------------------------------------
# Sync state persistence
# ---------------------------------------------------------------------------

def load_sync_state(project_dir: str | Path = ".") -> SyncState:
    """Load sync state from .graqle/sync-state.json."""
    state_path = Path(project_dir) / SYNC_STATE_FILE
    if not state_path.exists():
        return SyncState()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return SyncState.from_dict(data)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("Corrupt sync state: %s", exc)
        return SyncState()


def save_sync_state(state: SyncState, project_dir: str | Path = ".") -> None:
    """Save sync state to .graqle/sync-state.json."""
    state_path = Path(project_dir) / SYNC_STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state.to_dict(), indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Delta computation
# ---------------------------------------------------------------------------

def _hash_entity(entity: dict[str, Any]) -> str:
    """Compute content hash for a node or edge."""
    # Normalize: sort keys, exclude volatile fields
    stable = {k: v for k, v in sorted(entity.items())
              if k not in ("_sync_version", "_sync_hash", "_synced_at")}
    content = json.dumps(stable, sort_keys=True, default=str)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def compute_graph_hash(graph_data: dict[str, Any]) -> str:
    """Compute a hash of the entire graph for quick change detection."""
    content = json.dumps(graph_data, sort_keys=True, default=str)
    return hashlib.sha256(content.encode()).hexdigest()


def compute_delta(
    local_graph: dict[str, Any],
    baseline_graph: dict[str, Any] | None,
) -> SyncDelta:
    """Compute what changed between baseline and current local graph.

    Parameters
    ----------
    local_graph:
        Current local graph data (node_link_data format).
    baseline_graph:
        Graph state at last sync point. If None, all local data is "new".

    Returns
    -------
    SyncDelta
        The changes since last sync.
    """
    delta = SyncDelta()

    local_nodes = {n.get("id", ""): n for n in local_graph.get("nodes", [])}
    local_edges = {e.get("id", ""): e for e in local_graph.get("edges", local_graph.get("links", []))}

    if baseline_graph is None:
        # First sync — everything is new
        delta.nodes_added = list(local_nodes.values())
        delta.edges_added = list(local_edges.values())
        return delta

    baseline_nodes = {n.get("id", ""): n for n in baseline_graph.get("nodes", [])}
    baseline_edges = {e.get("id", ""): e for e in baseline_graph.get("edges", baseline_graph.get("links", []))}

    # Nodes: added, modified, deleted
    for nid, node in local_nodes.items():
        if nid not in baseline_nodes:
            delta.nodes_added.append(node)
        elif _hash_entity(node) != _hash_entity(baseline_nodes[nid]):
            delta.nodes_modified.append(node)

    for nid in baseline_nodes:
        if nid not in local_nodes:
            delta.nodes_deleted.append(nid)

    # Edges: added, modified, deleted
    for eid, edge in local_edges.items():
        if eid not in baseline_edges:
            delta.edges_added.append(edge)
        elif _hash_entity(edge) != _hash_entity(baseline_edges[eid]):
            delta.edges_modified.append(edge)

    for eid in baseline_edges:
        if eid not in local_edges:
            delta.edges_deleted.append(eid)

    return delta


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

def detect_conflicts(
    local_delta: SyncDelta,
    remote_delta: SyncDelta,
) -> list[SyncConflict]:
    """Detect conflicts between local and remote deltas.

    A conflict occurs when both sides modified the same entity.
    """
    conflicts: list[SyncConflict] = []

    # Build lookup of modified nodes by ID
    local_mod_nodes = {n.get("id"): n for n in local_delta.nodes_modified}
    remote_mod_nodes = {n.get("id"): n for n in remote_delta.nodes_modified}

    # Conflicts: both modified same node
    for nid in set(local_mod_nodes) & set(remote_mod_nodes):
        conflicts.append(SyncConflict(
            entity_id=nid,
            entity_type="node",
            local_value=local_mod_nodes[nid],
            remote_value=remote_mod_nodes[nid],
            local_source=local_mod_nodes[nid].get("source_type", "unknown"),
            remote_source=remote_mod_nodes[nid].get("source_type", "unknown"),
        ))

    # Conflicts: local modified + remote deleted (or vice versa)
    for nid in set(local_mod_nodes) & set(remote_delta.nodes_deleted):
        conflicts.append(SyncConflict(
            entity_id=nid,
            entity_type="node",
            local_value=local_mod_nodes[nid],
            remote_value={},
            local_source=local_mod_nodes[nid].get("source_type", "unknown"),
            remote_source="deleted",
        ))

    return conflicts


def auto_resolve_conflicts(conflicts: list[SyncConflict]) -> list[SyncConflict]:
    """Auto-resolve conflicts using source priority.

    Priority: Code > API spec > Config > Taught > Docs
    Returns only unresolved conflicts that need manual resolution.
    """
    unresolved: list[SyncConflict] = []
    priority = SyncConflict(
        entity_id="", entity_type="", local_value={}, remote_value={}
    ).source_priority

    for conflict in conflicts:
        local_pri = priority.get(conflict.local_source, 0)
        remote_pri = priority.get(conflict.remote_source, 0)

        if local_pri > remote_pri:
            conflict.resolution = "local"
        elif remote_pri > local_pri:
            conflict.resolution = "remote"
        else:
            # Same priority — check timestamps
            local_ts = conflict.local_value.get("updated_at", "")
            remote_ts = conflict.remote_value.get("updated_at", "")
            if local_ts > remote_ts:
                conflict.resolution = "local"
            elif remote_ts > local_ts:
                conflict.resolution = "remote"
            else:
                unresolved.append(conflict)

    return unresolved


# ---------------------------------------------------------------------------
# Snapshot management (for baseline tracking)
# ---------------------------------------------------------------------------

def save_sync_snapshot(
    graph_data: dict[str, Any],
    project_dir: str | Path = ".",
) -> str:
    """Save a snapshot of the current graph as the sync baseline.

    Returns the snapshot hash.
    """
    snapshot_dir = Path(project_dir) / ".graqle" / "sync-snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    graph_hash = compute_graph_hash(graph_data)
    snapshot_path = snapshot_dir / f"snapshot-{graph_hash[:12]}.json"

    snapshot_path.write_text(
        json.dumps(graph_data, default=str),
        encoding="utf-8",
    )

    # Also save as "latest" for quick access
    latest_path = snapshot_dir / "latest.json"
    latest_path.write_text(
        json.dumps(graph_data, default=str),
        encoding="utf-8",
    )

    return graph_hash


def load_sync_snapshot(
    project_dir: str | Path = ".",
) -> dict[str, Any] | None:
    """Load the latest sync snapshot (baseline for delta computation)."""
    latest_path = Path(project_dir) / ".graqle" / "sync-snapshots" / "latest.json"
    if not latest_path.exists():
        return None
    try:
        return json.loads(latest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load sync snapshot: %s", exc)
        return None
