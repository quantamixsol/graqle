# ADR-114: graq_generate stream=True Parameter
**Date:** 2026-03-27 | **Status:** ACCEPTED
**Branch:** feature-coding-assistant | **Phase:** T3.4

## Context
graq_generate needed streaming support so callers can receive incremental output. The challenge: MCP stdio uses request-response (not SSE), so true per-token streaming to the client isn't possible. But backends should still exercise their streaming paths for correctness and future-proofing.

## Decision
Add `stream: bool = False` to `graq_generate`. When `stream=True`:
1. Call `graph.areason_stream()` → collect all chunks into `metadata.chunks: list[str]`
2. Also call `graph.areason()` → get structured fields (confidence, active_nodes, cost_usd)
3. Return both in the same `CodeGenerationResult` response

## Rationale
- **Backend-agnostic**: All 14 backends work — Anthropic yields native tokens, others yield single chunk via `BaseBackend.agenerate_stream()` default (ADR-113)
- **No transport breakage**: MCP stdio stays request-response; chunks are returned in the JSON body
- **Additive-only**: `stream=False` is the default — zero regressions for existing callers
- **Testable without API key**: MockBackend word-by-word streaming validates the full path

## Consequences
- **Positive:** All backends exercise their streaming code path
- **Positive:** Clients can choose to render chunks progressively (join them) or use the single `answer` field
- **Negative:** When `stream=True`, the backend is called TWICE (stream + reason). Acceptable for Phase 3.
- **Future:** Phase 4+ CLI / Studio can use Server-Sent Events with true single-pass streaming

## Rule
When patching `load_credentials` in `_handle_generate` tests: patch `graqle.cloud.credentials.load_credentials` (the import source), NOT `graqle.plugins.mcp_dev_server.load_credentials` (local import — not on module).
