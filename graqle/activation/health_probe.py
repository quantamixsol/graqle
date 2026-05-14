"""Graph + activation health probe (CR-004 PR-004a).

``graph_health_probe(graph, activation_signal=None, config=None)`` returns
a :class:`GraphHealth` snapshot describing whether the loaded graph plus
the activation pipeline are in a state where ``graq_reason`` /
``graq_predict`` can be expected to produce a useful answer.

Design properties (per CR-004 spec § 3.2):

* **NEVER raises.** Any internal failure (missing attribute on a duck-typed
  graph, unexpected exception in a downstream call) is absorbed and
  converted into a ``GraphHealth`` with ``degraded=True`` and a sanitised
  ``reason`` string. Callers can therefore wire this probe into the
  reasoning envelope without a defensive ``try`` of their own (PR-004b).
* **Read-only.** The probe inspects, never mutates. No new write path,
  no new disk I/O, no network.
* **O(1) over already-loaded state.** ``len(graph.nodes)`` and
  ``len(graph.edges)`` are dict-lookups. ``activation_signal`` is an
  optional duck-typed accessor the caller (PR-004b) will pass; for
  PR-004a it is unused and ``chunks_unembedded`` defaults to ``0``.
* **Bounded latency.** A process-scoped :class:`cachetools.TTLCache` with
  a 5-second TTL absorbs bursty calls — repeat probes within the window
  return the cached snapshot instead of re-walking. The cache is guarded
  by a :class:`threading.Lock` so a probe + grow race produces a snapshot
  read, never a torn read. ``cachetools`` is an existing transitive
  dependency; if it is unavailable for any reason, the import error is
  absorbed and the probe falls back to direct computation (still
  bounded — see § Performance below).

EU AI Act notes:

* The probe does NOT log internally — caller is expected to attach the
  resulting ``GraphHealth.reason`` to whatever audit trail it already
  maintains (envelope, console output). Avoiding a second log site
  prevents accidental secret leakage via a transitively-configured
  handler.
* The ``reason`` string is sanitised before being placed into
  ``GraphHealth``: the project root + home directory paths are replaced
  with placeholders, and every credential pattern in
  ``graqle.core.secret_patterns`` is redacted. The 200-char cap is
  enforced by both this module AND the dataclass — defence in depth.

CR-002 / CR-003 interaction:

* This module does NOT call ``GraqleConfig.from_yaml`` directly — it
  accepts an optional ``config`` argument so the caller can pass in a
  config resolved via ``graqle.config._resolver_compat`` (the CR-002
  resolver-compat helper). PR-004a's tests pass ``config=None`` and
  thresholds default; PR-004b will wire a resolved config in.
* The ``edge_count == 0 with node_count > 0`` signal is the canonical
  symptom of the CR-003 silent-edge-loss regression — the probe surfaces
  it explicitly so callers know to bisect rather than retry.
"""

# graqle:intelligence
# module: graqle.activation.health_probe
# risk: LOW (new leaf module, no consumers in PR-004a; PR-004b will add 3)
# dependencies: dataclasses, pathlib, threading, typing, cachetools (optional), graqle.core.graph_health, graqle.core.secret_patterns
# constraints: must NEVER raise; must complete in <5ms p95 over an already-loaded graph
# /graqle:intelligence

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from graqle.core.graph_health import GraphHealth
from graqle.core.secret_patterns import check_secrets


# Probe configuration defaults. Mirror CR-004 spec § 3.3.
# These are intentionally module-level constants in PR-004a — PR-004b will
# wire ``graqle.yaml`` ``graph_health:`` overrides via the optional
# ``config`` parameter of :func:`graph_health_probe`.
_DEFAULT_STALE_CHUNKS_THRESHOLD: int = 500
_DEFAULT_EDGE_NODE_RATIO_THRESHOLD: float = 0.5
_DEFAULT_ZERO_EDGES_IS_DEGRADED: bool = True
_DEFAULT_DENSE_GRAPH_MIN_NODES: int = 100
_REASON_CAP: int = 200
_PROBE_TTL_SECONDS: float = 5.0


