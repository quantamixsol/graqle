"""EU AI Act Article 14 human-oversight gate — CG-MKT-01.

Per Article 14(4)(c) + 14(4)(d) of Regulation (EU) 2024/1689, deployers of
high-risk AI systems must ensure that natural persons retain meaningful
oversight over decisions the system takes — including a documented refusal
path when the system's confidence in a proposed action falls below an
operator-set threshold.

This module implements the **runtime enforcement** of that obligation for
GraQle's automated write paths:

    - ``graq edit`` / ``graq_edit`` (MCP)
    - ``graq apply`` / ``graq_apply`` (MCP)
    - ``graq auto`` / ``graq_auto`` (MCP — autonomous loop)

When ALL of the following hold, the auto-apply path REFUSES with a typed
``ARTICLE_14_HUMAN_REVIEW_REQUIRED`` error:

    1. The ``--human-review-required`` flag is set (CLI flag /
       ``human_review_required=True`` arg on the MCP tool) **OR** the
       environment variable ``GRAQLE_EU_AI_ACT_MODE`` is on (in which
       case the gate is always armed for ``graq auto``).
    2. The generation confidence is below the configured threshold
       (default 0.75 — **placeholder pending R25-EU-CALIB-01 calibration
       spike**; the threshold is configurable via
       :class:`graqle.config.settings.GovernanceConfig.human_review_required_threshold`).

The refusal carries structured fields per ADR-205 / R25-EU01 §
"Article 14 enforcement":

    - ``error_code``: ``"ARTICLE_14_HUMAN_REVIEW_REQUIRED"``
    - ``reason``: short human-readable reason
    - ``article_14_clauses``: ``["14(4)(c)", "14(4)(d)"]``
    - ``confidence``: the actual generation confidence
    - ``threshold``: the configured threshold
    - ``threshold_status``: ``"placeholder"`` | ``"calibrated"`` (always
      ``"placeholder"`` until R25-EU-CALIB-01 lands)
    - ``next_action``: ``"present_diff_to_human_reviewer"``

This module has **no internal trade-secret references** (TS-1..TS-4) — it
only consumes the public ``confidence`` float emitted by graq_generate /
graq_reason and compares it against a public threshold.

References:
    - Regulation (EU) 2024/1689 Article 14(4)(c) and 14(4)(d)
    - R25-EU01 § "Article 14 enforcement seam"
    - CG-MKT-01 in OPEN-TRACKER-CAPABILITY-GAPS.md
    - ADR-205 (binding research-team decision on Article 14 surfacing)
    - Companion module: :mod:`graqle.compliance.claim_limits`
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any

# Default threshold per ADR-205 §3 — PLACEHOLDER pending R25-EU-CALIB-01.
# Calibrated value will replace this in PR-010c-1 fast follow-on once the
# Research-Team-owned calibration spike completes. Until then, code that
# reads this constant MUST also surface ``threshold_status="placeholder"``
# so auditors know the value is not yet evidence-derived.
DEFAULT_HUMAN_REVIEW_THRESHOLD: float = 0.75

#: Article 14 clauses that the gate maps to in the refusal envelope.
ARTICLE_14_CLAUSES: tuple[str, ...] = ("14(4)(c)", "14(4)(d)")

#: Marker string surfaced in the refusal envelope so auditors / downstream
#: claim-status pipelines can tell at a glance whether the threshold is
#: evidence-derived (calibrated) or interim (placeholder).
THRESHOLD_STATUS_PLACEHOLDER: str = "placeholder"
THRESHOLD_STATUS_CALIBRATED: str = "calibrated"


# ---------------------------------------------------------------------------
# Gate result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Article14GateResult:
    """Outcome of the Article 14 oversight gate check.

    Attributes:
        allowed: True iff the auto-apply path may proceed without human
            review.
        confidence: The generation confidence the gate evaluated.
        threshold: The threshold the gate compared against.
        threshold_status: Always
            :data:`THRESHOLD_STATUS_PLACEHOLDER` until R25-EU-CALIB-01
            lands a calibrated value.
        reason: Short human-readable reason. Empty when ``allowed`` is
            True.
    """

    allowed: bool
    confidence: float
    threshold: float
    threshold_status: str = THRESHOLD_STATUS_PLACEHOLDER
    reason: str = ""

    def to_refusal_envelope(self) -> dict[str, Any]:
        """Build the structured refusal envelope for the MCP response.

        Callers should embed the result of this method as the JSON body of
        their tool response when ``allowed`` is False. Raises
        ``RuntimeError`` if called on an ``allowed=True`` result — that
        path has no refusal to envelope.
        """
        if self.allowed:
            raise RuntimeError(
                "to_refusal_envelope() called on an allowed gate result; "
                "the caller should check `.allowed` before envelope build."
            )
        return {
            "success": False,
            "error_code": "ARTICLE_14_HUMAN_REVIEW_REQUIRED",
            "error": self.reason,
            "article_14_clauses": list(ARTICLE_14_CLAUSES),
            "confidence": round(float(self.confidence), 4),
            "threshold": round(float(self.threshold), 4),
            "threshold_status": self.threshold_status,
            "next_action": "present_diff_to_human_reviewer",
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    """Best-effort bool coercion accepting ``True``, ``"true"``, ``"on"``.

    Mirrors the existing ``_coerce_bool`` helper in ``mcp_dev_server`` so
    the gate can be called with the same arg shape the MCP tool callers
    pass. Used by :func:`_is_eu_ai_act_mode_on` to share the truthy
    allowlist (sentinel-pass-1 MINOR: deduplicated string normalisation).
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _is_eu_ai_act_mode_on() -> bool:
    """Return True iff ``GRAQLE_EU_AI_ACT_MODE`` is set to a truthy value.

    Duplicated from :mod:`graqle.compliance.disclosure` to keep this
    module zero-dependency on the disclosure tree. Per sentinel pass 1
    MINOR finding, the truthy allowlist is shared with
    :func:`_coerce_bool` — both delegate to the same set
    ``{on, true, 1, yes}`` case-insensitive.
    """
    raw = os.environ.get("GRAQLE_EU_AI_ACT_MODE", "")
    return _coerce_bool(raw)


