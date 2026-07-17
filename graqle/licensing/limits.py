"""Tier-derived node limits — CR-LIC-01 (ADR-244 composite-trigger monetisation).

Resolves the *effective* node cap for the current install without any change to
the ``graqle-license-v2`` wire format:

* **No licence key at all** → anonymous install → ``ANONYMOUS_MAX_NODES``.
* **Licence with tier FREE** → registered free user → ``TIER_MAX_NODES[FREE]``.
* **PRO / TEAM / ENTERPRISE** → uncapped (``None``).
* **Per-licence override** — a signed ``features`` entry of the form
  ``max_nodes:<int>`` wins over the tier default. Because ``features`` is part
  of the signed payload in BOTH the legacy HMAC v1 and ed25519 v2 formats, the
  override inherits the licence signature; no new claim field is needed and no
  previously issued licence is invalidated.

Deliberately duck-typed: accepts any object exposing ``tier`` and ``features``
(``manager.License`` today, the v2 payload dataclass tomorrow).

This module only *resolves* limits. Recording usage against them lives in
:mod:`graqle.licensing.meter`; enforcement is a later CR (CR-LIC-03) and is
gated behind ``GRAQLE_ENFORCE_CAPS``.
"""

from __future__ import annotations

from dataclasses import dataclass

from graqle.licensing.manager import LicenseTier

__all__ = [
    "ANONYMOUS_MAX_NODES",
    "TIER_MAX_NODES",
    "WARN_RATIO",
    "EffectiveLimits",
    "resolve_limits",
]

# Anonymous (keyless) installs. Calibrated against the 2026-07 graph census:
# a fresh scan of a normal project lands in the hundreds of nodes, so a normal
# project fits; crossing the cap correlates with large repos or sustained use.
ANONYMOUS_MAX_NODES = 500

# Tier defaults. ``None`` means uncapped (fair-use).
TIER_MAX_NODES: dict[LicenseTier, int | None] = {
    LicenseTier.FREE: 1_000,
    LicenseTier.PRO: None,
    LicenseTier.TEAM: None,
    LicenseTier.ENTERPRISE: None,
}

# Fraction of the cap at which the meter starts warning.
WARN_RATIO = 0.8

_OVERRIDE_PREFIX = "max_nodes:"


@dataclass(frozen=True)
class EffectiveLimits:
    """The resolved node cap plus where it came from (for messaging/telemetry)."""

    max_nodes: int | None
    source: str  # "anonymous" | "tier:<name>" | "override"

    @property
    def unlimited(self) -> bool:
        return self.max_nodes is None

    def warn_threshold(self) -> int | None:
        """Node count at which warnings begin, or ``None`` when uncapped."""
        if self.max_nodes is None:
            return None
        return int(self.max_nodes * WARN_RATIO)


def _override_from_features(features) -> int | None:
    """Extract a signed ``max_nodes:<int>`` override from a features iterable.

    Malformed entries are ignored (a bad override must never grant more OR
    less than the tier default by accident — it simply doesn't apply). When
    several overrides are present the largest wins, so a re-issued upgrade key
    can only improve on a stale one.
    """
    best: int | None = None
    for entry in features or ():
        if not isinstance(entry, str) or not entry.startswith(_OVERRIDE_PREFIX):
            continue
        raw = entry[len(_OVERRIDE_PREFIX):]
        try:
            value = int(raw)
        except ValueError:
            continue
        if value <= 0:
            continue
        if best is None or value > best:
            best = value
    return best


def _normalise_tier(tier) -> LicenseTier | None:
    if isinstance(tier, LicenseTier):
        return tier
    if isinstance(tier, str):
        try:
            return LicenseTier(tier)
        except ValueError:
            return None
    return None


def resolve_limits(license=None) -> EffectiveLimits:
    """Resolve the effective node limits for ``license`` (``None`` = anonymous).

    Unknown/unrecognised tiers resolve to the FREE cap rather than uncapped —
    a garbled licence must never be more permissive than a valid one.
    """
    if license is None:
        return EffectiveLimits(max_nodes=ANONYMOUS_MAX_NODES, source="anonymous")

    override = _override_from_features(getattr(license, "features", None))
    if override is not None:
        return EffectiveLimits(max_nodes=override, source="override")

    tier = _normalise_tier(getattr(license, "tier", None))
    if tier is None:
        return EffectiveLimits(
            max_nodes=TIER_MAX_NODES[LicenseTier.FREE], source="tier:unknown"
        )
    return EffectiveLimits(
        max_nodes=TIER_MAX_NODES.get(tier, TIER_MAX_NODES[LicenseTier.FREE]),
        source=f"tier:{tier.value}",
    )
