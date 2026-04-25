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

"""Pattern Adaptation for Target Organization (R21 ADR-204).

Rewrites abstract pattern identifiers through target-org mapping tables.
Preserves structure, ordering, and semantic meaning; replaces identifiers
only.

Fail-closed posture: if a mapping is missing, the adaptation fails.
No raw source identifiers ever survive into the adapted pattern.

TS-2 Gate: Adaptation algorithm is core IP.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from graqle.governance.pattern_abstractor import (
    AbstractPattern,
    ClearanceTransition,
    GateStep,
    verify_privacy,
)

logger = logging.getLogger("graqle.governance.adaptation")


class TargetOrgContext(BaseModel):
    """Target organization mapping context.

    Each org supplies its own mapping tables to translate abstract
    gate classes and clearance labels back to concrete identifiers
    for that org.
    """

    model_config = ConfigDict(extra="forbid")

    org_id: str  # Raw org id — hashed on use, never stored in adapted pattern
    gate_type_map: dict[str, str] = Field(default_factory=dict)
    clearance_map: dict[str, str] = Field(default_factory=dict)
    tool_name_map: dict[str, str] = Field(default_factory=dict)
    adapter_version: str = "r21.v1"
    strict: bool = True  # If True: fail closed on unknown mappings

    @property
    def org_hash(self) -> str:
        return hashlib.sha256(self.org_id.encode("utf-8")).hexdigest()


class AdaptationResult(BaseModel):
    """Result of adapting a pattern to a target org."""

    model_config = ConfigDict(extra="forbid")

    adapted_pattern: AbstractPattern
    target_org_hash: str
    unmapped_gates: list[str] = Field(default_factory=list)
    unmapped_clearances: list[str] = Field(default_factory=list)
    adapted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AdaptationError(Exception):
    """Raised when adaptation fails (fail-closed on unknown mappings in strict mode)."""


def adapt_pattern(
    pattern: AbstractPattern,
    context: TargetOrgContext,
) -> AdaptationResult:
    """Adapt an abstract pattern to a target organization's identifiers.

    Parameters
    ----------
    pattern:
        Abstract pattern from source org (already privacy-verified).
    context:
        Target org mapping tables.

    Returns
    -------
    AdaptationResult with adapted pattern pointing to target org.

    Raises
    ------
    AdaptationError: in strict mode if any mapping is missing.
    """
    unmapped_gates: list[str] = []
    unmapped_clearances: list[str] = []

    # Adapt each gate step
    new_gate_sequence: list[GateStep] = []
    for step in pattern.gate_sequence:
        mapped_gate = context.gate_type_map.get(step.gate_type)
        if mapped_gate is None:
            if context.strict:
                unmapped_gates.append(step.gate_type)
                continue
            mapped_gate = "TARGET_UNKNOWN_GATE"

        mapped_clearance_before = context.clearance_map.get(step.clearance_before)
        mapped_clearance_after = context.clearance_map.get(step.clearance_after)

        if mapped_clearance_before is None:
            if context.strict:
                unmapped_clearances.append(step.clearance_before)
                continue
            mapped_clearance_before = "TARGET_UNKNOWN_CLEARANCE"

        if mapped_clearance_after is None:
            if context.strict:
                unmapped_clearances.append(step.clearance_after)
                continue
            mapped_clearance_after = "TARGET_UNKNOWN_CLEARANCE"

        new_gate_sequence.append(GateStep(
            gate_type=mapped_gate,
            decision=step.decision,  # decisions are already abstract
            clearance_before=mapped_clearance_before,
            clearance_after=mapped_clearance_after,
            outcome=step.outcome,
            ordinal=step.ordinal,
        ))

    # Adapt clearance transitions
    new_transitions: list[ClearanceTransition] = []
    for trans in pattern.clearance_transitions:
        from_level = context.clearance_map.get(trans.from_level)
        to_level = context.clearance_map.get(trans.to_level)
        trigger = context.gate_type_map.get(trans.trigger_gate)
        if from_level is None or to_level is None or trigger is None:
            if context.strict:
                if from_level is None:
                    unmapped_clearances.append(trans.from_level)
                if to_level is None:
                    unmapped_clearances.append(trans.to_level)
                if trigger is None:
                    unmapped_gates.append(trans.trigger_gate)
                continue
            from_level = from_level or "TARGET_UNKNOWN_CLEARANCE"
            to_level = to_level or "TARGET_UNKNOWN_CLEARANCE"
            trigger = trigger or "TARGET_UNKNOWN_GATE"
        new_transitions.append(ClearanceTransition(
            from_level=from_level,
            to_level=to_level,
            trigger_gate=trigger,
        ))

    # Fail-closed check
    if context.strict and (unmapped_gates or unmapped_clearances):
        raise AdaptationError(
            f"Adaptation failed in strict mode: "
            f"unmapped_gates={sorted(set(unmapped_gates))}, "
            f"unmapped_clearances={sorted(set(unmapped_clearances))}"
        )

    # Build adapted pattern — source_org_hash replaced with target's hash
    adapted = pattern.model_copy(update={
        "pattern_id": f"adapted-{pattern.pattern_id}-{context.org_hash[:8]}",
        "source_org_hash": context.org_hash,  # now points to target
        "gate_sequence": new_gate_sequence,
        "clearance_transitions": new_transitions,
    })

    # Post-adaptation privacy verification
    if not verify_privacy(adapted):
        raise AdaptationError(
            "Adapted pattern failed post-adaptation privacy verification. "
            "Possible leakage of source-org identifiers."
        )

    return AdaptationResult(
        adapted_pattern=adapted,
        target_org_hash=context.org_hash,
        unmapped_gates=sorted(set(unmapped_gates)),
        unmapped_clearances=sorted(set(unmapped_clearances)),
    )