def _validate_confidence(confidence: Any) -> float:
    """Validate + coerce a confidence value to a finite float in [0.0, 1.0].

    Per sentinel pass 1 MAJOR-2 finding, the gate must reject NaN,
    +/-inf, negative, and >1 values explicitly rather than silently
    comparing them against the threshold (which would produce
    surprising allows/refuses depending on how Python compares NaN).

    Args:
        confidence: Candidate confidence value.

    Returns:
        float: The validated finite confidence value.

    Raises:
        ValueError: If the value is NaN, +/-inf, or not in [0.0, 1.0].
        TypeError: If the value cannot be coerced to float.
    """
    try:
        c = float(confidence)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"Article 14 gate: confidence must be a real number, got "
            f"{type(confidence).__name__} ({confidence!r})"
        ) from exc
    if math.isnan(c) or math.isinf(c):
        raise ValueError(
            f"Article 14 gate: confidence must be a finite number, got {c!r}"
        )
    if c < 0.0 or c > 1.0:
        raise ValueError(
            f"Article 14 gate: confidence must be in [0.0, 1.0], got {c!r}"
        )
    return c


def _validate_threshold(threshold: Any) -> float:
    """Validate + coerce a threshold value to a finite float in [0.0, 1.0]."""
    try:
        t = float(threshold)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"Article 14 gate: threshold must be a real number, got "
            f"{type(threshold).__name__} ({threshold!r})"
        ) from exc
    if math.isnan(t) or math.isinf(t):
        raise ValueError(
            f"Article 14 gate: threshold must be a finite number, got {t!r}"
        )
    if t < 0.0 or t > 1.0:
        raise ValueError(
            f"Article 14 gate: threshold must be in [0.0, 1.0], got {t!r}"
        )
    return t


