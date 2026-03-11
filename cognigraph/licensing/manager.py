"""CogniGraph License Manager — offline verification with HMAC signing.

License keys are self-contained: base64(json_payload).base64(hmac_sha256).
No network calls required for verification. Keys can be provided via:

1. ``COGNIGRAPH_LICENSE_KEY`` environment variable
2. ``~/.cognigraph/license.key`` file
3. ``cognigraph.license`` file in the working directory

If no valid license is found, the free tier is assumed.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Callable, TypeVar, Any

F = TypeVar("F", bound=Callable[..., Any])


# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

class LicenseTier(str, Enum):
    """License tiers in ascending order of capability."""

    FREE = "free"
    PRO = "pro"
    TEAM = "team"
    ENTERPRISE = "enterprise"


# Features gated by tier.  Each tier's set contains *only* the features
# introduced at that tier — cumulative resolution happens in License.all_features.
TIER_FEATURES: dict[LicenseTier, set[str]] = {
    LicenseTier.FREE: {
        # Innovations 1-5 (always free)
        "pcst_activation",
        "master_observer",
        "convergent_message_passing",
        "backend_fallback",
        "hierarchical_aggregation",
        # Basic MCP tools
        "mcp_context",
        "mcp_inspect",
        "mcp_reason",
        # GCC / GSD / Ralph (always free — the hook)
        "gcc_protocol",
        "gsd_protocol",
        "ralph_loop",
    },
    LicenseTier.PRO: {
        # Innovations 6-13
        "semantic_shacl_gate",
        "constrained_f1",
        "ontology_generator",
        "adaptive_activation",
        "online_graph_learning",
        "lora_auto_selection",
        "tamr_connector",
        # Advanced MCP tools
        "mcp_preflight",
        "mcp_lessons",
        "mcp_impact",
        "mcp_checklist",
        "mcp_learn",
        # Pro features
        "multi_backend_fallback",
        "tiered_backends",
        "session_analytics",
    },
    LicenseTier.TEAM: {
        "shared_kg_sync",
        "multi_instance_coordination",
        "cross_dev_lessons",
        "team_analytics",
        "custom_ontologies",
    },
    LicenseTier.ENTERPRISE: {
        "private_deployment",
        "compliance_reporting",
        "sla_support",
        "custom_integrations",
        "audit_trail",
    },
}

# Pre-compute the ordered list for cumulative lookups.
_TIER_ORDER: list[LicenseTier] = list(LicenseTier)


# ---------------------------------------------------------------------------
# License dataclass
# ---------------------------------------------------------------------------

@dataclass
class License:
    """Represents a verified CogniGraph license."""

    tier: LicenseTier
    holder: str
    email: str
    issued_at: datetime
    expires_at: datetime | None = None  # ``None`` means perpetual
    features: set[str] = field(default_factory=set)

    # -- properties ----------------------------------------------------------

    @property
    def is_valid(self) -> bool:
        """Return ``True`` if the license has not expired."""
        if self.expires_at is None:
            return True
        return datetime.now(timezone.utc) < self.expires_at

    @property
    def all_features(self) -> set[str]:
        """All features available — cumulative tier features plus explicit extras."""
        cumulative: set[str] = set()
        for tier in _TIER_ORDER:
            cumulative |= TIER_FEATURES.get(tier, set())
            if tier == self.tier:
                break
        return cumulative | self.features


# ---------------------------------------------------------------------------
# License manager
# ---------------------------------------------------------------------------

class LicenseManager:
    """Offline license verification.  No phone-home, no telemetry."""

    # HMAC key for license-key verification.
    # A production deployment may swap this for RSA public-key verification.
    _VERIFICATION_KEY: bytes = b"cognigraph-quantamix-2026"

    def __init__(self) -> None:
        self._license: License | None = None
        self._load_license()

    # -- loading -------------------------------------------------------------

    def _load_license(self) -> None:
        """Attempt to load a license key from known locations."""
        # 1. Environment variable
        key = os.environ.get("COGNIGRAPH_LICENSE_KEY")
        if key:
            self._license = self._verify_key(key)
            if self._license is not None:
                return

        # 2. User-level license file
        license_path = Path.home() / ".cognigraph" / "license.key"
        if license_path.exists():
            key = license_path.read_text(encoding="utf-8").strip()
            self._license = self._verify_key(key)
            if self._license is not None:
                return

        # 3. Project-level license file
        local_path = Path("cognigraph.license")
        if local_path.exists():
            key = local_path.read_text(encoding="utf-8").strip()
            self._license = self._verify_key(key)
            if self._license is not None:
                return

        # No valid license — default to free tier.
        self._license = None

    # -- verification --------------------------------------------------------

    def _verify_key(self, key: str) -> License | None:
        """Verify a license key offline using HMAC-SHA256.

        Key format::

            base64url(json_payload).base64url(hmac_sha256_signature)

        Returns a :class:`License` on success or ``None`` on failure.
        """
        try:
            parts = key.split(".")
            if len(parts) != 2:
                return None

            payload_b64, sig_b64 = parts

            # base64url decode (pad as needed)
            payload_bytes = base64.urlsafe_b64decode(payload_b64 + "==")
            signature = base64.urlsafe_b64decode(sig_b64 + "==")

            # Verify HMAC
            expected = hmac.new(
                self._VERIFICATION_KEY,
                payload_bytes,
                hashlib.sha256,
            ).digest()

            if not hmac.compare_digest(signature, expected):
                return None

            # Parse the JSON payload
            data: dict = json.loads(payload_bytes)

            return License(
                tier=LicenseTier(data["tier"]),
                holder=data.get("holder", "Unknown"),
                email=data.get("email", ""),
                issued_at=datetime.fromisoformat(data["issued_at"]),
                expires_at=(
                    datetime.fromisoformat(data["expires_at"])
                    if data.get("expires_at")
                    else None
                ),
                features=set(data.get("features", [])),
            )
        except Exception:  # noqa: BLE001 — intentionally broad for untrusted input
            return None

    # -- public API ----------------------------------------------------------

    @property
    def current_tier(self) -> LicenseTier:
        """Return the active license tier (defaults to FREE)."""
        if self._license is not None and self._license.is_valid:
            return self._license.tier
        return LicenseTier.FREE

    @property
    def license(self) -> License | None:
        """Return the current :class:`License` or ``None``."""
        return self._license

    def has_feature(self, feature: str) -> bool:
        """Return ``True`` if *feature* is available under the current license."""
        # Free-tier features are always available.
        if feature in TIER_FEATURES[LicenseTier.FREE]:
            return True
        if self._license is not None and self._license.is_valid:
            return feature in self._license.all_features
        return False

    def check_feature(self, feature: str) -> None:
        """Raise :class:`LicenseError` if *feature* is not available."""
        if self.has_feature(feature):
            return

        # Determine which tier introduces this feature.
        required_tier: LicenseTier | None = None
        for tier in _TIER_ORDER:
            if feature in TIER_FEATURES.get(tier, set()):
                required_tier = tier
                break

        tier_label = required_tier.value.title() if required_tier else "Pro"
        raise LicenseError(
            f"Feature '{feature}' requires CogniGraph {tier_label}. "
            f"Current tier: {self.current_tier.value.title()}. "
            f"Upgrade at https://cognigraph.dev/pricing"
        )

    # -- key generation (internal) -------------------------------------------

    @staticmethod
    def generate_key(
        tier: str,
        holder: str,
        email: str,
        expires_at: str | None = None,
        extra_features: list[str] | None = None,
    ) -> str:
        """Generate a signed license key.

        .. warning:: This method is for internal/admin use only.  Do not
           expose the verification key in client-distributed builds.

        Parameters
        ----------
        tier:
            One of ``free``, ``pro``, ``team``, ``enterprise``.
        holder:
            Name of the individual or organisation.
        email:
            Contact email for the license holder.
        expires_at:
            ISO-8601 expiry timestamp, or ``None`` for perpetual.
        extra_features:
            Additional feature flags beyond the tier defaults.

        Returns
        -------
        str
            The signed license key in ``payload.signature`` format.
        """
        payload: dict = {
            "tier": tier,
            "holder": holder,
            "email": email,
            "issued_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": expires_at,
            "features": extra_features or [],
        }
        payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()

        signature = hmac.new(
            LicenseManager._VERIFICATION_KEY,
            payload_bytes,
            hashlib.sha256,
        ).digest()
        sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

        return f"{payload_b64}.{sig_b64}"


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class LicenseError(Exception):
    """Raised when a feature requires a higher license tier."""


# ---------------------------------------------------------------------------
# Module-level convenience API (singleton)
# ---------------------------------------------------------------------------

_manager: LicenseManager | None = None


def _get_manager() -> LicenseManager:
    """Return (and lazily create) the module-level :class:`LicenseManager`."""
    global _manager  # noqa: PLW0603
    if _manager is None:
        _manager = LicenseManager()
    return _manager


def check_license(feature: str) -> None:
    """Check if *feature* is available.  Raises :class:`LicenseError` if not."""
    _get_manager().check_feature(feature)


def has_feature(feature: str) -> bool:
    """Return ``True`` if *feature* is available under the current license."""
    return _get_manager().has_feature(feature)


def require_license(feature: str) -> Callable[[F], F]:
    """Decorator that gates a sync or async function behind a license feature.

    Example::

        @require_license("ontology_generator")
        def generate_ontology(graph):
            ...

        @require_license("tamr_connector")
        async def connect_tamr(endpoint):
            ...
    """

    def decorator(func: F) -> F:
        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                check_license(feature)
                return await func(*args, **kwargs)

            return async_wrapper  # type: ignore[return-value]

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            check_license(feature)
            return func(*args, **kwargs)

        return sync_wrapper  # type: ignore[return-value]

    return decorator  # type: ignore[return-value]
