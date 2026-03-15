"""MessageCompressor — LLM-powered message compression.

Uses a model backend to compress verbose agent messages into concise
key-claim summaries. Target: ~1000 tokens → ~55 tokens (OPTIMA result).

When no LLM is available, falls back to rule-based extraction.
"""

# ── graqle:intelligence ──
# module: graqle.optimization.message_compressor
# risk: LOW (impact radius: 1 modules)
# consumers: test_token_optimizer
# dependencies: __future__, logging, typing, message, types
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from typing import Any

from graqle.core.message import Message
from graqle.core.types import ModelBackend

logger = logging.getLogger("graqle.optimization.compressor")

COMPRESSION_PROMPT = """Compress this agent message into 1-2 concise sentences. Keep ONLY:
- The main claim/finding
- The confidence level
- Key evidence (if any)

Remove all filler, hedging, and repetition.

Original message:
{message}

Compressed (1-2 sentences max):"""


class MessageCompressor:
    """Compress messages using LLM or rule-based fallback.

    The OPTIMA paper showed agents can communicate in ~55 tokens
    instead of ~1000 tokens with minimal task performance loss.
    This compressor approximates that reduction.
    """

    def __init__(
        self,
        backend: ModelBackend | None = None,
        *,
        target_tokens: int = 60,
        fallback_to_rules: bool = True,
    ) -> None:
        self.backend = backend
        self.target_tokens = target_tokens
        self.fallback_to_rules = fallback_to_rules
        self._cost: float = 0.0

    async def compress(self, message: Message) -> Message:
        """Compress a message, preserving metadata."""
        original_len = len(message.content)

        # Skip if already short enough
        estimated_tokens = original_len // 4
        if estimated_tokens <= self.target_tokens:
            return message

        # Try LLM compression
        if self.backend:
            try:
                compressed = await self._llm_compress(message.content)
                return self._create_compressed(message, compressed)
            except Exception as e:
                logger.warning(f"LLM compression failed: {e}")
                if not self.fallback_to_rules:
                    return message

        # Rule-based fallback
        compressed = self._rule_compress(message.content)
        return self._create_compressed(message, compressed)

    async def compress_batch(self, messages: list[Message]) -> list[Message]:
        """Compress multiple messages."""
        results = []
        for msg in messages:
            results.append(await self.compress(msg))
        return results

    async def _llm_compress(self, text: str) -> str:
        """Use LLM to compress text."""
        prompt = COMPRESSION_PROMPT.format(message=text[:500])
        result = await self.backend.generate(
            prompt, max_tokens=self.target_tokens, temperature=0.1
        )
        self._cost += getattr(self.backend, 'cost_per_1k_tokens', 0) * 0.1 / 1000
        return result.strip()

    def _rule_compress(self, text: str) -> str:
        """Rule-based compression: extract first sentence + confidence."""
        import re

        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 10]

        if not sentences:
            return text[:self.target_tokens * 4]

        # First sentence = main claim
        result = sentences[0]

        # Find confidence mention
        for s in sentences:
            if any(w in s.lower() for w in ["confidence", "%", "confident"]):
                if s != sentences[0]:
                    result += ". " + s
                break

        # Truncate to target
        max_chars = self.target_tokens * 4
        if len(result) > max_chars:
            result = result[:max_chars].rsplit(" ", 1)[0] + "..."

        return result

    def _create_compressed(self, original: Message, compressed_content: str) -> Message:
        """Create new message with compressed content."""
        return Message(
            source_node_id=original.source_node_id,
            target_node_id=original.target_node_id,
            round=original.round,
            content=compressed_content,
            reasoning_type=original.reasoning_type,
            confidence=original.confidence,
            evidence=original.evidence,
        )

    @property
    def compression_cost(self) -> float:
        return self._cost
