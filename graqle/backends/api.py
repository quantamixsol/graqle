"""API model backends — Anthropic, OpenAI, Bedrock, Ollama, Custom.

All backends include:
- Exponential backoff retry (3 attempts)
- Response validation (defensive parsing)
- Structured error logging
- Timeout handling
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from graqle.backends.base import BaseBackend

logger = logging.getLogger("graqle.backends.api")

# Retry configuration
MAX_RETRIES = 3
BASE_DELAY = 1.0  # seconds
MAX_DELAY = 30.0


class BackendError(Exception):
    """Raised when a backend call fails after all retries."""

    def __init__(self, backend_name: str, message: str, attempts: int = 0) -> None:
        self.backend_name = backend_name
        self.attempts = attempts
        super().__init__(f"[{backend_name}] {message} (after {attempts} attempts)")


async def _retry_with_backoff(
    func, *, backend_name: str, max_retries: int = MAX_RETRIES
) -> Any:
    """Execute an async function with exponential backoff retry."""
    last_error = None
    for attempt in range(max_retries):
        try:
            return await func()
        except ImportError:
            raise  # Don't retry import errors
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                logger.warning(
                    f"[{backend_name}] Attempt {attempt + 1}/{max_retries} failed: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"[{backend_name}] All {max_retries} attempts failed: {e}"
                )

    raise BackendError(backend_name, str(last_error), max_retries)


class AnthropicBackend(BaseBackend):
    """Anthropic Claude API backend with retry + validation."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        api_key: str | None = None,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self._model = model
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client = None
        self._max_retries = max_retries

    def _get_client(self):
        if self._client is None:
            try:
                from anthropic import AsyncAnthropic
                self._client = AsyncAnthropic(api_key=self._api_key)
            except ImportError:
                raise ImportError(
                    "Anthropic backend requires 'anthropic'. "
                    "Install with: pip install graqle[api]"
                )
        return self._client

    async def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str:
        async def _call():
            client = self._get_client()
            response = await client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
                stop_sequences=stop or [],
            )
            # Defensive response validation
            if not response.content:
                logger.warning(f"[{self.name}] Empty content in response")
                return ""
            return response.content[0].text

        return await _retry_with_backoff(
            _call, backend_name=self.name, max_retries=self._max_retries
        )

    @property
    def name(self) -> str:
        return f"anthropic:{self._model}"

    @property
    def cost_per_1k_tokens(self) -> float:
        costs = {
            "claude-haiku-4-5-20251001": 0.001,
            "claude-sonnet-4-6": 0.003,
            "claude-opus-4-6": 0.015,
        }
        return costs.get(self._model, 0.003)


class OpenAIBackend(BaseBackend):
    """OpenAI GPT API backend with retry + validation."""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self._model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._client = None
        self._max_retries = max_retries

    def _get_client(self):
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(api_key=self._api_key)
            except ImportError:
                raise ImportError(
                    "OpenAI backend requires 'openai'. "
                    "Install with: pip install graqle[api]"
                )
        return self._client

    async def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str:
        async def _call():
            client = self._get_client()
            response = await client.chat.completions.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
                stop=stop,
            )
            # Defensive response validation
            if not response.choices:
                logger.warning(f"[{self.name}] No choices in response")
                return ""
            content = response.choices[0].message.content
            return content or ""

        return await _retry_with_backoff(
            _call, backend_name=self.name, max_retries=self._max_retries
        )

    @property
    def name(self) -> str:
        return f"openai:{self._model}"

    @property
    def cost_per_1k_tokens(self) -> float:
        costs = {"gpt-4o-mini": 0.0003, "gpt-4o": 0.005, "gpt-4-turbo": 0.01}
        return costs.get(self._model, 0.001)


