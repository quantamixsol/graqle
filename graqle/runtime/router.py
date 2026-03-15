"""Smart query router — classifies questions and recommends Graqle vs external tools.

This is the answer to "when should an AI assistant use Graqle?" — it provides
a programmatic routing recommendation so Claude Code / Cursor / etc. know
whether to call graq_reason or go straight to CloudWatch.
"""

# ── graqle:intelligence ──
# module: graqle.runtime.router
# risk: LOW (impact radius: 3 modules)
# consumers: __init__, test_router, test_nl_router
# dependencies: __future__, re, dataclasses, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RouteRecommendation:
    """Routing recommendation for a given question."""

    category: str  # ARCHITECTURE, IMPACT, RUNTIME, PERFORMANCE, CODE_NAV, HISTORICAL, DECISION
    graqle_priority: str  # HIGH, MEDIUM, LOW
    recommendation: str  # "graqle_first", "external_first", "hybrid", "graqle_only"
    graqle_tools: list[str] = field(default_factory=list)
    external_tools: list[str] = field(default_factory=list)
    confidence: float = 0.8
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "graqle_priority": self.graqle_priority,
            "recommendation": self.recommendation,
            "graqle_tools": self.graqle_tools,
            "external_tools": self.external_tools,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }


# ---------------------------------------------------------------------------
# Pattern-based classifier
# ---------------------------------------------------------------------------

# (regex_pattern, category, graqle_priority)
_ROUTE_PATTERNS: list[tuple[str, str, str]] = [
    # Architecture — Graqle excels
    (r"what\s+(depends|imports|calls|uses|connects)", "ARCHITECTURE", "HIGH"),
    (r"(depend|import|call|use)\s+on", "ARCHITECTURE", "HIGH"),
    (r"(architecture|structure|module|component)\s+(of|for|in)", "ARCHITECTURE", "HIGH"),
    (r"how\s+(does|do|is)\s+.*(structured|organized|architected)", "ARCHITECTURE", "HIGH"),
    (r"relationship\s+between", "ARCHITECTURE", "HIGH"),

    # Impact analysis — Graqle's sweet spot
    (r"what\s+(breaks|happens|changes|affected)\s+if", "IMPACT", "HIGH"),
    (r"impact\s+(of|analysis|if|when)", "IMPACT", "HIGH"),
    (r"(downstream|upstream|ripple)\s+effect", "IMPACT", "HIGH"),
    (r"safe\s+to\s+(change|modify|remove|delete)", "IMPACT", "HIGH"),
    (r"blast\s+radius", "IMPACT", "HIGH"),

    # Decision / ADR — Graqle has these in the KG
    (r"why\s+did\s+we\s+(choose|use|pick|select)", "DECISION", "HIGH"),
    (r"(decision|adr|rationale)\s+(for|behind|about)", "DECISION", "HIGH"),
    (r"trade.?off", "DECISION", "HIGH"),

    # Runtime / debugging — Graqle LOW, external HIGH
    (r"(timeout|timed?\s*out|504|502|500)", "RUNTIME", "LOW"),
    (r"(error|fail|crash|exception)\s+in\s+(production|prod|lambda|api)", "RUNTIME", "LOW"),
    (r"(why|what)\s+is\s+.*(failing|broken|down|slow|timing)", "RUNTIME", "LOW"),
    (r"(cloudwatch|logs?|metric|alarm|alert)", "RUNTIME", "LOW"),
    (r"(cold\s*start|warm\s*up|latency|p99|p95)", "RUNTIME", "LOW"),
    (r"(memory|cpu|disk)\s+(usage|leak|spike)", "RUNTIME", "LOW"),

    # Performance — mostly external tools
    (r"(slow|performance|bottleneck|optimize)", "PERFORMANCE", "LOW"),
    (r"(throughput|qps|rps|load\s+test)", "PERFORMANCE", "LOW"),

    # Code navigation — Graqle MEDIUM, grep/read as fallback
    (r"where\s+is\s+.*(defined|declared|implemented|located)", "CODE_NAV", "MEDIUM"),
    (r"find\s+(the|all)\s+(function|class|file|module)", "CODE_NAV", "MEDIUM"),
    (r"(show|list)\s+(all|the)\s+(endpoints|routes|handlers)", "CODE_NAV", "MEDIUM"),

    # Historical — git + Graqle hybrid
    (r"when\s+did\s+we\s+(add|change|remove|introduce)", "HISTORICAL", "MEDIUM"),
    (r"(history|changelog|last\s+changed|git\s+log)", "HISTORICAL", "MEDIUM"),
    (r"who\s+(wrote|added|changed|owns)", "HISTORICAL", "MEDIUM"),

    # Lessons / safety — Graqle HIGH
    (r"(lesson|mistake|gotcha|pitfall|avoid)", "LESSONS", "HIGH"),
    (r"(safety|boundary|constraint|rule)\s+(for|about|when)", "LESSONS", "HIGH"),
    (r"what\s+went\s+wrong", "LESSONS", "HIGH"),
    (r"common\s+(error|failure|issue|bug)", "LESSONS", "HIGH"),
]

