"""Mock backend for testing — returns configurable responses.

IMPORTANT: When MockBackend is used as a FALLBACK (not explicitly by tests),
it produces loud warnings so users know they're getting degraded results.
"""

# ── graqle:intelligence ──
# module: graqle.backends.mock
# risk: HIGH (impact radius: 57 modules)
# consumers: quickstart, __init__, conftest, test_routing, test_adaptive +52 more
# dependencies: __future__, logging, random, base
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import random

from graqle.backends.base import BaseBackend

logger = logging.getLogger("graqle.backends.mock")

# Track whether the warning has been shown this session
_FALLBACK_WARNING_SHOWN = False


class MockBackend(BaseBackend):
    """Mock model backend for testing and development.

    Returns configurable responses without any model inference.
    Useful for testing the orchestration pipeline without GPU/API costs.

    When used as a silent fallback (is_fallback=True), emits loud warnings
    so users know they're not getting real LLM reasoning.
    """

    def __init__(
        self,
        response: str | None = None,
        responses: list[str] | None = None,
        confidence_range: tuple[float, float] = (0.6, 0.9),
        latency_ms: float = 0.0,
        is_fallback: bool = False,
        fallback_reason: str = "",
    ) -> None:
        self._response = response
        self._responses = responses or []
        self._call_count = 0
        self._confidence_range = confidence_range
        self._latency_ms = latency_ms
        self._is_fallback = is_fallback
        self._fallback_reason = fallback_reason
        # Expose as public properties for fail-fast checks (e.g. graq bench)
        self.is_fallback = is_fallback
        self.fallback_reason = fallback_reason

    def _warn_fallback(self) -> None:
        """Emit a loud warning if this mock is being used as a fallback."""
        global _FALLBACK_WARNING_SHOWN
        if not self._is_fallback or _FALLBACK_WARNING_SHOWN:
            return
        _FALLBACK_WARNING_SHOWN = True

        reason = self._fallback_reason or "no backend configured"
        logger.warning(
            "\n"
            "============================================================\n"
            "  COGNIGRAPH: Using MOCK backend (%s)\n"
            "  Results are NOT real LLM reasoning!\n"
            "  \n"
            "  This means your queries return placeholder text,\n"
            "  not actual AI analysis of your code/knowledge graph.\n"
            "  \n"
            "  To fix (pick one):\n"
            "    graq setup-guide           -- see all options\n"
            "    graq setup-guide ollama    -- FREE, local, no API key\n"
            "    graq setup-guide anthropic -- best quality, $5 free credits\n"
            "    graq doctor                -- diagnose what's missing\n"
            "============================================================",
            reason,
        )

    async def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str:
        self._warn_fallback()

        if self._latency_ms > 0:
            import asyncio
            await asyncio.sleep(self._latency_ms / 1000)

        self._call_count += 1

        if self._response:
            return self._response

        if self._responses:
            idx = (self._call_count - 1) % len(self._responses)
            return self._responses[idx]

        # Fallback response clearly marked as mock — full transparency
        conf = random.uniform(*self._confidence_range)
        if self._is_fallback:
            return (
                f"[NO LLM CONFIGURED — this is a placeholder response, not real AI reasoning. "
                f"Run 'graq setup-guide' to choose a backend (free options available). "
                f"Run 'graq doctor' to check your setup.] "
                f"Placeholder analysis for this node. "
                f"Confidence: {conf:.0%}"
            )

        return (
            f"Based on my specialized knowledge, I can provide the following analysis. "
            f"The query relates to my domain expertise. "
            f"Confidence: {conf:.0%}"
        )

    @property
    def name(self) -> str:
        return "mock"

    @property
    def cost_per_1k_tokens(self) -> float:
        return 0.0

    @property
    def call_count(self) -> int:
        return self._call_count
