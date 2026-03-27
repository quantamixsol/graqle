"""Role-Based Access Control (RBAC) for governance gate.

Layer 3 — Actor identity model and permission matrix.

Compliance mapping:
  SOC2  CC6.2 — Access control: only authorized principals can approve T2/T3
  SOC2  CC6.1 — Responsibility assignment: roles define who approves what
  ISO27001 A.9.1.1 — Access control policy
  ISO27001 A.9.2.1 — User registration and de-registration

Design:
  - Roles are assigned offline (in governance policy config or graqle.yaml)
  - ActorToken is a signed HMAC-SHA256 token (role + actor_id + expiry)
  - The gate validates token signature before granting T2/T3 approval
  - No external auth service required — self-contained HMAC validation
  - Token signing key is loaded from env var or policy config (never hardcoded)

Roles:
  developer      — can approve T1 (auto-pass, role not checked)
  senior         — can approve T2 (medium-risk, bypass recorded)
  lead           — can approve T2 + T3 (high-risk, explicit approval required)
  admin          — can approve T2 + T3 + override cumulative cap
  ci_pipeline    — can approve T1 only (automated, no human approval)
  readonly       — can not approve anything (query-only access)

Usage::

    from graqle.core.rbac import ActorRegistry, ActorToken, RBACValidator

    registry = ActorRegistry()
    registry.register("alice", "lead")
    registry.register("ci-bot", "ci_pipeline")

    validator = RBACValidator(registry)
    ok, reason = validator.can_approve("alice", tier="T3")  # True
    ok, reason = validator.can_approve("ci-bot", tier="T2") # False
"""

# ── graqle:intelligence ──
# module: graqle.core.rbac
# risk: LOW (impact radius: 1 — governance.py)
# dependencies: hashlib, hmac, time, secrets, dataclasses, typing (stdlib only)
# constraints: MUST remain a pure stdlib leaf module — no graqle.* imports ever
# ── /graqle:intelligence ──

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Role definitions and permission matrix
# ---------------------------------------------------------------------------

#: Mapping from role name → set of tiers the role can approve
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "readonly":     frozenset(),                          # No approval authority
    "developer":    frozenset({"T1"}),                   # Auto-pass only
    "ci_pipeline":  frozenset({"T1"}),                   # Automated, no human approval
    "senior":       frozenset({"T1", "T2"}),             # Can approve medium-risk
    "lead":         frozenset({"T1", "T2", "T3"}),       # Can approve high-risk
    "admin":        frozenset({"T1", "T2", "T3"}),       # Full approval + cap override
}

#: Default role for unknown actors (conservative — no approval authority)
DEFAULT_ROLE = "developer"

#: Token expiry in seconds (default: 8 hours — one working day)
DEFAULT_TOKEN_TTL_SECONDS = 8 * 3600

#: Environment variable for HMAC signing key
_SIGNING_KEY_ENV = "GRAQLE_RBAC_SIGNING_KEY"


# ---------------------------------------------------------------------------
# Actor record
# ---------------------------------------------------------------------------

@dataclass
class Actor:
    """An actor in the governance system."""
    actor_id: str
    role: str
    email: str = ""
    display_name: str = ""
    created_at: float = field(default_factory=time.time)
    disabled: bool = False

    def can_approve(self, tier: str) -> bool:
        """Check if this actor can approve the given tier."""
        if self.disabled:
            return False
        perms = ROLE_PERMISSIONS.get(self.role, frozenset())
        return tier in perms

    def to_dict(self) -> dict:
        return {
            "actor_id": self.actor_id,
            "role": self.role,
            "email": self.email,
            "display_name": self.display_name,
            "disabled": self.disabled,
        }


# ---------------------------------------------------------------------------
# Signed token (HMAC-SHA256)
# ---------------------------------------------------------------------------

