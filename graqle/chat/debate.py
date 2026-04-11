"""Adversarial debate subsystem — PROPOSER / ADVERSARY / ARBITER.

TB-F5 of ChatAgentLoop v4 (ADR-152). Runs three personas in parallel
via ``asyncio.gather`` of three ``graq_reason`` calls (will migrate to
the native ``graq_reason_batch`` path now that CG-REASON-01 is fixed
in v0.47.3 — the constructor crash was unblocking this).

The arbiter applies a deterministic rule order:

  1. unresolved safety  (highest precedence)
  2. missing prerequisite
  3. cost
  4. ambiguity         (lowest)

Max 2 rounds. Each round emits ``debate_chip`` events labeled by
persona for the streaming UI to render expandable bubbles.

Backend abstraction
-------------------
The ``ReasonFn`` protocol decouples the debate from any concrete
``graq_reason`` implementation. Tests inject a deterministic stub.
ChatAgentLoop will inject the live MCP handler at construction time.

CGI-compatibility note (ADR-153 seed)
-------------------------------------
Each ``DebateRecord`` carries the fields a future CGI ``Decision``
node would need (proposer_text, adversary_text, arbiter_verdict,
arbiter_reason, options_considered, validated_by). Today these live
in the in-memory record; post-v0.50.0 the CGI design session can
decide whether to fold them into a ``Decision`` node on terminal
debate completion.
"""

# ── graqle:intelligence ──
# module: graqle.chat.debate
# risk: MEDIUM (concurrent reasoning calls — must time out gracefully)
# consumers: chat.agent_loop (planned TB-F7)
# dependencies: __future__, asyncio, dataclasses, typing
# constraints: deterministic arbiter rule order; max 2 rounds
# ── /graqle:intelligence ──

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

logger = logging.getLogger("graqle.chat.debate")

MAX_DEBATE_ROUNDS = 2

PROPOSER_PROMPT = """You are PROPOSER. Recommend the next tool call \
or sequence to advance the user's task. Keep it under 80 words. \
End with: VERDICT: <one_line_recommendation>."""

ADVERSARY_PROMPT = """You are ADVERSARY. Critique the proposed action. \
Look for: unresolved safety, missing prerequisites, hidden cost, ambiguity. \
Keep it under 80 words. End with: CONCERN: <one_line_concern> or NONE."""

ARBITER_PROMPT = """You are ARBITER. Given a PROPOSER recommendation \
and an ADVERSARY concern, choose: PROCEED, REFINE, or BLOCK. Apply rule \
order strictly: safety > prerequisite > cost > ambiguity. \
End with: VERDICT: <PROCEED|REFINE|BLOCK> REASON: <one_line>."""


# ──────────────────────────────────────────────────────────────────────
# Protocols + records
# ──────────────────────────────────────────────────────────────────────


class ReasonFn(Protocol):
    async def __call__(self, prompt: str, *, persona: str) -> str: ...


@dataclass
class PersonaResponse:
    persona: str
    text: str
    error: str | None = None


@dataclass
class DebateRound:
    round_index: int
    proposer: PersonaResponse
    adversary: PersonaResponse
    arbiter: PersonaResponse
    arbiter_verdict: str  # PROCEED|REFINE|BLOCK
    arbiter_reason: str


@dataclass
class DebateRecord:
    """Final debate outcome with full trail for streaming + CGI."""

    rounds: list[DebateRound] = field(default_factory=list)
    final_verdict: str = ""  # PROCEED|REFINE|BLOCK
    final_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rounds": [
                {
                    "round_index": r.round_index,
                    "proposer": r.proposer.text,
                    "adversary": r.adversary.text,
                    "arbiter": r.arbiter.text,
                    "arbiter_verdict": r.arbiter_verdict,
                    "arbiter_reason": r.arbiter_reason,
                }
                for r in self.rounds
            ],
            "final_verdict": self.final_verdict,
            "final_reason": self.final_reason,
        }


# ──────────────────────────────────────────────────────────────────────
# Deterministic arbiter rule
# ──────────────────────────────────────────────────────────────────────

# Match the rule order exactly: safety > prerequisite > cost > ambiguity.
_RULE_KEYWORDS: list[tuple[str, str]] = [
    ("safety", "unsafe"),
    ("safety", "destructive"),
    ("safety", "credentials env-var name leak"),
    ("safety", "credentials"),
    ("safety", "no governance"),
    ("prerequisite", "missing prerequisite"),
    ("prerequisite", "needs context"),
    ("prerequisite", "no preflight"),
    ("cost", "expensive"),
    ("cost", "slow"),
    ("cost", "high latency"),
    ("ambiguity", "ambiguous"),
    ("ambiguity", "unclear"),
]


