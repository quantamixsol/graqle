"""Reasoning-quota wall (W3, ADR-245) — free monthly cap on graph reasoning.

Free tier gets a bounded number of ``graq run`` / ``graq reason`` invocations per
calendar month; paid tiers (Pro/Team/Enterprise) are unlimited. This is the
*reasoning-frequency* wall in the multi-wall lattice — independent of the node-cap
(size) wall, so a user who stays under the node cap still hits this if they reason a lot.

Design (consistent with ADR-245 + CR-LIC-03a/03b):
  - Tier comes from the VERIFIED licence (``manager.current_tier``), never a raw env/key
    presence — an unverified signal must never grant a paid entitlement (CR-LIC-03b rule).
  - Enforcement is ON BY DEFAULT; ``GRAQLE_ENFORCE_CAPS`` is an OPT-OUT only (shared with
    the node-cap wall). "User sets a flag to be enforced" would be a trivial bypass.
  - The count is per calendar month, persisted locally in ``.graqle/reasoning_quota.json``.
    Local enforcement is the offline bar (the standard freemium wall); a determined user
    can delete the file — server-side accounting is the un-bypassable upgrade (separate CR).
  - INTERNAL reasoning (e.g. a PR-Guardian scan that calls reason under the hood) is
    EXEMPT via ``internal=True`` so W2 and W3 never double-charge one user action.
  - Fail-open on any metering error: a quota-file hiccup must never break reasoning.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("graqle.licensing.reasoning_quota")

__all__ = [
    "FREE_REASONS_PER_MONTH",
    "QUOTA_FILENAME",
    "ReasoningQuotaExceeded",
    "ReasoningQuota",
    "quota_enforcement_enabled",
]

QUOTA_FILENAME = "reasoning_quota.json"
FREE_REASONS_PER_MONTH = 30  # generous enough to try; paid = unlimited
_SCHEMA_VERSION = 1

# Shared opt-out flag with the node-cap wall (ADR-245): enforcement is ON by default.
_ENFORCE_ENV = "GRAQLE_ENFORCE_CAPS"
_FALSY = frozenset({"0", "false", "no", "off", ""})


class ReasoningQuotaExceeded(Exception):
    """Raised when a FREE user exceeds the monthly reasoning quota."""

    def __init__(self, used: int, limit: int, month: str) -> None:
        super().__init__(
            f"reasoning quota reached: {used}/{limit} this month ({month})"
        )
        self.used = used
        self.limit = limit
        self.month = month


def quota_enforcement_enabled() -> bool:
    """True unless explicitly opted out (GRAQLE_ENFORCE_CAPS=falsy). Default ON."""
    raw = os.environ.get(_ENFORCE_ENV)
    if raw is None:
        return True
    return raw.strip().lower() not in _FALSY


def _paid_tier() -> bool:
    """True iff the VERIFIED licence is a paid tier (Pro/Team/Enterprise).

    Uses manager.current_tier (paid only from a signature+CRL+nonce-verified licence);
    never a raw env/key (CR-LIC-03b). Fail-safe: any error → treat as FREE (enforce).
    """
    try:
        from graqle.licensing.manager import LicenseTier, _get_manager

        return _get_manager().current_tier in (
            LicenseTier.PRO,
            LicenseTier.TEAM,
            LicenseTier.ENTERPRISE,
        )
    except Exception:  # noqa: BLE001
        return False


@dataclass
class QuotaReading:
    used: int
    limit: int          # -1 = unlimited (paid)
    month: str
    allowed: bool


class ReasoningQuota:
    """Per-month local reasoning-quota meter under a project's ``.graqle`` dir."""

    def __init__(self, graqle_dir: Path | str) -> None:
        self._path = Path(graqle_dir) / QUOTA_FILENAME

    def _load(self) -> dict:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            logger.debug("reasoning quota file unreadable — treating as empty")
        return {}

    def _store(self, data: dict) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self._path)
        except Exception:
            logger.debug("could not persist reasoning quota (read-only fs?)")

    @staticmethod
    def _month() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def peek(self) -> QuotaReading:
        """Current usage without recording. Paid → unlimited/allowed."""
        month = self._month()
        if _paid_tier():
            return QuotaReading(used=0, limit=-1, month=month, allowed=True)
        used = int(self._load().get(month, 0) or 0)
        return QuotaReading(
            used=used,
            limit=FREE_REASONS_PER_MONTH,
            month=month,
            allowed=used < FREE_REASONS_PER_MONTH,
        )

    def check_and_record(self, *, internal: bool = False) -> QuotaReading:
        """Enforce + record ONE reasoning invocation.

        Parameters
        ----------
        internal:
            When True (reasoning invoked by another metered action, e.g. a PR-Guardian
            scan), the call is EXEMPT — not counted, never blocked. Prevents W2/W3
            double-charging one user action.

        Raises
        ------
        ReasoningQuotaExceeded
            when enforcement is on, the tier is FREE, and the monthly quota is used up.

        Never raises on a metering/file error — reasoning must not break on a quota
        hiccup (fail-open).
        """
        if internal or not quota_enforcement_enabled() or _paid_tier():
            return self.peek()
        try:
            month = self._month()
            data = self._load()
            used = int(data.get(month, 0) or 0)
            if used >= FREE_REASONS_PER_MONTH:
                raise ReasoningQuotaExceeded(used, FREE_REASONS_PER_MONTH, month)
            data[month] = used + 1
            data["schema_version"] = _SCHEMA_VERSION
            self._store(data)
            return QuotaReading(
                used=used + 1,
                limit=FREE_REASONS_PER_MONTH,
                month=month,
                allowed=True,
            )
        except ReasoningQuotaExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 — never break reasoning on a meter fault
            logger.debug("reasoning quota metering skipped: %s", exc)
            return QuotaReading(
                used=0, limit=FREE_REASONS_PER_MONTH, month=self._month(), allowed=True
            )