# ---------------------------------------------------------------------------
# Public gate entry point
# ---------------------------------------------------------------------------


def check_article_14_human_review(
    *,
    confidence: float,
    human_review_required: Any = None,
    threshold: float | None = None,
    threshold_status: str = THRESHOLD_STATUS_PLACEHOLDER,
    action_label: str = "edit",
) -> Article14GateResult:
    """Evaluate the Article 14 oversight gate.

    The gate is ARMED when EITHER:

        - ``human_review_required`` is truthy (per ``_coerce_bool``), OR
        - ``GRAQLE_EU_AI_ACT_MODE`` env var is on.

    When ARMED and ``confidence < threshold``, the gate REFUSES — the
    returned ``Article14GateResult`` has ``allowed=False`` and the caller
    must return :meth:`Article14GateResult.to_refusal_envelope` as the
    tool response.

    When DISARMED, or ARMED-but-above-threshold, the gate allows the
    operation. A disarmed gate is the zero-cost path: no env-var
    inspection beyond the one check, no envelope construction.

    Args:
        confidence: The generation / reasoning confidence in [0.0, 1.0].
            Values outside that range are clamped at the boundaries for
            comparison only; the raw value is preserved in the result.
        human_review_required: Per-call override. Truthy values force the
            gate ARMED regardless of env-var state. ``None``, ``False``,
            and empty strings leave the env-var to decide.
        threshold: Optional override for the comparison threshold. When
            ``None``, uses :data:`DEFAULT_HUMAN_REVIEW_THRESHOLD` (0.75).
            **Operators should never override this in production until
            R25-EU-CALIB-01 ships a calibrated value** — surface the
            ``threshold_status`` field so reviewers see the gate state.
        threshold_status: Marker for whether the threshold is calibrated
            or placeholder. Defaults to
            :data:`THRESHOLD_STATUS_PLACEHOLDER`.
        action_label: Short label (``"edit"``, ``"apply"``, ``"auto"``)
            used in the refusal reason string.

    Returns:
        Article14GateResult: ``allowed=True`` if the gate is disarmed or
        confidence meets the threshold; otherwise ``allowed=False`` with
        a populated ``reason``.
    """
    # Sentinel pass 1 MAJOR-2: validate confidence + threshold explicitly
    # before any comparison. NaN/inf/out-of-range values raise rather
    # than producing surprising allows/refuses.
    eff_confidence = _validate_confidence(confidence)
    eff_threshold = (
        _validate_threshold(threshold)
        if threshold is not None
        else DEFAULT_HUMAN_REVIEW_THRESHOLD
    )
    armed = _coerce_bool(human_review_required) or _is_eu_ai_act_mode_on()
    if not armed:
        return Article14GateResult(
            allowed=True,
            confidence=eff_confidence,
            threshold=eff_threshold,
            threshold_status=threshold_status,
        )

    # Comparison: a confidence at exactly the threshold ALLOWS — refusal
    # only fires strictly below the threshold. This makes operator
    # configuration intuitive: "set threshold=0.75 → 0.749 refused,
    # 0.75 allowed".
    if eff_confidence < eff_threshold:
        return Article14GateResult(
            allowed=False,
            confidence=eff_confidence,
            threshold=eff_threshold,
            threshold_status=threshold_status,
            reason=(
                f"Article 14(4)(c)+(d) human-review gate refused "
                f"{action_label!s}: confidence "
                f"{round(eff_confidence, 4)} is below threshold "
                f"{round(eff_threshold, 4)} (status: {threshold_status}). "
                f"Present the proposed change to a human reviewer before "
                f"applying."
            ),
        )
    return Article14GateResult(
        allowed=True,
        confidence=eff_confidence,
        threshold=eff_threshold,
        threshold_status=threshold_status,
    )