# ─── Cache wiring ──────────────────────────────────────────────────────────

try:
    from cachetools import TTLCache
    _PROBE_CACHE: TTLCache | None = TTLCache(maxsize=1, ttl=_PROBE_TTL_SECONDS)
except ImportError:
    # cachetools is a transitive dep but be defensive — degrade to no cache.
    TTLCache = None  # type: ignore[assignment,misc]
    _PROBE_CACHE = None

_PROBE_CACHE_LOCK = threading.Lock()


# ─── Public API ────────────────────────────────────────────────────────────


def graph_health_probe(
    graph: Any,
    activation_signal: Any = None,
    config: Any = None,
) -> GraphHealth:
    """Return a :class:`GraphHealth` snapshot for the given graph.

    Parameters
    ----------
    graph:
        Any object exposing ``.nodes`` (mapping/iterable) and ``.edges``
        (mapping/iterable). The standard ``graqle.core.graph.Graqle``
        satisfies this; duck-typed objects are accepted so tests can pass
        a stub. If the object lacks one of these attributes the probe
        returns ``degraded=True`` with a sanitised reason.
    activation_signal:
        Optional caller-supplied object exposing ``.chunks_unembedded:
        int`` and ``.activation_mode: str``. PR-004a does not wire this;
        callers (tests) may pass it. If ``None``, the probe reports
        ``chunks_unembedded=0`` and ``activation_mode="unknown"`` (the
        latter does NOT by itself set ``degraded``).
    config:
        Optional config-like object with attributes
        ``stale_chunks_threshold``, ``edge_node_ratio_threshold``,
        ``zero_edges_is_degraded``. When ``None`` (PR-004a default), the
        module-level constants are used. PR-004b will wire a resolved
        ``GraqleConfig`` here via CR-002's
        ``load_via_resolver_or_legacy``.

    Returns
    -------
    GraphHealth
        Snapshot describing the current health. Never ``None``. Never
        raises — callers do not need to wrap this call in ``try``.

    Notes
    -----
    The probe is cached with a 5-second TTL by default. The cache key is
    intentionally degenerate (single-slot) — a stable graph object plus
    stable thresholds within a 5-second window will return the cached
    result. Tests that need a fresh probe per call can clear the cache
    via :func:`_clear_probe_cache_for_tests`.
    """
    try:
        # Attempt cache hit first — single-slot, lock-protected.
        if _PROBE_CACHE is not None:
            with _PROBE_CACHE_LOCK:
                cached = _PROBE_CACHE.get(_CACHE_KEY)
                if cached is not None:
                    return cached

        result = _compute_health(graph, activation_signal, config)

        if _PROBE_CACHE is not None:
            with _PROBE_CACHE_LOCK:
                _PROBE_CACHE[_CACHE_KEY] = result
        return result
    except Exception as exc:  # noqa: BLE001 — probe MUST NEVER raise
        # Belt-and-braces: even if the cache layer itself misbehaves, we
        # return a degraded snapshot rather than propagating.
        return _build_failed_health(exc)


# Module-internal cache slot key.
_CACHE_KEY = "probe"


# ─── Internal helpers ──────────────────────────────────────────────────────


