# ------------------------------------------------------------------
# PATENT NOTICE -- Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Applications EP26162901.8 and EP26166054.2, owned by
# Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: support@quantamixsolutions.com
# ------------------------------------------------------------------

"""Governed Execution Trace Schema (R18 ADR-201).

Defines the Pydantic trace model for capturing governed execution events,
tool calls, and governance decisions. Every MCP tool call produces a
GovernedTrace record that is validated, persisted, and ingested into the KG.

Public serialization (to_public_dict) excludes governance_decisions.
Internal serialization (to_internal_dict) preserves the full trace.

TS-2 Gate: GovernanceDecision structure is internal IP.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class GateType(str, Enum):
    """Types of governance gates that can produce decisions."""

    CLEARANCE = "CLEARANCE"
    IP_TRADE = "IP_TRADE"
    GIT_GOVERNANCE = "GIT_GOVERNANCE"
    BUDGET = "BUDGET"


class Decision(str, Enum):
    """Outcome of a governance gate evaluation."""

    PASS = "PASS"
    BLOCK = "BLOCK"
    WARN = "WARN"


class ClearanceLevel(str, Enum):
    """Classification level for trace records.

    Aligned with core/types.ClearanceLevel (int, Enum).
    R18 spec uses 'SECRET' for the highest level; implementation uses
    'RESTRICTED' to match the existing core/types convention.
    Mapping: spec SECRET = implementation RESTRICTED.
    """

    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class Outcome(str, Enum):
    """Overall outcome of a governed tool execution."""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILURE = "FAILURE"
    BLOCKED = "BLOCKED"


# ---------------------------------------------------------------------------
# Nested Models
# ---------------------------------------------------------------------------


class ToolCall(BaseModel):
    """Record of a nested tool invocation within a governed execution."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    result_summary: str | None = None


class GovernanceDecision(BaseModel):
    """A single governance gate decision. TS-2 gated internal IP."""

    model_config = ConfigDict(extra="forbid")

    gate_id: str
    gate_type: GateType
    decision: Decision
    reason: str = Field(max_length=200)
    auto_corrected: bool = False


# ---------------------------------------------------------------------------
# Main Trace Model
# ---------------------------------------------------------------------------

_QUERY_MAX_LENGTH = 4000
_NON_PRINTABLE_RE = re.compile(r"[^\x20-\x7E\t\n]")


class GovernedTrace(BaseModel):
    """A single governed execution trace record.

    Every MCP tool call produces one GovernedTrace. The trace is validated
    at creation time, persisted to the append-only trace store, and
    asynchronously ingested into the knowledge graph.

    Invariants:
        - id is UUID v4 (auto-generated)
        - timestamp is always UTC-aware
        - query is sanitized and non-empty
        - confidence is finite and in [0.0, 1.0]
        - override_reason is required iff human_override is True
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    tool_name: str
    query: str
    context_nodes: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    governance_decisions: list[GovernanceDecision] = Field(
        default_factory=list,
        repr=False,
        json_schema_extra={"internal": True},
    )
    clearance_level: ClearanceLevel = ClearanceLevel.INTERNAL
    outcome: Outcome
    confidence: float = Field(ge=0.0, le=1.0)
    cost_usd: float = Field(ge=0.0, default=0.0)
    latency_ms: float = Field(ge=0.0, default=0.0)
    human_override: bool = False
    override_reason: str | None = None
    error: str | None = None

    # -- Validators --------------------------------------------------------

    @field_validator("query")
    @classmethod
    def sanitize_query(cls, value: str) -> str:
        """Strip whitespace, remove non-printable chars, truncate, reject empty."""
        sanitized = _NON_PRINTABLE_RE.sub("", value).strip()
        sanitized = sanitized[:_QUERY_MAX_LENGTH]
        if not sanitized:
            raise ValueError("query must not be empty after sanitization")
        return sanitized

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        """Ensure timestamp is UTC-aware. Naive datetimes are assumed UTC."""
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @field_validator("confidence")
    @classmethod
    def validate_confidence_finite(cls, value: float) -> float:
        """Reject NaN and Infinity values."""
        if math.isnan(value) or math.isinf(value):
            raise ValueError("confidence must be a finite number")
        return value

    @model_validator(mode="after")
    def validate_override(self) -> GovernedTrace:
        """Enforce override_reason consistency with human_override flag."""
        if self.human_override:
            if self.override_reason is None or not self.override_reason.strip():
                raise ValueError(
                    "override_reason is required when human_override is True"
                )
            self.override_reason = self.override_reason.strip()
        else:
            self.override_reason = None
        return self

    # -- Serialization -----------------------------------------------------

    def to_public_dict(self) -> dict[str, Any]:
        """Serialize excluding TS-2 gated governance_decisions."""
        return self.model_dump(
            mode="json",
            exclude={"governance_decisions"},
        )

    def to_internal_dict(self) -> dict[str, Any]:
        """Full serialization including all governance fields."""
        return self.model_dump(mode="json")
