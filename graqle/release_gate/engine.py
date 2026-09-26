"""Release Gate engine.

Composes a ReviewProvider (diff review) + PredictionProvider (risk prediction)
into a single ReleaseGateVerdict. Providers are injected so tests can use
fakes and production can wrap graq_review / graq_predict.

Error handling contract (non-leaky):
  - Provider exceptions, timeouts, None, or malformed payloads never crash.
  - They resolve to a fallback BLOCK verdict (CR-B: the gate fails CLOSED)
    with a caller-safe reason string that NEVER reveals internal thresholds,
    weights, or compose logic.
  - NaN / inf / non-string / None fields are normalized to neutral defaults.

Public-surface IP redaction:
  - The numeric default for min_confidence is a private module constant.
  - Public parameter type is `min_confidence: float | None = None`; callers
    must not be shown the default value in help text, action.yml, or docs.
  - risk_score / confidence / min_confidence are opaque floats in [0.0, 1.0].
    No compose formula, no internal threshold values, no weight names appear
    in user-facing strings.
"""
from __future__ import annotations

import asyncio
import logging
import math
from typing import Optional

from graqle.release_gate.models import (
    PredictionProvider,
    PredictionSummary,
    ReleaseGateVerdict,
    ReviewProvider,
    ReviewSummary,
    SUPPORTED_TARGETS,
    Verdict,
)

logger = logging.getLogger("graqle.release_gate.engine")


# ---------------------------------------------------------------------------
# Internal constants — IP-sensitive; never log, never surface in public strings.
# ---------------------------------------------------------------------------
_DEFAULT_MIN_CONFIDENCE = 0.92
_PROVIDER_TIMEOUT_SECONDS = 60
# Strictly greater-than comparison: `len(majors) >= _MAJORS_WARN_COUNT_THRESHOLD`
# means 3 or more majors trigger WARN (1 or 2 majors alone are not enough).
_MAJORS_WARN_COUNT_THRESHOLD = 3

# Per-target internal risk thresholds. These values are TRADE SECRETS and
# must not appear in any public string, log, docstring, or error message.
_INTERNAL_RISK_THRESHOLDS = {
    "pypi": 0.7,
    "vscode-marketplace": 0.65,
}


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class ReleaseGateEngine:
    """Gate composition engine. Inject providers; call gate().

    Parameters
    ----------
    review_provider:
        Async object implementing `review(diff, focus) -> ReviewSummary`.
    prediction_provider:
        Async object implementing `predict(diff, target) -> PredictionSummary`.
    """

    def __init__(
        self,
        review_provider: ReviewProvider,
        prediction_provider: PredictionProvider,
    ) -> None:
        self._review = review_provider
        self._predict = prediction_provider

    async def gate(
        self,
        diff: str,
        target: str,
        min_confidence: Optional[float] = None,
    ) -> ReleaseGateVerdict:
        """Run the full gate and return a ReleaseGateVerdict.

        Parameters
        ----------
        diff:
            Unified git diff text. Must be a non-empty string.
        target:
            One of the values in SUPPORTED_TARGETS.
        min_confidence:
            Optional override of the confidence requirement. `None` means
            "use the GraQle default" (value is not exposed publicly).

        Returns
        -------
        ReleaseGateVerdict — never raises; failure paths return BLOCK (CR-B: fail closed).
        """
        # ── Input validation (returns BLOCK fallback on bad input — never raises).
