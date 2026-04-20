"""G2 — ReleaseGateEngine tests (injection pattern; no real LLM calls)."""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from graqle.release_gate import (
    PredictionSummary,
    ReleaseGateEngine,
    ReleaseGateVerdict,
    ReviewSummary,
    Verdict,
)


# ── fake providers ────────────────────────────────────────────────────────

class FakeReviewProvider:
    def __init__(self, summary: ReviewSummary | None = None, raise_exc: Exception | None = None,
                 sleep: float = 0.0, returns=None):
        self._summary = summary
        self._raise = raise_exc
        self._sleep = sleep
        self._returns = returns  # allow returning arbitrary object to test normalization

    async def review(self, diff: str, focus: str = "correctness"):
        if self._sleep:
            await asyncio.sleep(self._sleep)
        if self._raise:
            raise self._raise
        if self._returns is not None:
            return self._returns
        return self._summary if self._summary is not None else ReviewSummary()


class FakePredictionProvider:
    def __init__(self, summary: PredictionSummary | None = None, raise_exc: Exception | None = None,
                 sleep: float = 0.0, returns=None):
        self._summary = summary
        self._raise = raise_exc
        self._sleep = sleep
        self._returns = returns

    async def predict(self, diff: str, target: str):
        if self._sleep:
            await asyncio.sleep(self._sleep)
        if self._raise:
            raise self._raise
        if self._returns is not None:
            return self._returns
        return self._summary if self._summary is not None else PredictionSummary(
            risk_score=0.1, confidence=0.95,
        )


def _engine(review: FakeReviewProvider | None = None, predict: FakePredictionProvider | None = None):
    return ReleaseGateEngine(
        review_provider=review or FakeReviewProvider(),
        prediction_provider=predict or FakePredictionProvider(),
    )


SAMPLE_DIFF = "diff --git a/foo.py b/foo.py\n+print('hello')\n"


# ── 1. CLEAR on clean diff ────────────────────────────────────────────────

def test_gate_clear_on_clean_diff():
    eng = _engine(
        FakeReviewProvider(ReviewSummary(summary="looks fine")),
        FakePredictionProvider(PredictionSummary(risk_score=0.1, confidence=0.95)),
    )
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi"))
    assert result.verdict is Verdict.CLEAR
    assert result.target == "pypi"
    assert result.blockers == ()


# ── 2. BLOCK on blockers ──────────────────────────────────────────────────

def test_gate_blocks_on_blockers():
    eng = _engine(
        FakeReviewProvider(ReviewSummary(
            blockers=("unsafe delete", "undefined symbol"),
            summary="has blockers",
        )),
        FakePredictionProvider(PredictionSummary(risk_score=0.1, confidence=0.99)),
    )
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi"))
    assert result.verdict is Verdict.BLOCK
    assert len(result.blockers) == 2


# ── 3. BLOCK on low confidence ────────────────────────────────────────────

def test_gate_blocks_on_low_confidence():
    eng = _engine(
        FakeReviewProvider(ReviewSummary(summary="ok")),
        FakePredictionProvider(PredictionSummary(risk_score=0.1, confidence=0.5)),
    )
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi"))
    assert result.verdict is Verdict.BLOCK


# ── 4. BLOCK on high risk score ───────────────────────────────────────────

def test_gate_blocks_on_high_risk_score():
    eng = _engine(
        FakeReviewProvider(ReviewSummary(summary="ok")),
        FakePredictionProvider(PredictionSummary(risk_score=0.95, confidence=0.99)),
    )
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi"))
    assert result.verdict is Verdict.BLOCK


# ── 5. WARN on many majors ────────────────────────────────────────────────

def test_gate_warn_on_many_majors():
    eng = _engine(
        FakeReviewProvider(ReviewSummary(
            majors=("a", "b", "c", "d"),
            summary="many concerns",
        )),
        FakePredictionProvider(PredictionSummary(risk_score=0.1, confidence=0.99)),
    )
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi"))
    assert result.verdict is Verdict.WARN


# ── 6. CLEAR with single major (below count threshold) ───────────────────

def test_gate_clear_with_single_major():
    eng = _engine(
        FakeReviewProvider(ReviewSummary(majors=("one",), summary="one concern")),
        FakePredictionProvider(PredictionSummary(risk_score=0.1, confidence=0.99)),
    )
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi"))
    assert result.verdict is Verdict.CLEAR


# ── 7. WARN on empty diff input ───────────────────────────────────────────

def test_gate_warn_on_empty_diff():
    eng = _engine()
    result = asyncio.run(eng.gate("", "pypi"))
    assert result.verdict is Verdict.WARN
    assert "invalid_diff" in result.prediction_reasons


