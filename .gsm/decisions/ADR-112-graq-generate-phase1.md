# ADR-112: graq_generate Phase 1 — Generation via graph.areason()
**Date:** 2026-03-27 | **Status:** ACCEPTED
**Branch:** feature-coding-assistant | **Phase:** T1.3

## Context
Phase 1 of the governed coding assistant needs `graq_generate` to produce a unified diff using the knowledge graph. The question is whether to call the backend directly or route through `graph.areason()`.

## Decision
Route through `graph.areason()` with a structured generation prompt that instructs the LLM to output a unified diff.

## Rationale
- `graph.areason()` activates context (PCST node selection) before the LLM call — the diff benefits from focused graph context
- Reuses the existing backend abstraction (all 14 backends, BYOK, air-gapped Ollama)
- Reuses error handling, governance audit logging, and metrics push already in `_handle_reason()`
- The LLM is instructed to produce `--- a/... +++ b/... @@ ...` format, then we parse lines_added/removed

## Consequences
- **Positive:** Full graph context before generation — aware of dependencies, callers, impact radius
- **Positive:** No new backend abstraction needed in Phase 1
- **Negative:** The diff quality depends on the LLM following the prompt format. Phase 3 will add `agenerate_stream()` for proper structured generation
- **Future:** Phase 2 (`graq_edit`) will apply the diff atomically. Phase 3 will stream the diff chunks.

## Enforcement
`_handle_generate()` must NEVER skip preflight. The preflight call is unconditional.
