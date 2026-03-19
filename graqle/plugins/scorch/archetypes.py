"""SCORCH Friction Archetypes — 6 universal UX failure patterns."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FrictionArchetype:
    id: int
    name: str
    code: str
    user_thought: str
    description: str
    scorch_tests: tuple[str, ...]


ARCHETYPES: tuple[FrictionArchetype, ...] = (
    FrictionArchetype(
        id=1,
        name="No Visible Response",
        code="NO_RESPONSE",
        user_thought="Is it working?",
        description="User acts but nothing changes on screen.",
        scorch_tests=("dead_clicks", "silent_submissions", "action_response_feedback"),
    ),
    FrictionArchetype(
        id=2,
        name="Response Mismatch",
        code="MISMATCH",
        user_thought="Not what I asked for.",
        description="UI promises X but delivers Y.",
        scorch_tests=("incomplete_generation", "copy_paste_friction"),
    ),
    FrictionArchetype(
        id=3,
        name="Unusable Output",
        code="UNUSABLE_OUTPUT",
        user_thought="Now what do I do with this?",
        description="User gets a result but cannot use it directly.",
        scorch_tests=("copy_paste_friction", "missing_inline_editor"),
    ),
    FrictionArchetype(
        id=4,
        name="User Stranded",
        code="STRANDED",
        user_thought="Okay... now what?",
        description="Process completes but no next step is offered.",
        scorch_tests=("missing_next_step_cta", "flow_continuity"),
    ),
    FrictionArchetype(
        id=5,
        name="User Confused",
        code="CONFUSED",
        user_thought="I'm lost.",
        description="User does not understand the UI or terminology.",
        scorch_tests=("unexplained_jargon", "feature_discoverability"),
    ),
    FrictionArchetype(
        id=6,
        name="UI Contradicts State",
        code="CONTRADICTS_STATE",
        user_thought="That's wrong.",
        description="UI shows incorrect state (e.g., upgrade CTA for owned tier).",
        scorch_tests=("upsell_integrity",),
    ),
)

ARCHETYPE_BY_CODE = {a.code: a for a in ARCHETYPES}
ARCHETYPE_BY_ID = {a.id: a for a in ARCHETYPES}
