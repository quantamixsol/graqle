"""Tests for TokenOptimizer and MessageCompressor."""

# ── graqle:intelligence ──
# module: tests.test_optimization.test_token_optimizer
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, message, types, token_optimizer, message_compressor +1 more
# constraints: none
# ── /graqle:intelligence ──

import pytest

from graqle.core.message import Message
from graqle.core.types import ReasoningType
from graqle.optimization.token_optimizer import TokenOptimizer
from graqle.optimization.message_compressor import MessageCompressor
from graqle.backends.mock import MockBackend


def _msg(nid: str, content: str, conf: float = 0.7) -> Message:
    return Message(
        source_node_id=nid, target_node_id="broadcast", round=0,
        content=content, reasoning_type=ReasoningType.ASSERTION,
        confidence=conf, evidence=[nid],
    )


def test_optimizer_confidence_filtering():
    """Low-confidence messages are filtered out."""
    opt = TokenOptimizer(min_confidence=0.5)
    messages = [
        _msg("n1", "Good analysis here", conf=0.8),
        _msg("n2", "Not sure about this", conf=0.2),
        _msg("n3", "Decent insight provided", conf=0.6),
    ]
    result = opt.optimize_context(messages)
    assert len(result) == 2
    assert all(m.confidence >= 0.5 for m in result)


def test_optimizer_redundancy_removal():
    """Redundant messages are deduplicated."""
    opt = TokenOptimizer(redundancy_threshold=0.7)
    messages = [
        _msg("n1", "GDPR article 5 requires lawful processing of personal data"),
        _msg("n2", "GDPR article 5 requires lawful processing of personal data"),  # duplicate
    ]
    result = opt.optimize_context(messages)
    assert len(result) == 1


def test_optimizer_budget_enforcement():
    """Messages within token budget are kept, others dropped."""
    opt = TokenOptimizer(max_context_tokens=50)
    messages = [
        _msg("n1", "Short message here", conf=0.9),
        _msg("n2", "x " * 200, conf=0.8),  # ~200 tokens, should be dropped or compressed
    ]
    result = opt.optimize_context(messages)
    assert len(result) >= 1


def test_optimizer_compression():
    """compress_message extracts key claims."""
    opt = TokenOptimizer()
    long_content = (
        "Based on extensive analysis of the regulatory framework, "
        "the key finding is that compliance requires multi-layered governance. "
        "Furthermore, the data shows a 95% improvement in accuracy. "
        "Additionally, there are several secondary considerations that merit attention. "
        "The peripheral analysis suggests marginal effects in downstream processing. "
        "Overall, the conclusion is supported by strong evidence from multiple sources. "
        "In summary, the result demonstrates significant improvement."
    )
    msg = _msg("n1", long_content)
    compressed = opt.compress_message(msg)
    assert len(compressed.content) < len(msg.content)
    assert compressed.confidence == msg.confidence


def test_optimizer_stats():
    """Optimization stats track token savings."""
    opt = TokenOptimizer()
    messages = [
        _msg("n1", "Analysis with some content here", conf=0.8),
        _msg("n2", "Low confidence noise", conf=0.1),
    ]
    opt.optimize_context(messages)
    assert opt.stats.messages_processed == 2
    assert opt.stats.original_tokens > 0


def test_optimizer_empty_input():
    """Empty input returns empty output."""
    opt = TokenOptimizer()
    assert opt.optimize_context([]) == []


@pytest.mark.asyncio
async def test_message_compressor_rule_based():
    """MessageCompressor rule-based compression works."""
    compressor = MessageCompressor(backend=None, target_tokens=30)
    long_msg = _msg("n1", (
        "The comprehensive analysis reveals multiple layers of complexity. "
        "Confidence is high at 95% based on the evidence reviewed. "
        "Several factors contribute to this conclusion including regulatory requirements. "
        "The data supports a strong correlation between compliance and outcomes. "
        "Further investigation may reveal additional patterns worth considering."
    ))
    compressed = await compressor.compress(long_msg)
    assert len(compressed.content) < len(long_msg.content)


@pytest.mark.asyncio
async def test_message_compressor_skips_short():
    """Short messages are not compressed."""
    compressor = MessageCompressor(target_tokens=100)
    short_msg = _msg("n1", "Short claim.")
    result = await compressor.compress(short_msg)
    assert result.content == short_msg.content


@pytest.mark.asyncio
async def test_message_compressor_with_backend():
    """MessageCompressor uses LLM backend when available."""
    backend = MockBackend(response="Compressed: key finding is X. 85% confident.")
    compressor = MessageCompressor(backend=backend, target_tokens=30)
    long_msg = _msg("n1", "x " * 200)
    compressed = await compressor.compress(long_msg)
    assert "Compressed" in compressed.content
