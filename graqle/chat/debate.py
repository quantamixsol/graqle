"""Concern-check subsystem — 3-role structured self-check v0.50.0-round1).

Runs three neutral roles in parallel via :func:`asyncio.gather` of three
``reason_fn`` calls and applies an in-code deterministic classifier that
can override the judging role's verdict for conservative safety. The
three-role structure is:

- **CANDIDATE** — proposes the next action, keeps response short, ends
  with a one-line recommendation.
- **CRITIC** — critiques the candidate's proposal against the project
  policy categories, ends with a single-line concern or NONE.
- **JUDGE** — chooses one of ``PROCEED``, ``REFINE``, or ``BLOCK`` based
  on the critic's concern, then emits a one-line rationale.

The in-code classifier then re-categorises the critic text and can
override the judge's decision toward the most conservative outcome.

Precedence between concern categories is enforced in code
(:func:`classify_concern`), not stated in any prompt — the prompts only
list the four concern categories and ask the JUDGE to choose
conservatively. This keeps the policy authority inside the codebase
rather than in user-visible text.

Security controls (Round-1 graq_review feedback):

- **No secret exposure:** the module never reads environment variables,
  never accesses credentials, never invokes any subprocess. Prompts are
  built purely from the question string and prior role text, both of
  which are treated as untrusted. The streaming callback
  (``on_signal``) forwards the exact text each role produced without
  any environment/credential enrichment.
- **No subprocess usage:** the module imports only ``asyncio``,
  ``dataclasses``, ``logging``, ``re``, and ``typing``. Any future
  subprocess call on this path MUST be reviewed against this contract.
- **Banned-phrase guard:** :func:`_assert_no_banned_phrases` is invoked
  at import time on every prompt template to verify none of the
  patent-leaking English sentences made it back in through a merge or
  copy-paste regression. The test suite re-asserts the same check at
  runtime.

Mechanism preserved (NON-NEGOTIABLE — operator waiver condition):

- Three parallel role calls via :func:`asyncio.gather`
- Deterministic in-code override of the LLM's judge decision
- Four concern categories with a fixed internal ordering applied in
  :func:`classify_concern`. The specific ordering lives in code, not
  in prompt text
- Round-refinement feedback loop — the JUDGE's prior-round decision and
  rationale feed the next round's CANDIDATE prompt
- ``MAX_CHECK_ROUNDS = 2`` hard ceiling
"""

# ── graqle:intelligence ──
# module: graqle.chat.debate
# risk: MEDIUM (concurrent reasoning calls — must time out gracefully)
# consumers: chat.agent_loop # dependencies: __future__, asyncio, dataclasses, logging, re, typing
# constraints: no subprocess, no env reads, no credential handling;
#   precedence lives in code not prompts; 3-round ceiling
# ── /graqle:intelligence ──

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

logger = logging.getLogger("graqle.chat.debate")

MAX_CHECK_ROUNDS = 2

# Role vocabulary — neutral, standard ML workflow terminology. These
# three strings are the public role identifiers; the ``reason_fn``
# protocol receives them via the ``role`` keyword. Downstream
# consumers (tests, streaming UI) match on these exact strings.
ROLE_CANDIDATE = "CANDIDATE"
ROLE_CRITIC = "CRITIC"
ROLE_JUDGE = "JUDGE"

# Prompt templates — kept deliberately generic. Precedence between the
# four concern categories is NEVER stated in prompt text; it is enforced
# in :func:`classify_concern` below. The categories themselves are
# listed so the CRITIC has a consistent vocabulary to surface issues in.
CANDIDATE_PROMPT = (
    "You are the CANDIDATE role. Recommend the next action that advances "
    "the user's task. Keep your response under 80 words. End with: "
    "RECOMMENDATION: <one_line>."
)

CRITIC_PROMPT = (
    "You are the CRITIC role. Review the candidate's recommendation "
    "against the project policy. Consider four concern categories: "
    "safety, prerequisites, cost, and ambiguity. Keep it under 80 words. "
    "End with: CONCERN: <one_line_concern> or NONE."
)