@dataclass
class ActorToken:
    """Signed, time-limited actor token.

    Format (after base64 decoding): JSON payload + "." + HMAC signature
    The signature covers: actor_id + role + issued_at + expires_at

    Tokens are used to verify that an `approved_by` field in a governance
    request was issued by an authorized actor, not spoofed.
    """
    actor_id: str
    role: str
    issued_at: float
    expires_at: float
    token_id: str = field(default_factory=lambda: secrets.token_hex(8))

    @classmethod
    def issue(
        cls,
        actor_id: str,
        role: str,
        signing_key: Optional[bytes] = None,
        ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS,
    ) -> tuple["ActorToken", str]:
        """Issue a new signed token.

        Returns (ActorToken, encoded_token_string).
        encoded_token_string can be stored/transmitted and verified later.
        """
        now = time.time()
        token = cls(
            actor_id=actor_id,
            role=role,
            issued_at=now,
            expires_at=now + ttl_seconds,
        )
        key = signing_key or _get_signing_key()
        encoded = token._encode(key)
        return token, encoded

    def _encode(self, signing_key: bytes) -> str:
        """Encode token to a verifiable string."""
        payload = json.dumps({
            "actor_id": self.actor_id,
            "role": self.role,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "token_id": self.token_id,
        }, separators=(",", ":"))
        sig = hmac.new(signing_key, payload.encode(), hashlib.sha256).hexdigest()
        import base64
        encoded_payload = base64.b64encode(payload.encode()).decode()
        return f"{encoded_payload}.{sig}"

    @classmethod
    def verify(
        cls,
        encoded: str,
        signing_key: Optional[bytes] = None,
    ) -> tuple[Optional["ActorToken"], str]:
        """Verify and decode a token.

        Returns (ActorToken, "") on success.
        Returns (None, error_reason) on failure.
        """
        try:
            import base64
            parts = encoded.split(".")
            if len(parts) != 2:
                return None, "Invalid token format"
            encoded_payload, provided_sig = parts
            payload_bytes = base64.b64decode(encoded_payload)
            payload = payload_bytes.decode()
            key = signing_key or _get_signing_key()
            expected_sig = hmac.new(key, payload_bytes, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected_sig, provided_sig):
                return None, "Token signature invalid — possible spoofing attempt"
            data = json.loads(payload)
            token = cls(
                actor_id=data["actor_id"],
                role=data["role"],
                issued_at=data["issued_at"],
                expires_at=data["expires_at"],
                token_id=data.get("token_id", ""),
            )
            if time.time() > token.expires_at:
                return None, f"Token expired for actor '{token.actor_id}'"
            return token, ""
        except Exception as exc:
            return None, f"Token decode error: {exc}"


def _get_signing_key() -> bytes:
    """Load HMAC signing key from environment or generate an ephemeral one.

    For production: set GRAQLE_RBAC_SIGNING_KEY to a 32+ byte hex string.
    For dev/test: an ephemeral key is generated at process start (tokens do
    not survive process restart — this is intentional for local dev).
    """
    raw = os.environ.get(_SIGNING_KEY_ENV, "")
    if raw:
        try:
            return bytes.fromhex(raw)
        except ValueError:
            return raw.encode()  # allow plain-text key for dev
    # Ephemeral key — valid only for this process lifetime
    return _EPHEMERAL_KEY


# Module-level ephemeral key (generated once per process start)
_EPHEMERAL_KEY: bytes = secrets.token_bytes(32)


# ---------------------------------------------------------------------------
# Actor registry
# ---------------------------------------------------------------------------

class ActorRegistry:
    """In-memory registry of actors and their roles.

    In production, populate from graqle.yaml [governance.rbac.actors] section.
    In CI, populate from environment variables (GRAQLE_RBAC_ACTORS_JSON).
    """

    def __init__(self) -> None:
        self._actors: dict[str, Actor] = {}
        self._load_from_env()

    def _load_from_env(self) -> None:
        """Load actors from GRAQLE_RBAC_ACTORS_JSON env var if set.

        Format: JSON array of {actor_id, role, email, display_name}
        """
        raw = os.environ.get("GRAQLE_RBAC_ACTORS_JSON", "")
        if not raw:
            return
        try:
            actors = json.loads(raw)
            for a in actors:
                self.register(
                    actor_id=a["actor_id"],
                    role=a.get("role", DEFAULT_ROLE),
                    email=a.get("email", ""),
                    display_name=a.get("display_name", ""),
                )
        except Exception:
            pass  # Malformed env var — start empty

    def register(
        self,
        actor_id: str,
        role: str,
        email: str = "",
        display_name: str = "",
    ) -> Actor:
        """Register an actor with a role."""
        if role not in ROLE_PERMISSIONS:
            raise ValueError(f"Unknown role '{role}'. Valid roles: {list(ROLE_PERMISSIONS)}")
        actor = Actor(actor_id=actor_id, role=role, email=email, display_name=display_name)
        self._actors[actor_id] = actor
        return actor

    def get(self, actor_id: str) -> Optional[Actor]:
        """Get actor by ID, or None if not registered."""
        return self._actors.get(actor_id)

    def disable(self, actor_id: str) -> None:
        """Disable an actor (revoke all approvals)."""
        if actor_id in self._actors:
            self._actors[actor_id].disabled = True

    def list_actors(self) -> list[dict]:
        return [a.to_dict() for a in self._actors.values()]


