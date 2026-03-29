"""GraQle Cloud metrics push — fire-and-forget ReasoningResult telemetry.

After each graq_reason / areason call, push lightweight metrics to the
Lambda /metrics endpoint so the dashboard can display usage trends.

Design:
- Fire-and-forget (never blocks the caller)
- Team plan only (free users skip silently)
- Only pushes opaque aggregate data — no user query content
- Single HTTP POST with urllib (no extra deps)
"""

# ── graqle:intelligence ──
# module: graqle.cloud.metrics_push
# risk: LOW (impact radius: 1 modules)
# consumers: graqle.plugins.mcp_dev_server
# dependencies: __future__, json, logging, urllib.request
# constraints: failure is always silent; never blocks caller
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("graqle.cloud.metrics_push")

# Lambda endpoint for metrics ingestion
_METRICS_ENDPOINT = "https://r3tj3qkjfu6ecxtpw7cb57jbha0qjmaw.lambda-url.eu-central-1.on.aws/api/metrics"


def push_reasoning_metrics(
    tool_name: str,
    latency_ms: float,
    confidence: float,
    rounds: int,
    node_count: int,
    cost_usd: float,
    project: str = "",
) -> None:
    """Push a single reasoning result metric to the cloud — non-blocking.

    Parameters are opaque aggregates only. No query text, no answers.
    Safe to call from any context; swallows all errors silently.
    """
    try:
        _push_sync({
            "tool": tool_name,
            "latency_ms": round(latency_ms, 1),
            "confidence": round(confidence, 4),
            "rounds": rounds,
            "node_count": node_count,
            "cost_usd": round(cost_usd, 6),
            "project": project[:64] if project else "",
        })
    except Exception as e:
        logger.debug("metrics_push failed (non-blocking): %s", e)


def _push_sync(payload: dict[str, Any]) -> None:
    """Inner HTTP push — raises on error (caller wraps with try/except)."""
    import urllib.request

    from graqle.cloud.credentials import load_credentials

    creds = load_credentials()
    if not creds.is_authenticated or creds.plan not in ("pro", "enterprise"):
        return  # Free tier — skip silently

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _METRICS_ENDPOINT,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": creds.api_key,
        },
        method="POST",
    )
    # Short timeout — never block the caller
    with urllib.request.urlopen(req, timeout=3) as resp:
        if resp.status not in (200, 202, 204):
            logger.debug("metrics_push returned status %d", resp.status)
