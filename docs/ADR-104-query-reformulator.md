# ADR-104: Context-Aware Query Reformulator

**Date:** 2026-03-12 | **Status:** ACCEPTED
**Author:** Harish Kumar, Quantamix Solutions B.V.

## Context

Graqle receives raw user queries and uses them directly for PCST node activation (embedding → cosine similarity → prize assignment). This works well for clear, specific queries but degrades significantly for:

1. **Vague queries** — "what does this do?" produces unfocused embeddings
2. **Follow-up questions** — "and what about that service?" loses conversational referent
3. **Multimodal inputs** — screenshots, error logs, and diagrams carry crucial context that a text-only query ignores
4. **Domain ambiguity** — "the database" could mean DynamoDB, Neo4j, or RDS depending on project context

**Key insight:** When Graqle runs inside an AI tool (Claude Code, Cursor, Codex), the tool already has rich conversation history, project context, and attachment descriptions. This context is **free** — the AI tool has already processed it. Graqle just needs to receive and use it.

## Decision

Implement a pluggable `QueryReformulator` that enhances raw queries before PCST activation, with three operating modes:

### Mode 1: AI Tool Mode (auto-hardened, zero extra cost)

When running inside Claude Code / Cursor / Codex (detected via environment variables), the AI tool passes a `ReformulationContext` containing:
- Chat history (recent conversation turns)
- Current file being edited
- Active symbols (functions/classes referenced)
- Attachments (screenshots, error logs, diagrams — pre-described by the AI's vision)
- Project summary

The reformulator applies four enhancement steps:

1. **Pronoun resolution** — "this", "it", "that" → concrete referent from chat history
2. **File context injection** — append current file if not mentioned
3. **Symbol grounding** — add active symbols not already in query
4. **Attachment injection** — weave screenshot/file descriptions into query text

**Cost: Zero.** All processing is string manipulation. No model calls.

### Mode 2: LLM Mode (standalone SDK, configurable)

For users running Graqle outside an AI tool (Python SDK, API, CI):
- Single lightweight model call (Haiku-class) to interpret and clarify
- Configurable backend via `reformulator.llm_backend` in YAML
- Prompt instructs model to return query unchanged if already clear
- Safety: reject responses >5x original length or wildly different

**Cost: ~$0.001 per query** (one Haiku call).

### Mode 3: Off (pass-through)

Set `reformulator.enabled: false` or `reformulator.mode: off` to bypass entirely.

### Auto-Detection

```python
_AI_TOOL_ENV_SIGNATURES = {
    "claude_code": ["CLAUDE_CODE", "CLAUDE_CODE_VERSION", "CLAUDE_PROJECT_DIR"],
    "cursor": ["CURSOR_SESSION_ID", "CURSOR_TRACE_ID"],
    "codex": ["OPENAI_CODEX", "CODEX_SESSION"],
    "windsurf": ["WINDSURF_SESSION"],
    "continue": ["CONTINUE_SESSION_ID"],
}
```

When `mode: "auto"` (default), the reformulator checks environment variables to detect the AI tool. If detected → AI Tool Mode. If not but a backend is configured → LLM Mode. Otherwise → pass-through.

### Multimodal Attachment Support

The `Attachment` dataclass supports:

| type | description | example |
|------|------------|---------|
| `screenshot` | UI/error screenshots | "Screenshot showing 500 error in auth Lambda logs" |
| `error_log` | Stack traces, log snippets | "TypeError: Cannot read property 'userId' of undefined" |
| `code_snippet` | Code blocks from chat | `async function handleAuth(req, res) { ... }` |
| `diagram` | Architecture/flow diagrams | "API Gateway → Lambda → DynamoDB flow" |
| `pdf` | Document attachments | "Deployment runbook for EU services" |
| `file` | Generic file reference | filename-only fallback |

The AI tool is responsible for pre-describing attachments (using vision/OCR). Graqle receives only the textual descriptions.

### Fail-Open Design

If reformulation fails for any reason (exception, timeout, bad response), the original query passes through unchanged. This is a non-breaking enhancement — never a blocker.

## Configuration

```yaml
reformulator:
  enabled: true          # Master switch
  mode: "auto"           # "auto", "ai_tool", "llm", "off"
  llm_backend: null      # Named model profile for LLM mode
  graph_summary: ""      # Brief KG description (helps LLM mode)
```

## Integration Points

- `Graqle.reason(query, context=...)` — accepts optional `ReformulationContext`
- `Graqle.areason(query, context=...)` — async version
- `Graqle.areason_stream(query, context=...)` — streaming version
- Reformulation happens in `_reformulate_query()` before `_activate_subgraph()`

## Consequences

### Positive
- Vague queries produce dramatically better PCST node activation
- Screenshots and error logs now inform node selection (impossible before)
- Follow-up questions correctly resolve to the discussed entity
- Zero additional cost when running inside an AI tool
- Fully backward compatible — existing code passes no context → no change
- AI tools don't need to format queries for Graqle — just pass context

### Negative
- AI Tool Mode adds ~1ms string processing latency (negligible)
- LLM Mode adds ~500-1500ms latency for a model call
- Context passing requires AI tool integration (MCP/plugin must send context)

### Trade-offs
- Reformulation max length capped at 500 chars to prevent PCST prize dilution
- Only first 3 attachments processed (more would bloat the query)
- LLM response >5x original length is rejected (safety against hallucination)
- Short queries (<10 chars) skip reformulation (likely commands, not questions)

## Test Coverage

49 tests in `tests/test_activation/test_reformulator.py`:
- 6 tests for AI tool environment detection
- 9 tests for context-based reformulation
- 6 tests for pronoun resolution
- 5 tests for attachment handling
- 3 tests for multimodal scenarios
- 5 tests for LLM-based reformulation
- 5 tests for pass-through/disabled modes
- 7 tests for edge cases
- 3 tests for graph integration

## References

- Patent EP26162901.8 — Innovation #1 (PCST Activation), Innovation #9 (Adaptive Activation)
- ADR-103 — Content-Aware PCST (predecessor, query flows into reformulated activation)
- `graqle/activation/reformulator.py` — Full implementation
- `graqle/config/settings.py` — ReformulatorConfig
- `graqle/core/graph.py` — Integration into reason() entry points