class BedrockBackend(BaseBackend):
    """AWS Bedrock API backend with retry + validation + token tracking."""

    # Bedrock pricing per 1K tokens (input/output) as of 2026-03
    # Supports both direct model IDs and inference profile IDs
    PRICING = {
        "anthropic.claude-sonnet-4-6": {"input": 0.003, "output": 0.015},
        "eu.anthropic.claude-sonnet-4-6": {"input": 0.003, "output": 0.015},
        "global.anthropic.claude-sonnet-4-6": {"input": 0.003, "output": 0.015},
        "anthropic.claude-sonnet-4-20250514-v1:0": {"input": 0.003, "output": 0.015},
        "eu.anthropic.claude-sonnet-4-20250514-v1:0": {"input": 0.003, "output": 0.015},
        "anthropic.claude-sonnet-4-5-20250929-v1:0": {"input": 0.003, "output": 0.015},
        "eu.anthropic.claude-sonnet-4-5-20250929-v1:0": {"input": 0.003, "output": 0.015},
        "anthropic.claude-haiku-4-5-20251001-v1:0": {"input": 0.0008, "output": 0.004},
        "eu.anthropic.claude-haiku-4-5-20251001-v1:0": {"input": 0.0008, "output": 0.004},
        "anthropic.claude-opus-4-6-v1": {"input": 0.015, "output": 0.075},
        "eu.anthropic.claude-opus-4-6-v1": {"input": 0.015, "output": 0.075},
        "anthropic.claude-opus-4-5-20251101-v1:0": {"input": 0.015, "output": 0.075},
    }

    def __init__(
        self,
        model: str = "anthropic.claude-sonnet-4-6-v1:0",
        region: str | None = None,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self._model = model
        self._region = region or os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "us-east-1"
        self._client = None
        self._max_retries = max_retries
        # Cumulative token/cost tracking
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0
        self.call_count = 0

    def _get_client(self):
        if self._client is None:
            try:
                import boto3
                from botocore.config import Config as BotoConfig
                # Increase connection pool for parallel node reasoning (20+ concurrent calls)
                boto_config = BotoConfig(
                    max_pool_connections=50,
                    retries={"max_attempts": 3, "mode": "adaptive"},
                )
                self._client = boto3.client(
                    "bedrock-runtime", region_name=self._region,
                    config=boto_config,
                )
            except ImportError:
                raise ImportError(
                    "Bedrock backend requires 'boto3'. "
                    "Install with: pip install graqle[api]"
                )
        return self._client

    def _calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost based on model-specific pricing."""
        pricing = self.PRICING.get(self._model, {"input": 0.003, "output": 0.015})
        return (input_tokens * pricing["input"] / 1000) + (output_tokens * pricing["output"] / 1000)

    async def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str:
        import json

        async def _call():
            client = self._get_client()
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
            })
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.invoke_model(
                    modelId=self._model,
                    body=body,
                    contentType="application/json",
                ),
            )
            result = json.loads(response["body"].read())

            # Track tokens from Bedrock response
            usage = result.get("usage", {})
            in_tok = usage.get("input_tokens", 0)
            out_tok = usage.get("output_tokens", 0)
            call_cost = self._calculate_cost(in_tok, out_tok)
            self.total_input_tokens += in_tok
            self.total_output_tokens += out_tok
            self.total_cost_usd += call_cost
            self.call_count += 1

            if in_tok > 0:
                logger.debug(
                    f"[{self.name}] call #{self.call_count}: "
                    f"{in_tok} in + {out_tok} out = ${call_cost:.6f} "
                    f"(cumulative: ${self.total_cost_usd:.6f})"
                )

            # Defensive validation
            if "content" not in result or not result["content"]:
                logger.warning(f"[{self.name}] No content in Bedrock response")
                return ""
            return result["content"][0].get("text", "")

        return await _retry_with_backoff(
            _call, backend_name=self.name, max_retries=self._max_retries
        )

    def get_cost_report(self) -> dict:
        """Return detailed cost breakdown."""
        return {
            "model": self._model,
            "region": self._region,
            "calls": self.call_count,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
        }

    @property
    def name(self) -> str:
        return f"bedrock:{self._model}"

    @property
    def cost_per_1k_tokens(self) -> float:
        pricing = self.PRICING.get(self._model, {"input": 0.003, "output": 0.015})
        return (pricing["input"] + pricing["output"]) / 2


class OllamaBackend(BaseBackend):
    """Ollama local model backend with retry + validation."""

    def __init__(
        self,
        model: str = "qwen2.5:0.5b",
        host: str = "http://localhost:11434",
        timeout: float = 120.0,
        max_retries: int = MAX_RETRIES,
        num_ctx: int | None = None,
    ) -> None:
        self._model = model
        self._host = host
        self._timeout = timeout
        self._max_retries = max_retries
        self._num_ctx = num_ctx  # context window size (e.g., 8192 for DeepSeek-R1)

    async def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str:
        async def _call():
            try:
                import httpx
            except ImportError:
                raise ImportError(
                    "Ollama backend requires 'httpx'. "
                    "Install with: pip install graqle[api]"
                )
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._host}/api/generate",
                    json={
                        "model": self._model,
                        "prompt": prompt,
                        "options": {
                            "num_predict": max_tokens,
                            "temperature": temperature,
                            **({"num_ctx": self._num_ctx} if self._num_ctx else {}),
                        },
                        "stream": False,
                    },
                )
                response.raise_for_status()
                data = response.json()
                text = data.get("response", "")
                # Strip <think>...</think> tags from reasoning models (DeepSeek-R1)
                if "<think>" in text:
                    import re
                    text = re.sub(
                        r"<think>.*?</think>\s*", "", text, flags=re.DOTALL
                    )
                return text.strip()

        return await _retry_with_backoff(
            _call, backend_name=self.name, max_retries=self._max_retries
        )

    @property
    def name(self) -> str:
        return f"ollama:{self._model}"

    @property
    def cost_per_1k_tokens(self) -> float:
        return 0.0001


class CustomBackend(BaseBackend):
    """Custom endpoint backend — any OpenAI-compatible API."""

    def __init__(
        self,
        endpoint: str,
        model: str = "default",
        api_key: str | None = None,
        cost: float = 0.001,
        timeout: float = 120.0,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self._endpoint = endpoint
        self._model = model
        self._api_key = api_key
        self._cost = cost
        self._timeout = timeout
        self._max_retries = max_retries

    async def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str:
        async def _call():
            try:
                import httpx
            except ImportError:
                raise ImportError(
                    "Custom backend requires 'httpx'. Install with: pip install httpx"
                )
            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._endpoint,
                    headers=headers,
                    json={
                        "model": self._model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "stop": stop,
                    },
                )
                response.raise_for_status()
                data = response.json()
                # Defensive validation
                choices = data.get("choices", [])
                if not choices:
                    logger.warning(f"[{self.name}] No choices in response")
                    return ""
                message = choices[0].get("message", {})
                return message.get("content", "")

        return await _retry_with_backoff(
            _call, backend_name=self.name, max_retries=self._max_retries
        )

    @property
    def name(self) -> str:
        return f"custom:{self._endpoint}"

    @property
    def cost_per_1k_tokens(self) -> float:
        return self._cost