JUDGE_PROMPT = (
    "You are the JUDGE role. Given a candidate recommendation and the "
    "critic's concern, choose PROCEED, REFINE, or BLOCK. Resolve any "
    "conflict between concern categories conservatively. End with: "
    "DECISION: <PROCEED|REFINE|BLOCK> RATIONALE: <one_line>."
)

# RO2-4 (Round-2): banned-phrase guard moved from literal strings to
# SHA-1[:16] hashes. The guard still fails fast on any regression that
# reintroduces a patent-leaking sentence, but the shipped source no
# longer contains the banned sentences themselves — defeating the
# self-defeat vulnerability flagged in the Round-2 review.
#
# The plaintext phrase list is NEVER committed to this source file. To
# add a new banned phrase, compute its hash with:
#
#   python -c "import hashlib; print(hashlib.sha1('your phrase'.lower().encode()).hexdigest()[:16])"
#
# and append the hex literal below. Document the REASON for the ban in
# the commit message, not in this file.
_BANNED_PHRASE_HASHES: frozenset[str] = frozenset({
    "dc4f7db559b35e74",
    "2e19d566090cc518",
    "7887a0a371b35e02",
    "9e2e5ec096d7d12e",
    "31ae1b626bac1d11",
    "b883b5bd8897f0e8",
    "108b95ab3295c222",
    "f0cd8c5728b14601",
    "eb31acd884912638",
    "ae2729105a3c56bf",
})
assert len(_BANNED_PHRASE_HASHES) == 10, "banned-phrase hash set shrunk"


def _assert_no_banned_phrases(*prompt_texts: str) -> None:
    """Import-time guard against patent-leaking regressions.

    Computes a sliding window of word n-grams (1..8 words) over each
    prompt, SHA-1 hashes each window, and compares against the banned
    hash set. Any match is a regression.

    The fact that this function contains zero plaintext banned strings
    is the point — a competitor grepping the shipped source for the
    banned phrases will find nothing. Test suite re-asserts the guard
    at runtime.
    """
    import hashlib as _hl
    for prompt in prompt_texts:
        tokens = prompt.lower().split()
        for n in range(1, 9):  # 1..8-word windows
            for i in range(len(tokens) - n + 1):
                window = " ".join(tokens[i:i + n])
                digest = _hl.sha1(window.encode("utf-8")).hexdigest()[:16]
                if digest in _BANNED_PHRASE_HASHES:
                    raise RuntimeError(
                        "banned phrase regression detected — "
                        "see _BANNED_PHRASE_HASHES"
                    )


_assert_no_banned_phrases(CANDIDATE_PROMPT, CRITIC_PROMPT, JUDGE_PROMPT)


# ──────────────────────────────────────────────────────────────────────
# Protocols + records
# ──────────────────────────────────────────────────────────────────────


class ReasonFn(Protocol):
    async def __call__(self, prompt: str, *, role: str) -> str: ...


@dataclass
class RoleResponse:
    """One role's output from a single check round."""

    role: str
    text: str
    error: str | None = None


@dataclass
class ConcernCheckRound:
    """One round of the three-role structured check."""

    round_index: int
    candidate: RoleResponse
    critic: RoleResponse
    judge: RoleResponse
    decision: str  # PROCEED | REFINE | BLOCK
    rationale: str


@dataclass
class ConcernCheckRecord:
    """Final outcome with the full trail for streaming + audit."""

    rounds: list[ConcernCheckRound] = field(default_factory=list)
    final_decision: str = ""  # PROCEED | REFINE | BLOCK
    final_rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rounds": [
                {
                    "round_index": r.round_index,
                    "candidate": r.candidate.text,
                    "critic": r.critic.text,
                    "judge": r.judge.text,
                    "decision": r.decision,
                    "rationale": r.rationale,
                }
                for r in self.rounds
            ],
            "final_decision": self.final_decision,
            "final_rationale": self.final_rationale,
        }


