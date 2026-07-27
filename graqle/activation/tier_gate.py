"""pre-reason-activation design — governance-MODE detection for the activation layer.

This resolves ONLY the activation *governance mode* (whether block-worthy safety
verdicts halt the turn), NOT a paid entitlement:

    ADVISORY mode  → scores visible, upgrade chip on block-worthy turns, turn CONTINUES
    ENFORCED mode  → turn HALTS on a block-worthy safety verdict

⚠️ CR-LIC-03b (ADR-245) SECURITY INVARIANT — this function MUST NEVER be used to grant a
paid feature, raise a cap, or confer any entitlement. It only makes governance STRICTER
(ENFORCED blocks your own unsafe turns). Because of that, an UNVERIFIED signal (env var,
config file) is allowed to opt INTO stricter governance, but it can never buy anything.
Any code that gates a PAID capability MUST consult ``manager.current_tier`` (a
cryptographically verified signed licence) — never this function, never GRAQLE_LICENSE_TIER.

Detection order (first match wins):
    1. VERIFIED licence tier (manager.current_tier) — the trustworthy source; a real
       paid licence → ENFORCED. Checked FIRST so a genuine entitlement always wins.
    2. GRAQLE_LICENSE_TIER env — governance-mode dev toggle ONLY (unverified; can raise
       to ENFORCED but confers NO entitlement — see invariant above).
    3. GRAQLE_LICENSE_KEY presence — a key is present (its validity is enforced elsewhere).
    4. Config file graqle.yaml -> license.tier (unverified hint; mode only).
    5. Default: ADVISORY (Free).

Never raises: unknown/error → ADVISORY (fail-safe = the least-strict, non-blocking mode).
"""
from __future__ import annotations

import logging
import os
from typing import Any

from graqle.activation.providers import TierMode

logger = logging.getLogger("graqle.activation.tier_gate")


_PRO_TIERS = frozenset({"pro", "enterprise", "team"})
_FREE_TIERS = frozenset({"free", "community", ""})


def _verified_tier_mode() -> TierMode | None:
    """Governance mode from the VERIFIED licence, or None if no valid paid licence.

    Consults manager.current_tier, which returns a paid tier ONLY from a signed licence
    that passed verification (signature + CRL + nonce). This is the trustworthy source;
    it is checked first so a real entitlement is never shadowed by an unverified hint.
    Fail-safe: any error → None (fall through to the mode-only hints).
    """
    try:
        # Lazy import: graqle.licensing may import graqle.activation transitively, so a
        # module-level import here risks a circular dependency. Import inside the call.
        from graqle.licensing.manager import LicenseTier, _get_manager

        tier = _get_manager().current_tier
        if tier in (LicenseTier.PRO, LicenseTier.TEAM, LicenseTier.ENTERPRISE):
            return TierMode.ENFORCED
        return TierMode.ADVISORY
    except Exception:  # noqa: BLE001 — mode detection must never raise
        return None


def resolve_tier_mode(config: dict[str, Any] | None = None) -> TierMode:
    """Resolve the activation GOVERNANCE MODE (not an entitlement — see module docstring).

    Returns TierMode.ENFORCED (halt on block-worthy verdicts) or ADVISORY (never halt).
    NEVER call this to decide a paid feature/cap — use manager.current_tier for that.
    """
    # 1. VERIFIED licence wins — a real paid entitlement always resolves ENFORCED.
    verified = _verified_tier_mode()
    if verified is TierMode.ENFORCED:
        return verified
    # (A verified FREE tier does NOT short-circuit: an unverified env/config hint may
    #  still opt a free user INTO stricter governance — that grants nothing, only rigor.)

    # 2. GRAQLE_LICENSE_TIER — governance-mode dev toggle ONLY (unverified; no entitlement).
    explicit = os.environ.get("GRAQLE_LICENSE_TIER", "").strip().lower()
    if explicit:
        if explicit in _PRO_TIERS:
            return TierMode.ENFORCED
        if explicit in _FREE_TIERS:
            return TierMode.ADVISORY
        logger.warning("unknown GRAQLE_LICENSE_TIER value %r; falling back to ADVISORY", explicit)
        return TierMode.ADVISORY

    # 3. License key presence (validity enforced elsewhere; mode signal only).
    if os.environ.get("GRAQLE_LICENSE_KEY", "").strip():
        return TierMode.ENFORCED

    # 4. Config file (unverified hint; mode only).
    if isinstance(config, dict):
        lic = config.get("license")
        if isinstance(lic, dict):
            tier_cfg = str(lic.get("tier", "")).strip().lower()
            if tier_cfg in _PRO_TIERS:
                return TierMode.ENFORCED
            if tier_cfg in _FREE_TIERS:
                return TierMode.ADVISORY

    # 5. Default
    return TierMode.ADVISORY
