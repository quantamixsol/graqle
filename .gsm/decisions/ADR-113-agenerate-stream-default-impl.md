# ADR-113: agenerate_stream() Default Implementation in BaseBackend
**Date:** 2026-03-27 | **Status:** ACCEPTED
**Branch:** feature-coding-assistant | **Phase:** T3.1

## Context
graq_generate Phase 3 needs streaming support. All 14 backends need to be streaming-compatible without code changes to each.

## Decision
Add `agenerate_stream()` as a non-abstract method on `BaseBackend` with a default implementation that calls `self.generate()` and yields the result as a single chunk.

## Rationale
- All 14 existing backends inherit the default — zero changes required
- Only backends with native streaming support (Anthropic, Mock) override it
- If a backend's native streaming fails, it falls back to single-chunk via `generate()` — graq_generate never breaks
- Python async generators compose cleanly: `async for chunk in backend.agenerate_stream(...):`

## Consequences
- **Positive:** Backward compatibility for all 14 backends guaranteed — additive-only
- **Positive:** MockBackend word-by-word streaming enables real streaming tests without API key
- **Positive:** AnthropicBackend uses `client.messages.stream()` for true token streaming
- **Negative:** Backends that don't override get single-chunk "streaming" — acceptable for Phase 3
- **Future:** OpenAI, Bedrock, Gemini can add real streaming overrides in Phase 4+

## Rule
NEVER make `agenerate_stream()` abstract — it would break all 14 existing backends.
