# ------------------------------------------------------------------
# PATENT NOTICE -- Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Applications EP26162901.8, EP26166054.2, EP26167849.4 (composite),
# owned by Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: support@quantamixsolutions.com
# ------------------------------------------------------------------

"""Pattern Abstractor for Cross-Org Transfer (R21 ADR-204).

Extracts structural governance patterns from R18 GovernedTrace records,
stripping all PII, credentials, raw identifiers, and org-specific strings.

Output: AbstractPattern containing only gate decision sequences,
clearance transitions, and aggregate outcomes — never raw data.

Privacy posture: allowlist-only schema. Any unrecognized input field is
dropped. Every emitted field is validated against the forbidden-content
denylist before return.

TS-2 Gate: Abstraction algorithm is core IP.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("graqle.governance.pattern_abstractor")

ABSTRACTOR_VERSION = "r21.v1"


# ---------------------------------------------------------------------------
# Forbidden content patterns (denylist for recursive scan)
# ---------------------------------------------------------------------------

# Patterns that must NEVER appear in an abstract pattern
_FORBIDDEN_PATTERNS = [
    re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),  # email
    re.compile(r"https?://[^\s]+"),                                  # URL
    re.compile(r"/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_./\\-]+"),             # unix path
    re.compile(r"[A-Za-z]:[\\/][^\s]+"),                            # windows path
    re.compile(r"\b(?:sk|pk|api)[-_][a-zA-Z0-9]{16,}"),             # API keys
    re.compile(r"\b[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\b"),  # IPv4
    re.compile(r"Bearer\s+[a-zA-Z0-9_\-.]+"),                       # Bearer token
    re.compile(r"[a-fA-F0-9]{32,}"),                                # long hex (not SHA-256)
]

# Minimum entropy to consider a string a potential credential
_ENTROPY_SUSPICION_THRESHOLD = 4.5


def _shannon_entropy(s: str) -> float:
    """Compute Shannon entropy of a string (bits per char)."""
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    import math
    length = len(s)
    entropy = 0.0
    for count in freq.values():
        p = count / length
        entropy -= p * math.log2(p)
    return entropy


def _contains_forbidden(value: Any, allow_sha256: bool = True) -> bool:
    """Recursively check if any value contains forbidden content."""
    if value is None or isinstance(value, (bool, int, float)):
        return False
    if isinstance(value, str):
        # Allow SHA-256 hashes (64 hex chars exactly)
        if allow_sha256 and len(value) == 64 and all(c in "0123456789abcdef" for c in value.lower()):
            return False
        for pattern in _FORBIDDEN_PATTERNS:
            if pattern.search(value):
                return True
        # Entropy check for opaque suspicious strings
        if len(value) >= 20 and _shannon_entropy(value) >= _ENTROPY_SUSPICION_THRESHOLD:
            # Allow if it looks like a normalized tag (lowercase words)
            if not re.match(r"^[a-z][a-z0-9_-]*$", value):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_forbidden(v, allow_sha256) for v in value)
    if isinstance(value, dict):
        return any(_contains_forbidden(v, allow_sha256) for v in value.values())
    return True  # unknown type -> fail closed


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class GateStep(BaseModel):
    """Single step in an abstracted gate sequence."""

    model_config = ConfigDict(extra="forbid")

    gate_type: str  # abstract class (e.g., "clearance", "budget", "ip_gate")
    decision: str  # normalized: pass/block/warn
    clearance_before: str  # normalized level name
    clearance_after: str
    outcome: str  # normalized outcome code
    ordinal: int  # order in sequence


class ClearanceTransition(BaseModel):
    """Single clearance level transition observed."""

    model_config = ConfigDict(extra="forbid")

    from_level: str
    to_level: str
    trigger_gate: str  # abstract gate class


class OutcomeAggregates(BaseModel):
    """Aggregate outcome statistics across traces."""

    model_config = ConfigDict(extra="forbid")

    pass_rate: float = 0.0
    fail_rate: float = 0.0
    block_rate: float = 0.0
    retry_count: int = 0
    escalation_count: int = 0
    avg_latency_ms: float = 0.0
    counts_by_outcome: dict[str, int] = Field(default_factory=dict)


class SimilarityProfile(BaseModel):
    """Multi-dimensional similarity profile for matching."""

    model_config = ConfigDict(extra="forbid")

    domain: float = 0.0  # [0, 1]
    stack: float = 0.0
    governance: float = 0.0


class Provenance(BaseModel):
    """Hash-only provenance. Never raw trace data."""

    model_config = ConfigDict(extra="forbid")

    r18_trace_hash: str  # SHA-256 of source trace batch
    extractor_version: str = ABSTRACTOR_VERSION
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Redactions(BaseModel):
    """Flags indicating which redactions were applied."""

    model_config = ConfigDict(extra="forbid")

    pii_removed: bool = True
    org_ids_removed: bool = True
    creds_removed: bool = True


class AbstractPattern(BaseModel):
    """An abstracted governance pattern safe for cross-org transfer.

    Invariants:
        - No PII, credentials, URLs, paths, or raw identifiers
        - source_org_hash is SHA-256 (never raw org name)
        - All fields are structural or aggregate — no free text
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "r21.v1"
    pattern_id: str = Field(default_factory=lambda: f"pat-{uuid4().hex[:12]}")
    source_org_hash: str  # SHA-256 of org identifier
    trace_class: str  # coarse category (e.g., "reasoning", "generation", "review")
    domain_tags: list[str] = Field(default_factory=list)
    stack_tags: list[str] = Field(default_factory=list)
    governance_tags: list[str] = Field(default_factory=list)
    gate_sequence: list[GateStep] = Field(default_factory=list)
    clearance_transitions: list[ClearanceTransition] = Field(default_factory=list)
    outcome_aggregates: OutcomeAggregates = Field(default_factory=OutcomeAggregates)
    similarity_profile: SimilarityProfile = Field(default_factory=SimilarityProfile)
    provenance: Provenance
    redactions: Redactions = Field(default_factory=Redactions)


