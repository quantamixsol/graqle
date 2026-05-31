"""Edition detection for the open-core build (WS-C C2).

GraQle ships in three **editions** — the install/feature-set axis:

* ``Edition.COMMUNITY`` — Apache-2.0, free forever (the default).
* ``Edition.STUDIO`` — proprietary hosted backend.
* ``Edition.ENTERPRISE`` — proprietary federation.

This is **distinct from the licence tier** (``graqle.licensing.LicenseTier`` =
FREE < PRO < TEAM < ENTERPRISE). :func:`detect_edition` folds the 4 tiers onto
the 3 editions per **ADR-214** (the single source of truth for this mapping):

    FREE → COMMUNITY · PRO → STUDIO · TEAM → STUDIO · ENTERPRISE → ENTERPRISE

Resolution order (feature-flagged, defaults Community):

1. ``GRAQLE_EDITION`` env override — validated against the enum; an invalid
   value is ignored (logged WARNING) and resolution falls through. Never raises,
   never silently upgrades.
2. Licence-derived — map ``LicenseManager().current_tier`` through ADR-214.
3. Default — ``Edition.COMMUNITY``.

**No-loophole invariant (ADR-214 §"No-loophole guarantees"):** every failure or
malformed-input path resolves to ``COMMUNITY``. There is NO code path where
invalid/forged/absent input yields ``STUDIO`` or ``ENTERPRISE`` — the meter and
gates fail *closed to the cheaper edition*. This module only *reports* the
edition; it grants no entitlement (feature gating verifies the licence itself —
WS-D), so the override is a packaging/test switch, not a licence bypass.

Pure stdlib. Safe to import from any Community surface.
"""

from __future__ import annotations

import logging
import os
from enum import Enum
from functools import lru_cache

__all__ = [
    "Edition",
    "detect_edition",
    "is_community",
    "is_studio_or_higher",
    "is_enterprise",
    "reset_edition_cache",
]

logger = logging.getLogger(__name__)

# The env override knob (ADR-214 step 1). A documented operator/packaging switch
# (C1 Studio/Enterprise wheels set it); NOT a licence — it reports an edition,
# it does not grant licensed features.
_EDITION_ENV_VAR = "GRAQLE_EDITION"


class Edition(str, Enum):
    """The install/feature-set axis (distinct from ``LicenseTier``).

    ``str`` mixin so an :class:`Edition` compares/serialises as its plain value
    (``Edition.COMMUNITY == "community"``) for config files and logs.
    """

    COMMUNITY = "community"
    STUDIO = "studio"
    ENTERPRISE = "enterprise"

    # Ordering helper for "studio or higher" style checks, without making the
    # enum itself orderable (which str-Enum is not by default).
    @property
    def _rank(self) -> int:
        return _EDITION_RANK[self]


# Ascending capability rank. COMMUNITY is the floor; ENTERPRISE the ceiling.
_EDITION_RANK: dict[Edition, int] = {
    Edition.COMMUNITY: 0,
    Edition.STUDIO: 1,
    Edition.ENTERPRISE: 2,
}


def _edition_from_env() -> Edition | None:
    """Resolve an explicit ``GRAQLE_EDITION`` override, or ``None`` to fall through.

    Matched case-insensitively against the EXACT enum values. Any other value
    (typo, injection, empty) is ignored with a WARNING — it never raises and
    never default-upgrades (ADR-214 guarantee #2).
    """
    raw = os.environ.get(_EDITION_ENV_VAR)
    if raw is None:
        return None
    normalised = raw.strip().lower()
    if not normalised:
        return None
    for edition in Edition:
        if normalised == edition.value:
            return edition
    # Truncate the echoed value: GRAQLE_EDITION is a non-secret packaging knob,
    # but never log unbounded external input (defence-in-depth — log-bloat/noise).
    shown = raw if len(raw) <= 32 else raw[:32] + "..."
    logger.warning(
        "%s=%r is not a valid edition (expected one of %s); ignoring the override "
        "and falling back to licence-derived detection",
        _EDITION_ENV_VAR,
        shown,
        ", ".join(e.value for e in Edition),
    )
    return None


def _edition_from_licence() -> Edition:
    """Map the active licence tier to an edition per ADR-214.

    Fail-closed to ``COMMUNITY`` (ADR-214 guarantee #1): if the licensing module
    is absent, raises, or yields an unrecognised tier, return COMMUNITY. A bug
    here can only ever under-privilege, never grant a paid edition.
    """
    try:
        from graqle.licensing.manager import LicenseManager, LicenseTier

        tier = LicenseManager().current_tier
        # ADR-214 fold (4 tiers → 3 editions). Anything not explicitly mapped
        # (a tier added later without updating this table) falls to COMMUNITY —
        # fail-closed-to-cheaper, never default-up.
        mapping: dict[LicenseTier, Edition] = {
            LicenseTier.FREE: Edition.COMMUNITY,
            LicenseTier.PRO: Edition.STUDIO,
            LicenseTier.TEAM: Edition.STUDIO,
            LicenseTier.ENTERPRISE: Edition.ENTERPRISE,
        }
        return mapping.get(tier, Edition.COMMUNITY)
    except Exception:  # noqa: BLE001 — fail closed to the cheaper edition (ADR-214 #1)
        logger.debug(
            "licence-derived edition detection failed; defaulting to COMMUNITY",
            exc_info=True,
        )
        return Edition.COMMUNITY


@lru_cache(maxsize=1)
def detect_edition() -> Edition:
    """Return the active :class:`Edition` (ADR-214 resolution order).

    Cached: resolution is pure given (env, licence state). Call
    :func:`reset_edition_cache` if either changes within a process (e.g. tests,
    or a runtime licence reload).

    Guarantees (ADR-214): defaults to ``COMMUNITY``; never raises; every
    failure/malformed path resolves to ``COMMUNITY`` (never a paid edition).
    """
    override = _edition_from_env()
    if override is not None:
        return override
    return _edition_from_licence()


def reset_edition_cache() -> None:
    """Clear the cached :func:`detect_edition` result (tests / licence reload)."""
    detect_edition.cache_clear()


def is_community() -> bool:
    """True iff the active edition is exactly Community (the free core)."""
    return detect_edition() is Edition.COMMUNITY


def is_studio_or_higher() -> bool:
    """True iff the active edition is Studio or Enterprise (any paid edition)."""
    return detect_edition()._rank >= Edition.STUDIO._rank


def is_enterprise() -> bool:
    """True iff the active edition is exactly Enterprise."""
    return detect_edition() is Edition.ENTERPRISE
