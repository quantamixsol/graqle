"""Provider presets — first-class support for popular LLM providers.

Each provider is a named preset that auto-resolves to a CustomBackend
with the correct endpoint URL, environment variable, and per-model pricing.

All providers use the OpenAI-compatible chat completions format.
For Google Gemini (which uses a different format), see gemini.py.

Usage:
    from graqle.backends.providers import create_provider_backend

    backend = create_provider_backend("groq", model="llama-3.3-70b-versatile")
    graph.set_default_backend(backend)
"""

from __future__ import annotations

import os
from typing import Any

from graqle.backends.api import CustomBackend

# ---------------------------------------------------------------------------
# Provider preset registry
# ---------------------------------------------------------------------------
# Each entry contains:
#   env_var       — environment variable for the API key
#   endpoint      — OpenAI-compatible chat completions URL
#   label         — human-readable name (for doctor/logs)
#   default_model — model used when none specified
#   models        — {model_name: cost_per_1k_tokens} pricing table
# ---------------------------------------------------------------------------

PROVIDER_PRESETS: dict[str, dict[str, Any]] = {
    "groq": {
        "env_var": "GROQ_API_KEY",
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
        "label": "Groq (Fast Inference)",
        "default_model": "llama-3.3-70b-versatile",
        "models": {
            "llama-3.3-70b-versatile": 0.00059,
            "llama-3.1-70b-versatile": 0.00059,
            "llama-3.1-8b-instant": 0.00005,
            "llama-3.2-3b-preview": 0.00006,
            "llama-3.2-1b-preview": 0.00004,
            "gemma2-9b-it": 0.00020,
            "mixtral-8x7b-32768": 0.00024,
        },
    },
    "deepseek": {
        "env_var": "DEEPSEEK_API_KEY",
        "endpoint": "https://api.deepseek.com/v1/chat/completions",
        "label": "DeepSeek",
        "default_model": "deepseek-chat",
        "models": {
            "deepseek-chat": 0.00014,
            "deepseek-reasoner": 0.00055,
        },
    },
    "together": {
        "env_var": "TOGETHER_API_KEY",
        "endpoint": "https://api.together.xyz/v1/chat/completions",
        "label": "Together AI",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "models": {
            "meta-llama/Llama-3.3-70B-Instruct-Turbo": 0.00088,
            "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo": 0.00018,
            "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo": 0.00088,
            "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo": 0.00350,
            "mistralai/Mixtral-8x7B-Instruct-v0.1": 0.00060,
            "Qwen/Qwen2.5-72B-Instruct-Turbo": 0.00120,
        },
    },
    "mistral": {
        "env_var": "MISTRAL_API_KEY",
        "endpoint": "https://api.mistral.ai/v1/chat/completions",
        "label": "Mistral AI",
        "default_model": "mistral-small-latest",
        "models": {
            "mistral-small-latest": 0.00020,
            "mistral-medium-latest": 0.00275,
            "mistral-large-latest": 0.00200,
            "open-mistral-nemo": 0.00015,
            "codestral-latest": 0.00030,
        },
    },
    "openrouter": {
        "env_var": "OPENROUTER_API_KEY",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "label": "OpenRouter",
        "default_model": "meta-llama/llama-3.3-70b-instruct",
        "models": {
            "meta-llama/llama-3.3-70b-instruct": 0.00039,
            "google/gemini-2.0-flash-001": 0.00010,
            "anthropic/claude-3.5-haiku": 0.00080,
            "deepseek/deepseek-chat-v3-0324": 0.00014,
            "qwen/qwen-2.5-72b-instruct": 0.00036,
            "mistralai/mistral-small-3.1-24b-instruct": 0.00015,
        },
    },
    "fireworks": {
        "env_var": "FIREWORKS_API_KEY",
        "endpoint": "https://api.fireworks.ai/inference/v1/chat/completions",
        "label": "Fireworks AI",
        "default_model": "accounts/fireworks/models/llama-v3p3-70b-instruct",
        "models": {
            "accounts/fireworks/models/llama-v3p3-70b-instruct": 0.00090,
            "accounts/fireworks/models/llama-v3p1-8b-instruct": 0.00020,
            "accounts/fireworks/models/llama-v3p1-405b-instruct": 0.00300,
            "accounts/fireworks/models/mixtral-8x7b-instruct": 0.00050,
            "accounts/fireworks/models/qwen2p5-72b-instruct": 0.00090,
        },
    },
    "cohere": {
        "env_var": "COHERE_API_KEY",
        "endpoint": "https://api.cohere.com/v2/chat",
        "label": "Cohere",
        "default_model": "command-r-plus",
        "models": {
            "command-r-plus": 0.00250,
            "command-r": 0.00015,
            "command-light": 0.00015,
        },
    },
}


def get_provider_names() -> list[str]:
    """Return all available provider names."""
    return list(PROVIDER_PRESETS.keys())


def get_provider_env_var(provider: str) -> str | None:
    """Return the expected environment variable for a provider."""
    preset = PROVIDER_PRESETS.get(provider)
    return preset["env_var"] if preset else None


def create_provider_backend(
    provider: str,
    model: str | None = None,
    api_key: str | None = None,
    endpoint: str | None = None,
) -> CustomBackend:
    """Create a CustomBackend from a provider preset.

    Args:
        provider: Provider name (e.g. "groq", "deepseek", "together").
        model: Model name. Defaults to provider's default_model.
        api_key: API key. Defaults to reading from the provider's env var.
        endpoint: Override endpoint URL (for self-hosted/proxy setups).

    Returns:
        A configured CustomBackend instance.

    Raises:
        ValueError: If provider is unknown or API key is missing.
    """
    if provider not in PROVIDER_PRESETS:
        available = ", ".join(sorted(PROVIDER_PRESETS.keys()))
        raise ValueError(
            f"Unknown provider '{provider}'. "
            f"Available: {available}"
        )

    preset = PROVIDER_PRESETS[provider]
    env_var = preset["env_var"]

    # Resolve API key
    resolved_key = api_key or os.environ.get(env_var)
    if not resolved_key:
        raise ValueError(
            f"API key required for {preset['label']}. "
            f"Set the {env_var} environment variable or pass api_key explicitly."
        )

    # Resolve model and cost
    resolved_model = model or preset["default_model"]
    cost = preset["models"].get(resolved_model, 0.001)

    # Resolve endpoint
    resolved_endpoint = endpoint or preset["endpoint"]

    return CustomBackend(
        endpoint=resolved_endpoint,
        model=resolved_model,
        api_key=resolved_key,
        cost=cost,
    )
