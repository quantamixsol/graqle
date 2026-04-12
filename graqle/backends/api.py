"""API model backends — Anthropic, OpenAI, Bedrock, Ollama, Custom.

All backends include:
- Exponential backoff retry (3 attempts)
- Response validation (defensive parsing)
- Structured error logging
- Timeout handling
"""

# ── graqle:intelligence ──
# module: graqle.backends.api
# risk: CRITICAL (impact radius: 19 modules)
# consumers: providers, benchmark_runner, run_multigov_v2, run_multigov_v3, init +14 more
# dependencies: __future__, asyncio, logging, os, typing +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from graqle.backends.base import BaseBackend, GenerateResult

logger = logging.getLogger("graqle.backends.api")

# Retry configuration
MAX_RETRIES = 3


def _get_env_with_win_fallback(key: str) -> str:
    """Read an environment variable with Windows registry fallback.

    On Windows, env vars set via SetEnvironmentVariable('User') or
    SetEnvironmentVariable('Machine') are only visible to processes
    started AFTER the change.  IDE extensions (VS Code, Claude Code)
    spawn shells before the user sets the key, so os.environ misses it.
    This function checks the User and Machine registry as fallback.
    """
    value = os.environ.get(key, "")
    if value:
        return value
    if os.name != "nt":
        return ""
    try:
        import winreg
        # Try User-level first, then Machine-level
        for hive, path in [
            (winreg.HKEY_CURRENT_USER, "Environment"),
            (winreg.HKEY_LOCAL_MACHINE,
             r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        ]:
            try:
                with winreg.OpenKey(hive, path) as hkey:
                    val, _ = winreg.QueryValueEx(hkey, key)
                    if val:
                        os.environ[key] = str(val)  # cache for future calls
                        return str(val)
            except (OSError, FileNotFoundError):
                continue
    except ImportError:
        pass
    return ""
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
    ) -> GenerateResult:
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
                return GenerateResult(
                    text="",
                    truncated=False,
                    stop_reason=getattr(response, "stop_reason", "") or "",
                    tokens_used=None,
                    model=self._model,
                )
            # Capture stop_reason for truncation detection
            stop_reason = getattr(response, "stop_reason", "") or ""
            truncated = stop_reason == "max_tokens"
            usage = getattr(response, "usage", None)
            tokens_used = getattr(usage, "output_tokens", None) if usage else None
            return GenerateResult(
                text=response.content[0].text,
                truncated=truncated,
                stop_reason=stop_reason,
                tokens_used=tokens_used,
                model=self._model,
            )

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

    async def agenerate_stream(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ):
        """Stream token chunks using Anthropic's native streaming API.

        Uses client.messages.stream() context manager to yield text_delta
        chunks as they arrive. Reduces time-to-first-token for graq_generate.

        v0.38.0: Phase 3 streaming implementation.
        """
        try:
            client = self._get_client()
            async with client.messages.stream(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
                stop_sequences=stop or [],
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception:
            # Streaming failed — fall back to single-chunk (non-streaming) result
            result = await self.generate(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                stop=stop,
            )
            yield str(result)


class OpenAIBackend(BaseBackend):
    """OpenAI GPT API backend with retry + validation."""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self._model = model
        self._api_key = api_key or _get_env_with_win_fallback("OPENAI_API_KEY")
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
    ) -> GenerateResult:
        async def _call():
            client = self._get_client()
            is_codex = "codex" in self._model.lower()
            _needs_new_param = (
                self._model.startswith("gpt-5")
                or self._model.startswith("o3")
                or self._model.startswith("o4")
            )

            if is_codex:
                # Codex models use completions API, not chat
                response = await client.completions.create(
                    model=self._model,
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stop=stop,
                )
                if not response.choices:
                    logger.warning(f"[{self.name}] No choices in response")
                    return GenerateResult(text="", model=self._model)
                choice = response.choices[0]
                content = choice.text or ""
            elif _needs_new_param:
                # GPT-5.x / o3 / o4 require max_completion_tokens
                response = await client.chat.completions.create(
                    model=self._model,
                    max_completion_tokens=max_tokens,
                    temperature=temperature,
                    messages=[{"role": "user", "content": prompt}],
                    stop=stop,
                )
                if not response.choices:
                    logger.warning(f"[{self.name}] No choices in response")
                    return GenerateResult(text="", model=self._model)
                choice = response.choices[0]
                content = choice.message.content or ""
            else:
                # Legacy models (gpt-4.1, gpt-4o, etc.)
                response = await client.chat.completions.create(
                    model=self._model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=[{"role": "user", "content": prompt}],
                    stop=stop,
                )
                if not response.choices:
                    logger.warning(f"[{self.name}] No choices in response")
                    return GenerateResult(text="", model=self._model)
                choice = response.choices[0]
                content = choice.message.content or ""
            # Capture finish_reason for truncation detection
            finish_reason = getattr(choice, "finish_reason", "") or ""
            truncated = finish_reason == "length"
            usage = getattr(response, "usage", None)
            tokens_used = getattr(usage, "completion_tokens", None) if usage else None
            return GenerateResult(
                text=content,
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
        return f"openai:{self._model}"

    @property
    def cost_per_1k_tokens(self) -> float:
        costs = {
            "gpt-4o-mini": 0.0003,
            "gpt-4o": 0.005,
            "gpt-4-turbo": 0.01,
            "gpt-5.4": 0.015,
            "gpt-5.4-mini": 0.003,
            "gpt-5.4-nano": 0.0006,
        }
        if self._model not in costs:
            logger.warning("Unknown OpenAI model %r for cost tracking; using default $0.001/1k tokens", self._model)
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

    # Region-to-inference-profile prefix mapping
    # AWS Bedrock requires cross-region inference profiles for newer models (Sonnet 4.5+)
    _REGION_PROFILE_PREFIXES = {
        "eu-central-1": "eu", "eu-west-1": "eu", "eu-west-2": "eu", "eu-west-3": "eu",
        "eu-north-1": "eu", "eu-south-1": "eu",
        "us-east-1": "us", "us-east-2": "us", "us-west-1": "us", "us-west-2": "us",
        "ap-southeast-1": "apac", "ap-southeast-2": "apac", "ap-northeast-1": "apac",
        "ap-northeast-2": "apac", "ap-south-1": "apac",
    }

    def __init__(
        self,
        model: str = "anthropic.claude-sonnet-4-6-v1:0",
        region: str | None = None,
        max_retries: int = MAX_RETRIES,
        profile_name: str | None = None,
    ) -> None:
        self._model = model
        self._region = region or os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "us-east-1"
        self._profile_name = profile_name
        self._client = None
        self._max_retries = max_retries
        self._inference_profile_attempted = False  # Track if we've tried profile fallback
        # Cumulative token/cost tracking
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0
        self.call_count = 0

    @staticmethod
    def adaptive_read_timeout(
        activated_nodes: int = 0,
        *,
        floor: float = 300.0,
        per_node: float = 5.0,
        cap: float = 900.0,
    ) -> float:
        """Calculate adaptive read timeout based on activated node count.

        Prevents ReadTimeoutError when large subgraphs trigger long
        reasoning chains on Sonnet/Opus.

        Formula: clamp(floor, activated_nodes * per_node, cap)
        Default: clamp(300, nodes * 5, 900) → 50 nodes = 300s, 100 nodes = 500s, max 900s
        """
        if activated_nodes <= 0:
            return floor
        return min(cap, max(floor, activated_nodes * per_node))

    def _get_client(self):
        if self._client is None:
            try:
                import boto3
                from botocore.config import Config as BotoConfig
                # Increase connection pool for parallel node reasoning (20+ concurrent calls)
                boto_config = BotoConfig(
                    max_pool_connections=50,
                    read_timeout=300,    # 5 min — large graph reasoning (hub nodes) can take 60-180s on Sonnet/Opus
                    connect_timeout=10,
                    retries={"max_attempts": 3, "mode": "adaptive"},
                )
                session = boto3.Session(
                    profile_name=self._profile_name,
                    region_name=self._region,
                )
                self._client = session.client(
                    "bedrock-runtime",
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
    ) -> GenerateResult:
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

            # Capture stop_reason for truncation detection
            stop_reason = result.get("stop_reason", "") or ""
            truncated = stop_reason == "max_tokens"

            # Defensive validation
            if "content" not in result or not result["content"]:
                logger.warning(f"[{self.name}] No content in Bedrock response")
                return GenerateResult(
                    text="", truncated=truncated, stop_reason=stop_reason,
                    tokens_used=out_tok or None, model=self._model,
                )
            return GenerateResult(
                text=result["content"][0].get("text", ""),
                truncated=truncated,
                stop_reason=stop_reason,
                tokens_used=out_tok or None,
                model=self._model,
            )

        try:
            return await _retry_with_backoff(
                _call, backend_name=self.name, max_retries=self._max_retries
            )
        except Exception as e:
            # Auto-detect inference profile requirement and retry
            err_msg = str(e).lower()
            if (
                "inference profile" in err_msg
                and not self._inference_profile_attempted
                and not self._model.startswith(("eu.", "us.", "apac.", "global."))
            ):
                self._inference_profile_attempted = True
                prefix = self._REGION_PROFILE_PREFIXES.get(self._region, "us")
                old_model = self._model
                self._model = f"{prefix}.{self._model}"
                logger.warning(
                    "Bedrock requires inference profile for %s in %s. "
                    "Auto-retrying with: %s",
                    old_model, self._region, self._model,
                )
                # Update pricing lookup to include new model ID
                if old_model in self.PRICING and self._model not in self.PRICING:
                    self.PRICING[self._model] = self.PRICING[old_model]
                return await _retry_with_backoff(
                    _call, backend_name=self.name, max_retries=self._max_retries
                )
            raise

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

    # Reasoning models spend tokens on internal chain-of-thought (<think> tags)
    # before producing visible output. They need a larger num_predict budget.
    _REASONING_MODEL_PREFIXES = ("deepseek-r1", "qwq", "qwen3")

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

    def _effective_num_predict(self, max_tokens: int) -> int:
        """Return an appropriate num_predict for the model.

        Reasoning models spend tokens on internal chain-of-thought before
        producing visible output, so they need a larger token budget.
        Non-reasoning models use caller's max_tokens unchanged.
        """
        model_lower = (self._model or "").lower()
        effective = max_tokens or 512  # null-coalesce for defensive safety
        if any(model_lower.startswith(p) for p in self._REASONING_MODEL_PREFIXES):
            return max(effective, 4096)
        return effective

    async def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> GenerateResult:
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
                            "num_predict": self._effective_num_predict(max_tokens),
                            "temperature": temperature,
                            **({"num_ctx": self._num_ctx} if self._num_ctx else {}),
                        },
                        "stream": False,
                    },
                )
                response.raise_for_status()
                data = response.json()
                text = data.get("response", "")
                # Strip <think>...</think> tags from reasoning models (DeepSeek-R1, Gemma4)
                # Fallback: if stripping produces empty, use last think block content
                if "<think>" in text:
                    import re
                    think_blocks = re.findall(
                        r"<think>(.*?)</think>", text, flags=re.DOTALL
                    )
                    stripped = re.sub(
                        r"<think>.*?</think>\s*", "", text, flags=re.DOTALL
                    ).strip()
                    if stripped:
                        text = stripped
                    elif think_blocks:
                        text = think_blocks[-1].strip()
                # Capture done_reason for truncation detection
                done_reason = data.get("done_reason", "") or ""
                truncated = done_reason == "length"
                if truncated:
                    logger.warning(
                        "[%s] Response truncated (done_reason='length', %d chars). "
                        "Consider increasing num_predict or num_ctx.",
                        self.name, len(text or ""),
                    )
                tokens_used = data.get("eval_count")  # Ollama output token count
                return GenerateResult(
                    text=text.strip(),
                    truncated=truncated,
                    stop_reason=done_reason,
                    tokens_used=tokens_used,
                    model=self._model,
                )

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
    ) -> GenerateResult:
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
                    return GenerateResult(text="", model=self._model)
                choice = choices[0]
                message = choice.get("message", {})
                # Best-effort finish_reason from OpenAI-compatible API
                finish_reason = choice.get("finish_reason", "") or ""
                truncated = finish_reason == "length"
                return GenerateResult(
                    text=message.get("content", ""),
                    truncated=truncated,
                    stop_reason=finish_reason,
                    tokens_used=None,  # Unknown for custom endpoints
                    model=self._model,
                )

        return await _retry_with_backoff(
            _call, backend_name=self.name, max_retries=self._max_retries
        )

    @property
    def name(self) -> str:
        return f"custom:{self._endpoint}"

    @property
    def cost_per_1k_tokens(self) -> float:
        return self._cost
