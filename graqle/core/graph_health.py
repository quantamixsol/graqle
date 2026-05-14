"""Result type for the graph_health_probe — leaf dataclass.

CR-004 PR-004a — leaf module by design.

``GraphHealth`` is the structured result that ``graph_health_probe`` (in
``graqle.activation.health_probe``) returns, and that PR-004b will attach
to ``ReasoningResult`` so callers of ``graq_reason`` / ``graq_predict``
can detect a degraded graph state instead of silently returning a
low-confidence answer over a zero-edge graph or a stale NPZ cache.

Why a separate leaf module instead of an addition to ``graqle.core.types``:
``core/types.py`` is a HIGH-risk hub with 27 downstream consumers. Adding
a new dataclass there forces re-validation of every consumer in the
sentinel chain even when none of them touch the new dataclass. A pure
stdlib leaf module avoids the hub-risk amplification while keeping the
import path predictable (``from graqle.core.graph_health import GraphHealth``).
PR-004b can re-export from ``core/types.py`` if a single import path is
preferred — additive, no breaking change.

EU AI Act note: this module is **pure data**. It performs no I/O, no
network access, no logging, and no LLM calls. The constructor validates
bounds and raises ``ValueError`` on out-of-range inputs — that is the
only behaviour. All sanitisation of the ``reason`` field happens in
``health_probe.py`` BEFORE the dataclass is constructed.
"""

# graqle:intelligence
# module: graqle.core.graph_health
# risk: LOW (new leaf, zero consumers at land time; PR-004b will add 1)
# dependencies: dataclasses, typing (stdlib only - ZERO graqle.* imports by design)
# constraints: MUST remain a pure stdlib leaf module - no graqle.* imports ever
# /graqle:intelligence

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class GraphHealth:
    """Snapshot of graph + activation health at a moment in time.

    All fields are populated by ``graph_health_probe``. The probe NEVER
    raises — on any internal error it returns a ``GraphHealth`` with
    ``degraded=True`` and a sanitised ``reason``.

    Fields
    ------
    node_count:
        Total nodes in the loaded graph at probe time. ``>= 0``.
    edge_count:
        Total edges. ``>= 0``. The combination ``node_count > 0`` and
        ``edge_count == 0`` is the canonical "silent edge-loss" symptom
        that motivated CR-004 (see CR-003 for the underlying defect).
    chunks_unembedded:
        Count of chunk-level nodes whose NPZ embedding cache entry is
        missing or older than the chunk's content hash. ``>= 0``. A high
        value means the activation pipeline will fall back to keyword
        matching on those chunks.
    percent_stale:
        ``chunks_unembedded / max(total_chunks, 1)``, clamped to
        ``[0.0, 1.0]``. Floats in ``__post_init__`` reject NaN by virtue
        of the range check (NaN compares false to everything).
    activation_mode:
        Which activation strategy is *actually* in use right now. Not what
        was configured — what executed. ``"semantic"`` is the healthy
        path; ``"keyword_fallback"`` is a degraded path; ``"hybrid"`` is
        a mixed mode; ``"unknown"`` is returned by the probe's exception
        path when the activation layer cannot be introspected.
    degraded:
        ``True`` iff any of: ``chunks_unembedded`` exceeds the configured
        threshold, ``edge_count == 0`` (with ``zero_edges_is_degraded``
        true), the edge/node ratio is below the configured threshold, or
        ``activation_mode == "keyword_fallback"``. The configured
        thresholds live in ``graqle.yaml`` ``graph_health:`` block and are
        consumed by ``graph_health_probe``; this dataclass holds only the
        computed boolean, not the thresholds.
    reason:
        Human-readable diagnostic. ``None`` when ``degraded`` is ``False``.
        When non-``None``, it has been passed through ``_sanitise_reason``
        in ``health_probe.py``: project-root and home-dir prefixes are
        replaced, every credential pattern in
        ``graqle.core.secret_patterns`` is redacted, and the length is
        capped at 200 chars. The 200-char cap is also enforced by
        ``__post_init__`` so callers that construct a ``GraphHealth``
        manually (e.g. tests) cannot bypass the cap.
    schema_version:
        Forward-compat string. Defaults to ``"1"``. PR-004b's wiring to
        ``ReasoningResult`` will serialise this field so out-of-band
        consumers (VS Code extension, audit log) can branch on schema
        evolution without a hard-coded version check.
    """

    node_count: int
    edge_count: int
    chunks_unembedded: int
    percent_stale: float
    activation_mode: Literal["semantic", "keyword_fallback", "hybrid", "unknown"]
    degraded: bool
    reason: str | None
    schema_version: str = "1"

    def __post_init__(self) -> None:
        if self.node_count < 0:
            raise ValueError(
                f"node_count must be >= 0, got {self.node_count}"
            )
        if self.edge_count < 0:
            raise ValueError(
                f"edge_count must be >= 0, got {self.edge_count}"
            )
        if self.chunks_unembedded < 0:
            raise ValueError(
                f"chunks_unembedded must be >= 0, got {self.chunks_unembedded}"
            )
        if not (0.0 <= self.percent_stale <= 1.0):
            raise ValueError(
                f"percent_stale must be in [0.0, 1.0], got {self.percent_stale}"
            )
        if self.reason is not None and len(self.reason) > 200:
            raise ValueError(
                f"reason too long ({len(self.reason)} chars); cap is 200"
            )
