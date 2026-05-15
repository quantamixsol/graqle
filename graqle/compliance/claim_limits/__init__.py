"""Claim-limits declaration per R25-EU11 v1.0.

Public API:
    - :data:`CLAIM_LIMITS_TAXONOMY_VERSION` (str)
    - :data:`CANONICAL_CLAIM_LIMITS` (frozenset[str])
    - :data:`LEGACY_BACKFILL_VALUE` (str)
    - :func:`is_valid_claim_limit`
    - :func:`validate_claim_limits`
    - :class:`ClaimLimitsValidationError`

The taxonomy is authored from Ricky Jones's (TrinityOS) public formulation
on LinkedIn (2026-05-13) and CR-010 design notes. See
:doc:`docs/compliance/eu-ai-act/claim-limits-taxonomy-v1.0.md`.
"""

from __future__ import annotations

from graqle.compliance.claim_limits.taxonomy import (
    CANONICAL_CLAIM_LIMITS,
    CLAIM_LIMITS_TAXONOMY_VERSION,
    COMPLIANCE_SCOPE_CLAIM_LIMITS,
    DATA_SCOPE_CLAIM_LIMITS,
    DECISION_SCOPE_CLAIM_LIMITS,
    LEGACY_BACKFILL_VALUE,
    MODEL_DEPENDENCY_CLAIM_LIMITS,
    TEMPORAL_CLAIM_LIMITS,
    TRUST_BOUNDARY_CLAIM_LIMITS,
    X_PREFIX,
    is_valid_claim_limit,
    validate_claim_limits,
)
from graqle.compliance.claim_limits.validator import (
    ClaimLimitsValidationError,
    require_non_empty_claim_limits,
)

__all__ = [
    "CANONICAL_CLAIM_LIMITS",
    "CLAIM_LIMITS_TAXONOMY_VERSION",
    "ClaimLimitsValidationError",
    "COMPLIANCE_SCOPE_CLAIM_LIMITS",
    "DATA_SCOPE_CLAIM_LIMITS",
    "DECISION_SCOPE_CLAIM_LIMITS",
    "LEGACY_BACKFILL_VALUE",
    "MODEL_DEPENDENCY_CLAIM_LIMITS",
    "TEMPORAL_CLAIM_LIMITS",
    "TRUST_BOUNDARY_CLAIM_LIMITS",
    "X_PREFIX",
    "is_valid_claim_limit",
    "require_non_empty_claim_limits",
    "validate_claim_limits",
]
