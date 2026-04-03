"""Model output token limits and resolution logic.

OT-028/030: Prevents silent truncation by ensuring max_tokens requests
don't exceed model capabilities, and provides ground truth for detecting
when a response hit the model's output ceiling.
"""

# ── graqle:intelligence ──
# module: graqle.backends.model_limits
# risk: LOW (impact radius: 0 modules)
# consumers: api
# dependencies: __future__, logging
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import functools
import logging

logger = logging.getLogger("graqle.backends.model_limits")

# ── Known model OUTPUT token limits ────────────────────────
# These are MAX OUTPUT tokens (not input context windows).
# Keys are lowercase. resolve_max_tokens() does longest-prefix matching.

MODEL_OUTPUT_LIMITS: dict[str, int] = {
    # ── Anthropic ──
    "claude-opus-4-6": 32768,
    "claude-sonnet-4-6": 16384,
    "claude-sonnet-4-20250514": 16384,
    "claude-sonnet-4-5": 8192,
    "claude-3-5-sonnet": 8192,
    "claude-3-5-haiku": 8192,
    "claude-haiku-4-5": 8192,
    "claude-3-opus": 4096,
    "claude-3-sonnet": 4096,
    "claude-3-haiku": 4096,
    "claude-2.1": 4096,
    "claude-2": 4096,
    "claude-instant": 4096,
    # ── OpenAI ──
    "gpt-4o": 16384,
    "gpt-4o-mini": 16384,
    "gpt-4o-2024-08-06": 16384,
    "gpt-4o-2024-05-13": 4096,
    "gpt-4-turbo": 4096,
    "gpt-4": 8192,
    "gpt-3.5-turbo": 4096,
    "gpt-5.4": 32768,
    "gpt-5.4-mini": 16384,
    "gpt-5.4-nano": 8192,
    "o1-preview": 32768,
    "o1-mini": 65536,
    "o1": 100000,
    "o3-mini": 65536,
    # ── Bedrock (Anthropic models via AWS) ──
    "anthropic.claude-opus-4-6": 32768,
    "anthropic.claude-sonnet-4-6": 16384,
    "anthropic.claude-sonnet-4-20250514": 16384,
    "anthropic.claude-3-5-sonnet": 8192,
    "anthropic.claude-3-sonnet": 4096,
    "anthropic.claude-3-haiku": 4096,
    "anthropic.claude-3-opus": 4096,
    # ── Bedrock with region prefix ──
    "eu.anthropic.claude-sonnet-4-6": 16384,
    "eu.anthropic.claude-sonnet-4-20250514": 16384,
    "us.anthropic.claude-sonnet-4-6": 16384,
    # ── Google Gemini ──
    "gemini-2.5-pro": 65536,
    "gemini-2.5-flash": 65536,
    "gemini-2.0-flash": 8192,
    "gemini-1.5-pro": 8192,
    "gemini-1.5-flash": 8192,
    "gemini-1.0-pro": 2048,
    # ── Meta / Llama ──
    "llama-3.1-405b": 4096,
    "llama-3.1-70b": 4096,
    "llama-3.1-8b": 4096,
    # ── Mistral ──
    "mistral-large": 8192,
    "mistral-medium": 8192,
    "mistral-small": 8192,
    "mixtral-8x7b": 4096,
}

# Default when model is unknown — conservative
DEFAULT_OUTPUT_LIMIT = 4096

# Safety margin below hard limit
_SAFETY_MARGIN = 64

# M4 fix: Pre-sort keys by length descending for correct longest-prefix matching
# (prevents "gpt-4o" matching before "gpt-4o-mini")
_SORTED_KEYS: list[tuple[str, int]] = sorted(
    MODEL_OUTPUT_LIMITS.items(), key=lambda kv: len(kv[0]), reverse=True
)


def resolve_max_tokens(
    model: str | None,
    user_override: int | None = None,
    *,
    safety_margin: int = _SAFETY_MARGIN,
) -> int:
    """Resolve the effective max_tokens for a generation call.

    Priority:
    1. user_override (clamped to model limit)
    2. Model's known output limit (minus safety margin)
    3. DEFAULT_OUTPUT_LIMIT
    """
    model_limit = get_model_limit(model)

    if user_override is not None:
        if user_override > model_limit:
            logger.warning(
                "Requested max_tokens=%d exceeds model limit (%d) for %r; clamping",
                user_override,
                model_limit,
                model,
            )
            return model_limit
        return user_override

    return max(model_limit - safety_margin, 1)


@functools.lru_cache(maxsize=256)
def get_model_limit(model: str | None) -> int:
    """Get the hard output token limit for a model.

    Uses longest-prefix matching (sorted by key length descending)
    for versioned model names. Cached for O(1) repeated lookups.
    Returns DEFAULT_OUTPUT_LIMIT for unknown models.

    M4 fix: sorted keys prevent "gpt-4o" matching before "gpt-4o-mini".
    """
    if not model:
        return DEFAULT_OUTPUT_LIMIT

    normalized = model.lower().strip()

    # Exact match (fast path)
    if normalized in MODEL_OUTPUT_LIMITS:
        return MODEL_OUTPUT_LIMITS[normalized]

    # Longest-prefix match using pre-sorted keys (longest first)
    for key, limit in _SORTED_KEYS:
        if normalized.startswith(key):
            return limit

    # Strip region prefixes for Bedrock (eu., us., apac., global.)
    for prefix in ("eu.", "us.", "apac.", "global."):
        if normalized.startswith(prefix):
            stripped = normalized[len(prefix):]
            return get_model_limit(stripped)

    logger.debug(
        "Model %r not in MODEL_OUTPUT_LIMITS, using DEFAULT_OUTPUT_LIMIT=%d",
        model, DEFAULT_OUTPUT_LIMIT,
    )
    return DEFAULT_OUTPUT_LIMIT
