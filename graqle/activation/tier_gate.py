"""pre-reason-activation design — License-tier detection for the pre-reason activation layer.

Rule (plain English):
    Free tier  → ADVISORY mode  (scores visible, upgrade chip shown on block-worthy turns, turn continues)
    Pro / Enterprise → ENFORCED mode (turn halts on block-worthy safety verdicts)

Detection order (first match wins):
    1. Environment variable GRAQLE_LICENSE_TIER (explicit override)
    2. Environment variable GRAQLE_LICENSE_KEY  (presence = Pro at minimum)
    3. Config file graqle.yaml -> license.tier
    4. Default: ADVISORY (Free)

Never raises: unknown tier strings fall back to ADVISORY.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from graqle.activation.providers import TierMode

logger = logging.getLogger("graqle.activation.tier_gate")


_PRO_TIERS = frozenset({"pro", "enterprise", "team"})
_FREE_TIERS = frozenset({"free", "community", ""})


def resolve_tier_mode(config: dict[str, Any] | None = None) -> TierMode:
    """Resolve the current tier's activation mode.

    Parameters
    ----------
    config:
        Optional parsed graqle.yaml content. If omitted, only env vars are
        consulted.

    Returns
    -------
    TierMode.ENFORCED if Pro/Enterprise/Team key is present; else ADVISORY.
    """
    # 1. Explicit override
    explicit = os.environ.get("GRAQLE_LICENSE_TIER", "").strip().lower()
    if explicit:
        if explicit in _PRO_TIERS:
            return TierMode.ENFORCED
        if explicit in _FREE_TIERS:
            return TierMode.ADVISORY
        logger.warning("unknown GRAQLE_LICENSE_TIER value %r; falling back to ADVISORY", explicit)
        return TierMode.ADVISORY

    # 2. License key presence
    if os.environ.get("GRAQLE_LICENSE_KEY", "").strip():
        return TierMode.ENFORCED

    # 3. Config file
    if isinstance(config, dict):
        lic = config.get("license")
        if isinstance(lic, dict):
            tier_cfg = str(lic.get("tier", "")).strip().lower()
            if tier_cfg in _PRO_TIERS:
                return TierMode.ENFORCED
            if tier_cfg in _FREE_TIERS:
                return TierMode.ADVISORY

    # 4. Default
    return TierMode.ADVISORY
