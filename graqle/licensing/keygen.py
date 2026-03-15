"""Internal tool for generating Graqle license keys.

Usage::

    python -m graqle.licensing.keygen <tier> <holder> <email> [duration_days]

Examples::

    # Perpetual pro license
    python -m graqle.licensing.keygen pro "Acme Corp" admin@acme.com

    # 365-day team license
    python -m graqle.licensing.keygen team "Acme Corp" admin@acme.com 365

.. warning::

    This module embeds the HMAC signing secret.  It must **never** be
    distributed to end users.  Keep it in the internal tooling repository only.
"""

# ── graqle:intelligence ──
# module: graqle.licensing.keygen
# risk: LOW (impact radius: 1 modules)
# consumers: test_keygen
# dependencies: __future__, sys, datetime
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone


def generate_license_key(
    tier: str,
    holder: str,
    email: str,
    duration_days: int | None = None,
) -> str:
    """Generate a signed Graqle license key.

    Parameters
    ----------
    tier:
        One of ``free``, ``pro``, ``team``, ``enterprise``.
    holder:
        Name of the individual or organisation.
    email:
        Contact email for the license holder.
    duration_days:
        Number of days until expiry.  ``None`` for a perpetual license.

    Returns
    -------
    str
        The signed license key string.
    """
    from graqle.licensing.manager import LicenseManager

    expires: str | None = None
    if duration_days is not None:
        expires = (
            datetime.now(timezone.utc) + timedelta(days=duration_days)
        ).isoformat()

    return LicenseManager.generate_key(tier, holder, email, expires)


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < 4:
        print(
            "Usage: python -m graqle.licensing.keygen "
            "<tier> <holder> <email> [duration_days]"
        )
        print()
        print("Tiers: free, pro, team, enterprise")
        print("Duration: number of days (omit for perpetual)")
        sys.exit(1)

    tier = sys.argv[1]
    holder = sys.argv[2]
    email = sys.argv[3]
    days = int(sys.argv[4]) if len(sys.argv) > 4 else None

    key = generate_license_key(tier, holder, email, days)
    print(f"License Key ({tier}):")
    print(key)


if __name__ == "__main__":
    main()