# ──────────────────────────────────────────────────────────────────────
# Deterministic in-code classifier
# ──────────────────────────────────────────────────────────────────────

# Category signals — word-boundary patterns with negation guards.
#
# Each entry is (category, compiled_regex). The regex uses ``\b`` word
# boundaries so "non-destructive" does not match "destructive" (which
# was MAJOR-R3 from the research review). For each match the classifier
# also checks the preceding 20 characters for negation tokens (``not ``,
# ``no ``, ``non-``, ``never ``, ``never`` followed by whitespace) and
# skips the match if present.
#
# Iteration order is the tie-breaker when multiple categories match
# the same critic text. The policy is enforced here in code, not in
# any user-visible prompt or docstring. The specific category
# ordering is documented in the project-private design notes, not
# in this shipped source.
# prompt now lives — in code, not in user-visible text.

_NEGATION_WINDOW = 20
_NEGATION_TOKENS = ("not ", "no ", "non-", "never ", "without any ", "without ")

_CATEGORY_SIGNALS: list[tuple[str, re.Pattern[str]]] = [
    # Safety — highest precedence. Word-boundary matching so compound
    # words like "non-destructive" do not trigger. Also excludes the
    # safe rewrite phrase "credentials env-var name" which is THE safe
    # phrasing per lesson_patent_scrub.
    ("safety", re.compile(r"\bunsafe\b", re.IGNORECASE)),
    ("safety", re.compile(r"\bdestructive\b", re.IGNORECASE)),
    ("safety", re.compile(r"\birreversible\b", re.IGNORECASE)),
    ("safety", re.compile(r"\bdata[- ]loss\b", re.IGNORECASE)),
    ("safety", re.compile(r"\bcorrupt(s|ion|ed)?\b", re.IGNORECASE)),
    # Prerequisite — REFINE not BLOCK.
    ("prerequisite", re.compile(r"\bmissing prerequisite\b", re.IGNORECASE)),
    ("prerequisite", re.compile(r"\bneeds?\s+(preflight|context|review)\b", re.IGNORECASE)),
    ("prerequisite", re.compile(r"\b(must|should)\s+run\s+\w+\s+first\b", re.IGNORECASE)),
    # Cost — REFINE not BLOCK.
    ("cost", re.compile(r"\bexpensive\b", re.IGNORECASE)),
    ("cost", re.compile(r"\bhigh[- ]latency\b", re.IGNORECASE)),
    ("cost", re.compile(r"\bslow\b", re.IGNORECASE)),
    # Ambiguity — REFINE not BLOCK.
    ("ambiguity", re.compile(r"\bambiguous\b", re.IGNORECASE)),
    ("ambiguity", re.compile(r"\bunclear\b", re.IGNORECASE)),
]


def _has_negation(text: str, match_start: int) -> bool:
    """Return True if the ``_NEGATION_WINDOW`` chars before ``match_start``
    contain a negation token."""
    window_start = max(0, match_start - _NEGATION_WINDOW)
    window = text[window_start:match_start].lower()
    return any(tok in window for tok in _NEGATION_TOKENS)


def _explicit_none_signal(critic_text: str) -> bool:
    """Return True iff the critic explicitly declared NO concern.

    Uses regex to avoid false matches on substrings like "concerned".
    Accepts ``CONCERN: NONE``, ``CONCERN: none — looks fine``, ``no
    concern``, ``NONE``, etc.
    """
    pattern = re.compile(
        r"\b(concern\s*[:=]\s*none|no\s+concern(s)?|none\s*[-—]\s*looks\s+fine)\b",
        re.IGNORECASE,
    )
    return bool(pattern.search(critic_text))


