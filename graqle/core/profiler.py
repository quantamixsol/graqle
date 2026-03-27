"""Performance profiling instrumentation for graqle reasoning pipelines.

# ── graqle:intelligence ──
# module: graqle.core.profiler
# risk: LOW (impact radius: 0 modules — new file, zero blast radius)
# dependencies: __future__, dataclasses, datetime, time, typing
# constraints: CodeMetric nodes are ADDITIVE — never overwrite existing metrics
# ── /graqle:intelligence ──

graq_profile wraps graq_reason invocations and records per-node latency,
token cost, and confidence at each reasoning step. Results are written as
CodeMetric KG nodes so that future calls to graq_reason can incorporate
profiling history in graph-based recommendations.

Usage:
    from graqle.core.profiler import Profiler, ProfileConfig

    config = ProfileConfig()
    profiler = Profiler(config)
    with profiler.trace("my-session") as trace:
        # ... run reasoning steps ...
        trace.record_step("ANCHOR", latency_ms=120, tokens=800, confidence=0.85)
    result = profiler.finish(trace)
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Profile Config
# ---------------------------------------------------------------------------

@dataclass
class ProfileConfig:
    """Configuration for graq_profile instrumentation.

    Stored in graqle.yaml under 'profiling:'.
    """
    enabled: bool = True
    # Minimum latency (ms) before a step is flagged as slow
    slow_step_threshold_ms: float = 2000.0
    # Minimum token count before a step is flagged as expensive
    expensive_step_threshold_tokens: int = 4000
    # Whether to write CodeMetric nodes back to the KG
    write_kg_nodes: bool = True
    # Whether to include per-step breakdowns in the summary
    include_step_breakdown: bool = True
    # Maximum steps to record per trace (prevents unbounded growth)
    max_steps: int = 50


# ---------------------------------------------------------------------------
# Step Record
# ---------------------------------------------------------------------------

@dataclass
class StepRecord:
    """Record of a single reasoning step within a profiling trace."""
    step_name: str              # e.g. "ANCHOR", "ACTIVATE", "GENERATE", "VALIDATE", "COMMIT"
    latency_ms: float           # wall-clock time for this step
    tokens_used: int = 0        # approximate token count consumed
    confidence: float = 0.0    # output confidence (0.0–1.0) at end of step
    model: str = ""             # model used (e.g. "claude-sonnet-4-6")
    notes: str = ""             # free-form context
    timestamp: str = ""         # ISO 8601 UTC start time

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def is_slow(self, threshold_ms: float) -> bool:
        return self.latency_ms >= threshold_ms

    def is_expensive(self, threshold_tokens: int) -> bool:
        return self.tokens_used >= threshold_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_name": self.step_name,
            "latency_ms": round(self.latency_ms, 2),
            "tokens_used": self.tokens_used,
            "confidence": round(self.confidence, 4),
            "model": self.model,
            "notes": self.notes,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Node Profiling Trace
# ---------------------------------------------------------------------------

@dataclass
class NodeProfilingTrace:
    """A complete profiling trace for a single graq_reason invocation.

    Accumulated via Profiler.trace() context manager.
    Written to KG as a CodeMetric node on completion.
    """
    trace_id: str
    session_label: str          # human-readable label (e.g. "graq_reason:my-goal")
    start_time: str             # ISO 8601 UTC
    query: str = ""             # the reasoning question / goal
    steps: list[StepRecord] = field(default_factory=list)

    # Aggregate fields (computed by Profiler.finish())
    total_latency_ms: float = 0.0
    total_tokens: int = 0
    peak_confidence: float = 0.0
    final_confidence: float = 0.0
    end_time: str = ""
    slow_steps: list[str] = field(default_factory=list)
    expensive_steps: list[str] = field(default_factory=list)

    def record_step(
        self,
        step_name: str,
        latency_ms: float,
        tokens_used: int = 0,
        confidence: float = 0.0,
        model: str = "",
        notes: str = "",
    ) -> StepRecord:
        """Append a step record. Returns the StepRecord."""
        rec = StepRecord(
            step_name=step_name,
            latency_ms=latency_ms,
            tokens_used=tokens_used,
            confidence=confidence,
            model=model,
            notes=notes,
        )
        self.steps.append(rec)
        return rec

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "session_label": self.session_label,
            "query": self.query,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_latency_ms": round(self.total_latency_ms, 2),
            "total_tokens": self.total_tokens,
            "peak_confidence": round(self.peak_confidence, 4),
            "final_confidence": round(self.final_confidence, 4),
            "slow_steps": self.slow_steps,
            "expensive_steps": self.expensive_steps,
            "steps": [s.to_dict() for s in self.steps],
        }

    def to_node_metadata(self) -> dict[str, Any]:
        """Build metadata dict for KG CodeMetric node."""
        return {
            "entity_type": "CodeMetric",
            "metric_type": "performance_profile",
            "trace_id": self.trace_id,
            "session_label": self.session_label,
            "query": self.query[:200] if self.query else "",  # truncate long queries
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_latency_ms": self.total_latency_ms,
            "total_tokens": self.total_tokens,
            "peak_confidence": self.peak_confidence,
            "final_confidence": self.final_confidence,
            "slow_steps": ",".join(self.slow_steps),
            "expensive_steps": ",".join(self.expensive_steps),
            "step_count": len(self.steps),
        }


# ---------------------------------------------------------------------------
# Profile Summary
# ---------------------------------------------------------------------------

@dataclass
class ProfileSummary:
    """Human-readable summary returned by graq_profile."""
    trace: NodeProfilingTrace
    bottleneck_step: str        # step with highest latency
    bottleneck_latency_ms: float
    total_latency_ms: float
    total_tokens: int
    final_confidence: float
    recommendations: list[str] = field(default_factory=list)
    kg_node_written: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace.trace_id,
            "session_label": self.trace.session_label,
            "total_latency_ms": round(self.total_latency_ms, 2),
            "total_tokens": self.total_tokens,
            "final_confidence": round(self.final_confidence, 4),
            "bottleneck_step": self.bottleneck_step,
            "bottleneck_latency_ms": round(self.bottleneck_latency_ms, 2),
            "slow_steps": self.trace.slow_steps,
            "expensive_steps": self.trace.expensive_steps,
            "recommendations": self.recommendations,
            "kg_node_written": self.kg_node_written,
            "step_breakdown": [s.to_dict() for s in self.trace.steps]
            if self.trace.steps else [],
        }


# ---------------------------------------------------------------------------
# Profiler
# ---------------------------------------------------------------------------

class Profiler:
    """Performance profiler for graqle reasoning pipelines.

    Instantiate once per server, call new_trace() before each invocation,
    and call finish() to compute aggregates and optionally write to KG.
    """

    def __init__(self, config: ProfileConfig | None = None) -> None:
        self.config = config or ProfileConfig()

    def new_trace(self, session_label: str, query: str = "") -> NodeProfilingTrace:
        """Create a new NodeProfilingTrace. Call before the reasoning session."""
        now = datetime.now(timezone.utc).isoformat()
        trace_id = (
            "profile_"
            + hashlib.sha256(f"{now}{session_label}".encode()).hexdigest()[:12]
        )
        return NodeProfilingTrace(
            trace_id=trace_id,
            session_label=session_label,
            start_time=now,
            query=query,
        )

    def finish(self, trace: NodeProfilingTrace) -> ProfileSummary:
        """Compute aggregates, build recommendations, return ProfileSummary.

        This does NOT write to the KG — the MCP handler does that so it
        can access the live graph object.
        """
        cfg = self.config
        now = datetime.now(timezone.utc).isoformat()
        trace.end_time = now

        # Aggregate totals
        trace.total_latency_ms = sum(s.latency_ms for s in trace.steps)
        trace.total_tokens = sum(s.tokens_used for s in trace.steps)
        confidences = [s.confidence for s in trace.steps if s.confidence > 0]
        trace.peak_confidence = max(confidences) if confidences else 0.0
        trace.final_confidence = trace.steps[-1].confidence if trace.steps else 0.0

        # Flag slow / expensive steps
        trace.slow_steps = [
            s.step_name for s in trace.steps if s.is_slow(cfg.slow_step_threshold_ms)
        ]
        trace.expensive_steps = [
            s.step_name
            for s in trace.steps
            if s.is_expensive(cfg.expensive_step_threshold_tokens)
        ]

        # Find bottleneck
        if trace.steps:
            worst = max(trace.steps, key=lambda s: s.latency_ms)
            bottleneck_step = worst.step_name
            bottleneck_latency_ms = worst.latency_ms
        else:
            bottleneck_step = ""
            bottleneck_latency_ms = 0.0

        # Build recommendations
        recs: list[str] = []
        if trace.slow_steps:
            recs.append(
                f"Slow steps detected: {trace.slow_steps}. "
                f"Consider caching activation signals or reducing beam_width."
            )
        if trace.expensive_steps:
            recs.append(
                f"High token steps: {trace.expensive_steps}. "
                f"Consider narrowing context or increasing confidence_threshold."
            )
        if trace.final_confidence < 0.60:
            recs.append(
                f"Final confidence {trace.final_confidence:.2f} is below 0.60. "
                f"Graph may need more nodes — run graq_learn to enrich."
            )
        if trace.total_latency_ms > 10_000:
            recs.append(
                f"Total latency {trace.total_latency_ms:.0f}ms exceeds 10s. "
                f"Consider dry_run=True for planning tasks."
            )
        if not recs:
            recs.append("No performance issues detected.")

        return ProfileSummary(
            trace=trace,
            bottleneck_step=bottleneck_step,
            bottleneck_latency_ms=bottleneck_latency_ms,
            total_latency_ms=trace.total_latency_ms,
            total_tokens=trace.total_tokens,
            final_confidence=trace.final_confidence,
            recommendations=recs,
        )

    def record_timed_step(
        self,
        trace: NodeProfilingTrace,
        step_name: str,
        start_ns: int,
        tokens_used: int = 0,
        confidence: float = 0.0,
        model: str = "",
        notes: str = "",
    ) -> StepRecord:
        """Helper: compute latency from start_ns = time.perf_counter_ns() snapshot."""
        elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
        return trace.record_step(
            step_name=step_name,
            latency_ms=elapsed_ms,
            tokens_used=tokens_used,
            confidence=confidence,
            model=model,
            notes=notes,
        )