def _compute_health(
    graph: Any,
    activation_signal: Any,
    config: Any,
) -> GraphHealth:
    """Compute a fresh :class:`GraphHealth` (no cache). Catches all errors.

    This is the "first defence" — any exception here is converted to a
    degraded snapshot. The outer :func:`graph_health_probe` then has a
    second-defence ``try`` so even a bug *inside this catch* still yields
    a valid return value.
    """
    try:
        node_count = _safe_count(graph, "nodes")
        edge_count = _safe_count(graph, "edges")

        # Threshold extraction with fall-through to defaults.
        stale_threshold = _read_attr(
            config, "stale_chunks_threshold", _DEFAULT_STALE_CHUNKS_THRESHOLD
        )
        ratio_threshold = _read_attr(
            config, "edge_node_ratio_threshold", _DEFAULT_EDGE_NODE_RATIO_THRESHOLD
        )
        zero_edges_is_degraded = _read_attr(
            config, "zero_edges_is_degraded", _DEFAULT_ZERO_EDGES_IS_DEGRADED
        )

        # Activation-signal probe (optional).
        chunks_unembedded = max(
            0, int(_read_attr(activation_signal, "chunks_unembedded", 0))
        )
        activation_mode_raw = str(
            _read_attr(activation_signal, "activation_mode", "unknown")
        )
        activation_mode = (
            activation_mode_raw
            if activation_mode_raw in {"semantic", "keyword_fallback", "hybrid"}
            else "unknown"
        )

        total_chunks = max(
            0, int(_read_attr(activation_signal, "total_chunks", 0))
        )
        if total_chunks <= 0:
            percent_stale = 0.0
        else:
            percent_stale = max(0.0, min(1.0, chunks_unembedded / total_chunks))

        # Degraded? — disjunction of four signals per spec § 3.3.
        reasons: list[str] = []
        if zero_edges_is_degraded and node_count > 0 and edge_count == 0:
            reasons.append(
                f"graph has {node_count} nodes but 0 edges "
                "(silent edge-loss; see CR-003)"
            )
        if chunks_unembedded > stale_threshold:
            reasons.append(
                f"{chunks_unembedded} unembedded chunks exceeds "
                f"threshold {stale_threshold}"
            )
        if (
            node_count > _DEFAULT_DENSE_GRAPH_MIN_NODES
            and edge_count > 0
            and (edge_count / max(node_count, 1)) < ratio_threshold
        ):
            ratio = edge_count / max(node_count, 1)
            reasons.append(
                f"edge/node ratio {ratio:.3f} below threshold {ratio_threshold}"
            )
        if activation_mode == "keyword_fallback":
            reasons.append("activation in keyword_fallback mode")

        degraded = bool(reasons)
        raw_reason = "; ".join(reasons) if reasons else None
        reason = (
            _sanitise_reason(raw_reason, _project_root())
            if raw_reason is not None
            else None
        )

        return GraphHealth(
            node_count=node_count,
            edge_count=edge_count,
            chunks_unembedded=chunks_unembedded,
            percent_stale=percent_stale,
            activation_mode=activation_mode,  # type: ignore[arg-type]
            degraded=degraded,
            reason=reason,
            schema_version="1",
        )
    except Exception as exc:  # noqa: BLE001 — never raise from the probe
        return _build_failed_health(exc)


def _safe_count(obj: Any, attr: str) -> int:
    """Return ``len(getattr(obj, attr))`` or ``0`` on any failure."""
    try:
        value = getattr(obj, attr)
    except Exception:  # noqa: BLE001
        return 0
    try:
        return int(len(value))
    except Exception:  # noqa: BLE001
        return 0


def _read_attr(obj: Any, name: str, default: Any) -> Any:
    """Read ``obj.name`` (or ``obj[name]`` for dict-likes) with a default."""
    if obj is None:
        return default
    try:
        return getattr(obj, name)
    except AttributeError:
        pass
    except Exception:  # noqa: BLE001
        return default
    # Dict-like fall-through.
    try:
        return obj[name]
    except Exception:  # noqa: BLE001
        return default


def _project_root() -> Path:
    """Best-effort project root for path-prefix sanitisation.

    Uses ``GRAQLE_SERVE_CWD`` if set (per S-010 / lesson_20260405T205343),
    else the process cwd. Never raises — falls back to ``Path('.')`` on
    any error. PR-004b will hand in a CR-002-resolved project root.
    """
    try:
        env = os.environ.get("GRAQLE_SERVE_CWD")
        if env:
            return Path(env).resolve(strict=False)
        return Path.cwd().resolve(strict=False)
    except Exception:  # noqa: BLE001
        return Path(".")


