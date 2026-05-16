"""R25-EU11 v1.0 — claim-limits validator (L08 SHACL gate + L19 audit-trail gate).

This module wraps the canonical taxonomy in
:mod:`graqle.compliance.claim_limits.taxonomy` with the **schema-level
enforcement** required by R25-EU11 § 4 (the SHACL constraint
``ClaimLimitsRequired``) and § 5 (audit-trail rejection on missing/empty
field).

Two enforcement points exist:

1. :func:`require_non_empty_claim_limits` — fires on every new write of a
   ``ResponseSnapshot`` / governance record. Empty list = rejected.
   This is the **default-deny rule**: if an operator doesn't declare what
   the record does NOT claim, the record cannot be written.

2. :func:`validate_for_write` — full validation: non-empty + every entry
   recognised + no backfill sentinel. Returns a structured
   :class:`ClaimLimitsValidationResult` instead of raising, so the
   ``_handle_apply`` / ``_handle_auto`` callers can emit a structured
   refusal reason without needing to catch.

The L08 SHACL constraint is enforced at the same boundary by calling
:func:`require_non_empty_claim_limits`; the SHACL graph itself ships with
the spec but the runtime check happens here.

Why a separate module from :mod:`taxonomy`:

- ``taxonomy`` is pure data + a stateless validator (importable from
  anywhere, no governance side-effects).
- ``validator`` is the governance-gate enforcement layer that raises
  :class:`ClaimLimitsValidationError` with structured reasons. The
  ``_handle_apply`` path in the MCP dev server imports from here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from graqle.compliance.claim_limits.taxonomy import (
    CLAIM_LIMITS_TAXONOMY_VERSION,
    LEGACY_BACKFILL_VALUE,
    is_valid_claim_limit,
    validate_claim_limits,
)


class ClaimLimitsValidationError(ValueError):
    """Raised when a write violates the R25-EU11 claim-limits invariant.

    Carries structured ``reasons`` so the caller can build a typed refusal
    response for L19 audit-trail logging without re-parsing the message.

    Attributes:
        reasons: List of short reason codes (e.g.
            ``["claim_limits_missing"]``,
            ``["claim_limits_empty"]``,
            ``["claim_limits_invalid:foo,bar"]``,
            ``["claim_limits_legacy_backfill_in_new_write"]``).
        invalid_values: The specific values that failed validation, if any.
    """

    def __init__(
        self,
        message: str,
        reasons: list[str] | None = None,
        invalid_values: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.reasons: list[str] = list(reasons) if reasons else []
        self.invalid_values: list[str] = (
            list(invalid_values) if invalid_values else []
        )


@dataclass(frozen=True)
class ClaimLimitsValidationResult:
    """Outcome of a non-raising validation pass.

    Attributes:
        ok: ``True`` iff the input passes every R25-EU11 invariant.
        reasons: Reason codes; empty when ``ok`` is True.
        invalid_values: The specific values that failed validation, if any.
        taxonomy_version: The taxonomy version this result was produced
            under (always equals :data:`CLAIM_LIMITS_TAXONOMY_VERSION` —
            included so audit-trail consumers can record it).
    """

    ok: bool
    reasons: list[str] = field(default_factory=list)
    invalid_values: list[str] = field(default_factory=list)
    taxonomy_version: str = CLAIM_LIMITS_TAXONOMY_VERSION


# ---------------------------------------------------------------------------
# Raising form — for write paths that should fail closed
# ---------------------------------------------------------------------------


def require_non_empty_claim_limits(
    claim_limits: Any,
    *,
    allow_legacy_backfill: bool = False,
    field_name: str = "claim_limits",
) -> list[str]:
    """Validate ``claim_limits`` for a new governance-record write.

    This is the L08 SHACL + L19 audit-trail gate. Fail-closed: any
    violation raises :class:`ClaimLimitsValidationError` with structured
    ``reasons`` so the caller can surface the refusal reason without
    re-parsing the message.

    Args:
        claim_limits: Value to validate. Must be a non-empty ``list[str]``
            where every entry passes
            :func:`graqle.compliance.claim_limits.taxonomy.is_valid_claim_limit`.
        allow_legacy_backfill: If ``True``, the single-element list
            ``["legacy_pre_R25_EU11"]`` is accepted (backfill migration
            path only). New writes MUST pass ``False``.
        field_name: Name used in error messages. Defaults to
            ``"claim_limits"``.

    Returns:
        list[str]: The same list, validated (returns a *copy* to prevent
        caller mutation from invalidating it after the check).

    Raises:
        ClaimLimitsValidationError: If any invariant is violated. The
            ``reasons`` attribute carries one or more codes:
            ``claim_limits_missing``,
            ``claim_limits_wrong_type``,
            ``claim_limits_empty``,
            ``claim_limits_legacy_backfill_in_new_write``,
            ``claim_limits_invalid``.
    """
    if claim_limits is None:
        raise ClaimLimitsValidationError(
            f"{field_name} is required (R25-EU11 L08 SHACL "
            f"ClaimLimitsRequired): default-deny rule rejects writes "
            f"with no claim_limits field.",
            reasons=["claim_limits_missing"],
        )
    if not isinstance(claim_limits, list):
        raise ClaimLimitsValidationError(
            f"{field_name} must be list[str], got "
            f"{type(claim_limits).__name__}.",
            reasons=["claim_limits_wrong_type"],
        )
    if len(claim_limits) == 0:
        raise ClaimLimitsValidationError(
            f"{field_name} must be non-empty (R25-EU11 L08 SHACL "
            f"ClaimLimitsRequired): default-deny rule rejects writes "
            f"with an empty claim_limits list.",
            reasons=["claim_limits_empty"],
        )

    # Type check every entry up front for clean errors.
    for v in claim_limits:
        if not isinstance(v, str):
            raise ClaimLimitsValidationError(
                f"{field_name} entries must be str, got "
                f"{type(v).__name__} ({v!r}).",
                reasons=["claim_limits_wrong_type"],
            )

    # Backfill sentinel handling.
    if LEGACY_BACKFILL_VALUE in claim_limits and not allow_legacy_backfill:
        raise ClaimLimitsValidationError(
            f"{field_name} contains {LEGACY_BACKFILL_VALUE!r} but "
            f"allow_legacy_backfill=False. New writes must declare a "
            f"concrete claim-limits set; the backfill sentinel is only "
            f"valid during the one-time migration of pre-R25-EU11 records.",
            reasons=["claim_limits_legacy_backfill_in_new_write"],
            invalid_values=[LEGACY_BACKFILL_VALUE],
        )

    # If backfill is allowed AND the list is exactly the backfill sentinel,
    # the validator-level check stops here — no further taxonomy validation
    # required (backfill is by definition outside the canonical taxonomy).
    if allow_legacy_backfill and claim_limits == [LEGACY_BACKFILL_VALUE]:
        return list(claim_limits)

    invalid = validate_claim_limits(claim_limits)
    if invalid:
        raise ClaimLimitsValidationError(
            f"{field_name} contains {len(invalid)} invalid entries: "
            f"{invalid!r}. Each entry must be in the v1.0 canonical "
            f"taxonomy or match the operator-extension namespace "
            f"^x-[a-z0-9_-]{{1,64}}$.",
            reasons=["claim_limits_invalid"],
            invalid_values=invalid,
        )

    return list(claim_limits)


# ---------------------------------------------------------------------------
# Non-raising form — for callers that prefer structured results
# ---------------------------------------------------------------------------


def validate_for_write(
    claim_limits: Any,
    *,
    allow_legacy_backfill: bool = False,
) -> ClaimLimitsValidationResult:
    """Non-raising counterpart to :func:`require_non_empty_claim_limits`.

    Returns a :class:`ClaimLimitsValidationResult` with structured
    ``reasons`` + ``invalid_values``. Used by ``_handle_apply`` /
    ``_handle_auto`` to emit a typed refusal reason without try/except.

    Args:
        claim_limits: Value to validate (same semantics as
            :func:`require_non_empty_claim_limits`).
        allow_legacy_backfill: As above.

    Returns:
        ClaimLimitsValidationResult: ``ok=True`` on success, else
        ``ok=False`` with reasons + invalid_values populated. Even on
        invalid input shape (non-list, None), this function returns a
        structured result instead of raising — except for non-str entries
        when the outer container is otherwise list-like, which still raise
        ``TypeError`` from the downstream taxonomy check.

    Note:
        For non-validation type errors (e.g. ``is_valid_claim_limit``
        receiving a non-str inside an otherwise list-shaped input), the
        downstream taxonomy validator raises ``TypeError``. Callers that
        want truly never-raising behaviour should wrap this in their own
        try/except — this function only suppresses
        :class:`ClaimLimitsValidationError`.
    """
    try:
        require_non_empty_claim_limits(
            claim_limits,
            allow_legacy_backfill=allow_legacy_backfill,
        )
    except ClaimLimitsValidationError as exc:
        return ClaimLimitsValidationResult(
            ok=False,
            reasons=list(exc.reasons),
            invalid_values=list(exc.invalid_values),
        )
    return ClaimLimitsValidationResult(ok=True)
