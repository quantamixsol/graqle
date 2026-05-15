"""R25-EU11 v1.0 — public claim-limits taxonomy.

Authored from the public formulation by **Ricky Jones (TrinityOS)** published
on LinkedIn 2026-05-13. The taxonomy makes the *scope of every governance
decision* explicit so a downstream auditor or regulator can answer
"what does this record NOT claim?" without guesswork.

The 17 canonical values are grouped into 6 categories:

    1. **TEMPORAL** — facts about *when* the underlying knowledge holds.
    2. **MODEL_DEPENDENCY** — facts about coupling to a specific LLM.
    3. **DATA_SCOPE** — facts about what data the response was derived from.
    4. **DECISION_SCOPE** — facts about what kind of decision this is NOT.
    5. **TRUST_BOUNDARY** — facts about confidence / verification status.
    6. **COMPLIANCE_SCOPE** — facts about which regulatory regime applies.

Operators MAY declare vendor-specific claim limits using the ``x-`` prefix
namespace (e.g. ``x-acme-internal-use-only``). The prefix-namespaced values
match the regex ``^x-[a-z0-9_-]{1,64}$``.

The backfill value :data:`LEGACY_BACKFILL_VALUE` (``legacy_pre_R25_EU11``)
is the ONLY value permitted on records produced before this taxonomy
shipped — newly written records MUST NOT use it.

This module has no external dependencies beyond stdlib ``re``.

References:
    - R25-EU11 spec § "Public Claim-Limits Taxonomy"
    - CG-MKT-10 in OPEN-TRACKER-CAPABILITY-GAPS.md
    - docs/compliance/eu-ai-act/claim-limits-taxonomy-v1.0.md
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Version + backfill constants
# ---------------------------------------------------------------------------

#: Canonical version string for the public taxonomy schema.
CLAIM_LIMITS_TAXONOMY_VERSION: str = "1.0"

#: The single backfill value permitted on records produced before R25-EU11.
#: New writes MUST NOT use this value.
LEGACY_BACKFILL_VALUE: str = "legacy_pre_R25_EU11"

#: Prefix that marks an operator-specific (extension) claim limit.
X_PREFIX: str = "x-"


# ---------------------------------------------------------------------------
# Category frozensets — 6 groups, 17 canonical values total
# ---------------------------------------------------------------------------

#: 2 values — when the underlying knowledge holds.
TEMPORAL_CLAIM_LIMITS: frozenset[str] = frozenset(
    {
        "knowledge_cutoff_apparent",
        "real_time_data_unavailable",
    }
)

#: 2 values — coupling to a specific LLM/backend.
MODEL_DEPENDENCY_CLAIM_LIMITS: frozenset[str] = frozenset(
    {
        "model_specific_calibration",
        "model_dependent_thresholds",
    }
)

#: 4 values — provenance of the underlying data.
DATA_SCOPE_CLAIM_LIMITS: frozenset[str] = frozenset(
    {
        "training_data_window",
        "training_data_jurisdiction",
        "public_data_only",
        "no_pii_processed",
    }
)

#: 4 values — what kind of decision this is NOT.
DECISION_SCOPE_CLAIM_LIMITS: frozenset[str] = frozenset(
    {
        "not_legal_advice",
        "not_medical_advice",
        "not_financial_advice",
        "human_review_required",
    }
)

#: 2 values — confidence / verification posture.
TRUST_BOUNDARY_CLAIM_LIMITS: frozenset[str] = frozenset(
    {
        "low_confidence_synthesised",
        "cited_sources_not_verified",
    }
)

#: 3 values — regulatory regime applicability.
COMPLIANCE_SCOPE_CLAIM_LIMITS: frozenset[str] = frozenset(
    {
        "eu_ai_act_article_14_oversight",
        "eu_ai_act_article_50_disclosure",
        "gdpr_processor_only",
    }
)

#: Union of all 6 categories — the full canonical set (17 values).
CANONICAL_CLAIM_LIMITS: frozenset[str] = (
    TEMPORAL_CLAIM_LIMITS
    | MODEL_DEPENDENCY_CLAIM_LIMITS
    | DATA_SCOPE_CLAIM_LIMITS
    | DECISION_SCOPE_CLAIM_LIMITS
    | TRUST_BOUNDARY_CLAIM_LIMITS
    | COMPLIANCE_SCOPE_CLAIM_LIMITS
)


# ---------------------------------------------------------------------------
# Extension namespace regex (operator-specific values)
# ---------------------------------------------------------------------------

# ``x-`` + 1..64 chars of [a-z0-9_-]. Conservative charset to stay
# auditor-friendly (no uppercase, no unicode, no separators that collide with
# SHACL identifiers).
_X_NAMESPACE_RE: re.Pattern[str] = re.compile(r"^x-[a-z0-9_-]{1,64}$")


# ---------------------------------------------------------------------------
# Public validators
# ---------------------------------------------------------------------------


def is_valid_claim_limit(value: str) -> bool:
    """Return True iff ``value`` is a recognised claim-limit string.

    A value is recognised iff:

    1. It is in :data:`CANONICAL_CLAIM_LIMITS` (17 canonical values), OR
    2. It matches the operator-extension regex ``^x-[a-z0-9_-]{1,64}$``.

    The backfill sentinel :data:`LEGACY_BACKFILL_VALUE` is NOT valid for
    new writes — callers writing fresh records must reject it explicitly.
    This function reports it as ``False`` for that reason.

    Args:
        value: Candidate claim-limit string.

    Returns:
        bool: ``True`` if recognised, ``False`` otherwise.

    Raises:
        TypeError: If ``value`` is not a ``str``.
    """
    if not isinstance(value, str):
        raise TypeError(
            f"is_valid_claim_limit expects str, got {type(value).__name__}"
        )
    if value in CANONICAL_CLAIM_LIMITS:
        return True
    if _X_NAMESPACE_RE.match(value):
        return True
    return False


def validate_claim_limits(values: list[str]) -> list[str]:
    """Return the subset of ``values`` that are NOT recognised.

    An empty input list returns an empty list (it is the *caller's*
    responsibility to reject empty claim-limit lists per the
    default-deny rule — that check lives in
    :func:`graqle.compliance.claim_limits.validator.require_non_empty_claim_limits`).

    Args:
        values: Claim-limit strings to validate.

    Returns:
        list[str]: Invalid entries (preserves order, deduplicated). Empty
        list means every entry is valid.

    Raises:
        TypeError: If ``values`` is not a ``list`` of ``str``.
    """
    if not isinstance(values, list):
        raise TypeError(
            f"validate_claim_limits expects list[str], got {type(values).__name__}"
        )
    invalid: list[str] = []
    seen: set[str] = set()
    for v in values:
        if not isinstance(v, str):
            raise TypeError(
                f"claim_limits entries must be str, got {type(v).__name__}"
            )
        if not is_valid_claim_limit(v) and v not in seen:
            invalid.append(v)
            seen.add(v)
    return invalid
