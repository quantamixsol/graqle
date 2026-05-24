"""Key-custody module — ed25519 signing-key lifecycle (R25-EU01 Task 1.7 / C-P2-1).

Layer 5 proof bundles are signed with an ed25519 key identified by a ``kid``
(``graqle-sdk-signing-2026-Q2`` and the like, per R25-EU01 §"signature"). Keys
rotate over time, so a verifier presented with an old proof must be able to ask:
*was this kid trusted to produce a signature at the moment the proof was made?*

:mod:`ed25519_key_manifest` answers that with a per-``kid`` validity window
(``valid_from`` / ``valid_until``) and a three-state lifecycle
(``ACTIVE → RETIRED → REVOKED``). See that module for the full contract.

Public API::

    from graqle.governance.custody import (
        KeyState, KeyEntry, Ed25519KeyManifest, KeyManifestError,
    )
"""

from __future__ import annotations

from graqle.governance.custody.ed25519_key_manifest import (
    Ed25519KeyManifest,
    KeyEntry,
    KeyManifestError,
    KeyState,
)

__all__ = [
    "KeyState",
    "KeyEntry",
    "Ed25519KeyManifest",
    "KeyManifestError",
]
