"""
tests/test_backends/test_streaming.py
T3.1 + T3.3 — Tests for agenerate_stream() on BaseBackend and MockBackend.
6 tests. No API key required — MockBackend only.
"""
from __future__ import annotations

import pytest

from graqle.backends.mock import MockBackend


class TestBaseBackendStreamingDefault:
    """BaseBackend default: yields full result as single chunk."""

    @pytest.mark.asyncio
    async def test_default_yields_at_least_one_chunk(self) -> None:
        backend = MockBackend(response="hello world")
        chunks = [chunk async for chunk in backend.agenerate_stream("test")]
        assert len(chunks) >= 1

    @pytest.mark.asyncio
    async def test_default_chunks_join_to_full_response(self) -> None:
        response = "The quick brown fox"
        backend = MockBackend(response=response)
        chunks = [chunk async for chunk in backend.agenerate_stream("test")]
        assert "".join(chunks) == response


class TestMockBackendStreaming:
    """MockBackend: word-by-word streaming."""

    @pytest.mark.asyncio
    async def test_multiple_chunks_for_multi_word_response(self) -> None:
        response = "one two three four five six seven"
        backend = MockBackend(response=response)
        chunks = [chunk async for chunk in backend.agenerate_stream("test")]
        assert len(chunks) >= 2

    @pytest.mark.asyncio
    async def test_chunks_reassemble_to_original(self) -> None:
        response = "add docstring to SyncEngine class"
        backend = MockBackend(response=response)
        chunks = [chunk async for chunk in backend.agenerate_stream("generate")]
        assert "".join(chunks) == response

    @pytest.mark.asyncio
    async def test_ten_plus_chunks_for_long_response(self) -> None:
        """Plan criterion: MockBackend yields 10+ chunks for a 50-word response."""
        response = " ".join(["word"] * 50)
        backend = MockBackend(response=response)
        chunks = [chunk async for chunk in backend.agenerate_stream("long test")]
        assert len(chunks) >= 10

    @pytest.mark.asyncio
    async def test_single_word_response_yields_one_chunk(self) -> None:
        backend = MockBackend(response="hello")
        chunks = [chunk async for chunk in backend.agenerate_stream("test")]
        assert len(chunks) == 1
        assert chunks[0] == "hello"
