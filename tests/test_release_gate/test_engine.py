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

def test_gate_blocks_on_empty_diff():
    eng = _engine()
    result = asyncio.run(eng.gate("", "pypi"))
    assert result.verdict is Verdict.BLOCK
    assert "invalid_diff" in result.prediction_reasons


# ── 8. WARN on non-string diff ────────────────────────────────────────────

def test_gate_blocks_on_non_string_diff():
    eng = _engine()
    result = asyncio.run(eng.gate(None, "pypi"))  # type: ignore[arg-type]
    assert result.verdict is Verdict.BLOCK
    assert "invalid_diff" in result.prediction_reasons


# ── 9. WARN on invalid target ─────────────────────────────────────────────

def test_gate_blocks_on_invalid_target():
    eng = _engine()
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "npm"))
    assert result.verdict is Verdict.BLOCK
    assert "invalid_target" in result.prediction_reasons


# ── 10. WARN on invalid min_confidence ────────────────────────────────────

def test_gate_blocks_on_invalid_min_confidence():
    eng = _engine()
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi", min_confidence=2.0))
    assert result.verdict is Verdict.BLOCK
    assert "invalid_min_confidence" in result.prediction_reasons

    result2 = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi", min_confidence=float("nan")))
    assert result2.verdict is Verdict.BLOCK


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


# ── 15. Review provider exception → BLOCK (CR-B: fail closed) ─────────────────────────────────

def test_gate_handles_review_provider_exception():
    eng = _engine(
        review=FakeReviewProvider(raise_exc=RuntimeError("provider down")),
    )
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi"))
    assert result.verdict is Verdict.BLOCK
    assert "review_error" in result.prediction_reasons


def test_provider_exception_text_reaches_the_operator_log(caplog):
    """The real error must be diagnosable from the log, never from the verdict.

    Regression for the 0.84.0/0.84.1 release-gate failures: the handler logged
    only ``type(exc).__name__``, so every CI failure read as a bare class name
    with no message and no traceback, and the cause stayed unknown across
    multiple releases.

    The two surfaces have opposite requirements and both are asserted here:
    the operator log carries the full exception, while the verdict object stays
    redacted because it is user-facing (see the module's IP-redaction contract).
    """
    import logging

    eng = _engine(
        review=FakeReviewProvider(raise_exc=RuntimeError("upstream 503 from review api")),
    )
    with caplog.at_level(logging.ERROR, logger="graqle.release_gate.engine"):
        result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi"))

    logged = caplog.text
    assert "upstream 503 from review api" in logged, (
        "the exception message must reach the operator log — logging only the "
        "exception class is what made the 0.84.0 failures undiagnosable"
    )
    assert "RuntimeError" in logged
    assert "Traceback" in logged, "logger.exception must attach the traceback"

    # ...and must NOT appear anywhere in the caller-visible verdict.
    blob = json.dumps(result.to_dict())
    assert "upstream 503" not in blob
    assert "RuntimeError" not in blob


# ── CR-B: the fail-closed contract itself ────────────────────────────────

def test_every_unevaluatable_path_blocks_never_warns():
    """CR-B (Research ruling): a gate that could not evaluate must BLOCK.

    The defect this pins: the fallback returned WARN at confidence 0.0 with
    zero findings, so an internal crash read as "low confidence, proceed" and
    the release went out ungated. `Release Gate (PyPI)` was red on every PR
    for exactly this reason and blocked nothing.

    A timeout and an internal error are treated identically -- neither is
    evidence the release is safe, only that the gate could not say.

    Asserted over EVERY fallback entry point at once, so adding a new failure
    path that returns WARN fails here rather than silently reopening the gate.
    """
    # Exceptions.
    for reason, eng in {
        "review_error": _engine(review=FakeReviewProvider(raise_exc=RuntimeError("x"))),
        "prediction_error": _engine(predict=FakePredictionProvider(raise_exc=RuntimeError("x"))),
    }.items():
        result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi"))
        assert result.verdict is Verdict.BLOCK, (
            f"{reason} returned {result.verdict}; the gate must fail CLOSED"
        )
        assert reason in result.prediction_reasons

    # Timeouts. The real timeout is 60s, so it is shortened here rather than
    # slept through -- the assertion is about the VERDICT, not the duration.
    import graqle.release_gate.engine as _eng_mod

    original = _eng_mod._PROVIDER_TIMEOUT_SECONDS
    try:
        _eng_mod._PROVIDER_TIMEOUT_SECONDS = 0.01
        for reason, eng in {
            "review_timeout": _engine(review=FakeReviewProvider(sleep=0.2)),
            "prediction_timeout": _engine(predict=FakePredictionProvider(sleep=0.2)),
        }.items():
            result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi"))
            assert result.verdict is Verdict.BLOCK, (
                f"{reason} returned {result.verdict}; the gate must fail CLOSED"
            )
            assert reason in result.prediction_reasons
    finally:
        _eng_mod._PROVIDER_TIMEOUT_SECONDS = original

    # Bad input is equally unevaluatable: a gate that cannot parse its own
    # input has no basis to pass a release.
    eng = _engine()
    for bad in (
        lambda: eng.gate(SAMPLE_DIFF, "not-a-target"),
        lambda: eng.gate("", "pypi"),
        lambda: eng.gate(SAMPLE_DIFF, "pypi", min_confidence=2.0),
    ):
        assert asyncio.run(bad()).verdict is Verdict.BLOCK


def test_block_still_leaks_nothing(caplog):
    """Failing closed must not become an excuse to leak internals."""
    eng = _engine(review=FakeReviewProvider(raise_exc=RuntimeError("secret-internal-detail")))
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi"))
    assert result.verdict is Verdict.BLOCK
    blob = json.dumps(result.to_dict())
    assert "secret-internal-detail" not in blob
    assert "RuntimeError" not in blob


# ── 16. Prediction provider exception → BLOCK (CR-B: fail closed) ─────────────────────────────

def test_gate_handles_prediction_provider_exception():
    eng = _engine(
        predict=FakePredictionProvider(raise_exc=ValueError("predict fail")),
    )
    result = asyncio.run(eng.gate(SAMPLE_DIFF, "pypi"))
    assert result.verdict is Verdict.BLOCK
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
    assert result.verdict is Verdict.BLOCK
    d = result.to_dict()
    j = json.dumps(d)
    assert "review_error" in j
    # Fallback must NEVER leak the exception message (IP safety)
    assert "io" not in d["review_summary"]
