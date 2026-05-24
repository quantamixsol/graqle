"""ed25519 signing-key manifest with a validity window (R25-EU01 Task 1.7 / C-P2-1).

Layer 5 proof bundles carry ``signature = {alg: ed25519, kid, sig}`` (R25-EU01
§"signature"). A ``kid`` (key id, e.g. ``graqle-sdk-signing-2026-Q2``) is rotated
on a schedule, so the manifest must let a verifier decide whether a given ``kid``
was *trusted to sign* at the time a proof was produced — long after the active
key has moved on.

C-P2-1 (ADR-RT-002 §4.4 / ADR-RT-003 §11.2 PR-7) models that with two things per
key:

* a **validity window** ``valid_from`` / ``valid_until`` (UTC), and
* a three-state **lifecycle**::

      ACTIVE  ── retire() ──▶  RETIRED  ── revoke() ──▶  REVOKED
        │                                                  ▲
        └────────────────── revoke() ──────────────────────┘

  | state    | can sign | verify-trusted (within window) |
  |----------|----------|--------------------------------|
  | ACTIVE   | yes      | yes                            |
  | RETIRED  | no       | yes  (historical proofs only)  |
  | REVOKED  | no       | NO   (key compromised)         |

The lifecycle is **monotonic** (like the layer-status monotonic-on rule): a key
can only move forward ACTIVE → RETIRED → REVOKED (or jump ACTIVE → REVOKED on an
emergency compromise). It can never move back — a ``REVOKED`` key is dead, and
re-activating a retired key would silently re-open a closed signing window. This
mirrors ``layer_status.monotonic_on``: once you tighten custody you do not loosen
it without re-instantiating the key.

**Verify semantics (the security-critical part).** ``verify`` accepts a proof's
signature iff ALL of:

1. the ``kid`` is known to the manifest,
2. the key is ACTIVE or RETIRED (REVOKED is rejected unconditionally — a revoked
   key's *past* signatures are no longer trusted, the conservative default; the
   spec line for C-P2-1 is "kid rotation → valid_from/valid_until in key
   manifest", and revocation is the compromise escape hatch),
3. the verification instant ``at`` falls within ``[valid_from, valid_until]``,
   and
4. the ed25519 signature is cryptographically valid for the message.

``sign`` additionally requires the key be ACTIVE and hold a private key.

The actual ed25519 primitives come from ``cryptography`` (a core dependency), so
this module needs no optional extras and runs in CI unconditionally.

Private-key handling (known limitation). Private keys are held in a process-local
dict, separate from the public, shareable :class:`KeyEntry`, and are dropped on
:meth:`Ed25519KeyManifest.retire` / :meth:`Ed25519KeyManifest.revoke` (a key that
may not sign keeps no signing material). This module deliberately does NOT attempt
in-memory zeroization of key bytes: CPython provides no guaranteed memory wipe and
``cryptography``'s ``Ed25519PrivateKey`` does not expose its raw bytes for
overwriting, so any "zeroization" here would be security theater. Deployments that
need hardware-backed key custody should supply a private key from an HSM/KMS via a
signing callback — out of scope for the C-P2-1 validity-window manifest, which
governs *which kid is trusted when*, not at-rest key protection.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from graqle.governance.tamper_evidence.errors import TamperEvidenceError

__all__ = [
    "KeyState",
    "KeyEntry",
    "Ed25519KeyManifest",
    "KeyManifestError",
]


class KeyManifestError(TamperEvidenceError):
    """Base class for key-manifest errors (unknown kid, illegal transition, …)."""


class UnknownKidError(KeyManifestError, KeyError):
    """The requested ``kid`` is not registered in the manifest.

    Subclasses ``KeyError`` so ``except KeyError`` callers catch it naturally.
    """

    def __init__(self, kid: str) -> None:
        self.kid = kid
        super().__init__(f"unknown key id {kid!r}: not registered in the manifest")


class IllegalKeyTransitionError(KeyManifestError):
    """An attempt to move a key backwards in the lifecycle (e.g. un-revoke)."""

    def __init__(self, kid: str, current: KeyState, requested: KeyState) -> None:
        self.kid = kid
        self.current = current
        self.requested = requested
        super().__init__(
            f"illegal key transition for {kid!r}: {current.value} → "
            f"{requested.value}. The key lifecycle is monotonic "
            f"(ACTIVE → RETIRED → REVOKED); a key never moves backwards."
        )


class KeyNotSignableError(KeyManifestError):
    """A signing request targeted a key that may not (or cannot) sign."""


class KeyState(enum.Enum):
    """Lifecycle state of a signing key (monotonic ACTIVE → RETIRED → REVOKED)."""

    ACTIVE = "active"
    RETIRED = "retired"
    REVOKED = "revoked"


# Rank used to enforce monotonic forward-only transitions.
_STATE_RANK = {KeyState.ACTIVE: 0, KeyState.RETIRED: 1, KeyState.REVOKED: 2}


def _as_utc(dt: datetime) -> datetime:
    """Normalise a datetime to timezone-aware UTC.

    A naive datetime is assumed to be UTC (the manifest's canonical zone); an
    aware datetime is converted. This keeps all window comparisons total-ordered
    and avoids the "can't compare naive and aware" trap that silently breaks
    validity checks.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class KeyEntry:
    """One signing key's identity, public material, window, and lifecycle state.

    Frozen: a key's immutable facts (its id, public key, and validity window) do
    not change. The *state* changes only through the manifest's monotonic
    :meth:`Ed25519KeyManifest.retire` / :meth:`Ed25519KeyManifest.revoke`, which
    replace the entry with a new frozen copy rather than mutating it — so a stale
    reference can never silently observe a state downgrade.

    Attributes
    ----------
    kid:
        Key id (the ``kid`` field of a proof signature).
    public_key:
        The ed25519 public key, used for verification.
    valid_from, valid_until:
        UTC validity window. A proof signed/verified outside this window is not
        trusted even if the signature is cryptographically valid.
    state:
        Current :class:`KeyState`.
    """

    kid: str
    public_key: Ed25519PublicKey
    valid_from: datetime
    valid_until: datetime
    state: KeyState = KeyState.ACTIVE

    def is_within_window(self, at: datetime) -> bool:
        """True iff ``at`` is within ``[valid_from, valid_until]`` (UTC, inclusive)."""
        at_utc = _as_utc(at)
        return _as_utc(self.valid_from) <= at_utc <= _as_utc(self.valid_until)

    def can_sign(self, at: datetime) -> bool:
        """True iff this key may produce a NEW signature at ``at`` (ACTIVE + in-window)."""
        return self.state is KeyState.ACTIVE and self.is_within_window(at)

    def is_verify_trusted(self, at: datetime) -> bool:
        """True iff a signature from this key is TRUSTED at ``at``.

        ACTIVE and RETIRED keys are verify-trusted within their window; a REVOKED
        key is never trusted (its past signatures are repudiated on compromise).
        """
        if self.state is KeyState.REVOKED:
            return False
        return self.is_within_window(at)


class Ed25519KeyManifest:
    """Registry of ed25519 signing keys with windowed, lifecycle-gated trust.

    Construct empty, then :meth:`register` keys. Use :meth:`sign` to produce a
    signature with the (single) ACTIVE key for a kid, and :meth:`verify` to check
    a proof's signature under the trust rules documented at module level.

    The manifest is the single authority on which kid is trusted when; it holds
    no global mutable trust beyond the per-key entries, so it is safe to share.
    """

    def __init__(self) -> None:
        self._keys: dict[str, KeyEntry] = {}
        # Private keys live here, separate from the public, shareable KeyEntry,
        # and are dropped on retire()/revoke(). A verify-only manifest simply
        # leaves this empty (see the module-level note on key handling).
        self._private_keys: dict[str, Ed25519PrivateKey] = {}

    # ---- registration -------------------------------------------------------

    def register(
        self,
        kid: str,
        public_key: Ed25519PublicKey,
        valid_from: datetime,
        valid_until: datetime,
        state: KeyState = KeyState.ACTIVE,
        private_key: Ed25519PrivateKey | None = None,
    ) -> KeyEntry:
        """Register a key under ``kid``.

        ``private_key`` is held separately (never stored on the frozen
        :class:`KeyEntry`, which is the public, shareable record) and is required
        only to :meth:`sign`. Registering an ACTIVE key without a private key
        yields a verify-only key (the common case for a verifier that holds only
        public material).

        Raises
        ------
        ValueError
            If ``kid`` is empty, the window is inverted (``valid_until`` before
            ``valid_from``), or ``kid`` is already registered (re-registration
            could silently widen a window or swap a public key).
        """
        if not isinstance(kid, str) or not kid:
            raise ValueError("kid must be a non-empty string")
        if _as_utc(valid_until) < _as_utc(valid_from):
            raise ValueError(
                f"invalid validity window for {kid!r}: valid_until precedes valid_from"
            )
        if kid in self._keys:
            raise ValueError(
                f"kid {kid!r} is already registered; re-registration is refused "
                f"to prevent silently swapping a key's public material or window"
            )
        entry = KeyEntry(
            kid=kid,
            public_key=public_key,
            valid_from=valid_from,
            valid_until=valid_until,
            state=state,
        )
        self._keys[kid] = entry
        if private_key is not None:
            self._private_keys[kid] = private_key
        return entry

    def get(self, kid: str) -> KeyEntry:
        """Return the :class:`KeyEntry` for ``kid`` or raise :class:`UnknownKidError`."""
        try:
            return self._keys[kid]
        except KeyError:
            raise UnknownKidError(kid) from None

    def kids(self) -> tuple[str, ...]:
        """Return all registered kids (registration order)."""
        return tuple(self._keys)

    # ---- lifecycle transitions (monotonic) ----------------------------------

    def _transition(self, kid: str, new_state: KeyState) -> KeyEntry:
        entry = self.get(kid)
        if _STATE_RANK[new_state] <= _STATE_RANK[entry.state]:
            raise IllegalKeyTransitionError(kid, entry.state, new_state)
        # Replace with a new frozen copy (dataclasses.replace would also work;
        # explicit construction keeps the field set auditable).
        updated = KeyEntry(
            kid=entry.kid,
            public_key=entry.public_key,
            valid_from=entry.valid_from,
            valid_until=entry.valid_until,
            state=new_state,
        )
        self._keys[kid] = updated
        return updated

    def retire(self, kid: str) -> KeyEntry:
        """Move a key ACTIVE → RETIRED (verify-only). Drops its private material.

        After retirement the key can no longer sign, so its private key (if held)
        is discarded — there is no reason to keep signing material for a key that
        may not sign, and discarding it shrinks the compromise surface.
        """
        updated = self._transition(kid, KeyState.RETIRED)
        self._private_keys.pop(kid, None)
        return updated

    def revoke(self, kid: str) -> KeyEntry:
        """Move a key to REVOKED from ACTIVE or RETIRED. Drops its private material.

        REVOKED is terminal: the key can neither sign nor be verify-trusted, and
        cannot be un-revoked. Use on compromise.
        """
        updated = self._transition(kid, KeyState.REVOKED)
        self._private_keys.pop(kid, None)
        return updated

    # ---- sign / verify ------------------------------------------------------

    def sign(self, kid: str, message: bytes, at: datetime | None = None) -> bytes:
        """Sign ``message`` with ``kid``'s private key (ACTIVE + in-window only).

        Parameters
        ----------
        kid:
            Key id to sign with. Must be ACTIVE, in-window at ``at``, and have a
            registered private key.
        message:
            The bytes to sign (typically the canonical proof bundle minus its
            signature field).
        at:
            Signing instant; defaults to ``datetime.now(timezone.utc)``.

        Raises
        ------
        UnknownKidError
            If ``kid`` is not registered.
        KeyNotSignableError
            If the key is not ACTIVE, is outside its window, or has no private key.
        """
        when = _as_utc(at) if at is not None else datetime.now(timezone.utc)
        entry = self.get(kid)
        if not entry.can_sign(when):
            raise KeyNotSignableError(
                f"key {kid!r} cannot sign at {when.isoformat()}: state="
                f"{entry.state.value}, in_window={entry.is_within_window(when)} "
                f"(only an ACTIVE, in-window key may sign)"
            )
        private_key = self._private_keys.get(kid)
        if private_key is None:
            raise KeyNotSignableError(
                f"key {kid!r} is ACTIVE and in-window but no private key is held; "
                f"this manifest can verify but not sign with it"
            )
        return private_key.sign(message)

    def verify(
        self, kid: str, message: bytes, signature: bytes, at: datetime | None = None
    ) -> bool:
        """Return whether ``signature`` is trusted for ``message`` under ``kid`` at ``at``.

        Returns ``True`` only if the kid is verify-trusted at ``at`` (ACTIVE or
        RETIRED, within window — REVOKED always fails) AND the ed25519 signature
        is cryptographically valid. Returns ``False`` (never raises) for an
        untrusted kid or a bad signature, so a verifier can treat any falsey
        result as "not tamper-proven" uniformly.

        ``at`` is the instant whose trust is being asked about. To verify a
        HISTORICAL proof, pass the proof's recording/creation time — the question
        is "was this kid trusted to sign *when the proof was made*", not "is it
        trusted now". Defaulting ``at`` to ``now()`` answers the present-tense
        question and will reject a proof whose key window has since closed; that
        is correct for "is this key trusted right now" but NOT for replaying a
        valid old proof, so callers verifying archived proofs MUST pass the
        recorded time explicitly. REVOKED is the one state that fails regardless
        of ``at`` — a compromised key's past signatures are repudiated.

        Raises
        ------
        UnknownKidError
            If ``kid`` is not registered — an unknown signer is a caller error,
            distinct from a known-but-untrusted or cryptographically-invalid
            signature (both of which return ``False``).
        """
        when = _as_utc(at) if at is not None else datetime.now(timezone.utc)
        entry = self.get(kid)
        if not entry.is_verify_trusted(when):
            return False
        try:
            entry.public_key.verify(signature, message)
        except InvalidSignature:
            return False
        return True
