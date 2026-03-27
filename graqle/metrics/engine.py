"""Core metrics tracking engine for Graqle.

Persists usage data to `.graqle/metrics.json` and provides ROI
reporting so users can quantify the value of graph-governed development.
"""

# ── graqle:intelligence ──
# module: graqle.metrics.engine
# risk: MEDIUM (impact radius: 4 modules)
# consumers: metrics_cmd, dashboard, __init__, test_metrics_accuracy
# dependencies: __future__, json, logging, collections, datetime +2 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.metrics")

_DEFAULT_TOKENS_WITHOUT = 2_000  # avg tokens when loading a file manually (realistic)


class MetricsEngine:
    """Track and report GraQle usage metrics.

    Metrics are stored in a single JSON file and updated incrementally.
    A *session* spans from ``start_session()`` to ``end_session()`` and
    captures per-session deltas so trends can be visualised over time.
    """

    def __init__(self, metrics_dir: Path | None = None) -> None:
        if metrics_dir is None:
            import os
            if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
                metrics_dir = Path("/tmp") / ".graqle"
            else:
                metrics_dir = Path.cwd() / ".graqle"
        self._metrics_path = Path(metrics_dir) / "metrics.json"
        self._metrics_path.parent.mkdir(parents=True, exist_ok=True)

        # Lifetime counters
        self.context_loads: int = 0
        self.queries: int = 0
        self.tokens_saved: int = 0
        self.mistakes_prevented: int = 0
        self.lessons_applied: int = 0
        self.safety_checks: int = 0
        self.safety_blocks: int = 0

        # Session history
        self.sessions: list[dict[str, Any]] = []

        # Per-node access tracking
        self.node_access: dict[str, dict[str, Any]] = {}

        # Timestamps
        self.init_timestamp: str = datetime.now(timezone.utc).isoformat()

        # Graph statistics snapshots
        self.graph_stats: dict[str, Any] = {}
        self.graph_stats_current: dict[str, Any] = {}

        # Internal session accumulators (not persisted directly)
        self._session_active: bool = False
        self._session_start: str | None = None
        self._session_queries: int = 0
        self._session_tokens_saved: int = 0
        self._session_lessons_applied: int = 0
        self._session_mistakes_prevented: int = 0
        self._session_safety_checks: int = 0
        self._session_safety_blocks: int = 0

        # Try to load existing data
        self.load()

        # S3 context — set by app.py _resolve_graph() on Lambda to target per-project key
        self._s3_email: str | None = None
        self._s3_project: str | None = None

    # ------------------------------------------------------------------
    # Recording methods
    # ------------------------------------------------------------------

    def record_context_load(
        self,
        service: str,
        tokens_returned: int,
        tokens_without: int = _DEFAULT_TOKENS_WITHOUT,
    ) -> None:
        """Record a context load event.

        Parameters
        ----------
        service:
            The service / node whose context was loaded.
        tokens_returned:
            Actual tokens returned by Graqle.
        tokens_without:
            Estimated tokens that would have been loaded without GraQle
            (defaults to 25 000 — the average full-file load).
        """
        self.context_loads += 1
        saved = max(tokens_without - tokens_returned, 0)
        self.tokens_saved += saved
        self._session_tokens_saved += saved

        # Track node access
        now = datetime.now(timezone.utc).isoformat()
        if service not in self.node_access:
            self.node_access[service] = {"count": 0, "last_accessed": now}
        self.node_access[service]["count"] += 1
        self.node_access[service]["last_accessed"] = now

        self.save()

    def record_query(self, query: str, result_tokens: int, caller: str = "") -> None:
        """Record a reasoning query.

        Token savings are tracked only via ``record_context_load()`` to
        avoid double-counting.  This method increments query counters only.

        Parameters
        ----------
        query:
            The query text.
        result_tokens:
            Number of tokens in the result.
        caller:
            Optional caller identifier for multi-agent tracking
            (e.g., "agent-1", "ci-pipeline", "claude-code").
        """
        self.queries += 1
        self._session_queries += 1

        # Track caller if provided
        if caller:
            if not hasattr(self, "caller_stats"):
                self.caller_stats: dict[str, dict[str, Any]] = {}
            if caller not in self.caller_stats:
                self.caller_stats[caller] = {"queries": 0, "last_seen": ""}
            self.caller_stats[caller]["queries"] += 1
            self.caller_stats[caller]["last_seen"] = datetime.now(timezone.utc).isoformat()

        self.save()

    def record_mistake_prevented(self, mistake_id: str, service: str) -> None:
        """Record a preflight check that prevented a mistake."""
        self.mistakes_prevented += 1
        self._session_mistakes_prevented += 1
        logger.info(
            "Mistake prevented: %s on service %s (total: %d)",
            mistake_id,
            service,
            self.mistakes_prevented,
        )
        self.save()

    def record_lesson_applied(self, lesson_id: str, task: str) -> None:
        """Record a lesson being matched and applied to a task."""
        self.lessons_applied += 1
        self._session_lessons_applied += 1
        logger.info(
            "Lesson applied: %s for task '%s' (total: %d)",
            lesson_id,
            task,
            self.lessons_applied,
        )
        self.save()

    def record_safety_check(self, rule: str, passed: bool) -> None:
        """Record a safety boundary check.

        Parameters
        ----------
        rule:
            The safety rule that was evaluated.
        passed:
            ``True`` if the action was allowed, ``False`` if it was blocked.
        """
        self.safety_checks += 1
        self._session_safety_checks += 1
        if not passed:
            self.safety_blocks += 1
            self._session_safety_blocks += 1
            logger.warning("Safety block: rule '%s' prevented an action", rule)
        self.save()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def start_session(self) -> None:
        """Mark the beginning of a new session."""
        self._session_active = True
        self._session_start = datetime.now(timezone.utc).isoformat()
        self._session_queries = 0
        self._session_tokens_saved = 0
        self._session_lessons_applied = 0
        self._session_mistakes_prevented = 0
        self._session_safety_checks = 0
        self._session_safety_blocks = 0
        logger.info("Metrics session started at %s", self._session_start)

    def end_session(self) -> None:
        """Mark the end of the current session and persist session totals."""
        if not self._session_active:
            return

        session_record: dict[str, Any] = {
            "date": self._session_start or datetime.now(timezone.utc).isoformat(),
            "ended": datetime.now(timezone.utc).isoformat(),
            "queries": self._session_queries,
            "tokens_saved": self._session_tokens_saved,
            "lessons_applied": self._session_lessons_applied,
            "mistakes_prevented": self._session_mistakes_prevented,
            "safety_checks": self._session_safety_checks,
            "safety_blocks": self._session_safety_blocks,
        }
        self.sessions.append(session_record)
        self._session_active = False
        logger.info(
            "Metrics session ended — queries=%d, tokens_saved=%d",
            self._session_queries,
            self._session_tokens_saved,
        )
        self.save()

    # ------------------------------------------------------------------
    # Graph statistics
    # ------------------------------------------------------------------

    def set_graph_stats(
        self,
        nodes: int,
        edges: int,
        node_types: dict[str, int] | None = None,
        edge_types: dict[str, int] | None = None,
        *,
        initial: bool = False,
    ) -> None:
        """Capture graph statistics.

        Parameters
        ----------
        initial:
            If ``True`` this is the first snapshot (stored as ``graph_stats``
            *and* ``graph_stats_current``). Otherwise only ``graph_stats_current``
            is updated.
        """
        stats: dict[str, Any] = {
            "nodes": nodes,
            "edges": edges,
            "node_types": node_types or {},
            "edge_types": edge_types or {},
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
        if initial or not self.graph_stats:
            self.graph_stats = stats
        self.graph_stats_current = stats
        self.save()

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_summary(self) -> dict[str, Any]:
        """Return a summary dict of all tracked metrics."""
        return {
            "context_loads": self.context_loads,
            "queries": self.queries,
            "tokens_saved": self.tokens_saved,
            "mistakes_prevented": self.mistakes_prevented,
            "lessons_applied": self.lessons_applied,
            "safety_checks": self.safety_checks,
            "safety_blocks": self.safety_blocks,
            "sessions_count": len(self.sessions),
            "unique_nodes_accessed": len(self.node_access),
            "init_timestamp": self.init_timestamp,
            "graph_stats": self.graph_stats,
            "graph_stats_current": self.graph_stats_current,
            "caller_stats": getattr(self, "caller_stats", {}),
        }

    def get_roi_report(self) -> str:
        """Generate a human-readable ROI report.

        The report estimates cost savings using a rate of $0.015 per 1 000
        input tokens (a typical mid-tier LLM pricing).
        """
        cost_per_1k = 0.015
        estimated_savings_usd = (self.tokens_saved / 1000) * cost_per_1k
        avg_tokens_saved_per_load = (
            self.tokens_saved // self.context_loads
            if self.context_loads
            else 0
        )
        avg_tokens_returned = max(_DEFAULT_TOKENS_WITHOUT - avg_tokens_saved_per_load, 1)
        reduction_factor = (
            round(_DEFAULT_TOKENS_WITHOUT / avg_tokens_returned, 1)
            if self.context_loads
            else 0
        )

        lines = [
            "=" * 60,
            "  GraQle ROI Report",
            "=" * 60,
            "",
            f"  Initialised:          {self.init_timestamp[:10]}",
            f"  Sessions completed:   {len(self.sessions)}",
            "",
            "  --- Token Efficiency ---",
            f"  Context loads:        {self.context_loads:,}",
            f"  Total tokens saved:   {self.tokens_saved:,}",
            f"  Avg saved per load:   {avg_tokens_saved_per_load:,}",
            f"  Reduction factor:     {reduction_factor}x",
            "",
            "  --- Quality ---",
            f"  Queries answered:     {self.queries:,}",
            f"  Mistakes prevented:   {self.mistakes_prevented:,}",
            f"  Lessons applied:      {self.lessons_applied:,}",
            "",
            "  --- Safety ---",
            f"  Safety checks:        {self.safety_checks:,}",
            f"  Violations blocked:   {self.safety_blocks:,}",
            f"  Block rate:           {self.safety_blocks / max(self.safety_checks, 1):.0%}",
            "",
            "  --- Estimated Cost Impact ---",
            "  Token cost rate:      $0.015 / 1K input tokens",
            f"  Estimated savings:    ${estimated_savings_usd:,.2f}",
            "",
            "=" * 60,
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist all metrics to disk as JSON, and to S3 when running on Lambda."""
        import os as _os
        data: dict[str, Any] = {
            "init_timestamp": self.init_timestamp,
            "context_loads": self.context_loads,
            "queries": self.queries,
            "tokens_saved": self.tokens_saved,
            "mistakes_prevented": self.mistakes_prevented,
            "lessons_applied": self.lessons_applied,
            "safety_checks": self.safety_checks,
            "safety_blocks": self.safety_blocks,
            "sessions": self.sessions,
            "node_access": self.node_access,
            "graph_stats": self.graph_stats,
            "graph_stats_current": self.graph_stats_current,
            "caller_stats": getattr(self, "caller_stats", {}),
        }
        payload = json.dumps(data, indent=2, ensure_ascii=False)
        try:
            self._metrics_path.write_text(payload, encoding="utf-8")
        except OSError:
            logger.warning("Failed to persist metrics to %s", self._metrics_path)

        # On Lambda: also write to S3 so metrics survive cold starts.
        # Key: graphs/{email_hash}/{project}/metrics.json — same prefix as the KG.
        if _os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
            email = getattr(self, "_s3_email", None)
            project = getattr(self, "_s3_project", None)
            if email and project:
                try:
                    import hashlib as _hashlib
                    import boto3 as _boto3
                    bucket = _os.environ.get("GRAQLE_GRAPHS_BUCKET", "graqle-graphs-eu")
                    email_hash = _hashlib.sha256(email.lower().encode()).hexdigest()
                    s3_key = f"graphs/{email_hash}/{project}/metrics.json"
                    s3 = _boto3.client("s3", region_name=_os.environ.get("AWS_REGION", "eu-central-1"))
                    s3.put_object(Bucket=bucket, Key=s3_key, Body=payload.encode("utf-8"), ContentType="application/json")
                    logger.debug("Metrics saved to S3: %s/%s", bucket, s3_key)
                except Exception as exc:
                    logger.warning("Failed to save metrics to S3: %s", exc)

    def load(self) -> None:
        """Load metrics from disk, merging into current state."""
        if not self._metrics_path.exists():
            return
        try:
            raw = self._metrics_path.read_text(encoding="utf-8")
            data: dict[str, Any] = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not load metrics from %s", self._metrics_path)
            return

        self.init_timestamp = data.get("init_timestamp", self.init_timestamp)
        self.context_loads = data.get("context_loads", 0)
        self.queries = data.get("queries", 0)
        self.tokens_saved = data.get("tokens_saved", 0)
        self.mistakes_prevented = data.get("mistakes_prevented", 0)
        self.lessons_applied = data.get("lessons_applied", 0)
        self.safety_checks = data.get("safety_checks", 0)
        self.safety_blocks = data.get("safety_blocks", 0)
        self.sessions = data.get("sessions", [])
        self.node_access = data.get("node_access", {})
        self.graph_stats = data.get("graph_stats", {})
        self.graph_stats_current = data.get("graph_stats_current", {})
        self.caller_stats: dict[str, dict[str, Any]] = data.get("caller_stats", {})

    def load_from_s3(self, email: str, project: str) -> None:
        """Load metrics from S3 (Lambda only). Call once per cold start after user context is known."""
        import os as _os
        if not _os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
            return
        try:
            import hashlib as _hashlib
            import boto3 as _boto3
            bucket = _os.environ.get("GRAQLE_GRAPHS_BUCKET", "graqle-graphs-eu")
            email_hash = _hashlib.sha256(email.lower().encode()).hexdigest()
            s3_key = f"graphs/{email_hash}/{project}/metrics.json"
            s3 = _boto3.client("s3", region_name=_os.environ.get("AWS_REGION", "eu-central-1"))
            obj = s3.get_object(Bucket=bucket, Key=s3_key)
            raw = obj["Body"].read().decode("utf-8")
            # Merge S3 data only if it has more queries (S3 is the durable store)
            s3_data = json.loads(raw)
            if s3_data.get("queries", 0) >= self.queries:
                self.context_loads = s3_data.get("context_loads", self.context_loads)
                self.queries = s3_data.get("queries", self.queries)
                self.tokens_saved = s3_data.get("tokens_saved", self.tokens_saved)
                self.mistakes_prevented = s3_data.get("mistakes_prevented", self.mistakes_prevented)
                self.lessons_applied = s3_data.get("lessons_applied", self.lessons_applied)
                self.safety_checks = s3_data.get("safety_checks", self.safety_checks)
                self.safety_blocks = s3_data.get("safety_blocks", self.safety_blocks)
                self.sessions = s3_data.get("sessions", self.sessions)
                self.node_access = s3_data.get("node_access", self.node_access)
                logger.debug("Metrics loaded from S3: %s/%s (%d queries)", bucket, s3_key, self.queries)
        except Exception as exc:
            logger.debug("No S3 metrics found for %s/%s: %s", email, project, exc)

    def reset(self) -> None:
        """Reset all metrics to zero and persist."""
        self.context_loads = 0
        self.queries = 0
        self.tokens_saved = 0
        self.mistakes_prevented = 0
        self.lessons_applied = 0
        self.safety_checks = 0
        self.safety_blocks = 0
        self.sessions = []
        self.node_access = {}
        self.graph_stats = {}
        self.graph_stats_current = {}
        self.caller_stats = {}
        self.init_timestamp = datetime.now(timezone.utc).isoformat()
        self._session_active = False
        self.save()