# ---------------------------------------------------------------------------
# RBAC Validator
# ---------------------------------------------------------------------------

class RBACValidator:
    """Validates actor approval authority for governance gate decisions.

    Used by GovernanceMiddleware to check whether `approved_by` has
    sufficient role to approve the requested tier.
    """

    def __init__(
        self,
        registry: Optional[ActorRegistry] = None,
        signing_key: Optional[bytes] = None,
    ) -> None:
        self._registry = registry or ActorRegistry()
        self._signing_key = signing_key

    def can_approve(self, actor_id: str, tier: str) -> tuple[bool, str]:
        """Check if actor can approve the given tier.

        Returns (allowed: bool, reason: str).
        Reason is empty string when allowed=True.

        If actor is not registered: use DEFAULT_ROLE (developer = T1 only).
        This is intentionally conservative — unknown actors cannot approve T2/T3.
        """
        if not actor_id:
            return False, "No actor_id provided — approval rejected for T2/T3"

        actor = self._registry.get(actor_id)
        if actor is None:
            # Unknown actor — default to developer role (T1 only)
            if tier == "T1":
                return True, ""
            return False, (
                f"Actor '{actor_id}' not registered in RBAC registry. "
                f"Only registered actors with role 'senior'/'lead'/'admin' can approve {tier}."
            )

        if actor.disabled:
            return False, f"Actor '{actor_id}' is disabled — approval rejected"

        if actor.can_approve(tier):
            return True, ""

        return False, (
            f"Actor '{actor_id}' (role: {actor.role}) does not have authority to approve {tier}. "
            f"Required role: senior (T2) or lead/admin (T3)."
        )

    def validate_token(self, encoded_token: str, required_tier: str) -> tuple[bool, str]:
        """Validate a signed ActorToken and check tier approval authority.

        Returns (valid: bool, reason: str).
        """
        token, err = ActorToken.verify(encoded_token, signing_key=self._signing_key)
        if token is None:
            return False, err

        # Check token actor against registry
        ok, reason = self.can_approve(token.actor_id, required_tier)
        if not ok:
            return False, reason

        return True, ""

    def resolve_actor(self, approved_by: str) -> Optional[Actor]:
        """Resolve approved_by string to an Actor.

        approved_by can be:
        - A plain actor_id ("alice", "ci-pipeline-123")
        - A signed token (starts with "eyJ" or contains ".")

        Returns Actor if resolved, None otherwise.
        """
        if not approved_by:
            return None

        # Try as signed token first
        if "." in approved_by and len(approved_by) > 50:
            token, err = ActorToken.verify(approved_by, signing_key=self._signing_key)
            if token:
                # Synthesize actor from token
                return Actor(
                    actor_id=token.actor_id,
                    role=token.role,
                    display_name=f"token:{token.token_id}",
                )

        # Try as plain actor_id
        return self._registry.get(approved_by)


# ---------------------------------------------------------------------------
# Convenience: global default validator (lazy-initialized)
# ---------------------------------------------------------------------------

_default_validator: Optional[RBACValidator] = None


def get_default_validator() -> RBACValidator:
    """Get or create the module-level default RBAC validator."""
    global _default_validator
    if _default_validator is None:
        _default_validator = RBACValidator()
    return _default_validator


def check_approval(actor_id: str, tier: str) -> tuple[bool, str]:
    """Convenience function: check if actor can approve tier using default validator."""
    return get_default_validator().can_approve(actor_id, tier)
