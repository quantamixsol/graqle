"""TokenOptimizer — reduce token usage in message passing.

Inspired by OPTIMA (ACL 2025): agents learn to communicate efficiently.
The reward function balances task performance vs token cost:
    R(τ) = R_task - λ_token * R_token + λ_loss * (1/R_loss)

This module provides rule-based token optimization that doesn't require
training. For OPTIMA-style learned optimization, use with DPO training.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from graqle.core.message import Message

logger = logging.getLogger("graqle.optimization")


@dataclass
class OptimizationStats:
    """Token optimization statistics."""

    original_tokens: int = 0
    optimized_tokens: int = 0
    messages_processed: int = 0

    @property
    def reduction_pct(self) -> float:
        if self.original_tokens == 0:
            return 0.0
        return 1.0 - (self.optimized_tokens / self.original_tokens)

    @property
    def tokens_saved(self) -> int:
        return self.original_tokens - self.optimized_tokens


class TokenOptimizer:
    """Reduce message token count through compression techniques.

    Techniques:
    1. Redundancy removal: skip messages that overlap >70% with existing context
    2. Key-claim extraction: keep only essential claims from verbose messages
    3. Context window packing: fit maximum info into minimum tokens
    4. Confidence filtering: drop low-confidence messages (noise)
    """

    def __init__(
        self,
        *,
        max_context_tokens: int = 2048,
        min_confidence: float = 0.3,
        redundancy_threshold: float = 0.7,
        enable_compression: bool = True,
    ) -> None:
        self.max_context_tokens = max_context_tokens
        self.min_confidence = min_confidence
        self.redundancy_threshold = redundancy_threshold
        self.enable_compression = enable_compression
        self.stats = OptimizationStats()

    def optimize_context(
        self, messages: list[Message], query: str = ""
    ) -> list[Message]:
        """Optimize a list of messages for minimal token usage.

        Returns filtered and compressed messages.
        """
        if not messages:
            return messages

        # 1. Confidence filtering
        filtered = [m for m in messages if m.confidence >= self.min_confidence]

        # 2. Redundancy removal
        deduplicated = self._remove_redundant(filtered)

        # 3. Sort by relevance (confidence * recency)
        deduplicated.sort(key=lambda m: m.confidence, reverse=True)

        # 4. Token budget enforcement
        budgeted = self._enforce_budget(deduplicated)

        # Track stats
        orig_tokens = sum(self._estimate_tokens(m.content) for m in messages)
        opt_tokens = sum(self._estimate_tokens(m.content) for m in budgeted)
        self.stats.original_tokens += orig_tokens
        self.stats.optimized_tokens += opt_tokens
        self.stats.messages_processed += len(messages)

        return budgeted

    def compress_message(self, message: Message) -> Message:
        """Compress a single message by extracting key claims."""
        if not self.enable_compression:
            return message

        content = message.content
        tokens = self._estimate_tokens(content)

        # Only compress if over threshold
        if tokens <= 100:
            return message

        compressed = self._extract_key_claims(content)
        new_msg = Message(
            source_node_id=message.source_node_id,
            target_node_id=message.target_node_id,
            round=message.round,
            content=compressed,
            reasoning_type=message.reasoning_type,
            confidence=message.confidence,
            evidence=message.evidence,
        )
        return new_msg

    def _remove_redundant(self, messages: list[Message]) -> list[Message]:
        """Remove messages that substantially overlap with others."""
        if len(messages) <= 1:
            return messages

        kept: list[Message] = [messages[0]]
        for msg in messages[1:]:
            is_redundant = False
            for existing in kept:
                overlap = self._text_overlap(msg.content, existing.content)
                if overlap > self.redundancy_threshold:
                    is_redundant = True
                    # Keep the higher-confidence version
                    if msg.confidence > existing.confidence:
                        kept.remove(existing)
                        kept.append(msg)
                    break
            if not is_redundant:
                kept.append(msg)
        return kept

    def _enforce_budget(self, messages: list[Message]) -> list[Message]:
        """Keep messages within the token budget."""
        total = 0
        result: list[Message] = []
        for msg in messages:
            tokens = self._estimate_tokens(msg.content)
            if total + tokens > self.max_context_tokens:
                # Try compression first
                compressed = self.compress_message(msg)
                comp_tokens = self._estimate_tokens(compressed.content)
                if total + comp_tokens <= self.max_context_tokens:
                    result.append(compressed)
                    total += comp_tokens
                else:
                    break  # budget exhausted
            else:
                result.append(msg)
                total += tokens
        return result

    def _extract_key_claims(self, text: str) -> str:
        """Extract key claims from verbose text."""
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]

        if len(sentences) <= 2:
            return text

        # Keep first sentence (usually the claim) + any with confidence/numbers
        key_sentences = [sentences[0]]
        for s in sentences[1:]:
            # Keep sentences with quantitative info or strong claims
            if any(indicator in s.lower() for indicator in [
                "confidence", "%", "key", "important", "critical",
                "therefore", "conclude", "finding", "result",
                "evidence", "data", "shows",
            ]):
                key_sentences.append(s)

        # Keep at most 3 key sentences
        return ". ".join(key_sentences[:3]) + "."

    @staticmethod
    def _text_overlap(text_a: str, text_b: str) -> float:
        """Word-level overlap ratio."""
        words_a = set(text_a.lower().split())
        words_b = set(text_b.lower().split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        return len(intersection) / min(len(words_a), len(words_b))

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimate (~4 chars per token)."""
        return max(1, len(text) // 4)
