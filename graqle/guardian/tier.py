"""Tier enforcement for PR Guardian — Free vs Pro usage limits.

Free tier: 10 PR scans/month, no custom SHACL rules.
Pro tier:  Unlimited scans, custom SHACL rules, custom governance policies.

Usage is tracked in .graqle/guardian_usage.json (local) or via API key
validation (cloud).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("graqle.guardian.tier")

_USAGE_FILE = Path(".graqle") / "guardian_usage.json"

# Tier limits
FREE_SCANS_PER_MONTH = 10
PRO_SCANS_PER_MONTH = -1  # unlimited


@dataclass
class TierStatus:
    """Current tier usage status."""

    tier: str  # "free" or "pro"
    scans_used: int
    scans_limit: int  # -1 = unlimited
    month: str  # "2026-04"
    can_scan: bool
    custom_shacl_allowed: bool


def check_tier(api_key: str = "") -> TierStatus:
    """Check current tier status and whether a scan is allowed.

    Args:
        api_key: GraQle API key. Empty = free tier.

    Returns:
        TierStatus with current usage and whether scanning is allowed.
    """
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")

    if api_key:
        # Pro tier — validate API key format (actual validation via API)
        return TierStatus(
            tier="pro",
            scans_used=0,
            scans_limit=PRO_SCANS_PER_MONTH,
            month=current_month,
            can_scan=True,
            custom_shacl_allowed=True,
        )

    # Free tier — track local usage
    usage = _load_usage()
    month_usage = usage.get(current_month, 0)

    return TierStatus(
        tier="free",
        scans_used=month_usage,
        scans_limit=FREE_SCANS_PER_MONTH,
        month=current_month,
        can_scan=month_usage < FREE_SCANS_PER_MONTH,
        custom_shacl_allowed=False,
    )


def record_scan(api_key: str = "") -> None:
    """Record a scan against the current tier's usage.

    Only tracks for free tier (local file). Pro tier tracked server-side.
    """
    if api_key:
        return  # Pro tier tracked via API

    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    usage = _load_usage()
    usage[current_month] = usage.get(current_month, 0) + 1
    _save_usage(usage)


def _load_usage() -> dict[str, int]:
    """Load usage data from local file."""
    try:
        if _USAGE_FILE.exists():
            return json.loads(_USAGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        logger.debug("Failed to load usage file, starting fresh")
    return {}


def _save_usage(usage: dict[str, int]) -> None:
    """Save usage data to local file."""
    try:
        _USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _USAGE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(usage, indent=2), encoding="utf-8")
        tmp.replace(_USAGE_FILE)
    except Exception:
        logger.debug("Failed to save usage file")