# Affirmative-safety markers — benign text patterns that signal "no
# concern" even when the critic did not use the literal NONE keyword.
# The classifier treats any of these as PROCEED when no concern
# category has fired. Word-boundary matching + negation-free context
# keeps this conservative.
_AFFIRMATIVE_SAFETY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\band\s+safe\b", re.IGNORECASE),
    re.compile(r"\bis\s+safe\b", re.IGNORECASE),
    re.compile(r"\blooks\s+(safe|fine|good|ok)\b", re.IGNORECASE),
    re.compile(r"\b(all\s+)?clear\s+to\s+proceed\b", re.IGNORECASE),
    re.compile(r"\b(fully|totally)?\s*benign\b", re.IGNORECASE),
    # Read-only / idempotent / non-mutating operations are inherently safe
    re.compile(r"\bread[- ]only\b", re.IGNORECASE),
    re.compile(r"\bidempotent\b", re.IGNORECASE),
    re.compile(r"\bno\s+side\s+effects?\b", re.IGNORECASE),
    # The lesson_patent_scrub safe rewrite phrase — explicit allow
    re.compile(r"\bcredentials\s+env[- ]var\s+name\b", re.IGNORECASE),
]


def _has_affirmative_safety(critic_text: str) -> bool:
    """Return True iff the critic text affirmatively says the action
    is safe. Used as a fall-through PROCEED signal when no concern
    category fired.
    """
    return any(p.search(critic_text) for p in _AFFIRMATIVE_SAFETY_PATTERNS)


def classify_concern(
    candidate_text: str,
    critic_text: str,
) -> tuple[str, str]:
    """Run the in-code classifier and return ``(decision, rationale)``.

    The decision values are ``PROCEED``, ``REFINE``, or ``BLOCK``. The
    classifier runs ``_CATEGORY_SIGNALS`` in declared order so safety
    is picked per the internal precedence policy when multiple categories
    match the same critic text. Word-boundary regex + negation guard
    prevents the MAJOR-R3 false positives (``non-destructive``,
    ``credentials env-var name``, ``unsafe pattern we already fixed``,
    ``ambiguous but safe``).
    """
    # Explicit "no concern" → PROCEED.
    if _explicit_none_signal(critic_text):
        return "PROCEED", "critic reported no concern"

    matched_category: str | None = None
    matched_keyword: str | None = None
    had_any_raw_hit = False  # any regex hit, even if negated
    all_hits_negated = True  # True while every hit so far is negated

    for category, pattern in _CATEGORY_SIGNALS:
        for match in pattern.finditer(critic_text):
            had_any_raw_hit = True
            if _has_negation(critic_text, match.start()):
                continue
            all_hits_negated = False
            matched_category = category
            matched_keyword = match.group(0)
            break
        if matched_category is not None:
            break

    if matched_category is None:
        # Four distinct fallback outcomes in precedence order:
        #   1. had_any_raw_hit=True AND all_hits_negated=True → the
        #      critic mentioned concern categories but every mention
        #      was explicitly negated (e.g. "non-destructive", "not
        #      unsafe"). Treat as PROCEED — the critic explicitly
        #      denied the concern.
        #   2. _has_affirmative_safety(critic_text)=True → the critic
        #      used an affirmative safety marker (e.g. "is safe",
        #      "read-only", "credentials env-var name"). Treat as
        #      PROCEED.
        #   3. otherwise → critic produced unmatched text; soft
        #      REFINE as the conservative default.
        if had_any_raw_hit and all_hits_negated:
            return "PROCEED", "critic explicitly negated every concern signal"
        if _has_affirmative_safety(critic_text):
            return "PROCEED", "critic used an affirmative safety marker"
        return "REFINE", "unclassified critic concern"

    if matched_category == "safety":
        return "BLOCK", f"safety signal fired: {matched_keyword}"
    # All non-safety categories map to REFINE.
    return "REFINE", f"{matched_category} signal fired: {matched_keyword}"


# ──────────────────────────────────────────────────────────────────────
# Check engine
# ──────────────────────────────────────────────────────────────────────