def deterministic_arbiter(
    proposer_text: str,
    adversary_text: str,
) -> tuple[str, str]:
    """Apply the deterministic rule order to decide the verdict.

    Returns ``(verdict, reason)`` where verdict ∈ {PROCEED, REFINE, BLOCK}.

    The function never calls a backend — it inspects the strings the
    backend already produced. This is the safety net under the LLM
    arbiter: if the LLM picks an inconsistent verdict, the deterministic
    rule overrides it.
    """
    adv_lower = adversary_text.lower()
    if "concern: none" in adv_lower or "no concern" in adv_lower:
        return "PROCEED", "no adversary concern"

    for category, keyword in _RULE_KEYWORDS:
        if keyword in adv_lower:
            if category == "safety":
                return "BLOCK", f"safety rule fired: {keyword}"
            if category == "prerequisite":
                return "REFINE", f"prerequisite rule fired: {keyword}"
            if category == "cost":
                return "REFINE", f"cost rule fired: {keyword}"
            if category == "ambiguity":
                return "REFINE", f"ambiguity rule fired: {keyword}"

    # Adversary raised a concern but it didn't match a rule → REFINE
    # (the safer default).
    return "REFINE", "unclassified adversary concern"


# ──────────────────────────────────────────────────────────────────────
# Debate engine
# ──────────────────────────────────────────────────────────────────────


async def _safe_reason(
    reason_fn: ReasonFn,
    prompt: str,
    persona: str,
) -> PersonaResponse:
    try:
        text = await reason_fn(prompt, persona=persona)
        return PersonaResponse(persona=persona, text=text)
    except Exception as exc:
        logger.warning("Debate persona %s failed: %s", persona, exc)
        return PersonaResponse(persona=persona, text="", error=str(exc))


async def run_debate(
    question: str,
    *,
    reason_fn: ReasonFn,
    max_rounds: int = MAX_DEBATE_ROUNDS,
    on_chip: Callable[[str, str, str], Awaitable[None]] | None = None,
) -> DebateRecord:
    """Run up to ``max_rounds`` of PROPOSER/ADVERSARY/ARBITER debate.

    Args:
        question: The action under debate (a tool plan, a code suggestion, ...)
        reason_fn: Async callable that returns persona text given a prompt
            + persona label. ChatAgentLoop will inject a graq_reason wrapper.
        max_rounds: Hard ceiling — never exceeds MAX_DEBATE_ROUNDS even if
            higher is requested.
        on_chip: Optional async callback ``(persona, text, verdict)`` for
            streaming each round to the UI.

    Returns:
        ``DebateRecord`` with the full trail and the final verdict.
    """
    record = DebateRecord()
    capped_rounds = min(max_rounds, MAX_DEBATE_ROUNDS)
    for idx in range(capped_rounds):
        proposer_prompt = f"{PROPOSER_PROMPT}\n\nQUESTION: {question}"
        if record.rounds:
            last = record.rounds[-1]
            proposer_prompt += (
                f"\n\nPRIOR ROUND ARBITER VERDICT: {last.arbiter_verdict} "
                f"({last.arbiter_reason}). Refine accordingly."
            )

        # Phase 1: PROPOSER alone.
        proposer = await _safe_reason(reason_fn, proposer_prompt, "PROPOSER")

        adversary_prompt = (
            f"{ADVERSARY_PROMPT}\n\nQUESTION: {question}\n\n"
            f"PROPOSER SAID: {proposer.text}"
        )
        # Phase 2: ADVERSARY alone (sees proposer output).
        adversary = await _safe_reason(reason_fn, adversary_prompt, "ADVERSARY")

        arbiter_prompt = (
            f"{ARBITER_PROMPT}\n\nQUESTION: {question}\n\n"
            f"PROPOSER: {proposer.text}\n\nADVERSARY: {adversary.text}"
        )
        arbiter = await _safe_reason(reason_fn, arbiter_prompt, "ARBITER")

        # Deterministic override of LLM verdict using rule order.
        det_verdict, det_reason = deterministic_arbiter(
            proposer.text, adversary.text,
        )
        round_record = DebateRound(
            round_index=idx,
            proposer=proposer,
            adversary=adversary,
            arbiter=arbiter,
            arbiter_verdict=det_verdict,
            arbiter_reason=det_reason,
        )
        record.rounds.append(round_record)

        if on_chip is not None:
            await on_chip("PROPOSER", proposer.text, "")
            await on_chip("ADVERSARY", adversary.text, "")
            await on_chip("ARBITER", arbiter.text, det_verdict)

        # Stop early on PROCEED or BLOCK; only REFINE continues.
        if det_verdict in ("PROCEED", "BLOCK"):
            record.final_verdict = det_verdict
            record.final_reason = det_reason
            return record

    # Exhausted rounds — last round's verdict stands.
    last = record.rounds[-1]
    record.final_verdict = last.arbiter_verdict
    record.final_reason = last.arbiter_reason
    return record


__all__ = [
    "ADVERSARY_PROMPT",
    "ARBITER_PROMPT",
    "DebateRecord",
    "DebateRound",
    "MAX_DEBATE_ROUNDS",
    "PROPOSER_PROMPT",
    "PersonaResponse",
    "ReasonFn",
    "deterministic_arbiter",
    "run_debate",
]
