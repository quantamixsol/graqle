"""FastAPI / Starlette attachment for Mode B runtime capture (ADR-221 §4.1 / R1).

Two ergonomic ways to attach GraQle to a deployed AI service so every governed
decision is captured as a PII-safe, tamper-evidence-ready record — with no change to
the decision code itself:

.. code-block:: python

    # app-wide middleware
    from graqle.governance.runtime.fastapi import GraqleGovernanceMiddleware
    app.add_middleware(GraqleGovernanceMiddleware, mapping="loan_mapping.yaml")

    # or per-route decorator
    from graqle.governance.runtime import governed

    @governed(domain="recruitment", mapping="recruitment_mapping.yaml")
    async def screen_candidate(payload: dict) -> dict:
        ...

Both compose the **shipped** :meth:`GovernedRuntime.attest` (R0) and the fail-closed
:class:`~graqle.governance.runtime.mapping.DomainMapping` (R1). This module adds no
cryptography and does not touch ``tamper_evidence`` / ``layer_status``.

Design contract (ADR-221 §4.1, §4.3, §4.4):

* **0 ms on the response path.** The middleware schedules ``attest`` on a Starlette
  ``BackgroundTask`` after the response is produced — the user never waits on a
  hash + sink append, and never on Rekor (the sink batches/anchors out of band).
* **The mapping is fail-closed.** Only allowlisted fields are routed; an unmapped
  field is dropped, never stored raw. A middleware sees whole payloads, so this is
  the load-bearing PII control.
* **Capture failure is configurable and defaults to fail-open** (``on_error="log"``).
  This is an audit *side-channel* over live user traffic: a failed audit write must
  not turn a healthy 200 into a 503 for a real user. The no-silent-drop rule is
  honoured by **loud structured logging** of every capture failure (never a bare
  ``pass``). Deployers who must fail-closed for their controls set
  ``on_error="raise"``.

Scope / limitations (R1):

* The middleware captures **buffered ``application/json`` responses** — the shape of a
  governed decision endpoint. A **streaming** JSON response (a ``StreamingResponse``
  emitting ``application/json``) would be fully buffered by the capture path, defeating
  streaming; do not mount this middleware on streaming/SSE decision routes, or use the
  per-route :func:`governed` decorator there instead. Server-Sent Events
  (``text/event-stream``) and any non-JSON response are passed through untouched.
* ``max_body_bytes`` (default 1 MiB) bounds what is buffered for capture; a larger body
  is streamed back to the client unmodified but **not** captured (logged as
  ``capture_skipped_oversize``).
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from graqle.governance.runtime.mapping import DomainMapping, load_mapping
from graqle.governance.runtime.runtime import GovernedRuntime

logger = logging.getLogger("graqle.governance.runtime.fastapi")

__all__ = [
    "GraqleGovernanceMiddleware",  # noqa: F822 - exposed lazily via module __getattr__ (PEP 562)
    "governed",
]

# Governance-metadata keys that attest() promotes into the leaf via dedicated kwargs.
# Forwarding only these keeps the attest() call total-function over arbitrary mapping
# output (any other governance field still rides in output -> content_hash).
_PROMOTED_GOV_KEYS = ("reason_code", "confidence", "human_review")

# Default cap on the response body the middleware will buffer for capture. A governed
# decision response is small (a decision + reason + a few fields); a body larger than
# this is not a legitimate decision payload, so it is passed through to the client
# uncaptured rather than buffered — defence against a memory-exhaustion DoS via a
# pathologically large response. Overridable per-middleware via max_body_bytes.
_DEFAULT_MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MiB

# Valid capture-failure policies.
_ON_ERROR_POLICIES = frozenset({"log", "raise"})


def _resolve_mapping(mapping: str | Path | DomainMapping) -> DomainMapping:
    """Accept a path or an already-built DomainMapping; load if it is a path."""
    if isinstance(mapping, DomainMapping):
        return mapping
    return load_mapping(mapping)


def _capture(
    runtime: GovernedRuntime,
    mapping: DomainMapping,
    payload: dict[str, Any],
    *,
    model_id: str,
    policy_id: str | None,
) -> dict[str, Any]:
    """Map a payload and attest it. Returns the attested record.

    Pure of HTTP concerns so it is reusable by both the middleware and the decorator
    and is trivially unit-testable. Raises whatever the mapping/attest raise — the
    caller decides the failure policy.
    """
    inputs_digest, output, governance_metadata = mapping.apply(payload, runtime)
    promoted = {
        k: governance_metadata[k]
        for k in _PROMOTED_GOV_KEYS
        if k in governance_metadata
    }
    return runtime.attest(
        domain=mapping.domain,
        model_id=model_id,
        output=output,
        inputs=inputs_digest,
        policy_id=policy_id,
        **promoted,
    )


def _handle_capture_error(exc: Exception, on_error: str, *, domain: str) -> None:
    """Apply the configured capture-failure policy.

    ``"raise"`` re-raises (fail-closed); ``"log"`` emits a structured error and
    swallows (fail-open). Never a silent drop: the log line carries the domain and the
    exception **type** so a monitoring rule can alert on it (ADR-221 §4.4 no-silent-skip).

    PII safety: only the exception *type* is logged, never ``str(exc)``. An exception
    raised deep in mapping/attest could embed a raw payload value in its message; logging
    that text would defeat the whole point of the fail-closed mapping. The type + domain
    are enough to alert and triage; the offending value never reaches the log sink.
    """
    if on_error == "raise":
        raise exc
    logger.error(
        "graqle.runtime.capture_failed",
        extra={"domain": domain, "error_type": type(exc).__name__},
    )


# --------------------------------------------------------------------------- #
# Decorator (per-route)
# --------------------------------------------------------------------------- #


def governed(
    *,
    domain: str | None = None,
    mapping: str | Path | DomainMapping,
    model_id: str = "unknown",
    policy_id: str | None = None,
    runtime: GovernedRuntime | None = None,
    on_error: str = "log",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorate a decision function so its return value is captured + attested.

    The wrapped function is called untouched; its **return value** (a ``dict``) is the
    payload routed through ``mapping`` and attested *after* the function returns.
    Works on both sync and ``async def`` functions.

    Parameters
    ----------
    domain:
        Optional override/cross-check. If given it must equal the mapping's domain
        (guards against attaching a recruitment mapping to a loan route).
    mapping:
        Path to a ``*_mapping.yaml`` or a pre-built :class:`DomainMapping`.
    model_id / policy_id:
        Forwarded to :meth:`GovernedRuntime.attest`.
    runtime:
        The :class:`GovernedRuntime` to attest through. Defaults to a process-wide
        instance (durable JSONL sink).
    on_error:
        ``"log"`` (default, fail-open) or ``"raise"`` (fail-closed) for capture errors.
    """
    if on_error not in _ON_ERROR_POLICIES:
        raise ValueError(f"on_error must be one of {sorted(_ON_ERROR_POLICIES)}")
    dmap = _resolve_mapping(mapping)
    if domain is not None and domain != dmap.domain:
        raise ValueError(
            f"@governed domain={domain!r} does not match mapping domain {dmap.domain!r}"
        )
    gov = runtime if runtime is not None else _default_runtime()

    def _capture_result(result: Any) -> None:
        """Route a decorated function's return value through capture, per policy."""
        if not isinstance(result, dict):
            # Nothing to map. Fail-closed on the PII axis (store nothing) but this
            # is a usage error, so surface it under the configured policy.
            _handle_capture_error(
                TypeError(
                    "@governed expects the decorated function to return a dict "
                    f"payload; got {type(result).__name__}"
                ),
                on_error,
                domain=dmap.domain,
            )
            return
        try:
            _capture(gov, dmap, result, model_id=model_id, policy_id=policy_id)
        except Exception as exc:  # noqa: BLE001 - policy decides re-raise vs log
            _handle_capture_error(exc, on_error, domain=dmap.domain)

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        import functools
        import inspect

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                result = await func(*args, **kwargs)
                _capture_result(result)
                return result

            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            result = func(*args, **kwargs)
            _capture_result(result)
            return result

        return sync_wrapper

    return decorator


