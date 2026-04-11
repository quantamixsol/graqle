"""Round-1 tests for graqle.chat.debate (concern-check subsystem).

Covers:
  - Original 15 cases under the new CANDIDATE/CRITIC/JUDGE vocabulary
  - MAJOR-R3 four false-positive regression cases
    (non-destructive / credentials env-var name / unsafe fixed / ambiguous but safe)
  - Banned-phrase guard import-time + runtime assertion
  - Security invariants: no secret leakage, no subprocess usage, no env reads
"""

# ── graqle:intelligence ──
# module: tests.test_chat.test_debate
# risk: LOW
# dependencies: pytest, asyncio, graqle.chat.debate
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import inspect
import pathlib

import pytest

from graqle.chat.debate import (
    CANDIDATE_PROMPT,
    CRITIC_PROMPT,
    JUDGE_PROMPT,
    MAX_CHECK_ROUNDS,
    ROLE_CANDIDATE,
    ROLE_CRITIC,
    ROLE_JUDGE,
    ConcernCheckRecord,
    _BANNED_PHRASE_HASHES,
    _assert_no_banned_phrases,
    classify_concern,
    resolve_concern,
)


# ──────────────────────────────────────────────────────────────────────
# classify_concern — deterministic in-code override
# ──────────────────────────────────────────────────────────────────────


def test_classify_explicit_none_proceeds() -> None:
    decision, rationale = classify_concern(
        "use graq_read",
        "CONCERN: none — looks fine",
    )
    assert decision == "PROCEED"


def test_classify_no_concern_variant_proceeds() -> None:
    decision, _ = classify_concern("do x", "no concern here")
    assert decision == "PROCEED"


def test_classify_safety_blocks() -> None:
    decision, rationale = classify_concern(
        "run rm -rf",
        "this is destructive — will lose data",
    )
    assert decision == "BLOCK"
    assert "safety" in rationale


def test_classify_safety_beats_cost() -> None:
    """Precedence in code: safety wins over cost."""
    decision, _ = classify_concern(
        "do x", "destructive AND expensive AND slow",
    )
    assert decision == "BLOCK"


def test_classify_prerequisite_refines() -> None:
    decision, rationale = classify_concern(
        "call graq_generate",
        "missing prerequisite — needs preflight first",
    )
    assert decision == "REFINE"
    assert "prerequisite" in rationale


def test_classify_cost_refines() -> None:
    decision, rationale = classify_concern(
        "call graq_reason 6 times",
        "this is expensive — high-latency",
    )
    assert decision == "REFINE"
    assert "cost" in rationale


def test_classify_ambiguity_refines() -> None:
    decision, rationale = classify_concern(
        "do something",
        "ambiguous — unclear what the user wants",
    )
    assert decision == "REFINE"
    assert "ambiguity" in rationale


def test_classify_unclassified_concern_refines() -> None:
    decision, _ = classify_concern("do x", "I have a vague feeling about this")
    assert decision == "REFINE"


# ──────────────────────────────────────────────────────────────────────
# MAJOR-R3 — the four false-positive regression cases
# ──────────────────────────────────────────────────────────────────────


def test_major_r3_non_destructive_proceeds() -> None:
    """'non-destructive' must not match 'destructive'."""
    decision, _ = classify_concern(
        "stage a read-only tool",
        "This action is non-destructive and safe.",
    )
    assert decision == "PROCEED", (
        "negation guard failed — 'non-destructive' incorrectly flagged"
    )


def test_major_r3_credentials_env_var_name_proceeds() -> None:
    """'credentials env-var name' is the lesson_patent_scrub safe rewrite
    phrase — it must not be flagged by any category signal.
    """
    decision, _ = classify_concern(
        "use the backend",
        "Uses credentials env-var name from the project config.",
    )
    assert decision == "PROCEED", (
        "safe rewrite phrase incorrectly blocked"
    )


def test_major_r3_unsafe_already_fixed_blocks() -> None:
    """'unsafe pattern we already fixed' still contains 'unsafe' word-
    boundary match — the operator's safer default is to BLOCK on any
    unresolved-sounding safety mention. This matches the conservative
    stance documented in classify_concern.
    """
    decision, _ = classify_concern(
        "re-apply",
        "This is an unsafe pattern we already fixed.",
    )
    # Intentional: word-boundary 'unsafe' fires without negation. The
    # conservative default is BLOCK — the operator can revisit via a
    # more nuanced signal_kind field in a future round.
    assert decision == "BLOCK"


def test_major_r3_ambiguous_but_safe_refines() -> None:
    """'ambiguous but safe' still matches the 'ambiguous' signal — the
    conservative default is REFINE. The engine never silently proceeds
    on an ambiguity signal.
    """
    decision, _ = classify_concern(
        "do x",
        "The concern is ambiguous, but safe.",
    )
    assert decision == "REFINE"


def test_major_r3_no_not_negations_proceed() -> None:
    """Multiple negation tokens must be recognised."""
    for text in [
        "This is not destructive at all.",
        "There is no destructive effect here.",
        "The action is never unsafe.",
        "Runs without destructive side effects.",
    ]:
        decision, _ = classify_concern("x", text)
        assert decision == "PROCEED", f"failed on: {text}"


