"""Management-review-control gate — SOX/COSO vocabulary (CR-010.R3).

The EU AI Act calls it *human oversight* (Article 14). SOX calls it a
*management review control*. The mechanics are the same: before an
automated outcome is relied upon, a competent human must look at it, and
the fact that they looked must be evidenced.

This module is the SOX-vocabulary counterpart of
:mod:`graqle.compliance.article_14_gate`. It exists as a **sibling module
rather than a modification** of that one, deliberately:

``article_14_gate`` is a live EU AI Act enforcement path with four
production consumers pinning its contract — ``mcp_dev_server.py`` at three
sites (two of which hardcode the string ``"ARTICLE_14_HUMAN_REVIEW_REQUIRED"``)
and ``switch_status.py``, which republishes the default threshold and the
refusal error code into a public status envelope. Renaming its fields or
generalising its error code to cover SOX would be a silent breaking change
across those consumers for no functional gain. So the Article 14 surface is
left byte-for-byte alone and the shared *logic* is reused by import.

What is shared vs. what differs
-------------------------------
Shared, by import (not by copy): confidence/threshold validation, the
placeholder-vs-calibrated threshold markers, and the comparison rule that
a confidence **exactly at** the threshold ALLOWS — refusal fires only
strictly below it.

Different: the error code (``MANAGEMENT_REVIEW_REQUIRED``), the vocabulary
in the reason string, the arming signal (an explicit argument rather than
``GRAQLE_EU_AI_ACT_MODE``, because SOX applicability is a property of the
*control*, not of a global deployment mode), and the ability to name the
control the refusal belongs to.

Threshold calibration
---------------------
Like the Article 14 gate, this gate's default threshold is a **placeholder**
and says so in every result via ``threshold_status``. Wiring the existing
calibration subsystem into both gates is deliberately out of scope for this
CR (see CR-010.R3 § 4.4): it changes behaviour on a live enforcement path
and belongs in its own reviewable slice.

References:
    - CR-010.R3 § 4.3 — additive generalisation
    - Sarbanes-Oxley Act § 404; COSO Internal Control — Integrated Framework
    - Companion: :mod:`graqle.compliance.article_14_gate`
    - Companion: :mod:`graqle.pct.extensions.x_sox`
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from graqle.compliance._gate_helpers import (
    coerce_arming_flag,
    validate_confidence,
    validate_threshold,
)
from graqle.compliance.article_14_gate import (
    DEFAULT_HUMAN_REVIEW_THRESHOLD,
    THRESHOLD_STATUS_CALIBRATED,
    THRESHOLD_STATUS_PLACEHOLDER,
)

__all__ = [
    "DEFAULT_MANAGEMENT_REVIEW_THRESHOLD",
    "MANAGEMENT_REVIEW_ERROR_CODE",
    "MANAGEMENT_REVIEW_VOCABULARY",
    "ManagementReviewGateResult",
    "THRESHOLD_STATUS_CALIBRATED",
    "THRESHOLD_STATUS_PLACEHOLDER",
    "check_management_review",
]

#: Typed error code for a management-review refusal. Distinct from
#: ``ARTICLE_14_HUMAN_REVIEW_REQUIRED`` so a downstream handler can tell
#: which regime refused — an auditor asking "why was this blocked?" gets a
#: different answer under SOX than under the EU AI Act.
MANAGEMENT_REVIEW_ERROR_CODE: str = "MANAGEMENT_REVIEW_REQUIRED"

#: Default control vocabulary label carried in the result.
MANAGEMENT_REVIEW_VOCABULARY: str = "management_review"

#: Default threshold. Deliberately aliased to the Article 14 default rather
#: than redeclared: one placeholder value, one place to replace when the
#: calibration work lands. PLACEHOLDER — not evidence-derived.
DEFAULT_MANAGEMENT_REVIEW_THRESHOLD: float = DEFAULT_HUMAN_REVIEW_THRESHOLD


@dataclass(frozen=True)
class ManagementReviewGateResult:
    """Outcome of the management-review-control gate check.

    Field names and ordering intentionally mirror
    :class:`~graqle.compliance.article_14_gate.Article14GateResult` for the
    first five fields, so code that handles one shape handles the other.
    The SOX-specific fields are appended, never interleaved.

    Attributes:
        allowed: True iff the automated path may proceed without review.
        confidence: The confidence the gate evaluated.
        threshold: The threshold it compared against.
        threshold_status: :data:`THRESHOLD_STATUS_PLACEHOLDER` until a
            calibrated value is wired in.
        reason: Human-readable reason. Empty when ``allowed`` is True.
        control_id: The named internal control this decision falls under,
            when known. Carried so a refusal is traceable to a control
            without a second lookup.
        control_vocabulary: Which vocabulary produced this result. Defaults
            to :data:`MANAGEMENT_REVIEW_VOCABULARY`.
    """

    allowed: bool
    confidence: float
    threshold: float
    threshold_status: str = THRESHOLD_STATUS_PLACEHOLDER
    reason: str = ""
    control_id: str | None = None
    control_vocabulary: str = MANAGEMENT_REVIEW_VOCABULARY

    def to_refusal_envelope(self) -> dict[str, Any]:
        """Build the structured refusal envelope for the tool response.

        Mirrors ``Article14GateResult.to_refusal_envelope`` — including
        raising on an allowed result, because an "allowed refusal" is a
        caller bug that should surface loudly rather than emit a
        contradictory envelope.

        Raises:
            RuntimeError: If called on an ``allowed=True`` result.
        """
        if self.allowed:
            raise RuntimeError(
                "to_refusal_envelope() called on an allowed gate result; "
                "the caller should check `.allowed` before envelope build."
            )
        envelope: dict[str, Any] = {
            "success": False,
            "error_code": MANAGEMENT_REVIEW_ERROR_CODE,
            "error": self.reason,
            "control_vocabulary": self.control_vocabulary,
            "confidence": round(float(self.confidence), 4),
            "threshold": round(float(self.threshold), 4),
            "threshold_status": self.threshold_status,
            "next_action": "present_to_management_reviewer",
        }
        if self.control_id is not None:
            envelope["control_id"] = self.control_id
        return envelope


def check_management_review(
    *,
    confidence: float,
    management_review_required: Any = None,
    threshold: float | None = None,
    threshold_status: str = THRESHOLD_STATUS_PLACEHOLDER,
    control_id: str | None = None,
    action_label: str = "decision",
) -> ManagementReviewGateResult:
    """Evaluate the management-review-control gate.

    The gate is ARMED when ``management_review_required`` is truthy (per the
    same coercion the Article 14 gate uses). Unlike the Article 14 gate,
    there is **no environment-variable arming path**: SOX applicability is a
    property of the specific control a decision falls under, not of a
    deployment-wide mode, so arming this gate globally via an env var would
    misrepresent scope.

    When ARMED and ``confidence < threshold``, the gate REFUSES: the result
    has ``allowed=False`` and the caller should return
    :meth:`ManagementReviewGateResult.to_refusal_envelope` as its response.

    A confidence **exactly at** the threshold ALLOWS, matching the Article 14
    gate: "set threshold=0.75 → 0.749 refused, 0.75 allowed".

    Args:
        confidence: Confidence in [0.0, 1.0]. NaN, infinity, and
            out-of-range values raise rather than producing a surprising
            allow or refuse.
        management_review_required: Arming signal. Truthy arms the gate.
        threshold: Optional threshold override. When ``None``, uses
            :data:`DEFAULT_MANAGEMENT_REVIEW_THRESHOLD` — a **placeholder**,
            not an evidence-derived value.
        threshold_status: Marker for whether the threshold is calibrated or
            placeholder.
        control_id: Optional named internal control, carried into the result
            and the refusal envelope.
        action_label: Short label used in the refusal reason string.

    Returns:
        ManagementReviewGateResult: ``allowed=True`` if the gate is disarmed
        or confidence meets the threshold; otherwise ``allowed=False`` with a
        populated ``reason``.

    Raises:
        ValueError: If ``confidence`` or ``threshold`` is NaN, infinite, or
            outside [0.0, 1.0].
    """
    eff_confidence = validate_confidence(confidence)
    eff_threshold = (
        validate_threshold(threshold)
        if threshold is not None
        else DEFAULT_MANAGEMENT_REVIEW_THRESHOLD
    )

    if not coerce_arming_flag(management_review_required):
        return ManagementReviewGateResult(
            allowed=True,
            confidence=eff_confidence,
            threshold=eff_threshold,
            threshold_status=threshold_status,
            control_id=control_id,
        )

    if eff_confidence < eff_threshold:
        control_phrase = (
            f" under control {control_id}" if control_id else ""
        )
        return ManagementReviewGateResult(
            allowed=False,
            confidence=eff_confidence,
            threshold=eff_threshold,
            threshold_status=threshold_status,
            control_id=control_id,
            reason=(
                f"Management review control refused {action_label!s}"
                f"{control_phrase}: confidence "
                f"{round(eff_confidence, 4)} is below threshold "
                f"{round(eff_threshold, 4)} (status: {threshold_status}). "
                f"Present the proposed outcome to a management reviewer "
                f"before relying on it."
            ),
        )

    return ManagementReviewGateResult(
        allowed=True,
        confidence=eff_confidence,
        threshold=eff_threshold,
        threshold_status=threshold_status,
        control_id=control_id,
    )