# ---------------------------------------------------------------------------
# Abstraction Algorithm
# ---------------------------------------------------------------------------

# Map raw tool names to abstract trace classes
_TRACE_CLASS_MAP = {
    "graq_reason": "reasoning",
    "graq_reason_batch": "reasoning",
    "graq_generate": "generation",
    "graq_edit": "editing",
    "graq_review": "review",
    "graq_predict": "prediction",
    "graq_auto": "autonomous",
    "graq_bash": "shell",
    "graq_read": "read",
    "graq_write": "write",
}

# Map raw gate IDs to abstract gate classes
_GATE_CLASS_MAP = {
    "CG-01": "session",
    "CG-02": "plan",
    "CG-03": "edit_gate",
    "CG-04": "batch",
    "CLEARANCE": "clearance",
    "IP_TRADE": "ip_gate",
    "GIT_GOVERNANCE": "git_gate",
    "BUDGET": "budget_gate",
}


def _hash_org(org_id: str) -> str:
    """Hash an org identifier to SHA-256."""
    return hashlib.sha256(org_id.encode("utf-8")).hexdigest()


def _hash_trace_batch(traces: list[dict[str, Any]]) -> str:
    """Hash a trace batch for provenance (no content stored)."""
    hasher = hashlib.sha256()
    for t in traces:
        trace_id = str(t.get("id", ""))
        hasher.update(trace_id.encode("utf-8"))
    return hasher.hexdigest()


def _abstract_trace_class(tool_name: str) -> str:
    """Map tool_name to abstract trace class, stripping kogni_ prefix."""
    canonical = tool_name.replace("kogni_", "graq_", 1) if tool_name.startswith("kogni_") else tool_name
    return _TRACE_CLASS_MAP.get(canonical, "other")


def _abstract_gate_type(gate_id: str, gate_type: str) -> str:
    """Map a raw gate to an abstract gate class."""
    if gate_id in _GATE_CLASS_MAP:
        return _GATE_CLASS_MAP[gate_id]
    return _GATE_CLASS_MAP.get(gate_type, "other_gate")


def _normalize_clearance(level: str) -> str:
    """Normalize a clearance level label to abstract form."""
    normalized = level.upper().strip() if isinstance(level, str) else "UNKNOWN"
    if normalized in ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"):
        return normalized
    return "UNKNOWN"


def _normalize_decision(decision: str) -> str:
    """Normalize a gate decision to abstract form."""
    normalized = decision.upper().strip() if isinstance(decision, str) else "UNKNOWN"
    if normalized in ("PASS", "BLOCK", "WARN"):
        return normalized
    return "UNKNOWN"


def _normalize_outcome(outcome: str) -> str:
    """Normalize a trace outcome to abstract form."""
    normalized = outcome.upper().strip() if isinstance(outcome, str) else "UNKNOWN"
    if normalized in ("SUCCESS", "PARTIAL", "FAILURE", "BLOCKED"):
        return normalized
    return "UNKNOWN"