# ──────────────────────────────────────────────────────────────────────
# Banned-phrase guard (import-time + runtime)
# ──────────────────────────────────────────────────────────────────────


def test_banned_phrase_guard_catches_slip() -> None:
    """The guard must fail fast on any reintroduction of banned phrasing."""
    with pytest.raises(RuntimeError, match="banned phrase"):
        _assert_no_banned_phrases(
            "You are proposer and the next step",
        )


def test_banned_phrase_guard_passes_on_neutral_text() -> None:
    _assert_no_banned_phrases(
        "You are the CANDIDATE role. Recommend the next action.",
    )


def test_prompts_contain_no_banned_phrases() -> None:
    """Runtime re-assertion — every shipped prompt must be clean."""
    _assert_no_banned_phrases(CANDIDATE_PROMPT, CRITIC_PROMPT, JUDGE_PROMPT)


def test_prompts_do_not_state_strict_ordering() -> None:
    """No prompt may contain the verbatim rule-order sentence."""
    banned_sentence = "safety > prerequisite > cost > ambiguity"
    for prompt in (CANDIDATE_PROMPT, CRITIC_PROMPT, JUDGE_PROMPT):
        assert banned_sentence.lower() not in prompt.lower()


def test_module_source_has_no_persona_names() -> None:
    """The shipped debate.py source (as loaded on disk) must not contain
    the legacy persona names PROPOSER / ADVERSARY / ARBITER in ANY form —
    neither at capitals nor as lowercase plaintext. RO2-4 round-2
    remediation: the banned-phrase guard now uses SHA-1 hashes so the
    banned tokens themselves never appear as plaintext in the source.
    """
    module_path = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "graqle" / "chat" / "debate.py"
    )
    src = module_path.read_text(encoding="utf-8")
    for word in ("PROPOSER", "ADVERSARY", "ARBITER"):
        # Capital form: must not appear anywhere in shipped source.
        cap_count = src.count(word)
        assert cap_count == 0, f"found {cap_count} stray '{word}' in debate.py"
        # Lowercase form: must also not appear as plaintext anywhere.
        # The hashed guard means the banned tokens live only as hex
        # digests in _BANNED_PHRASE_HASHES.
        low_count = src.lower().count(word.lower())
        assert low_count == 0, (
            f"found {low_count} stray lowercase '{word.lower()}' in debate.py — "
            "hashed guard is defeated by plaintext leak"
        )


def test_banned_phrase_hashes_size() -> None:
    """RO2-4 sanity: the hashed guard set is non-empty and each entry
    is a 16-char lowercase hex digest."""
    assert len(_BANNED_PHRASE_HASHES) >= 6
    import re
    for h in _BANNED_PHRASE_HASHES:
        assert re.fullmatch(r"[0-9a-f]{16}", h), (
            f"banned hash {h!r} is not a 16-char hex digest"
        )


def test_banned_hash_guard_catches_strict_ordering_regression() -> None:
    """The hash-based guard still fires when the strict-ordering
    sentence is reintroduced, even though the sentence itself is not
    in the shipped source."""
    with pytest.raises(RuntimeError, match="banned phrase regression"):
        _assert_no_banned_phrases(
            "Apply rule order strictly: safety > prerequisite > cost > ambiguity",
        )


def test_banned_hash_guard_catches_persona_regression() -> None:
    """The hash-based guard still fires on each legacy persona token."""
    for legacy in ("You are proposer today", "call the adversary", "the arbiter decides"):
        with pytest.raises(RuntimeError):
            _assert_no_banned_phrases(legacy)


# ──────────────────────────────────────────────────────────────────────
# Security invariants — no secrets, no subprocess, no env reads
# ──────────────────────────────────────────────────────────────────────


def test_module_source_has_no_subprocess_usage() -> None:
    """graqle/chat/debate.py must not import or call any subprocess API."""
    module_path = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "graqle" / "chat" / "debate.py"
    )
    src = module_path.read_text(encoding="utf-8")
    forbidden = [
        "import subprocess",
        "from subprocess",
        "subprocess.run",
        "subprocess.Popen",
        "os.system",
        "os.popen",
    ]
    for token in forbidden:
        assert token not in src, f"forbidden token in debate.py: {token}"


def test_module_source_has_no_env_reads() -> None:
    """debate.py must not read environment variables directly."""
    module_path = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "graqle" / "chat" / "debate.py"
    )
    src = module_path.read_text(encoding="utf-8")
    forbidden = ["os.environ", "os.getenv", "environ["]
    for token in forbidden:
        assert token not in src, f"env-read pattern in debate.py: {token}"


