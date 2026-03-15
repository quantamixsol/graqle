"""Natural language query router — zero-LLM-cost classification."""

# ── graqle:intelligence ──
# module: graqle.scanner.nl_router
# risk: LOW (impact radius: 1 modules)
# consumers: test_nl_router
# dependencies: __future__, re, dataclasses
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class RouteResult:
    """Result of routing a natural language query."""

    tool: str  # "context", "impact", "preflight", "lessons", "reason", "inspect"
    confidence: float  # 0.0 - 1.0
    query: str  # Original or rewritten query
    explanation: str  # Why this route was chosen


# Keyword patterns -> tool mapping
_ROUTE_PATTERNS: list[tuple[str, list[str], str]] = [
    # (tool_name, keyword_patterns, explanation)
    ("impact", [
        r"\bwhat\s+(?:happens|breaks|changes)\s+if\b",
        r"\bimpact\s+of\b",
        r"\baffected\s+by\b",
        r"\bwhat\s+depends\s+on\b",
        r"\bdependenc(?:y|ies)\s+(?:of|for)\b",
        r"\bwhat\s+uses\b",
        r"\bwhat\s+calls\b",
        r"\bwho\s+calls\b",
        r"\bis\s+it\s+safe\s+to\s+(?:change|modify|delete|remove|refactor)\b",
    ], "Impact analysis query"),
    ("preflight", [
        r"(?i)\bbefore\s+(?:I|we)\s+(?:change|modify|deploy|push|merge)\b",
        r"\bpreflight\b",
        r"\bsafety\s+check\b",
        r"\bpre-?change\b",
        r"\bready\s+to\s+deploy\b",
        r"\bcan\s+(?:i|we)\s+safely\b",
    ], "Pre-change safety check"),
    ("lessons", [
        r"\bwhat\s+went\s+wrong\b",
        r"\blast\s+time\b",
        r"\bpast\s+(?:mistakes?|errors?|issues?|bugs?|incidents?)\b",
        r"\blessons?\s+(?:from|learned|about)\b",
        r"\bhistory\s+of\s+(?:bug|error|issue|problem)\b",
        r"\bprevious(?:ly)?\s+(?:fail|broke|crash)\b",
    ], "Lessons learned query"),
    ("inspect", [
        r"\bstats?\b",
        r"\bstatistics\b",
        r"\bgraph\s+(?:size|info|summary|overview)\b",
        r"\bhow\s+(?:many|big|large)\b",
        r"\bnode\s+count\b",
        r"\bedge\s+count\b",
    ], "Graph inspection query"),
    ("context", [
        r"\bexplain\b",
        r"\bwhat\s+(?:is|does|are)\b",
        r"\bhow\s+does\b",
        r"\btell\s+me\s+about\b",
        r"\bshow\s+me\b",
        r"\bdescribe\b",
        r"\bwho\s+owns\b",
        r"\bwhere\s+is\b",
        r"\bfind\b",
        r"\bsearch\b",
        r"\blook\s+(?:up|for)\b",
    ], "Context/lookup query"),
]


def route_query(query: str) -> RouteResult:
    """Route a natural language query to the best tool.

    Uses keyword-based classification (zero LLM cost).
    Falls back to 'reason' for complex multi-hop questions.
    """
    q_lower = query.lower().strip()

    best_tool = "reason"
    best_confidence = 0.3  # default: fall back to reasoning
    best_explanation = "Complex query — using full reasoning"

    for tool, patterns, explanation in _ROUTE_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, q_lower):
                # Multiple pattern matches increase confidence
                match_count = sum(1 for p in patterns if re.search(p, q_lower))
                confidence = min(0.95, 0.7 + match_count * 0.1)

                if confidence > best_confidence:
                    best_tool = tool
                    best_confidence = confidence
                    best_explanation = explanation

    return RouteResult(
        tool=best_tool,
        confidence=best_confidence,
        query=query,
        explanation=best_explanation,
    )


def is_natural_language(text: str) -> bool:
    """Check if input looks like natural language vs a command/entity name."""
    # Contains spaces + has question words or verb patterns
    if " " not in text:
        return False
    words = text.split()
    if len(words) < 3:
        return False
    question_words = {"what", "how", "why", "who", "where", "when", "which", "is", "can", "does", "do", "should", "will", "would"}
    return words[0].lower() in question_words or text.endswith("?")