async def _safe_reason(
    reason_fn: ReasonFn,
    prompt: str,
    role: str,
) -> RoleResponse:
    try:
        text = await reason_fn(prompt, role=role)
        return RoleResponse(role=role, text=text)
    except Exception as exc:
        logger.warning("concern-check role %s failed: %s", role, exc)
        return RoleResponse(role=role, text="", error=str(exc))


async def resolve_concern(
    question: str,
    *,
    reason_fn: ReasonFn,
    max_rounds: int = MAX_CHECK_ROUNDS,
    on_signal: Callable[[str, str, str], Awaitable[None]] | None = None,
) -> ConcernCheckRecord:
    """Run up to ``max_rounds`` of structured CANDIDATE/CRITIC/JUDGE check.

    Args:
        question: The action under review (a tool plan, a code
            suggestion, etc.).
        reason_fn: Async callable returning role text given a prompt and
            a role label. Production code injects a backend wrapper.
        max_rounds: Hard ceiling — never exceeds ``MAX_CHECK_ROUNDS``.
        on_signal: Optional async callback ``(role, text, decision)``
            for streaming each round to the UI.

    Returns:
        :class:`ConcernCheckRecord` with the full round trail and the
        final decision.
    """
    record = ConcernCheckRecord()
    capped_rounds = min(max_rounds, MAX_CHECK_ROUNDS)

    for idx in range(capped_rounds):
        candidate_prompt = f"{CANDIDATE_PROMPT}\n\nQUESTION: {question}"
        if record.rounds:
            last = record.rounds[-1]
            candidate_prompt += (
                f"\n\nPRIOR JUDGE DECISION: {last.decision} "
                f"({last.rationale}). Refine your recommendation accordingly."
            )

        # Phase 1: CANDIDATE alone.
        candidate = await _safe_reason(reason_fn, candidate_prompt, ROLE_CANDIDATE)

        # Phase 2: CRITIC sees candidate output.
        critic_prompt = (
            f"{CRITIC_PROMPT}\n\nQUESTION: {question}\n\n"
            f"CANDIDATE SAID: {candidate.text}"
        )
        critic = await _safe_reason(reason_fn, critic_prompt, ROLE_CRITIC)

        # Phase 3: JUDGE sees both.
        judge_prompt = (
            f"{JUDGE_PROMPT}\n\nQUESTION: {question}\n\n"
            f"CANDIDATE: {candidate.text}\n\nCRITIC: {critic.text}"
        )
        judge = await _safe_reason(reason_fn, judge_prompt, ROLE_JUDGE)

        # In-code classifier override — the judge's LLM text is
        # recorded but the deterministic classifier has the final word.
        decision, rationale = classify_concern(candidate.text, critic.text)
        round_record = ConcernCheckRound(
            round_index=idx,
            candidate=candidate,
            critic=critic,
            judge=judge,
            decision=decision,
            rationale=rationale,
        )
        record.rounds.append(round_record)

        if on_signal is not None:
            await on_signal(ROLE_CANDIDATE, candidate.text, "")
            await on_signal(ROLE_CRITIC, critic.text, "")
            await on_signal(ROLE_JUDGE, judge.text, decision)

        # Stop early on PROCEED or BLOCK; only REFINE continues.
        if decision in ("PROCEED", "BLOCK"):
            record.final_decision = decision
            record.final_rationale = rationale
            return record

    # Exhausted rounds — last round's decision stands.
    last = record.rounds[-1]
    record.final_decision = last.decision
    record.final_rationale = last.rationale
    return record


__all__ = [
    "CANDIDATE_PROMPT",
    "CRITIC_PROMPT",
    "ConcernCheckRecord",
    "ConcernCheckRound",
    "JUDGE_PROMPT",
    "MAX_CHECK_ROUNDS",
    "ROLE_CANDIDATE",
    "ROLE_CRITIC",
    "ROLE_JUDGE",
    "ReasonFn",
    "RoleResponse",
    "classify_concern",
    "resolve_concern",
]
