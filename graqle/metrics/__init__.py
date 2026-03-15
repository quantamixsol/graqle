"""Graqle metrics — usage tracking, ROI reporting, and dashboards."""

# ── graqle:intelligence ──
# module: graqle.metrics.__init__
# risk: LOW (impact radius: 0 modules)
# dependencies: engine, dashboard
# constraints: none
# ── /graqle:intelligence ──

from graqle.metrics.dashboard import generate_dashboard
from graqle.metrics.engine import MetricsEngine

__all__ = ["MetricsEngine", "generate_dashboard", "get_metrics"]

# Module-level singleton for cumulative metrics across all graph instances
_global_engine: MetricsEngine | None = None


def get_metrics() -> MetricsEngine:
    """Get the shared MetricsEngine singleton.

    All Graqle instances share this engine so metrics accumulate
    across queries within a session and persist to disk between sessions.
    """
    global _global_engine
    if _global_engine is None:
        _global_engine = MetricsEngine()
    return _global_engine