# CR-B: a gate that cannot parse its own input must not pass a release.
        # Normalize target FIRST so every subsequent fallback uses the same value.
        # If target is malformed, fall back to "pypi" and surface invalid_target once.
        effective_target = target if target in SUPPORTED_TARGETS else "pypi"
        if target not in SUPPORTED_TARGETS:
            return self._fallback_verdict(
                effective_target,
                reason="invalid_target",
                review_summary=f"target must be one of {sorted(SUPPORTED_TARGETS)}",
            )
        if not isinstance(diff, str) or not diff:
            return self._fallback_verdict(
                effective_target,
                reason="invalid_diff",
                review_summary="diff must be a non-empty string",
            )

        effective_confidence = _DEFAULT_MIN_CONFIDENCE
        if min_confidence is not None:
            # Reject booleans explicitly (bool is a subclass of int in Python,
            # so True/False would otherwise coerce to 1.0/0.0 silently).
            if isinstance(min_confidence, bool) or not isinstance(min_confidence, (int, float)):
                return self._fallback_verdict(
                    effective_target,
                    reason="invalid_min_confidence",
                    review_summary="min_confidence must be a number",
                )
            if not math.isfinite(min_confidence) or not (0.0 <= float(min_confidence) <= 1.0):
                return self._fallback_verdict(
                    effective_target,
                    reason="invalid_min_confidence",
                    review_summary="min_confidence must be in [0.0, 1.0]",
                )
            effective_confidence = float(min_confidence)

        # ── Invoke review provider with timeout + exception catch.
        # B4 (wave-1 hardening): pass `effective_target` (validated + normalized)
        # to every _fallback_verdict call, not raw `target`. If validation order
        # ever changes or a future refactor inserts work between normalization
        # and provider calls, this keeps fallback targets consistent.
        try:
            review_raw = await asyncio.wait_for(
                self._review.review(diff, focus="correctness"),
                timeout=_PROVIDER_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return self._fallback_verdict(effective_target, reason="review_timeout")
        except Exception as exc:  # pylint: disable=broad-except
            # Log the full exception (type, message, traceback) to the operator
            # log. Diagnosing a gate that fails needs the actual error: logging
            # only the class name is why the 0.84.0 failures were undiagnosable.
            # The verdict object stays redacted — see _fallback_verdict.
            logger.exception("release_gate review provider failed: %r", exc)
            return self._fallback_verdict(effective_target, reason="review_error")

        review = self._normalize_review(review_raw)

        # ── Invoke prediction provider with timeout + exception catch.
        # B4-extended (post-round-2 review): pass effective_target to the
        # prediction call itself, not just the fallback branches, so both
        # providers see the same normalized target.
        try:
            prediction_raw = await asyncio.wait_for(
                self._predict.predict(diff, effective_target),
                timeout=_PROVIDER_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return self._fallback_verdict(effective_target, reason="prediction_timeout")
        except Exception as exc:  # pylint: disable=broad-except
            # Full exception to the operator log; the verdict stays redacted.
            logger.exception("release_gate prediction provider failed: %r", exc)
            return self._fallback_verdict(effective_target, reason="prediction_error")

        prediction = self._normalize_prediction(prediction_raw)

        # ── Compose verdict. Order matters: BLOCK conditions checked first.
        # B3 (wave-1 hardening): defensive .get() instead of direct indexing.
        # target is validated above, but if _INTERNAL_RISK_THRESHOLDS gets
        # out of sync with SUPPORTED_TARGETS in a future refactor, direct
        # indexing raises KeyError and violates the never-crash contract.
        # Fail-open to the safer default threshold and log — better than a
        # server-side exception leaking to the user.
        risk_threshold = _INTERNAL_RISK_THRESHOLDS.get(effective_target)
        if risk_threshold is None:
            logger.error(
                "release_gate invariant drift: target %r validated but "
                "missing from _INTERNAL_RISK_THRESHOLDS. Falling back to "
                "default threshold; fix the constants map.",
                effective_target,
            )
            # Use the pypi threshold as the safest fallback — it's the
            # strictest and matches the most common release surface.
            risk_threshold = _INTERNAL_RISK_THRESHOLDS.get("pypi", 0.7)

        if review.blockers:
            verdict = Verdict.BLOCK
        elif prediction.confidence < effective_confidence:
            verdict = Verdict.BLOCK
        elif prediction.risk_score >= risk_threshold:
            verdict = Verdict.BLOCK
        elif len(review.majors) >= _MAJORS_WARN_COUNT_THRESHOLD:
            verdict = Verdict.WARN
        else:
            verdict = Verdict.CLEAR

        return ReleaseGateVerdict(
            verdict=verdict,
            target=target,
            blockers=review.blockers,
            majors=review.majors,
            minors=review.minors,
            risk_score=prediction.risk_score,
            confidence=prediction.confidence,
            review_summary=review.summary,
            prediction_reasons=prediction.reasons,
        )

    # ── normalization helpers ────────────────────────────────────────────

    @staticmethod
    def _coerce_str_tuple(value) -> tuple:
        """Normalize an iterable to tuple of non-empty strings.

        Only genuine strings are accepted — non-string items (dicts, ints,
        custom objects) are dropped to avoid polluting blockers/majors/minors
        with misleading stringified representations.
        """
        if value is None:
            return ()
        if isinstance(value, str):
            return (value,) if value else ()
        try:
            return tuple(v for v in value if isinstance(v, str) and v)
        except TypeError:
            return ()

    @staticmethod
    def _coerce_finite_float(value, default: float = 0.0) -> float:
        """Normalize a value to a finite float in [0.0, 1.0]; fallback = default."""
        if value is None:
            return default
        try:
            f = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(f):
            return default
        if f < 0.0:
            return 0.0
        if f > 1.0:
            return 1.0
        return f

    def _normalize_review(self, raw) -> ReviewSummary:
        """Defensively coerce a provider-returned review into ReviewSummary."""
        if raw is None:
            return ReviewSummary()
        blockers = self._coerce_str_tuple(getattr(raw, "blockers", None))
        majors = self._coerce_str_tuple(getattr(raw, "majors", None))
        minors = self._coerce_str_tuple(getattr(raw, "minors", None))
        summary_raw = getattr(raw, "summary", "")
        summary = summary_raw if isinstance(summary_raw, str) else ""
        return ReviewSummary(
            blockers=blockers,
            majors=majors,
            minors=minors,
            summary=summary,
        )

    def _normalize_prediction(self, raw) -> PredictionSummary:
        """Defensively coerce a provider-returned prediction into PredictionSummary."""
        if raw is None:
            return PredictionSummary(risk_score=0.5, confidence=0.0, reasons=())
        risk = self._coerce_finite_float(getattr(raw, "risk_score", None), default=0.5)
        conf = self._coerce_finite_float(getattr(raw, "confidence", None), default=0.0)
        reasons = self._coerce_str_tuple(getattr(raw, "reasons", None))
        return PredictionSummary(risk_score=risk, confidence=conf, reasons=reasons)

    # ── fallback verdict ─────────────────────────────────────────────────

    @staticmethod
    def _fallback_verdict(
        target: str,
        reason: str,
        review_summary: str = "internal governance error",
    ) -> ReleaseGateVerdict:
        """Return a BLOCK verdict on provider failure or bad input.

        CR-B (Research Team ruling): the gate FAILS CLOSED. A provider timeout
        and an internal error both block. A gate that returns WARN when it
        could not evaluate is not a gate -- it reports low confidence and lets
        the release through, which is the failure mode this exists to prevent.

        Both halves of the ruling are satisfied without a context flag here,
        because BLOCK is mapped differently by target at the consumer:

          * publish targets run `graq release-gate` and exit 1 on BLOCK, so
            the publish is stopped uniformly across every target;
          * pull requests get a red report -- the same BLOCK verdict rendered
            as a failing check, which informs without gating a merge.

        The engine keeps its never-crash and no-leak contract unchanged: it
        still never raises, and `reason` is a short machine-readable tag
        (e.g. "review_timeout") that never contains internal threshold values,
        weights, or compose logic.

        An override exists at the workflow level: role-gated, requiring a
        written justification, and written to the audit trail BEFORE anything
        publishes. It is deliberately not a parameter of this function -- an
        engine that can be asked to not-block is not fail-closed.
        """
        safe_target = target if target in SUPPORTED_TARGETS else "pypi"
        return ReleaseGateVerdict(
            verdict=Verdict.BLOCK,
            target=safe_target,
            blockers=(),
            majors=(),
            minors=(),
            risk_score=0.5,
            confidence=0.0,
            review_summary=review_summary,
            prediction_reasons=(reason,),
        )
