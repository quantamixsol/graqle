"""SDK-HF-02 (v0.47.2) regression tests for Aggregator._weighted_synthesis.

These reproduce the SDK-HF-02 failure mode (synthesis silently returning
empty/partial text when stop_reason=max_tokens) and verify that the new
generate_with_continuation helper recovers correctly.

Cases:
  (a) clean synthesis (no truncation) → unchanged behavior
  (b) truncated synthesis recovers via 1 continuation → non-empty text
  (c) persistent truncation exhausts max_continuations → still_truncated=True
  (d) regression: max_tokens=4096 must be passed to backend.generate
      (do NOT raise to 8192 in this hotfix)
  (e) trunc_info shape preserved exactly: same two keys, no extras
"""

# ── graqle:intelligence ──
# module: tests.test_orchestration.test_aggregation
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, asyncio, graqle.orchestration.aggregation
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from typing import Any

import pytest

from graqle.backends.base import GenerateResult
from graqle.core.message import Message
from graqle.core.types import ReasoningType
from graqle.orchestration.aggregation import Aggregator


class _ScriptedBackend:
    """Minimal backend that returns scripted responses."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> Any:
        self.calls.append({
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stop": stop,
        })
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    @property
    def name(self) -> str:
        return "scripted"

    @property
    def cost_per_1k_tokens(self) -> float:
        return 0.0


def _gr(text: str, truncated: bool = False, stop_reason: str = "") -> GenerateResult:
    return GenerateResult(text=text, truncated=truncated, stop_reason=stop_reason)


def _msg(node_id: str, content: str, confidence: float = 0.9) -> Message:
    return Message(
        source_node_id=node_id,
        target_node_id="__broadcast__",
        round=1,
        content=content,
        reasoning_type=ReasoningType.ASSERTION,
        confidence=confidence,
        evidence=[node_id],
        parent_messages=[],
        token_count=len(content.split()),
    )


# ── (a) clean synthesis ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_synthesis_clean_no_continuation() -> None:
    backend = _ScriptedBackend([_gr("clean synthesized answer")])
    agg = Aggregator(strategy="weighted_synthesis", backend=backend)
    messages = {
        "n1": _msg("n1", "agent one says X", confidence=0.9),
        "n2": _msg("n2", "agent two says Y", confidence=0.8),
    }
    text, trunc_info = await agg.aggregate("the query", messages, backend=backend)
    assert text == "clean synthesized answer"
    # v0.51.3: trunc_info gained an optional 'candidates' key for the
    # VS Code ambiguity-pause feature — assert the load-bearing truncation
    # fields, not strict dict equality, so future additive keys don't break
    # this test.
    assert trunc_info.get("synthesis_truncated") is False
    assert trunc_info.get("synthesis_stop_reason") == ""
    assert len(backend.calls) == 1


# ── (b) truncated → recovery ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_synthesis_recovers_from_truncation(caplog: pytest.LogCaptureFixture) -> None:
    """The headline SDK-HF-02 fix: synthesis was silently returning empty
    text when the first response was truncated. Now it should continue
    and return the full stitched answer."""
    first = _gr(
        "first part of synthesis\nsecond line\nthird line\nfourth",
        truncated=True, stop_reason="length",
    )
    second = _gr("fifth line\nsixth line\nFINAL")
    backend = _ScriptedBackend([first, second])
    agg = Aggregator(strategy="weighted_synthesis", backend=backend)
    messages = {"n1": _msg("n1", "agent says hello", confidence=0.9)}

    import logging
    with caplog.at_level(logging.INFO, logger="graqle.aggregation"):
        text, trunc_info = await agg.aggregate("q", messages, backend=backend)

    assert "first part" in text and "FINAL" in text
    assert trunc_info["synthesis_truncated"] is False
    assert trunc_info["synthesis_stop_reason"] == ""
    assert len(backend.calls) == 2
    # OT-028 recovery log should have fired
    assert any(
        "Synthesis recovered from truncation" in r.message
        for r in caplog.records
    )


# ── (c) persistent truncation → exhaustion ────────────────────────────


@pytest.mark.asyncio
async def test_synthesis_exhausts_max_continuations() -> None:
    seqs = [
        _gr("p1 alpha\np1 bravo", truncated=True, stop_reason="length"),
        _gr("p2 charlie\np2 delta", truncated=True, stop_reason="length"),
        _gr("p3 echo\np3 foxtrot", truncated=True, stop_reason="length"),
        _gr("p4 golf\np4 hotel", truncated=True, stop_reason="length"),
    ]
    backend = _ScriptedBackend(seqs)
    agg = Aggregator(strategy="weighted_synthesis", backend=backend)
    messages = {"n1": _msg("n1", "x", confidence=0.9)}
    text, trunc_info = await agg.aggregate("q", messages, backend=backend)
    assert trunc_info["synthesis_truncated"] is True
    assert trunc_info["synthesis_stop_reason"] == "length"
    # Should have called backend max_continuations+1 = 4 times
    assert len(backend.calls) == 4


# ── (d) max_tokens=4096 regression ────────────────────────────────────


@pytest.mark.asyncio
async def test_synthesis_passes_max_tokens_4096() -> None:
    """Regression: SDK-HF-02 hotfix must NOT raise max_tokens to 8192.
    The 8192 tuning is a separate decision (lesson_20260407T065640)."""
    backend = _ScriptedBackend([_gr("clean")])
    agg = Aggregator(strategy="weighted_synthesis", backend=backend)
    messages = {"n1": _msg("n1", "x", confidence=0.9)}
    await agg.aggregate("q", messages, backend=backend)
    assert backend.calls[0]["max_tokens"] == 4096
    assert backend.calls[0]["temperature"] == 0.2


# ── (e) trunc_info shape preserved ────────────────────────────────────


@pytest.mark.asyncio
async def test_trunc_info_shape_preserved() -> None:
    backend = _ScriptedBackend([_gr("clean")])
    agg = Aggregator(strategy="weighted_synthesis", backend=backend)
    messages = {"n1": _msg("n1", "x", confidence=0.9)}
    _, trunc_info = await agg.aggregate("q", messages, backend=backend)
    # Exact dict equality — no extra keys, no missing keys
    assert set(trunc_info.keys()) == {"synthesis_truncated", "synthesis_stop_reason"}
    assert trunc_info == {"synthesis_truncated": False, "synthesis_stop_reason": ""}


# ── (f) initial-call exception propagates ─────────────────────────────


@pytest.mark.asyncio
async def test_synthesis_initial_call_exception_propagates() -> None:
    backend = _ScriptedBackend([RuntimeError("backend down")])
    agg = Aggregator(strategy="weighted_synthesis", backend=backend)
    messages = {"n1": _msg("n1", "x", confidence=0.9)}
    with pytest.raises(RuntimeError, match="backend down"):
        await agg.aggregate("q", messages, backend=backend)


# ── (g) continuation_error → fail-open with warning log ───────────────


@pytest.mark.asyncio
async def test_synthesis_continuation_error_fails_open(caplog: pytest.LogCaptureFixture) -> None:
    first = _gr("partial synthesis", truncated=True, stop_reason="length")
    backend = _ScriptedBackend([first, RuntimeError("API hiccup")])
    agg = Aggregator(strategy="weighted_synthesis", backend=backend)
    messages = {"n1": _msg("n1", "x", confidence=0.9)}

    import logging
    with caplog.at_level(logging.WARNING, logger="graqle.aggregation"):
        text, trunc_info = await agg.aggregate("q", messages, backend=backend)

    assert text == "partial synthesis"  # accumulated text returned
    assert any(
        "continuation hit an error mid-loop" in r.message
        for r in caplog.records
    )