def _build_failed_health(exc: BaseException) -> GraphHealth:
    """Construct a degraded :class:`GraphHealth` for an internal failure.

    The reason names the exception TYPE only — never the message, which
    can contain user-supplied paths or secrets that have not yet been
    sanitised. Type names alone are safe (they come from the call stack,
    not the data).
    """
    return GraphHealth(
        node_count=0,
        edge_count=0,
        chunks_unembedded=0,
        percent_stale=0.0,
        activation_mode="unknown",
        degraded=True,
        reason=f"health probe failed: {type(exc).__name__}",
        schema_version="1",
    )


# ─── Reason-string sanitisation ────────────────────────────────────────────


def _redact_secrets(text: str) -> str:
    """Redact any credential pattern in ``text`` using ``check_secrets``.

    ``graqle.core.secret_patterns.check_secrets(content) -> (found, matches)``
    is the canonical secret-detection API (200+ patterns). Spec § 3.4
    described a ``scan_for_secrets(replace=True)`` API that does not
    exist; this thin wrapper bridges the gap by iterating the returned
    matches and replacing each truncated snippet with ``<redacted:group>``.

    For text that contains no secrets the function is a no-op (returns
    the input unchanged). Never raises — pattern errors silently fall
    through to the input string.
    """
    if not text:
        return text
    try:
        found, matches = check_secrets(text)
        if not found:
            return text
        out = text
        for m in matches:
            # ``snippet`` is already truncated to 40 chars by check_secrets.
            # Replace ALL occurrences (a single secret can recur in a reason).
            placeholder = f"<redacted:{m.group}>"
            if m.snippet and m.snippet in out:
                out = out.replace(m.snippet, placeholder)
        return out
    except Exception:  # noqa: BLE001 — sanitisation must not crash probe
        return text


def _sanitise_reason(raw: str, project_root: Path) -> str:
    """Strip project_root prefix + home dir + redact secrets + cap length.

    Order matters: path replacements first (so a path containing a secret
    is shortened to ``<project>/foo`` rather than redacted-verbose).
    Length cap last so the placeholder substitutions are never truncated
    mid-token.
    """
    if not raw:
        return raw
    try:
        # 1. Project root prefix.
        try:
            root_str = str(project_root)
        except Exception:  # noqa: BLE001
            root_str = ""
        if root_str and root_str in raw:
            raw = raw.replace(root_str, "<project>")

        # 2. Home directory.
        try:
            home_str = str(Path.home())
        except Exception:  # noqa: BLE001
            home_str = ""
        if home_str and home_str in raw:
            raw = raw.replace(home_str, "~")

        # 3. Secret patterns (after path elision so we don't redact paths
        # that contain credential-adjacent substrings like "secret/").
        raw = _redact_secrets(raw)

        # 4. Length cap.
        if len(raw) > _REASON_CAP:
            raw = raw[: _REASON_CAP - 3] + "..."
        return raw
    except Exception:  # noqa: BLE001
        # Worst case: return a generic note so callers never get raw paths
        # back. Short-circuits any further sanitiser failure.
        return "health probe sanitiser error"


# ─── Test hook ─────────────────────────────────────────────────────────────


def _clear_probe_cache_for_tests() -> None:
    """Clear the TTL cache. Test-only — production callers don't use this.

    Exposed as a module-private helper (leading underscore) so tests can
    guarantee a fresh probe per call without waiting 5 seconds for TTL
    expiry. Not part of the public API.
    """
    if _PROBE_CACHE is not None:
        with _PROBE_CACHE_LOCK:
            _PROBE_CACHE.clear()