@pytest.mark.asyncio
async def test_secret_like_input_not_echoed_to_callback() -> None:
    """A secret-like string in the question stays in the candidate/critic
    trail but is not transformed / enriched / forwarded to anything
    outside the record. The callback receives exactly what the roles
    produced — nothing more.
    """
    secret_question = "deploy my-service with SECRET=sk-fake-not-real-0123456789"
    emitted: list[tuple[str, str, str]] = []

    async def on_signal(role: str, text: str, decision: str) -> None:
        emitted.append((role, text, decision))

    async def stub(prompt: str, *, role: str) -> str:
        # Roles never echo the secret — they only output their own text.
        return f"{role} acknowledged the request"

    record = await resolve_concern(
        secret_question, reason_fn=stub, on_signal=on_signal,
    )
    assert record.final_decision == "REFINE"
    # The record text never contains the secret — the role callables
    # produced clean outputs and the engine only passed their outputs
    # through.
    for _, text, _ in emitted:
        assert "sk-fake-not-real-0123456789" not in text


# ──────────────────────────────────────────────────────────────────────
# resolve_concern — full-integration async behavior
# ──────────────────────────────────────────────────────────────────────


def _stub(responses: dict[str, str]):
    async def _fn(prompt: str, *, role: str) -> str:
        return responses.get(role, f"{role} says nothing")
    return _fn


@pytest.mark.asyncio
async def test_resolve_proceeds_with_no_concern() -> None:
    reason_fn = _stub({
        ROLE_CANDIDATE: "use graq_read on file.py",
        ROLE_CRITIC: "CONCERN: none",
        ROLE_JUDGE: "PROCEED",
    })
    record = await resolve_concern("read file.py", reason_fn=reason_fn)
    assert record.final_decision == "PROCEED"
    assert len(record.rounds) == 1


@pytest.mark.asyncio
async def test_resolve_blocks_on_safety() -> None:
    reason_fn = _stub({
        ROLE_CANDIDATE: "rm everything",
        ROLE_CRITIC: "this is destructive — irreversible",
        ROLE_JUDGE: "BLOCK",
    })
    record = await resolve_concern("clean up", reason_fn=reason_fn)
    assert record.final_decision == "BLOCK"
    assert len(record.rounds) == 1


@pytest.mark.asyncio
async def test_resolve_refines_then_proceeds() -> None:
    """REFINE continues to next round; PROCEED stops."""
    counts: dict[str, int] = {ROLE_CANDIDATE: 0, ROLE_CRITIC: 0, ROLE_JUDGE: 0}

    async def fn(prompt: str, *, role: str) -> str:
        counts[role] += 1
        if role == ROLE_CRITIC:
            if counts[role] == 1:
                return "missing prerequisite — needs context first"
            return "CONCERN: none"
        return f"{role} round {counts[role]}"

    record = await resolve_concern("question", reason_fn=fn)
    assert len(record.rounds) == 2
    assert record.final_decision == "PROCEED"


@pytest.mark.asyncio
async def test_resolve_caps_at_max_rounds() -> None:
    reason_fn = _stub({
        ROLE_CANDIDATE: "do x",
        ROLE_CRITIC: "ambiguous — unclear",
        ROLE_JUDGE: "REFINE",
    })
    record = await resolve_concern("q", reason_fn=reason_fn, max_rounds=10)
    assert len(record.rounds) == MAX_CHECK_ROUNDS
    assert record.final_decision == "REFINE"


@pytest.mark.asyncio
async def test_resolve_signal_callback_fires_with_new_roles() -> None:
    signals: list[tuple[str, str, str]] = []

    async def on_signal(role: str, text: str, decision: str) -> None:
        signals.append((role, text, decision))

    reason_fn = _stub({
        ROLE_CANDIDATE: "ok",
        ROLE_CRITIC: "CONCERN: none",
        ROLE_JUDGE: "PROCEED",
    })
    await resolve_concern("q", reason_fn=reason_fn, on_signal=on_signal)
    roles = {s[0] for s in signals}
    assert {ROLE_CANDIDATE, ROLE_CRITIC, ROLE_JUDGE} <= roles


@pytest.mark.asyncio
async def test_resolve_reason_fn_exception_recorded() -> None:
    """A role failure does not crash the engine; it's recorded and the
    engine falls through to its fail-safe default (REFINE)."""

    async def fn(prompt: str, *, role: str) -> str:
        if role == ROLE_CRITIC:
            raise RuntimeError("backend down")
        return "ok"

    record = await resolve_concern("q", reason_fn=fn)
    # CRITIC error → empty text → no "concern: none" marker → REFINE.
    assert record.final_decision == "REFINE"
    assert record.rounds[0].critic.error == "backend down"


def test_concern_check_record_to_dict() -> None:
    rec = ConcernCheckRecord()
    d = rec.to_dict()
    assert "rounds" in d
    assert "final_decision" in d
    assert "final_rationale" in d


def test_role_labels_are_public_module_constants() -> None:
    """The three role labels must be stable public constants for the
    VS Code extension to match on without importing private names.
    """
    assert ROLE_CANDIDATE == "CANDIDATE"
    assert ROLE_CRITIC == "CRITIC"
    assert ROLE_JUDGE == "JUDGE"


def test_resolve_concern_signature_matches_protocol() -> None:
    """Resolve-concern must accept the same kwargs the ChatAgentLoop uses."""
    sig = inspect.signature(resolve_concern)
    params = list(sig.parameters)
    assert "question" in params
    assert "reason_fn" in params
    assert "max_rounds" in params
    assert "on_signal" in params
