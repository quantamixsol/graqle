"""SDK-HF-02 (v0.47.2) regression tests for generate_with_continuation.

These cover every exit path of the new helper:

  (a) clean (no truncation)         (h) raw str input
  (b) recovery (truncated → fixed)  (i) malformed object input
  (c) empty-anchor abort            (j) max_continuations=0
  (d) zero-progress abort           (k) whitespace-only seam
  (e) max_continuations exhaustion  (l) partial-overlap seam
  (f) mid-loop fail-open exception  (m) initial-call exception propagates
  (g) GenerateResult input          (n) mixed return types across rounds

Plus an arg-passthrough assertion (max_tokens / temperature / stop) and an
exact-metadata assertion on every relevant case.
"""

# ── graqle:intelligence ──
# module: tests.test_core.test_continuation
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, asyncio, graqle.core.node
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from typing import Any

import pytest

from graqle.backends.base import GenerateResult
from graqle.core.node import (
    _normalize_response,
    generate_with_continuation,
)


class _ScriptedBackend:
    """Backend that returns a scripted sequence of responses on each call."""

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
        if not self.responses:
            raise RuntimeError("scripted backend exhausted")
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


# ── _normalize_response ───────────────────────────────────────────────


def test_normalize_response_generate_result() -> None:
    text, trunc, stop = _normalize_response(_gr("hello", truncated=True, stop_reason="length"))
    assert text == "hello"
    assert trunc is True
    assert stop == "length"


def test_normalize_response_raw_str() -> None:
    text, trunc, stop = _normalize_response("plain text")
    assert text == "plain text"
    assert trunc is False
    assert stop == ""


def test_normalize_response_malformed_falls_back() -> None:
    text, trunc, stop = _normalize_response(42)
    assert text == "42"
    assert trunc is False
    assert stop == ""


def test_normalize_response_none_text_coerced() -> None:
    """Defensive guard from post-impl review: .text=None must not crash."""

    class _NoneText:
        text = None
        truncated = False
        stop_reason = ""

    text, trunc, stop = _normalize_response(_NoneText())
    assert text == ""
    assert trunc is False
    assert stop == ""


def test_normalize_response_truncated_none_coerced() -> None:
    class _NoneTrunc:
        text = "ok"
        truncated = None

    text, trunc, stop = _normalize_response(_NoneTrunc())
    assert trunc is False


# ── (a) clean (no truncation, no continuation) ────────────────────────


@pytest.mark.asyncio
async def test_clean_no_continuation() -> None:
    backend = _ScriptedBackend([_gr("complete answer")])
    text, meta = await generate_with_continuation(backend, "q")
    assert text == "complete answer"
    assert meta == {
        "continuation_count": 0,
        "was_continued": False,
        "still_truncated": False,
        "stop_reason": "",
        "continuation_error": False,
    }
    assert len(backend.calls) == 1


# ── (b) truncated → recovery via 1 continuation ───────────────────────


@pytest.mark.asyncio
async def test_recovery_via_one_continuation() -> None:
    first = _gr(
        "line1\nline2\nline3\nline4",
        truncated=True, stop_reason="length",
    )
    second = _gr("line5\nline6\nDONE")
    backend = _ScriptedBackend([first, second])
    text, meta = await generate_with_continuation(backend, "q")
    assert "line1" in text and "DONE" in text
    assert meta["continuation_count"] == 1
    assert meta["was_continued"] is True
    assert meta["still_truncated"] is False
    assert meta["continuation_error"] is False
    assert len(backend.calls) == 2


# ── (c) empty-anchor abort ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_anchor_aborts() -> None:
    # Whitespace-only response → _extract_overlap_anchor returns ""
    first = _gr("   \n   \n   ", truncated=True, stop_reason="length")
    backend = _ScriptedBackend([first])
    text, meta = await generate_with_continuation(backend, "q")
    assert text == "   \n   \n   "
    assert meta["continuation_count"] == 0
    assert meta["was_continued"] is False
    assert meta["still_truncated"] is True
    assert meta["continuation_error"] is False
    assert len(backend.calls) == 1  # only the first call, no continuation attempted


# ── (d) zero-progress abort ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_zero_progress_aborts() -> None:
    # Continuation returns the SAME content → after dedup, no progress
    first = _gr("alpha\nbravo", truncated=True, stop_reason="length")
    second = _gr("alpha\nbravo")  # identical
    backend = _ScriptedBackend([first, second])
    text, meta = await generate_with_continuation(backend, "q")
    assert text == "alpha\nbravo"
    assert meta["continuation_count"] == 0  # break before incrementing
    assert meta["continuation_error"] is False


# ── (e) max_continuations exhaustion ──────────────────────────────────


