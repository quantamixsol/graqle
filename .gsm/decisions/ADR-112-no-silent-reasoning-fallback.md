# ADR-112: No Silent Reasoning Fallback in graq_reason
**Date:** 2026-03-24 | **Status:** ACCEPTED

## Context
`graq_reason` was falling back to keyword-match graph traversal when the LLM backend failed.
This produced results with `mode: "fallback_traversal"` and `confidence: 0.5` — visually
indistinguishable from real multi-hop reasoning. Users (and Claude Code) had no way to know
reasoning was broken. The entire value proposition of Graqle — graph-of-agents LLM reasoning —
was silently not working.

Root cause discovered during Phantom self-audit (2026-03-23): Bedrock backend was misconfigured
(wrong region, missing credentials in MCP subprocess env), causing `areason()` to throw
`RuntimeError: No backend assigned`. The catch block silently swallowed the error and ran
keyword traversal instead.

## Decision
`graq_reason` returns a **hard error** (`"error": "REASONING_BACKEND_UNAVAILABLE"`) when
the LLM backend fails. No keyword fallback. No silent degradation.

`graq_inspect` remains available for keyword-based node lookup when that's what's needed.

## Consequences
**Positive:**
- Users immediately know when reasoning is broken
- No false confidence — `confidence: 0.5` from keyword match is meaningless and misleading
- Forces correct backend configuration instead of hiding misconfigs
- Preserves the integrity of the Graqle value proposition

**Negative:**
- `graq_reason` calls fail hard until backend is fixed (acceptable — better than silent lies)
- Requires users to have a valid backend configured (expected behavior)

## Implementation
- `graqle/plugins/mcp_dev_server.py`: replaced fallback block with hard `REASONING_BACKEND_UNAVAILABLE` error
- `graqle.yaml`: `backend: bedrock`, `model: eu.anthropic.claude-sonnet-4-6`, `region: eu-central-1`
- `.mcp.json`: `AWS_DEFAULT_REGION: eu-central-1` in env passthrough
- `graqle/core/graph.py`: `_auto_create_backend` reads `region` from config first

## Fix for broken backend
```bash
graq doctor          # diagnose
# Edit graqle.yaml:
# model:
#   backend: bedrock
#   model: eu.anthropic.claude-sonnet-4-6
#   region: eu-central-1
# Then reload Claude Code
```
