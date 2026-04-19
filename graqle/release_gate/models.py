"""Release Gate data models + provider protocols (injection pattern).

Protocols mirror R18 GovernedTrace's injection shape: the engine does not
import graq_review/graq_predict directly, it receives a ReviewProvider +
PredictionProvider at construction so tests can wire fakes without any
LLM calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol, Tuple


SUPPORTED_TARGETS = frozenset({"pypi", "vscode-marketplace"})


class Verdict(str, Enum):
    """Release Gate verdict. BLOCK halts, WARN advises, CLEAR passes."""
    CLEAR = "CLEAR"
    WARN = "WARN"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class ReviewSummary:
    """Output of graq_review (correctness focus), normalized.

    Every field is safe to surface on a public interface.
    """
    blockers: Tuple[str, ...] = ()
    majors: Tuple[str, ...] = ()
    minors: Tuple[str, ...] = ()
    summary: str = ""


@dataclass(frozen=True)
class PredictionSummary:
    """Output of graq_predict, normalized.

    risk_score and confidence are opaque floats in [0.0, 1.0]. Their
    internal derivation is not exposed; only the values themselves.
    """
    risk_score: float = 0.0
    confidence: float = 0.0
    reasons: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ReleaseGateVerdict:
    """Final gate outcome. Frozen; serializable via asdict()."""
    verdict: Verdict
    target: str
    blockers: Tuple[str, ...]
    majors: Tuple[str, ...]
    minors: Tuple[str, ...]
    risk_score: float
    confidence: float
    review_summary: str
    prediction_reasons: Tuple[str, ...]
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict (Enum→str, tuple→list, datetime→ISO)."""
        return {
            "verdict": self.verdict.value,
            "target": self.target,
            "blockers": list(self.blockers),
            "majors": list(self.majors),
            "minors": list(self.minors),
            "risk_score": self.risk_score,
            "confidence": self.confidence,
            "review_summary": self.review_summary,
            "prediction_reasons": list(self.prediction_reasons),
            "timestamp": self.timestamp.isoformat(),
        }


class ReviewProvider(Protocol):
    """Provides a diff review. Concrete implementations wrap graq_review."""
    async def review(self, diff: str, focus: str = "correctness") -> ReviewSummary: ...


class PredictionProvider(Protocol):
    """Provides a risk prediction. Concrete implementations wrap graq_predict."""
    async def predict(self, diff: str, target: str) -> PredictionSummary: ...