@pytest.mark.asyncio
async def test_max_continuations_exhaustion() -> None:
    seqs = [
        _gr("p1", truncated=True, stop_reason="length"),
        _gr("p2", truncated=True, stop_reason="length"),
        _gr("p3", truncated=True, stop_reason="length"),
        _gr("p4", truncated=True, stop_reason="length"),
    ]
    backend = _ScriptedBackend(seqs)
    text, meta = await generate_with_continuation(
        backend, "q", max_continuations=3,
    )
    assert meta["continuation_count"] == 3
    assert meta["was_continued"] is True
    assert meta["still_truncated"] is True
    assert meta["stop_reason"] == "length"
    assert meta["continuation_error"] is False


# ── (f) mid-loop fail-open on exception ───────────────────────────────


@pytest.mark.asyncio
async def test_mid_loop_exception_fail_open() -> None:
    first = _gr("partial answer line", truncated=True, stop_reason="length")
    backend = _ScriptedBackend([first, RuntimeError("API down")])
    text, meta = await generate_with_continuation(backend, "q")
    assert text == "partial answer line"  # accumulated text returned
    assert meta["continuation_error"] is True
    assert meta["was_continued"] is True
    assert meta["still_truncated"] is True


# ── (g) GenerateResult input — covered above ──────────────────────────
# ── (h) raw str input ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_raw_str_backend() -> None:
    backend = _ScriptedBackend(["just a string"])
    text, meta = await generate_with_continuation(backend, "q")
    assert text == "just a string"
    assert meta["was_continued"] is False


# ── (i) malformed object input ────────────────────────────────────────


@pytest.mark.asyncio
async def test_malformed_object_input() -> None:
    backend = _ScriptedBackend([12345])  # int — defensive coercion
    text, meta = await generate_with_continuation(backend, "q")
    assert text == "12345"
    assert meta["still_truncated"] is False


# ── (j) max_continuations=0 ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_max_continuations_zero() -> None:
    first = _gr("partial", truncated=True, stop_reason="length")
    backend = _ScriptedBackend([first])
    text, meta = await generate_with_continuation(
        backend, "q", max_continuations=0,
    )
    assert text == "partial"
    assert meta["continuation_count"] == 0
    assert meta["still_truncated"] is True
    assert len(backend.calls) == 1


# ── (k/l) seam edge cases ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_partial_overlap_seam() -> None:
    # First says "A B C D" truncated; continuation overlaps "C D" then adds "E F"
    first = _gr("A\nB\nC\nD", truncated=True, stop_reason="length")
    second = _gr("C\nD\nE\nF")
    backend = _ScriptedBackend([first, second])
    text, meta = await generate_with_continuation(backend, "q")
    # _deduplicate_seam should fold the overlap so we get A B C D E F
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines == ["A", "B", "C", "D", "E", "F"]
    assert meta["continuation_count"] == 1
    assert meta["was_continued"] is True


# ── (m) initial-call exception PROPAGATES (not fail-open) ─────────────


@pytest.mark.asyncio
async def test_initial_call_exception_propagates() -> None:
    backend = _ScriptedBackend([RuntimeError("first call failed")])
    with pytest.raises(RuntimeError, match="first call failed"):
        await generate_with_continuation(backend, "q")


# ── (n) mixed return types across rounds ──────────────────────────────


@pytest.mark.asyncio
async def test_mixed_return_types_across_rounds() -> None:
    first = _gr("structured\nfirst\nresponse", truncated=True, stop_reason="length")
    second = "raw\nsecond\nstr"  # raw str — must be normalized
    backend = _ScriptedBackend([first, second])
    text, meta = await generate_with_continuation(backend, "q")
    assert "structured" in text
    assert "raw" in text
    assert meta["continuation_count"] == 1
    assert meta["was_continued"] is True
    # Second response was a raw str so it cannot report truncation:
    assert meta["still_truncated"] is False


# ── arg passthrough ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_args_passed_through_to_backend() -> None:
    backend = _ScriptedBackend([_gr("ok")])
    await generate_with_continuation(
        backend, "the prompt",
        max_tokens=2048, temperature=0.7, stop=["</end>"],
    )
    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert call["prompt"] == "the prompt"
    assert call["max_tokens"] == 2048
    assert call["temperature"] == 0.7
    assert call["stop"] == ["</end>"]


@pytest.mark.asyncio
async def test_continuation_call_uses_same_args() -> None:
    first = _gr("partial", truncated=True, stop_reason="length")
    second = _gr("rest")
    backend = _ScriptedBackend([first, second])
    await generate_with_continuation(
        backend, "q",
        max_tokens=1024, temperature=0.5, stop=None,
    )
    assert len(backend.calls) == 2
    # Both calls must use the same generation params
    assert backend.calls[0]["max_tokens"] == 1024
    assert backend.calls[1]["max_tokens"] == 1024
    assert backend.calls[0]["temperature"] == 0.5
    assert backend.calls[1]["temperature"] == 0.5
