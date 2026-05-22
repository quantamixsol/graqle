"""Sigstore Rekor anchor for Layer 5 tamper-evidence (R25-EU01 Task 1.4).

The batcher (PR-3) builds an RFC 6962 Merkle root over each batch of governed
records. To make that root externally verifiable — so a third party with zero
GraQle knowledge can confirm the batch existed at a point in time — the root is
submitted to **Sigstore Rekor**, a public append-only transparency log. Rekor
returns a *log inclusion certificate*: the log index, log id, signed tree head,
and inclusion proof that together prove the root was logged.

    anchor(root_bytes) -> RekorReceipt(log_index, log_id, signed_tree_head, cert)

This module is deliberately structured so the heavy ``sigstore`` package (a
network + crypto dependency, pinned ``>=3.0,<3.1``) is **optional**:

* ``sigstore`` is imported lazily and guarded — importing this module never
  requires it, so the rest of Layer 5 (and the whole SDK) loads without it.
* :class:`RekorAnchor` takes an injectable ``transport`` (anything implementing
  :class:`RekorTransport`). Tests inject a fake transport and exercise every
  branch — retries, backoff, success, permanent failure — with no network and
  no ``sigstore`` installed.
* The real ``sigstore``-backed transport is constructed only when no transport
  is injected AND an anchor is actually attempted. If ``sigstore`` is missing at
  that point, a clear :class:`AnchorUnavailableError` explains the
  ``pip install graqle[attestation]`` remedy.

Install the optional dependency with ``pip install graqle[attestation]``.

Retry policy: bounded exponential backoff (default 3 attempts). A transient
transport error is retried; once attempts are exhausted the error is surfaced as
:class:`AnchorError` — never swallowed (fail-closed; see ``AttestationConfig
.security.fail_open_on_anchor_error``, which defaults to ``False``). The caller
(PR-5 committer / the replay queue) decides whether to queue for later or pause
writes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

from graqle.config.attestation_config import RekorConfig
from graqle.governance.tamper_evidence.errors import TamperEvidenceError

# The optional dependency name, surfaced in the remediation message.
_OPTIONAL_EXTRA = "graqle[attestation]"


class AnchorError(TamperEvidenceError):
    """A batch root could not be anchored after exhausting the retry budget."""


class AnchorUnavailableError(AnchorError):
    """The Sigstore anchor cannot run because ``sigstore`` is not installed.

    Distinct from :class:`AnchorError` (a transport/availability failure of an
    installed backend): this means the optional dependency itself is absent, so
    the remedy is ``pip install graqle[attestation]`` rather than a retry.
    """

    def __init__(self) -> None:
        super().__init__(
            "the Sigstore Rekor anchor requires the optional 'sigstore' package "
            f"(>=3.0,<3.1). Install it with: pip install {_OPTIONAL_EXTRA}"
        )


@dataclass(frozen=True)
class RekorReceipt:
    """A Rekor log inclusion certificate for one anchored Merkle root.

    These are the externally-verifiable fields a third party uses to confirm the
    root was logged (R25-EU01 §358 Proof Bundle Schema, anchor section):

    * ``log_index`` — the root's position in the Rekor log.
    * ``log_id`` — identifies which Rekor log instance.
    * ``signed_tree_head`` — Rekor's signed commitment to its log state.
    * ``inclusion_cert`` — the inclusion proof / certificate bytes (opaque here;
      verified by ``graqle.verify`` / an external auditor against the Rekor
      public key).
    * ``integrated_time`` — Rekor's record of when the root was logged (unix s).
    """

    log_index: int
    log_id: str
    signed_tree_head: str
    inclusion_cert: str
    integrated_time: int


@runtime_checkable
class RekorTransport(Protocol):
    """The minimal surface :class:`RekorAnchor` needs from a Rekor backend.

    Implemented by the real ``sigstore``-backed transport and by test fakes.
    Keeping it this narrow is what makes the anchor fully testable without the
    network: a fake transport returns a canned :class:`RekorReceipt` or raises.
    """

    def submit(self, root_bytes: bytes) -> RekorReceipt:
        """Submit a Merkle root, returning its inclusion certificate, or raise."""
        ...


class RekorAnchor:
    """Anchors Merkle batch roots to Sigstore Rekor with bounded retry.

    Parameters
    ----------
    config:
        :class:`RekorConfig` — supplies ``url``, ``public_key_path``, and
        ``retry_max_attempts`` (1..10). Defaults to ``RekorConfig()``.
    transport:
        An object satisfying :class:`RekorTransport`. If omitted, a real
        ``sigstore``-backed transport is built lazily on first anchor; if
        ``sigstore`` is not installed at that point, :class:`AnchorUnavailableError`
        is raised. Injecting a fake transport here is how tests avoid the
        network and the optional dependency entirely.
    sleep:
        Injectable sleep (defaults to :func:`time.sleep`) so retry backoff is
        deterministically testable without real delays.
    """

    def __init__(
        self,
        config: RekorConfig | None = None,
        transport: RekorTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config or RekorConfig()
        self._transport = transport
        self._sleep = sleep

    @property
    def available(self) -> bool:
        """True if an anchor attempt could proceed (transport injected or sigstore importable).

        A pure capability probe — it does not anchor anything. Used by the
        committer / replay queue to decide between anchoring now and degrading to
        the local replay queue without triggering an exception.
        """
        if self._transport is not None:
            return True
        return _sigstore_importable()

    def anchor(self, root_bytes: bytes) -> RekorReceipt:
        """Anchor ``root_bytes`` to Rekor, retrying transient failures.

        Tries up to ``config.retry_max_attempts`` times with exponential backoff
        (1s, 2s, 4s, ... via the injectable ``sleep``). On success returns the
        :class:`RekorReceipt`. If every attempt fails, raises :class:`AnchorError`
        chaining the last transport error — the failure is surfaced, never
        silently dropped (fail-closed).
        """
        if not isinstance(root_bytes, (bytes, bytearray)):
            raise AnchorError(
                f"root_bytes must be bytes, got {type(root_bytes).__name__}"
            )
        # A Merkle root is a single SHA-256 digest (32 bytes). Anything wildly
        # larger is a caller bug, not a root — reject it before it reaches the
        # network (defence-in-depth size guard). A small upper bound (not exactly
        # 32) tolerates future digest sizes while still refusing absurd input.
        if not 0 < len(root_bytes) <= 64:
            raise AnchorError(
                f"root_bytes has implausible length {len(root_bytes)} for a Merkle "
                f"root (expected a single hash digest, <= 64 bytes)"
            )
        transport = self._get_transport()
        attempts = self._config.retry_max_attempts
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return transport.submit(bytes(root_bytes))
            except AnchorUnavailableError:
                # The dependency is absent — retrying cannot help; surface now.
                raise
            except Exception as exc:  # transport/transient failure: retry
                last_error = exc
                if attempt + 1 < attempts:
                    # Exponential backoff: 1, 2, 4, ... seconds (injectable sleep).
                    self._sleep(float(2**attempt))
        raise AnchorError(
            f"failed to anchor batch root to Rekor after {attempts} attempt(s): "
            f"{last_error}"
        ) from last_error

    def _get_transport(self) -> RekorTransport:
        """Return the injected transport, or lazily build the real sigstore one."""
        if self._transport is not None:
            return self._transport
        self._transport = _build_sigstore_transport(self._config)
        return self._transport


def _sigstore_importable() -> bool:
    """True iff the optional ``sigstore`` package can be imported (no network)."""
    import importlib.util

    return importlib.util.find_spec("sigstore") is not None


def _build_sigstore_transport(config: RekorConfig) -> RekorTransport:
    """Construct the real ``sigstore``-backed transport, or raise if unavailable.

    The ``sigstore`` import lives here — the only place that touches the optional
    dependency — so importing this module never pulls it in. The concrete wiring
    to the ``sigstore`` 3.x API is intentionally minimal and isolated behind the
    :class:`RekorTransport` Protocol; it is exercised in integration (not unit)
    tests, since unit tests inject a fake transport.

    The configured Rekor URL is validated here (SSRF guard): a misconfigured or
    malicious ``graqle.yaml`` must not be able to point the anchor at an internal
    service. Only ``https://`` URLs are accepted, and obvious loopback/internal
    hosts are rejected.
    """
    if not _sigstore_importable():
        raise AnchorUnavailableError()
    _validate_rekor_url(config.url)
    return _SigstoreRekorTransport(config)


# Hostnames that must never be a Rekor endpoint (SSRF guard). A transparency log
# is an external public service; a loopback/metadata target indicates an attack
# or a serious misconfiguration.
_BLOCKED_HOSTS = frozenset({
    "localhost", "127.0.0.1", "::1", "0.0.0.0",
    "169.254.169.254",  # cloud instance metadata endpoint
    "metadata.google.internal",
})


def _validate_rekor_url(url: str) -> None:
    """Reject non-HTTPS or internal-target Rekor URLs (SSRF defence).

    Raises :class:`AnchorError` for a URL that is not ``https://`` or that points
    at a loopback / link-local / cloud-metadata host. This runs before any real
    network client is constructed, so a bad ``rekor.url`` can never trigger a
    request to an internal service.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise AnchorError(
            f"Rekor URL must use https:// (got scheme {parsed.scheme!r}); "
            f"refusing to anchor over an untrusted scheme"
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise AnchorError(f"Rekor URL {url!r} has no host")
    if host in _BLOCKED_HOSTS:
        raise AnchorError(
            f"Rekor URL host {host!r} is a loopback/internal target; "
            f"a transparency log must be an external service (SSRF guard)"
        )


class _SigstoreRekorTransport:
    """Real Rekor transport backed by the ``sigstore`` package.

    Thin adapter: translates a Merkle root into a Rekor submission and the Rekor
    response into a :class:`RekorReceipt`. Constructed only when ``sigstore`` is
    installed and no fake transport was injected. Not unit-tested (it requires
    the optional dependency + network); covered by the optional integration
    suite. Kept tiny so the untested surface is minimal.
    """

    def __init__(self, config: RekorConfig) -> None:
        self._config = config
        self._client: Any = None  # lazily created on first submit

    def submit(self, root_bytes: bytes) -> RekorReceipt:  # pragma: no cover - needs sigstore + network
        # Import inside the method so even constructing the adapter never imports
        # sigstore unless an actual submission is attempted.
        from sigstore._internal.rekor import client as _rekor_client  # type: ignore

        if self._client is None:
            self._client = _rekor_client.RekorClient(self._config.url)
        entry = self._client.log.entries.create(root_bytes)
        return RekorReceipt(
            log_index=int(entry.log_index),
            log_id=str(entry.log_id),
            signed_tree_head=str(getattr(entry, "signed_tree_head", "")),
            inclusion_cert=str(getattr(entry, "inclusion_proof", "")),
            integrated_time=int(getattr(entry, "integrated_time", 0)),
        )