# --------------------------------------------------------------------------- #
# Middleware (app-wide)
# --------------------------------------------------------------------------- #


def _build_middleware_class() -> type:
    """Build GraqleGovernanceMiddleware against Starlette, imported lazily.

    Starlette is a core dep, but importing it at module top would make this module
    unimportable in a minimal install. Lazy-building keeps ``from ...fastapi import
    governed`` working even where Starlette is absent, and lets tests
    ``importorskip("starlette")`` cleanly.
    """
    from starlette.background import BackgroundTask
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response

    class GraqleGovernanceMiddleware(BaseHTTPMiddleware):
        """Capture every governed decision flowing through a Starlette/FastAPI app.

        For each request it buffers the JSON response body, schedules an ``attest``
        on a :class:`~starlette.background.BackgroundTask` (so the client is not made
        to wait), and returns the response unchanged. The response JSON is the payload
        routed through the fail-closed mapping.

        Parameters mirror :func:`governed`. ``model_id`` / ``policy_id`` may also be
        read per-request from response headers (``x-graqle-model-id`` /
        ``x-graqle-policy-id``) so a single mounted middleware can serve many models.
        """

        def __init__(
            self,
            app: Any,
            *,
            mapping: str | Path | DomainMapping,
            model_id: str = "unknown",
            policy_id: str | None = None,
            runtime: GovernedRuntime | None = None,
            on_error: str = "log",
            max_body_bytes: int = _DEFAULT_MAX_BODY_BYTES,
        ) -> None:
            super().__init__(app)
            if on_error not in _ON_ERROR_POLICIES:
                raise ValueError(
                    f"on_error must be one of {sorted(_ON_ERROR_POLICIES)}"
                )
            if max_body_bytes <= 0:
                raise ValueError("max_body_bytes must be a positive integer")
            self._mapping = _resolve_mapping(mapping)
            self._model_id = model_id
            self._policy_id = policy_id
            self._runtime = runtime if runtime is not None else _default_runtime()
            self._on_error = on_error
            self._max_body_bytes = max_body_bytes

        async def dispatch(
            self,
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            response = await call_next(request)

            # Only attempt to capture JSON responses; anything else is passed through
            # untouched (fail-closed on the PII axis: a non-JSON body is never parsed
            # or stored).
            content_type = response.headers.get("content-type", "")
            if "application/json" not in content_type.lower():
                return response

            # Buffer the body so we can both capture it and return it to the client.
            # Stop *capturing* once the cap is exceeded (a body that large is not a
            # legitimate decision payload), but keep buffering so the client still gets
            # the full, unmodified response — the cap bounds what we attest, and is a
            # defence against a memory-exhaustion DoS via a pathologically large body.
            body = b""
            over_cap = False
            async for chunk in response.body_iterator:
                body += chunk
                if not over_cap and len(body) > self._max_body_bytes:
                    over_cap = True

            background = None
            if over_cap:
                # The cap is a deliberate bound, not an audit failure: always skip +
                # log loudly, NEVER raise on the response path (raising here would turn
                # a large legitimate response into a 500 for the user). on_error governs
                # mapping/attest failures, not this size guard.
                logger.error(
                    "graqle.runtime.capture_skipped_oversize",
                    extra={
                        "domain": self._mapping.domain,
                        "max_body_bytes": self._max_body_bytes,
                    },
                )
            else:
                # Per-request model/policy override via headers (one middleware, many
                # models). Falls back to the constructor defaults.
                model_id = response.headers.get("x-graqle-model-id", self._model_id)
                policy_id = response.headers.get("x-graqle-policy-id", self._policy_id)
                background = BackgroundTask(
                    self._capture_task,
                    body=body,
                    model_id=model_id,
                    policy_id=policy_id,
                )

            # Rebuild the response from the buffered body (the original iterator is now
            # exhausted) and attach the capture (if any) as a background task that runs
            # AFTER the body is sent to the client. Drop a stale Content-Length: we pass
            # the exact same bytes back, and Starlette's Response recomputes the correct
            # Content-Length from `content` — copying the original header risks a mismatch
            # if the upstream value disagreed with the actual body length.
            rebuilt_headers = {
                k: v for k, v in response.headers.items() if k.lower() != "content-length"
            }
            return Response(
                content=body,
                status_code=response.status_code,
                headers=rebuilt_headers,
                media_type=response.media_type,
                background=background,
            )

        def _capture_task(
            self, *, body: bytes, model_id: str, policy_id: str | None
        ) -> None:
            try:
                payload = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                _handle_capture_error(exc, self._on_error, domain=self._mapping.domain)
                return
            if not isinstance(payload, dict):
                _handle_capture_error(
                    TypeError(
                        "response JSON must be an object to capture; "
                        f"got {type(payload).__name__}"
                    ),
                    self._on_error,
                    domain=self._mapping.domain,
                )
                return
            try:
                _capture(
                    self._runtime,
                    self._mapping,
                    payload,
                    model_id=model_id,
                    policy_id=policy_id,
                )
            except Exception as exc:  # noqa: BLE001 - policy decides re-raise vs log
                _handle_capture_error(exc, self._on_error, domain=self._mapping.domain)

    return GraqleGovernanceMiddleware


_DEFAULT_RUNTIME: GovernedRuntime | None = None
_DEFAULT_RUNTIME_LOCK = threading.Lock()


def _default_runtime() -> GovernedRuntime:
    """Lazily build and cache a process-wide GovernedRuntime (durable JSONL sink).

    Double-checked locking so concurrent first-callers (e.g. several routes decorated
    at import time across threads) build exactly one shared instance rather than racing
    to create several. GovernedRuntime itself is thread-safe to share.
    """
    global _DEFAULT_RUNTIME
    if _DEFAULT_RUNTIME is None:
        with _DEFAULT_RUNTIME_LOCK:
            if _DEFAULT_RUNTIME is None:
                _DEFAULT_RUNTIME = GovernedRuntime()
    return _DEFAULT_RUNTIME


def __getattr__(name: str) -> Any:
    """Lazily expose GraqleGovernanceMiddleware (PEP 562).

    Building the class requires Starlette; deferring it to first attribute access
    keeps the module importable for the decorator-only path in a Starlette-free env.
    """
    if name == "GraqleGovernanceMiddleware":
        cls = _build_middleware_class()
        globals()["GraqleGovernanceMiddleware"] = cls
        return cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