# ── 8. WARN on non-string diff ────────────────────────────────────────────

def test_gate_warn_on_non_string_diff():
    eng = _engine()
    result = asyncio.run(eng.gate(None, "pypi"))  # type: ignore[arg-type]
    assert result.verdict is Verdict.WARN
    assert "invalid_diff" in result.prediction_reasons


# ── 9. WARN on invalid target ─────────────────────────────────────────────

def test_gate_warn_on_invalid_target():
    eng = _engine()
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "npm"))
    assert result.verdict is Verdict.WARN
    assert "invalid_target" in result.prediction_reasons


# ── 10. WARN on invalid min_confidence ────────────────────────────────────

def test_gate_warn_on_invalid_min_confidence():
    eng = _engine()
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi", min_confidence=2.0))
    assert result.verdict is Verdict.WARN
    assert "invalid_min_confidence" in result.prediction_reasons

    result2 = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi", min_confidence=float("nan")))
    assert result2.verdict is Verdict.WARN


# ── 11. Verdict dataclass is frozen ───────────────────────────────────────

def test_gate_verdict_is_frozen():
    eng = _engine()
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi"))
    with pytest.raises((AttributeError, Exception)):
        result.verdict = Verdict.BLOCK  # type: ignore[misc]


# ── 12. Verdict serializes to JSON ────────────────────────────────────────

def test_gate_verdict_serializes_to_json():
    eng = _engine()
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi"))
    d = result.to_dict()
    j = json.dumps(d)
    loaded = json.loads(j)
    assert loaded["verdict"] in ("CLEAR", "WARN", "BLOCK")
    assert loaded["target"] == "pypi"


# ── 13. pypi target accepted ──────────────────────────────────────────────

def test_gate_target_pypi():
    eng = _engine()
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi"))
    assert result.target == "pypi"


# ── 14. vscode-marketplace target accepted ────────────────────────────────

def test_gate_target_vscode_marketplace():
    eng = _engine()
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "vscode-marketplace"))
    assert result.target == "vscode-marketplace"


# ── 15. Review provider exception → WARN ─────────────────────────────────

def test_gate_handles_review_provider_exception():
    eng = _engine(
        review=FakeReviewProvider(raise_exc=RuntimeError("provider down")),
    )
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi"))
    assert result.verdict is Verdict.WARN
    assert "review_error" in result.prediction_reasons


# ── 16. Prediction provider exception → WARN ─────────────────────────────

def test_gate_handles_prediction_provider_exception():
    eng = _engine(
        predict=FakePredictionProvider(raise_exc=ValueError("predict fail")),
    )
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi"))
    assert result.verdict is Verdict.WARN
    assert "prediction_error" in result.prediction_reasons


# ── 17. Malformed review summary (arbitrary object) → normalized ─────────

def test_gate_handles_malformed_review_summary():
    # Provider returns a random object lacking required fields
    class Weird: pass
    eng = _engine(review=FakeReviewProvider(returns=Weird()))
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi"))
    # Normalized to empty — no blockers, so not BLOCK from blockers
    # With default prediction (confidence=0.95, risk=0.1) → CLEAR
    assert result.verdict is Verdict.CLEAR


# ── 18. NaN / inf risk_score normalized ──────────────────────────────────

def test_gate_handles_nan_risk_score():
    eng = _engine(
        predict=FakePredictionProvider(
            PredictionSummary(risk_score=float("nan"), confidence=0.99),
        ),
    )
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi"))
    # NaN normalizes to default 0.5 (below pypi threshold 0.7) → CLEAR
    assert result.verdict is Verdict.CLEAR
    assert math.isfinite(result.risk_score)


# ── 19. None prediction fields → normalized ──────────────────────────────

def test_gate_handles_none_prediction():
    class NonePred:
        risk_score = None
        confidence = None
        reasons = None
    eng = _engine(predict=FakePredictionProvider(returns=NonePred()))
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi"))
    # None confidence (=0.0) < default min_confidence (0.92) → BLOCK
    assert result.verdict is Verdict.BLOCK
    assert math.isfinite(result.confidence)
    assert math.isfinite(result.risk_score)


# ── 20. Fallback WARN serializes safely ──────────────────────────────────

def test_gate_fallback_verdict_serializes_safely():
    eng = _engine(review=FakeReviewProvider(raise_exc=OSError("io")))
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi"))
    assert result.verdict is Verdict.WARN
    d = result.to_dict()
    j = json.dumps(d)
    assert "review_error" in j
    # Fallback must NEVER leak the exception message (IP safety)
    assert "io" not in d["review_summary"]
