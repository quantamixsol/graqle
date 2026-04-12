"""Google Gemini API backend.

Gemini uses Google's own ``generateContent`` API format, not the
OpenAI-compatible chat completions format used by other providers.
This backend handles the translation.

Usage:
    from graqle.backends.gemini import GeminiBackend

    backend = GeminiBackend(model="gemini-2.0-flash")
    graph.set_default_backend(backend)

Requires:
    - ``GEMINI_API_KEY`` or ``GOOGLE_API_KEY`` environment variable
    - ``httpx`` (already a GraQle dependency)
"""

# ── graqle:intelligence ──
# module: graqle.backends.gemini
# risk: LOW (impact radius: 1 modules)
# consumers: test_gemini
# dependencies: __future__, logging, os, typing, base
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import os
from typing import Any

from graqle.backends.base import BaseBackend, GenerateResult

logger = logging.getLogger("graqle.backends.gemini")

# Gemini pricing (USD per 1K tokens, blended input/output estimate)
GEMINI_PRICING: dict[str, float] = {
    "gemini-2.5-pro": 0.00125,
    "gemini-2.5-flash": 0.00015,
    "gemini-2.0-flash": 0.00010,
    "gemini-2.0-flash-lite": 0.00004,
    "gemini-1.5-pro": 0.00125,
    "gemini-1.5-flash": 0.00008,
}

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiBackend(BaseBackend):
    """Google Gemini API backend using the generateContent endpoint."""

    def __init__(
        self,
        model: str = "gemini-2.0-flash",
        api_key: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 3,
    ) -> None:
        self._model = model
        self._api_key = (
            api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )
        self._timeout = timeout
        self._max_retries = max_retries

    async def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> GenerateResult:
        if not self._api_key:
            raise ValueError(
                "Gemini API key required. "
                "Set GEMINI_API_KEY or GOOGLE_API_KEY environment variable."
            )

        from graqle.backends.api import _retry_with_backoff

        async def _call() -> GenerateResult:
            try:
                import httpx
            except ImportError:
                raise ImportError(
                    "Gemini backend requires 'httpx'. Install with: pip install httpx"
                )

            url = (
                f"{_BASE_URL}/models/{self._model}:generateContent"
                f"?key={self._api_key}"
            )

            body: dict[str, Any] = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": max_tokens,
                    "temperature": temperature,
                },
            }
            if stop:
                body["generationConfig"]["stopSequences"] = stop

            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=body)
                response.raise_for_status()
                data = response.json()

            # Parse Gemini response format
            candidates = data.get("candidates", [])
            if not candidates:
                logger.warning("[%s] No candidates in Gemini response", self.name)
                return GenerateResult(text="", model=self._model)

            candidate = candidates[0]
            content = candidate.get("content", {})
            parts = content.get("parts", [])
            text = parts[0].get("text", "") if parts else ""

            # Capture finishReason for truncation detection
            finish_reason = candidate.get("finishReason", "") or ""
            truncated = finish_reason == "MAX_TOKENS"
            # Gemini token count from usageMetadata
            usage = data.get("usageMetadata", {})
            tokens_used = usage.get("candidatesTokenCount")

            return GenerateResult(
                text=text,
                truncated=truncated,
                stop_reason=finish_reason,
                tokens_used=tokens_used,
                model=self._model,
            )

        return await _retry_with_backoff(
            _call, backend_name=self.name, max_retries=self._max_retries
        )

    @property
    def name(self) -> str:
        return f"gemini:{self._model}"

    @property
    def cost_per_1k_tokens(self) -> float:
        return GEMINI_PRICING.get(self._model, 0.0005)
