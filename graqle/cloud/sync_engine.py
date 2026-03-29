"""GraQle SyncEngine — orchestrates local-first delta sync to cloud.

Architecture:
- Local graqle.json is ALWAYS the source of truth
- Cloud (S3 + optionally Neptune) is an eventually-consistent backup
- Delta push: only changed nodes/edges are sent, not the full graph
- Non-blocking: sync failure NEVER blocks local operations
- Team tier only: free users skip sync silently

Usage:
    engine = SyncEngine.from_project_dir(Path("."))
    result = engine.push_if_changed()   # no-op if nothing changed
    result = engine.push(force=True)    # full push regardless
"""

# ── graqle:intelligence ──
# module: graqle.cloud.sync_engine
# risk: LOW (impact radius: 1 modules)
# consumers: cli.commands.scan, cli.commands.grow, cli.commands.learn
# dependencies: __future__, logging, pathlib, graqle.cloud.sync, graqle.cloud.credentials
# constraints: none — failure is always silent
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from graqle.cloud.sync import (
    SyncDelta,
    SyncState,
    compute_delta,
    compute_graph_hash,
    load_sync_state,
    save_sync_state,
)

logger = logging.getLogger("graqle.cloud.sync_engine")

# Snapshot file — stores the graph state at last successful push
_SNAPSHOT_FILE = ".graqle/sync-snapshot.json"


@dataclass
class SyncResult:
    """Result of a sync operation."""
    status: str           # "pushed", "no_changes", "skipped", "failed"
    nodes_pushed: int = 0
    edges_pushed: int = 0
    error: str = ""

    @property
    def succeeded(self) -> bool:
        return self.status in ("pushed", "no_changes")


class SyncEngine:
    """Orchestrates local-first delta sync to cloud.

    Local is source of truth. Cloud is backup.
    Never blocks local operations on failure.
    """

    def __init__(self, project_dir: Path, graph_path: Path) -> None:
        self._project_dir = project_dir
        self._graph_path = graph_path

    @classmethod
    def from_project_dir(cls, project_dir: Path) -> "SyncEngine":
        """Create engine from project directory (auto-detects graqle.json)."""
        graph_path = project_dir / "graqle.json"
        return cls(project_dir=project_dir, graph_path=graph_path)

    # ── Public API ────────────────────────────────────────────────────────────

    def push_if_changed(self) -> SyncResult:
        """Push to cloud only if graph has changed since last sync.

        Uses compute_graph_hash to detect changes — zero cost if unchanged.
        """
        if not self._graph_path.exists():
            return SyncResult(status="skipped", error="no graph file")

        if not self._is_team_plan():
            return SyncResult(status="skipped", error="free tier")

        try:
            current = self._load_graph()
            current_hash = compute_graph_hash(current)

            state = load_sync_state(self._project_dir)
            if state.last_snapshot_hash == current_hash:
                return SyncResult(status="no_changes")

            return self._do_push(current, current_hash)
        except Exception as e:
            logger.debug("SyncEngine.push_if_changed failed (non-blocking): %s", e)
            return SyncResult(status="failed", error=str(e)[:200])

    def push(self, force: bool = False) -> SyncResult:
        """Push to cloud. If force=True, skips delta check and pushes full graph."""
        if not self._graph_path.exists():
            return SyncResult(status="skipped", error="no graph file")

        if not self._is_team_plan():
            return SyncResult(status="skipped", error="free tier")

        try:
            current = self._load_graph()
            current_hash = compute_graph_hash(current)

            if not force:
                state = load_sync_state(self._project_dir)
                if state.last_snapshot_hash == current_hash:
                    return SyncResult(status="no_changes")

            return self._do_push(current, current_hash)
        except Exception as e:
            logger.debug("SyncEngine.push failed (non-blocking): %s", e)
            return SyncResult(status="failed", error=str(e)[:200])

    # ── Internal ─────────────────────────────────────────────────────────────

    def _is_team_plan(self) -> bool:
        """Check if current credentials allow cloud sync."""
        try:
            from graqle.cloud.credentials import load_credentials
            creds = load_credentials()
            return creds.is_authenticated and creds.plan in ("pro", "enterprise")
        except Exception:
            return False

    def _load_graph(self) -> dict[str, Any]:
        return json.loads(self._graph_path.read_text(encoding="utf-8"))

    def _load_snapshot(self) -> dict[str, Any] | None:
        snapshot_path = self._project_dir / _SNAPSHOT_FILE
        if not snapshot_path.exists():
            return None
        try:
            return json.loads(snapshot_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _save_snapshot(self, graph: dict[str, Any]) -> None:
        snapshot_path = self._project_dir / _SNAPSHOT_FILE
        try:
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text(
                json.dumps(graph, separators=(",", ":")),  # compact for storage
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug("Could not save sync snapshot: %s", e)

    def _do_push(self, current: dict[str, Any], current_hash: str) -> SyncResult:
        """Compute delta, push via auto_cloud_sync, update sync state."""
        snapshot = self._load_snapshot()
        delta = compute_delta(current, snapshot)

        if delta.is_empty and snapshot is not None:
            return SyncResult(status="no_changes")

        # Delegate to existing auto_cloud_sync transport (S3 + Neptune)
        try:
            from graqle.cli.commands.cloud import auto_cloud_sync
            auto_cloud_sync(self._project_dir, quiet=True, graph_json=current)
        except Exception as e:
            logger.debug("Cloud transport failed (non-blocking): %s", e)
            return SyncResult(status="failed", error=str(e)[:200])

        # Update state + snapshot on success
        self._save_snapshot(current)
        state = load_sync_state(self._project_dir)
        state.last_snapshot_hash = current_hash
        state.status = "in_sync"
        import time
        state.last_push = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save_sync_state(state, self._project_dir)

        nodes_pushed = len(delta.nodes_added) + len(delta.nodes_modified)
        edges_pushed = len(delta.edges_added) + len(delta.edges_modified)
        logger.info(
            "SyncEngine pushed delta: %s nodes, %s edges (%s)",
            nodes_pushed, edges_pushed, delta.summary,
        )
        return SyncResult(status="pushed", nodes_pushed=nodes_pushed, edges_pushed=edges_pushed)