def extract_abstract_pattern(
    traces: list[dict[str, Any]],
    org_id: str,
    trace_class_override: str | None = None,
    domain_tags: list[str] | None = None,
    stack_tags: list[str] | None = None,
    governance_tags: list[str] | None = None,
) -> AbstractPattern:
    """Extract an abstract pattern from a batch of R18 traces.

    Parameters
    ----------
    traces:
        List of GovernedTrace dicts (from TraceStore.read_traces).
    org_id:
        Raw org identifier. Will be SHA-256 hashed before storage.
    trace_class_override:
        Optional override for trace class (default: inferred from majority tool).
    domain_tags, stack_tags, governance_tags:
        Optional normalized tag lists for similarity matching.

    Returns
    -------
    AbstractPattern with all PII/raw identifiers stripped.

    Raises
    ------
    ValueError: if the abstract pattern fails privacy verification.
    """
    if not traces:
        raise ValueError("Cannot extract pattern from empty trace batch")

    source_org_hash = _hash_org(org_id)
    provenance_hash = _hash_trace_batch(traces)

    # Infer trace class from majority tool
    if trace_class_override:
        trace_class = trace_class_override
    else:
        tool_classes: dict[str, int] = {}
        for t in traces:
            tool = t.get("tool_name", "")
            cls = _abstract_trace_class(tool)
            tool_classes[cls] = tool_classes.get(cls, 0) + 1
        trace_class = max(tool_classes.items(), key=lambda x: x[1])[0] if tool_classes else "other"

    # Build gate sequence (up to first 50 gate decisions)
    gate_sequence: list[GateStep] = []
    for t in traces[:50]:
        clearance = _normalize_clearance(t.get("clearance_level", ""))
        for gd in t.get("governance_decisions", []):
            gate_type = _abstract_gate_type(
                gd.get("gate_id", ""),
                gd.get("gate_type", ""),
            )
            decision = _normalize_decision(gd.get("decision", ""))
            gate_sequence.append(GateStep(
                gate_type=gate_type,
                decision=decision,
                clearance_before=clearance,
                clearance_after=clearance,  # simplified for v1
                outcome=_normalize_outcome(t.get("outcome", "")),
                ordinal=len(gate_sequence),
            ))

    # Clearance transitions (observed level changes)
    transitions: list[ClearanceTransition] = []
    clearance_levels = set()
    for t in traces:
        cl = _normalize_clearance(t.get("clearance_level", ""))
        if cl != "UNKNOWN":
            clearance_levels.add(cl)

    # Outcome aggregates
    outcome_counts: dict[str, int] = {}
    total_latency = 0.0
    latency_count = 0
    retry_count = 0
    escalation_count = 0
    for t in traces:
        outcome = _normalize_outcome(t.get("outcome", ""))
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        latency = t.get("latency_ms", 0.0)
        if isinstance(latency, (int, float)) and latency >= 0:
            total_latency += latency
            latency_count += 1
        if t.get("human_override"):
            escalation_count += 1

    total = len(traces)
    aggregates = OutcomeAggregates(
        pass_rate=outcome_counts.get("SUCCESS", 0) / total,
        fail_rate=outcome_counts.get("FAILURE", 0) / total,
        block_rate=outcome_counts.get("BLOCKED", 0) / total,
        retry_count=retry_count,
        escalation_count=escalation_count,
        avg_latency_ms=total_latency / latency_count if latency_count > 0 else 0.0,
        counts_by_outcome=outcome_counts,
    )

    # Normalize provided tags (lowercase, alphanumeric + hyphens/underscores)
    def _normalize_tags(tags: list[str] | None) -> list[str]:
        if not tags:
            return []
        out = []
        for tag in tags:
            if isinstance(tag, str):
                clean = re.sub(r"[^a-z0-9_-]", "", tag.lower().strip())
                if clean and len(clean) <= 32:
                    out.append(clean)
        return out[:20]  # cap count

    pattern = AbstractPattern(
        source_org_hash=source_org_hash,
        trace_class=trace_class,
        domain_tags=_normalize_tags(domain_tags),
        stack_tags=_normalize_tags(stack_tags),
        governance_tags=_normalize_tags(governance_tags),
        gate_sequence=gate_sequence,
        clearance_transitions=transitions,
        outcome_aggregates=aggregates,
        provenance=Provenance(r18_trace_hash=provenance_hash),
    )

    # Post-abstraction privacy verification
    if not verify_privacy(pattern):
        raise ValueError("Abstracted pattern failed privacy verification")

    return pattern


def verify_privacy(pattern: AbstractPattern) -> bool:
    """Verify an abstract pattern contains no forbidden content.

    Three-layer verification:
    1. Schema is allowlist-only (enforced by Pydantic extra=forbid)
    2. source_org_hash is valid SHA-256
    3. Recursive denylist scan on all fields

    Returns False on any violation (fail-closed).
    """
    # Layer 2: SHA-256 format check
    if not isinstance(pattern.source_org_hash, str):
        return False
    if len(pattern.source_org_hash) != 64:
        return False
    if not all(c in "0123456789abcdef" for c in pattern.source_org_hash.lower()):
        return False

    # Layer 3: Recursive denylist scan on model_dump output
    data = pattern.model_dump(mode="json")
    # The source_org_hash and r18_trace_hash are SHA-256 (allowed)
    if _contains_forbidden(data, allow_sha256=True):
        return False

    return True
