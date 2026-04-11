"""TB-F5 tests for graqle.chat.debate."""

# ── graqle:intelligence ──
# module: tests.test_chat.test_debate
# risk: LOW
# dependencies: pytest, asyncio, graqle.chat.debate
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import pytest

from graqle.chat.debate import (
    MAX_DEBATE_ROUNDS,
    DebateRecord,
    deterministic_arbiter,
    run_debate,
)


# ──────────────────────────────────────────────────────────────────────
# deterministic_arbiter — rule order
# ──────────────────────────────────────────────────────────────────────


def test_arbiter_no_concern_proceeds() -> None:
    verdict, reason = deterministic_arbiter(
        "use graq_read", "CONCERN: none — looks fine",
    )
    assert verdict == "PROCEED"


def test_arbiter_safety_blocks() -> None:
    verdict, reason = deterministic_arbiter(
        "run rm -rf", "this is destructive — will lose data",
    )
    assert verdict == "BLOCK"
    assert "safety" in reason


def test_arbiter_safety_beats_cost() -> None:
    """Safety wins over cost in rule order."""
    verdict, _ = deterministic_arbiter(
        "do x", "destructive AND expensive AND slow",
    )
    assert verdict == "BLOCK"


def test_arbiter_prerequisite_refines() -> None:
    verdict, reason = deterministic_arbiter(
        "call graq_generate", "missing prerequisite — needs preflight first",
    )
    assert verdict == "REFINE"
    assert "prerequisite" in reason


def test_arbiter_cost_refines() -> None:
    verdict, reason = deterministic_arbiter(
        "call graq_reason 6 times", "this is expensive — high latency",
    )
    assert verdict == "REFINE"
    assert "cost" in reason


def test_arbiter_ambiguity_refines() -> None:
    verdict, reason = deterministic_arbiter(
        "do something", "ambiguous — unclear what the user wants",
    )
    assert verdict == "REFINE"
    assert "ambiguity" in reason


def test_arbiter_unclassified_concern_refines() -> None:
    verdict, _ = deterministic_arbiter(
        "do x", "I have a vague feeling about this",
    )
    assert verdict == "REFINE"


def test_arbiter_prerequisite_beats_cost() -> None:
    """Prerequisite wins over cost in rule order."""
    verdict, _ = deterministic_arbiter(
        "do x", "missing prerequisite — also expensive",
    )
    assert verdict == "REFINE"  # prerequisite is REFINE not BLOCK
    # Sanity: it's prerequisite-refine, not cost-refine.
    _, reason = deterministic_arbiter(
        "do x", "missing prerequisite — also expensive",
    )
    assert "prerequisite" in reason


# ──────────────────────────────────────────────────────────────────────
# run_debate — full integration with stub reason_fn
# ──────────────────────────────────────────────────────────────────────


def _stub_reason(responses: dict[str, str]):
    """Build an async stub reason_fn that returns canned text per persona."""
    async def _fn(prompt: str, *, persona: str) -> str:
        return responses.get(persona, f"{persona} says nothing")
    return _fn


@pytest.mark.asyncio
async def test_debate_proceeds_with_no_concern() -> None:
    reason_fn = _stub_reason({
        "PROPOSER": "use graq_read on file.py",
        "ADVERSARY": "CONCERN: none",
        "ARBITER": "PROCEED",
    })
    record = await run_debate("read file.py", reason_fn=reason_fn)
    assert record.final_verdict == "PROCEED"
    assert len(record.rounds) == 1


@pytest.mark.asyncio
async def test_debate_blocks_on_safety() -> None:
    reason_fn = _stub_reason({
        "PROPOSER": "rm everything",
        "ADVERSARY": "this is destructive — irreversible",
        "ARBITER": "BLOCK",
    })
    record = await run_debate("clean up", reason_fn=reason_fn)
    assert record.final_verdict == "BLOCK"
    assert len(record.rounds) == 1


@pytest.mark.asyncio
async def test_debate_refines_for_two_rounds_then_proceeds() -> None:
    """REFINE means continue to the next round; PROCEED stops."""
    call_counts: dict[str, int] = {"PROPOSER": 0, "ADVERSARY": 0, "ARBITER": 0}

    async def fn(prompt: str, *, persona: str) -> str:
        call_counts[persona] += 1
        if persona == "ADVERSARY":
            if call_counts[persona] == 1:
                return "missing prerequisite — needs context first"
            return "CONCERN: none"
        return f"{persona} round {call_counts[persona]}"

    record = await run_debate("question", reason_fn=fn)
    assert len(record.rounds) == 2
    assert record.final_verdict == "PROCEED"


@pytest.mark.asyncio
async def test_debate_caps_at_max_rounds() -> None:
    """Even if every round REFINEs, the engine stops at MAX_DEBATE_ROUNDS."""
    reason_fn = _stub_reason({
        "PROPOSER": "do x",
        "ADVERSARY": "ambiguous — unclear",
        "ARBITER": "REFINE",
    })
    record = await run_debate("question", reason_fn=reason_fn, max_rounds=10)
    assert len(record.rounds) == MAX_DEBATE_ROUNDS
    assert record.final_verdict == "REFINE"


@pytest.mark.asyncio
async def test_debate_chip_callback_fires() -> None:
    chips: list[tuple[str, str, str]] = []

    async def on_chip(persona: str, text: str, verdict: str) -> None:
        chips.append((persona, text, verdict))

    reason_fn = _stub_reason({
        "PROPOSER": "ok",
        "ADVERSARY": "CONCERN: none",
        "ARBITER": "PROCEED",
    })
    await run_debate("q", reason_fn=reason_fn, on_chip=on_chip)
    personas = {c[0] for c in chips}
    assert {"PROPOSER", "ADVERSARY", "ARBITER"} <= personas


@pytest.mark.asyncio
async def test_debate_reason_fn_exception_recorded() -> None:
    """A persona failure does not crash the engine; it's recorded."""
    async def fn(prompt: str, *, persona: str) -> str:
        if persona == "ADVERSARY":
            raise RuntimeError("backend down")
        return "ok"

    record = await run_debate("q", reason_fn=fn)
    # ADVERSARY error → empty text → no "concern: none" marker → fail-safe REFINE
    # (the engine treats unparseable adversary output as a soft refine,
    # never as silent approval).
    assert record.final_verdict == "REFINE"
    assert record.rounds[0].adversary.error == "backend down"


def test_debate_record_to_dict() -> None:
    rec = DebateRecord()
    d = rec.to_dict()
    assert "rounds" in d
    assert "final_verdict" in d
