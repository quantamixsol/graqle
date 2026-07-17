"""GraQle License Manager — offline verification with HMAC signing.

License keys are self-contained: base64(json_payload).base64(hmac_sha256).
No network calls required for verification. Keys can be provided via:

1. ``COGNIGRAPH_LICENSE_KEY`` environment variable
2. ``~/.graqle/license.key`` file
3. ``graqle.license`` file in the working directory

If no valid license is found, the free tier is assumed.
"""

# ── graqle:intelligence ──
# module: graqle.licensing.manager
# risk: MEDIUM (impact radius: 3 modules)
# consumers: __init__, test_keygen, test_manager
# dependencies: __future__, asyncio, base64, hashlib, hmac +8 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar

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
        # Innovations 1-5 (core graph reasoning)
        "pcst_activation",
        "master_observer",
        "convergent_message_passing",
        "backend_fallback",
        "hierarchical_aggregation",
        # Innovations 6-13 (ungated for solo developers — v0.7.5)
        "semantic_shacl_gate",
        "debate_protocol",
        "explanation_trace",
        "constrained_f1",
        "ontology_generator",
        "adaptive_activation",
        "online_graph_learning",
        "lora_auto_selection",
        "tamr_connector",
        "multi_resolution_embeddings",
        "bayesian_edge_weighting",
        "domain_detection",
        # All MCP tools (ungated — v0.7.5)
        "mcp_context",
        "mcp_inspect",
        "mcp_reason",
        "mcp_preflight",
        "mcp_lessons",
        "mcp_impact",
        "mcp_checklist",
        "mcp_learn",
        # Workflow engine (session continuity, structured work, iteration loops)
        "workflow_engine",
        # Solo developer features (ungated — v0.7.5)
        "multi_backend_fallback",
        "tiered_backends",
        "session_analytics",
        "auto_grow_hook",
        "metrics_dashboard",
    },
    # PRO tier (ADR-244 composite triggers): the professional governance
    # surface. Feature constants only in CR-LIC-01 — no gating call sites yet;
    # enforcement lands in CR-LIC-03.
    LicenseTier.PRO: {
        "governance_suite",  # preflight, impact, review, predict, release_gate
        "ci_mode",  # headless/CI execution
        "multi_backend_debate",  # R15 debate + task routing
        "unlimited_learn",  # lessons beyond the free-tier cap
    },
    LicenseTier.TEAM: {
        "shared_kg_sync",
        "multi_instance_coordination",
        "cross_dev_lessons",
        "team_analytics",
        "custom_ontologies",
        # Cloud sync + Neptune "cloud_sync",
        "cloud_observability",
        "cloud_metrics",
        "shared_graph",
        "cross_repo",
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

# WS-D D1b: offline expiry grace window. Default 60 days (Harish Q-D2), overridable
# via GRAQLE_LICENSE_GRACE_DAYS. Covers offline/air-gapped installs that cannot
# refresh promptly; past it the licence is invalid.
_DEFAULT_GRACE_DAYS = 60


def _grace_delta() -> "timedelta":
    """The configured grace window as a timedelta (>= 0; bad/negative => default)."""
    raw = os.environ.get("GRAQLE_LICENSE_GRACE_DAYS")
    days = _DEFAULT_GRACE_DAYS
    if raw is not None:
        try:
            parsed = int(raw)
            if parsed >= 0:
                days = parsed
        except (TypeError, ValueError):
            pass  # malformed override => keep the safe default
    return timedelta(days=days)


def _as_utc_expiry(dt: "datetime") -> "datetime":
    """Normalise an expiry datetime to aware-UTC (naive assumed UTC).

    Defends the grace comparison against the naive/aware mismatch trap — a naive
    ``expires_at`` (e.g. parsed from a tz-less ISO string) would otherwise raise
    on comparison with ``now(timezone.utc)``.
    """
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# License dataclass
# ---------------------------------------------------------------------------

@dataclass
class License:
    """Represents a verified GraQle license."""

    tier: LicenseTier
    holder: str
    email: str
    issued_at: datetime
    expires_at: datetime | None = None  # ``None`` means perpetual
    features: set[str] = field(default_factory=set)
    # WS-D D1a: populated for ed25519 (v2) licences; None for legacy HMAC (v1).
    # license_id is the CRL revocation target; nonce drives replay protection;
    # kid is the signing key id (kid-revocation invalidates all its licences).
    license_id: str | None = None
    nonce: str | None = None
    kid: str | None = None

    # -- properties ----------------------------------------------------------

    @property
    def is_valid(self) -> bool:
        """Return ``True`` iff the licence is STRICTLY within its validity window.

        This keeps its long-standing meaning: expired (past ``expires_at``) ==
        invalid, with no grace. A perpetual licence (``expires_at is None``) is
        always valid. The WS-D D1b offline grace is a SEPARATE concept — see
        :attr:`in_grace` / :attr:`is_valid_or_in_grace`, which the manager's
        acceptance gate and ``current_tier`` use. Splitting them preserves the
        original ``is_valid`` contract (and its tests) while still delivering the
        grace allowance at the acceptance layer.
        """
        if self.expires_at is None:
            return True
        return datetime.now(timezone.utc) < _as_utc_expiry(self.expires_at)

    @property
    def in_grace(self) -> bool:
        """True iff the licence is PAST ``expires_at`` but still within the grace window.

        WS-D D1b: the grace is the offline-tolerance window AFTER strict expiry
        (default 60 days, ``GRAQLE_LICENSE_GRACE_DAYS``). ``is_valid`` stays
        STRICT (expired == invalid at ``expires_at``) — its long-standing meaning
        is preserved; grace is a SEPARATE allowance applied by the licence
        acceptance gate (:meth:`LicenseManager._accept_license`), not a silent
        redefinition of ``is_valid``.
        """
        if self.expires_at is None:
            return False
        now = datetime.now(timezone.utc)
        exp = _as_utc_expiry(self.expires_at)
        return exp <= now < exp + _grace_delta()

    @property
    def is_valid_or_in_grace(self) -> bool:
        """True iff the licence is strictly valid OR within the offline grace window."""
        return self.is_valid or self.in_grace

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

_license_logger = logging.getLogger("graqle.licensing.manager")


def _get_verification_key() -> bytes:
    """Load HMAC signing key from environment, with dev fallback."""
    env_val = os.environ.get("GRAQLE_LICENSE_KEY_SECRET")
    if env_val:
        return env_val.encode("utf-8")
    _license_logger.warning(
        "GRAQLE_LICENSE_KEY_SECRET not set — using dev fallback key. "
        "Set the env var in production (e.g. AWS Lambda config)."
    )
    return b"graqle-dev-fallback-rotate-2025Q3"


# WS-D D1a: the trusted ed25519 public-key manifest for licence verification.
# Cached so the manifest (and any PEM parse) happens once. Public material only —
# safe to ship in the Community wheel; it can verify but never sign/forge.
_trusted_license_manifest: "object | None" = None
_trusted_manifest_loaded = False


def _get_trusted_license_manifest():
    """Return the ed25519 ``Ed25519KeyManifest`` of trusted licence-signing keys.

    Sources, in order:
    1. ``GRAQLE_LICENSE_PUBLIC_KEYS`` env — JSON list of
       ``{kid, public_key_pem, valid_from, valid_until, state}`` (the production
       path; the deployer pins the trusted signer keys).
    2. A vendored manifest file ``graqle/licensing/trusted_keys.json`` if present
       (shipped public keys).
    3. ``None`` — no ed25519 trust configured; v2 verification yields ``None`` and
       the dual-verify path falls back to HMAC. (A Community user with no v2
       licence is unaffected.)

    Never raises: a malformed source logs a warning and yields ``None`` (fail
    closed — an unverifiable manifest must not be treated as trusting anything).
    """
    global _trusted_license_manifest, _trusted_manifest_loaded  # noqa: PLW0603
    if _trusted_manifest_loaded:
        return _trusted_license_manifest
    _trusted_manifest_loaded = True
    _trusted_license_manifest = _build_trusted_license_manifest()
    return _trusted_license_manifest


def _build_trusted_license_manifest():
    """Construct the trusted-key manifest from env or a vendored file (or None)."""
    import json as _json
    from datetime import datetime as _dt

    from graqle.governance.custody.ed25519_key_manifest import (
        Ed25519KeyManifest,
        KeyState,
    )
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    raw = os.environ.get("GRAQLE_LICENSE_PUBLIC_KEYS")
    if not raw:
        vendored = Path(__file__).with_name("trusted_keys.json")
        if vendored.exists():
            try:
                raw = vendored.read_text(encoding="utf-8")
            except OSError:
                raw = None
    if not raw:
        return None  # no ed25519 trust configured

    try:
        entries = _json.loads(raw)
        if not isinstance(entries, list):
            raise ValueError("trusted-keys source must be a JSON list")
        manifest = Ed25519KeyManifest()
        for e in entries:
            pub = load_pem_public_key(e["public_key_pem"].encode("utf-8"))
            manifest.register(
                kid=e["kid"],
                public_key=pub,
                valid_from=_dt.fromisoformat(e["valid_from"]),
                valid_until=_dt.fromisoformat(e["valid_until"]),
                state=KeyState(e.get("state", "active")),
            )
        return manifest
    except Exception as exc:  # noqa: BLE001 — fail closed on a bad manifest
        _license_logger.warning(
            "GRAQLE_LICENSE_PUBLIC_KEYS / trusted_keys.json could not be parsed; "
            "ed25519 licence verification disabled (falling back to HMAC). cause: %s",
            exc,
        )
        return None


# WS-D D1d: the active (verified) CRL. Loaded from GRAQLE_LICENSE_CRL (a signed
# CRL token) or a vendored graqle/licensing/crl.token file; verified against the
# trusted manifest. Cached. None => no CRL configured => nothing is CRL-revoked.
_active_crl: "object | None" = None
_active_crl_loaded = False


def _get_active_crl():
    """Return the verified :class:`RevocationList` (or None). Cached; fail-closed."""
    global _active_crl, _active_crl_loaded  # noqa: PLW0603
    if _active_crl_loaded:
        return _active_crl
    _active_crl_loaded = True
    _active_crl = _build_active_crl()
    return _active_crl


def _build_active_crl():
    """Load + verify the configured CRL token against the trusted manifest, or None."""
    token = os.environ.get("GRAQLE_LICENSE_CRL")
    if not token:
        vendored = Path(__file__).with_name("crl.token")
        if vendored.exists():
            try:
                token = vendored.read_text(encoding="utf-8").strip()
            except OSError:
                token = None
    if not token:
        return None
    manifest = _get_trusted_license_manifest()
    if manifest is None:
        # A CRL we cannot verify must NOT be trusted (it could be a forged
        # all-empty CRL that un-revokes everything). No manifest => no CRL.
        _license_logger.warning(
            "a CRL is configured but no trusted manifest is available to verify it; "
            "ignoring the CRL (cannot trust an unverifiable revocation list)"
        )
        return None
    try:
        from graqle.licensing.crl import verify_crl

        # min_sequence -1 accepts any non-negative sequence on first load. (A
        # persistent last-accepted-sequence store is a future hardening; the
        # signature + monotonic body already block a downgraded forgery.)
        return verify_crl(token, manifest, min_sequence=-1)
    except Exception:  # noqa: BLE001 — unverifiable CRL => fail closed to "no CRL"
        _license_logger.warning("CRL could not be verified; ignoring it", exc_info=True)
        return None


# WS-D D1c: the licence nonce store (replay protection). OFF by default — it
# writes to disk, and most installs don't need per-nonce replay defence. Opt in
# by setting GRAQLE_LICENSE_NONCE_DIR to a writable directory.
_nonce_store: "object | None" = None
_nonce_store_loaded = False


def _get_nonce_store():
    """Return the configured :class:`LicenseNonceStore` (or None if disabled)."""
    global _nonce_store, _nonce_store_loaded  # noqa: PLW0603
    if _nonce_store_loaded:
        return _nonce_store
    _nonce_store_loaded = True
    directory = os.environ.get("GRAQLE_LICENSE_NONCE_DIR")
    if not directory:
        _nonce_store = None
        return None
    try:
        from graqle.licensing.nonce_store import LicenseNonceStore

        _nonce_store = LicenseNonceStore(directory)
    except Exception:  # noqa: BLE001 — a broken store must not block licence load
        _license_logger.warning("nonce store init failed; replay protection off", exc_info=True)
        _nonce_store = None
    return _nonce_store


class LicenseManager:
    """Offline license verification.  No phone-home, no telemetry."""

    def __init__(self) -> None:
        self._license: License | None = None
        self._load_license()

    # -- loading -------------------------------------------------------------

    def _load_license(self) -> None:
        """Attempt to load a license key from known locations.

        Each candidate key is cryptographically verified (:meth:`_verify_key`),
        then passed through :meth:`_accept_license` which applies the WS-D
        post-verify gates (expiry+grace, CRL revocation, nonce replay). Only a
        licence that passes ALL gates is accepted; otherwise the search continues
        and ultimately falls back to the free tier.
        """
        for key in self._candidate_keys():
            lic = self._accept_license(self._verify_key(key))
            if lic is not None:
                self._license = lic
                return
        # No valid license — default to free tier.
        self._license = None

    @staticmethod
    def _candidate_keys() -> "list[str]":
        """Yield licence-key strings from the known locations, in priority order."""
        keys: list[str] = []
        env = os.environ.get("COGNIGRAPH_LICENSE_KEY")
        if env:
            keys.append(env)
        for path in (Path.home() / ".graqle" / "license.key", Path("graqle.license")):
            try:
                if path.exists():
                    keys.append(path.read_text(encoding="utf-8").strip())
            except OSError:
                continue  # unreadable file => skip, try the next source
        return keys

    def _accept_license(self, lic: "License | None") -> "License | None":
        """Apply WS-D post-verify gates; return the licence iff it passes all.

        Gates (each fail-closed → return None → caller falls back to free tier):
        1. **expiry + grace** — ``lic.is_valid`` (D1b: valid until expiry + grace).
        2. **CRL revocation** — if a trusted CRL is configured and lists this
           ``license_id``, reject (D1d). No CRL configured => not revoked.
        3. **nonce replay** — if a nonce store is configured, the licence's nonce
           must be accept-once; a replayed nonce is rejected (D1c). Legacy HMAC
           licences (no nonce) skip this gate.

        A gate failure NEVER raises — it degrades to "no valid licence".
        """
        if lic is None:
            return None
        try:
            if not lic.is_valid_or_in_grace:
                return None
            if lic.license_id is not None:
                crl = self._get_active_crl()
                if crl is not None and crl.is_revoked(lic.license_id):
                    _license_logger.warning(
                        "licence %s is revoked by CRL (seq=%s); falling back to free tier",
                        lic.license_id, crl.sequence,
                    )
                    return None
            if lic.nonce is not None:
                store = self._get_nonce_store()
                if store is not None and not store.accept_once(lic.nonce):
                    _license_logger.warning(
                        "licence nonce replay detected (license_id=%s); rejecting",
                        lic.license_id,
                    )
                    return None
            return lic
        except Exception:  # noqa: BLE001 — any gate fault fails closed to free tier
            _license_logger.warning("licence post-verify gate errored; failing closed", exc_info=True)
            return None

    @staticmethod
    def _get_active_crl():
        """Load + verify the configured CRL (or None). Cached at module level."""
        return _get_active_crl()

    @staticmethod
    def _get_nonce_store():
        """Return the configured nonce store (or None if replay-protection off)."""
        return _get_nonce_store()

    # -- verification --------------------------------------------------------

    def _verify_key(self, key: str) -> License | None:
        """Verify a licence key offline. Dual-format (WS-D D1a).

        Dispatches by wire shape — ed25519 v2 (``payload.kid.sig``, 3 dot-parts)
        is tried FIRST; the legacy HMAC v1 (``payload.sig``, 2 parts) is the
        back-compat fallback for licences issued before the ed25519 migration.

        ed25519 is asymmetric: the Community wheel verifies with a PUBLIC key it
        cannot forge with (the private signing key stays server-side). HMAC is
        symmetric and is retained only for a deprecation window — new licences are
        issued as v2. Returns a :class:`License` on success, ``None`` otherwise.
        """
        if isinstance(key, str) and key.count(".") == 2:
            lic = self._verify_key_ed25519(key)
            if lic is not None:
                return lic
            # fall through: a malformed v2-shaped token is not a valid v1 either,
            # but try HMAC anyway (cheap) so a genuine v1 key is never rejected on
            # shape alone if the format tag was absent.
        return self._verify_key_hmac(key)

    def _verify_key_ed25519(self, key: str) -> License | None:
        """Verify an ed25519 (v2) licence against the trusted public-key manifest.

        Composes :func:`graqle.licensing.ed25519_license.verify_ed25519_license`
        (signature + kid-revocation + kid-window) and maps the trusted payload to
        a :class:`License`. Returns ``None`` for any untrusted/forged/malformed
        token, or if no trusted manifest is configured. Fails closed.
        """
        try:
            from graqle.licensing.ed25519_license import verify_ed25519_license

            manifest = _get_trusted_license_manifest()
            if manifest is None:
                return None
            payload = verify_ed25519_license(key, manifest)
            if payload is None:
                return None
            return License(
                tier=LicenseTier(payload["tier"]),
                holder=payload.get("holder", "Unknown"),
                email=payload.get("email", ""),
                issued_at=datetime.fromisoformat(payload["issued_at"]),
                expires_at=(
                    datetime.fromisoformat(payload["expires_at"])
                    if payload.get("expires_at")
                    else None
                ),
                features=set(payload.get("features", [])),
                license_id=payload.get("license_id"),
                nonce=payload.get("nonce"),
                kid=payload.get("kid"),
            )
        except Exception:  # noqa: BLE001 — untrusted input, fail closed to None
            return None

    def _verify_key_hmac(self, key: str) -> License | None:
        """Verify a legacy HMAC-SHA256 (v1) licence key.

        Key format::

            base64url(json_payload).base64url(hmac_sha256_signature)

        DEPRECATED (WS-D): symmetric — retained only for the back-compat window.
        Returns a :class:`License` on success or ``None`` on failure.
        """
        try:
            # WS-D security gate (sentinel graq_predict vector #4): the HMAC
            # secret's dev FALLBACK is a public literal that ships in the
            # Community wheel. If no REAL secret is configured
            # (GRAQLE_LICENSE_KEY_SECRET unset), the only available key is that
            # public fallback — so an attacker could forge a v1 licence and slip
            # it through the dual-verify fallback. Refuse to verify v1 in that
            # case: a genuine legacy v1 customer licence was signed with the
            # PRODUCTION secret, so verifying it legitimately REQUIRES that secret
            # to be set (server-side). No real secret => no HMAC trust.
            if not os.environ.get("GRAQLE_LICENSE_KEY_SECRET"):
                return None

            if not isinstance(key, str) or not key:
                return None  # explicit type guard (defence-in-depth; also fail-closed)

            parts = key.split(".")
            if len(parts) != 2:
                return None

            payload_b64, sig_b64 = parts

            # base64url decode (pad as needed)
            payload_bytes = base64.urlsafe_b64decode(payload_b64 + "==")
            signature = base64.urlsafe_b64decode(sig_b64 + "==")

            # Verify HMAC
            expected = hmac.new(
                _get_verification_key(),
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
        """Return the active license tier (defaults to FREE).

        WS-D D1b: honours the offline grace window — a licence that is strictly
        valid OR within grace reports its tier. (``self._license`` is only set by
        ``_load_license`` after passing the full acceptance gate, so a present
        licence here is already CRL/nonce-clean; this guard re-confirms only the
        time validity, now grace-aware.)
        """
        if self._license is not None and self._license.is_valid_or_in_grace:
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
            f"Feature '{feature}' requires GraQle {tier_label}. "
            f"Current tier: {self.current_tier.value.title()}. "
            f"Upgrade at https://graqle.com/pricing"
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
            _get_verification_key(),
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
