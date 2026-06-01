"""Edition / feature entitlement gating (WS-D D2).

The decorators here are the first *enforcing* consumer of the WS-C edition axis
(:func:`graqle.edition.detect_edition`) combined with the WS-D hardened licence
verification (:class:`graqle.licensing.LicenseManager`). They turn "which edition
am I?" from a *report* into an *enforced gate* on proprietary surfaces.

* :func:`requires_edition` — gate a callable on the active edition being at least
  the required :class:`~graqle.edition.Edition` (COMMUNITY < STUDIO < ENTERPRISE).
* :func:`requires_feature` — gate on a licensed feature flag (delegates to the
  shipped :func:`graqle.licensing.check_license`, which already raises
  :class:`~graqle.licensing.manager.LicenseError`). Edition-aware: an
  ENTERPRISE-edition install implicitly has every feature.

GUARDRAIL (the load-bearing rule): **Community surfaces must NEVER be gated.**
The free core (reasoning, governance, tamper-evidence, the offline verifier,
local anchoring, the metering interface) stays unconditionally available. These
decorators only belong on *proprietary* surfaces. A CI gate
(``tests/test_entitlement/``) fails the build if a decorator lands on a
Community-core module. The decorators themselves also refuse a nonsensical
``requires_edition(Edition.COMMUNITY)`` (gating on the free floor is always a
mistake — it would gate nothing, or signal confusion).

Why edition AND licence (defence in depth): ``detect_edition()`` can be forced
via ``GRAQLE_EDITION`` (a packaging/test switch, NOT a grant — ADR-214). So an
entitlement gate must ALSO confirm a verified, non-revoked, non-expired licence
of sufficient tier — otherwise setting ``GRAQLE_EDITION=enterprise`` would unlock
paid features for free. The edition is the fast pre-check; the licence is the
authority.
"""

from __future__ import annotations

import asyncio
import functools
from typing import Any, Callable, TypeVar

from graqle.edition import Edition, detect_edition

__all__ = ["EntitlementError", "requires_edition", "requires_feature"]

F = TypeVar("F", bound=Callable[..., Any])

# Edition → the minimum LicenseTier that legitimately grants it (ADR-214 inverse).
# A forced GRAQLE_EDITION must be backed by a licence of at least this tier.
_EDITION_MIN_TIER = {
    Edition.STUDIO: ("pro", "team", "enterprise"),
    Edition.ENTERPRISE: ("enterprise",),
}


class EntitlementError(Exception):
    """Raised when the active edition/licence does not satisfy a gated surface."""


def _edition_rank(e: Edition) -> int:
    return {Edition.COMMUNITY: 0, Edition.STUDIO: 1, Edition.ENTERPRISE: 2}[e]


def _licence_tier_value() -> str:
    """Active verified licence tier value (e.g. 'enterprise'), or 'free'. Fail-closed."""
    try:
        from graqle.licensing.manager import _get_manager

        return _get_manager().current_tier.value
    except Exception:  # noqa: BLE001 — no/broken licence => free (fail closed)
        return "free"


def _entitled_for(required: Edition) -> bool:
    """True iff the active edition AND a sufficient verified licence satisfy ``required``.

    Defence in depth: the EDITION must be >= required (fast check, honours
    GRAQLE_EDITION), AND the verified LICENCE tier must be one that legitimately
    grants ``required`` (so a forced edition without a real licence does not
    unlock). COMMUNITY requires nothing.
    """
    if required is Edition.COMMUNITY:
        return True
    if _edition_rank(detect_edition()) < _edition_rank(required):
        return False
    return _licence_tier_value() in _EDITION_MIN_TIER[required]


def requires_edition(required: Edition) -> Callable[[F], F]:
    """Gate a (sync or async) callable on the active edition + a sufficient licence.

    Raises :class:`EntitlementError` if the active edition is below ``required``
    OR no verified licence of a tier that grants ``required`` is present.

    ``requires_edition(Edition.COMMUNITY)`` is rejected at decoration time — the
    free core is never gated (the WS-D guardrail), so gating on COMMUNITY is
    always a programming error.
    """
    if not isinstance(required, Edition):
        raise TypeError("requires_edition expects an Edition")
    if required is Edition.COMMUNITY:
        raise ValueError(
            "requires_edition(Edition.COMMUNITY) is invalid — the Community core is "
            "never gated. Gate only proprietary (Studio/Enterprise) surfaces."
        )

    def _decorator(func: F) -> F:
        def _check() -> None:
            if not _entitled_for(required):
                raise EntitlementError(
                    f"'{getattr(func, '__name__', 'this feature')}' requires the GraQle "
                    f"{required.value.title()} edition with a valid licence. "
                    f"Active edition: {detect_edition().value}, licence tier: "
                    f"{_licence_tier_value()}."
                )

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def _async(*args: Any, **kwargs: Any) -> Any:
                _check()
                return await func(*args, **kwargs)

            return _async  # type: ignore[return-value]

        @functools.wraps(func)
        def _sync(*args: Any, **kwargs: Any) -> Any:
            _check()
            return func(*args, **kwargs)

        return _sync  # type: ignore[return-value]

    return _decorator


def requires_feature(feature: str) -> Callable[[F], F]:
    """Gate a callable on a licensed *feature* flag.

    Delegates to :func:`graqle.licensing.check_license` (which raises the shipped
    :class:`~graqle.licensing.manager.LicenseError` when the feature is not
    available under the current licence). This composes with — does not duplicate
    — the existing ``require_license`` decorator; use ``requires_feature`` from
    the entitlement surface so edition + feature gating live in one place.

    An ENTERPRISE-edition install (with a matching licence) implicitly satisfies
    any feature gate (top tier has all features), short-circuiting the lookup.
    """
    if not isinstance(feature, str) or not feature:
        raise ValueError("requires_feature expects a non-empty feature name")

    def _decorator(func: F) -> F:
        def _check() -> None:
            # Top-tier short-circuit: a real ENTERPRISE entitlement has everything.
            if _entitled_for(Edition.ENTERPRISE):
                return
            from graqle.licensing import check_license  # raises LicenseError if absent

            check_license(feature)

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def _async(*args: Any, **kwargs: Any) -> Any:
                _check()
                return await func(*args, **kwargs)

            return _async  # type: ignore[return-value]

        @functools.wraps(func)
        def _sync(*args: Any, **kwargs: Any) -> Any:
            _check()
            return func(*args, **kwargs)

        return _sync  # type: ignore[return-value]

    return _decorator
