"""Graqle Runtime — live observability data for the knowledge graph.

Auto-detects cloud environment (AWS, Azure, GCP) or local dev,
fetches logs/metrics, and builds RUNTIME_EVENT nodes in the KG.
"""

# ── graqle:intelligence ──
# module: graqle.runtime.__init__
# risk: LOW (impact radius: 0 modules)
# dependencies: detector, fetcher, kg_builder
# constraints: none
# ── /graqle:intelligence ──

from graqle.runtime.detector import detect_environment, EnvironmentInfo
from graqle.runtime.fetcher import LogFetcher, create_fetcher
from graqle.runtime.kg_builder import RuntimeKGBuilder

__all__ = [
    "detect_environment",
    "EnvironmentInfo",
    "LogFetcher",
    "create_fetcher",
    "RuntimeKGBuilder",
]