# Category -> tool recommendations
_TOOL_MAP: dict[str, dict[str, Any]] = {
    "ARCHITECTURE": {
        "recommendation": "graqle_first",
        "graqle_tools": ["graq_context", "graq_reason"],
        "external_tools": [],
        "reasoning": "Architecture questions are Graqle's strength — the KG captures all module relationships.",
    },
    "IMPACT": {
        "recommendation": "graqle_only",
        "graqle_tools": ["graq_impact", "graq_preflight"],
        "external_tools": [],
        "reasoning": "Impact analysis requires dependency graph traversal. Graqle does this natively.",
    },
    "DECISION": {
        "recommendation": "graqle_first",
        "graqle_tools": ["graq_reason", "graq_lessons"],
        "external_tools": [],
        "reasoning": "ADRs and design decisions are stored as KG nodes. Graqle can retrieve them directly.",
    },
    "RUNTIME": {
        "recommendation": "hybrid",
        "graqle_tools": ["graq_runtime", "graq_context"],
        "external_tools": ["cloudwatch_logs", "metrics_dashboard", "traces"],
        "reasoning": "Runtime issues need live observability data (graq_runtime) plus structural context (graq_context).",
    },
    "PERFORMANCE": {
        "recommendation": "external_first",
        "graqle_tools": ["graq_context"],
        "external_tools": ["cloudwatch_metrics", "xray_traces", "profiler"],
        "reasoning": "Performance requires live metrics. Use graq_context for code structure only.",
    },
    "CODE_NAV": {
        "recommendation": "hybrid",
        "graqle_tools": ["graq_inspect", "graq_context"],
        "external_tools": ["grep", "read"],
        "reasoning": "Graqle finds entities fast via the KG. Use grep/read for exact line-level code.",
    },
    "HISTORICAL": {
        "recommendation": "hybrid",
        "graqle_tools": ["graq_context"],
        "external_tools": ["git_log", "git_blame"],
        "reasoning": "Git is authoritative for history. Graqle adds context about why changes happened.",
    },
    "LESSONS": {
        "recommendation": "graqle_only",
        "graqle_tools": ["graq_lessons", "graq_preflight"],
        "external_tools": [],
        "reasoning": "Lessons and safety boundaries live in the KG. Graqle is the only source for these.",
    },
}


def route_question(question: str, *, has_runtime: bool = False) -> RouteRecommendation:
    """Classify a question and return a routing recommendation.

    Parameters
    ----------
    question : str
        The user's question or investigation topic.
    has_runtime : bool
        Whether graq_runtime is available (affects RUNTIME category routing).
    """
    question_lower = question.lower().strip()

    # Try pattern matching
    best_category = None
    best_priority = None
    best_confidence = 0.0

    for pattern, category, priority in _ROUTE_PATTERNS:
        if re.search(pattern, question_lower):
            # Score: more specific patterns get higher confidence
            specificity = len(pattern) / 100.0  # Rough heuristic
            confidence = min(0.6 + specificity, 0.95)
            if confidence > best_confidence:
                best_category = category
                best_priority = priority
                best_confidence = confidence

    # Default to ARCHITECTURE with medium confidence if no pattern matches
    if best_category is None:
        best_category = "ARCHITECTURE"
        best_priority = "MEDIUM"
        best_confidence = 0.5

    # Build recommendation from tool map
    tool_info = _TOOL_MAP.get(best_category, _TOOL_MAP["ARCHITECTURE"])

    # Adjust for runtime availability
    recommendation = tool_info["recommendation"]
    graqle_tools = list(tool_info["graqle_tools"])
    external_tools = list(tool_info["external_tools"])
    reasoning = tool_info["reasoning"]

    if best_category == "RUNTIME" and has_runtime:
        recommendation = "graqle_first"
        graqle_tools = ["graq_runtime", "graq_context", "graq_reason"]
        reasoning = "graq_runtime provides live observability data. Use it first, supplement with CloudWatch for deep dives."

    return RouteRecommendation(
        category=best_category,
        graqle_priority=best_priority,
        recommendation=recommendation,
        graqle_tools=graqle_tools,
        external_tools=external_tools,
        confidence=round(best_confidence, 2),
        reasoning=reasoning,
    )
