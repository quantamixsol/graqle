# ADR-113: graq_predict as a Self-Validating Deployment Gate
**Date:** 2026-03-25 | **Status:** ACCEPTED
**Author:** SDK Team

---

## Context

Before shipping v0.34.0 (graq_predict Layer A + embedding dimension safety), we needed
a deployment gate that could reason about risk across 11 changed files simultaneously —
something neither unit tests nor manual code review could do cheaply.

The question was: can graq_predict validate its own deployment? Can the tool we're
shipping be used to decide whether it's safe to ship?

## Decision

We used `graq_predict` with `fold_back=False` (dry-run mode) as a **diff-driven
deployment gate**. For every changed file group in v0.34.0, we ran a structured query
against the live knowledge graph and treated the `answer_confidence` score + reasoning
verdict as a binary ship/no-ship signal per change group.

### Protocol

1. Group changed files by concern (routing, embeddings, graph core, MCP server)
2. For each group, craft a query describing the exact diff and asking for regression risk
3. Run `graq_predict fold_back=False` — reasons over 4,892 nodes, returns `answer_confidence`
4. Gate: `answer_confidence >= 0.80` = CLEAR. Below = FLAG for human review.
5. Any FLAG blocks shipping until addressed.

### Results (v0.34.0)

| Group | Files | answer_confidence | Verdict |
|---|---|---|---|
| Routing + version bump | routing.py, __version__.py, pyproject.toml | 0.95 | ✅ CLEAR |
| Embedding engine properties | embeddings.py | 0.979 | ✅ CLEAR |
| Cache key + _meta (P0+P1) | graph.py | 0.842 | ✅ CLEAR |
| Load validation + matmul guard (P2+P4) | graph.py | 0.927 | ✅ CLEAR |
| graq_predict + _ensure_graph fix | mcp_server.py | 0.819 | ⚠️ FLAG → fixed |

Group 5 flagged that `_ensure_graph` is a shared code path and no test covered the
new `Graqle.from_json` return type. We added two regression tests and re-ran. All 5
groups cleared.

## Why This Works

graq_predict runs graph-of-agents reasoning where each relevant node becomes an agent
that reasons about the question and exchanges messages with neighbours. For a deployment
gate query, this means:

- `test_mcp_server.py` agent (92% confidence) knows which assertions exist
- `graph.py` agent (88%) knows the exact cache key format
- `mcp_dev_server.py` agent (90%) knows the dispatch table
- `routing.py` agent (91%) knows every existing tool-to-task mapping

No single code reviewer holds all of this simultaneously. The graph does.

## Consequences

**Positive:**
- Deployment gates are now graph-reasoned, not just unit-tested
- The tool validates itself before shipping — true dogfooding
- Flags are specific: "this shared code path has no test coverage" vs "looks fine"
- Cost: ~$0.37 total for all 5 gate checks (50 nodes × 2 rounds × 5 queries)

**Negative / Trade-offs:**
- Gate requires the MCP server to be running (adds setup cost to CI pipeline)
- `answer_confidence` threshold (0.80) is empirically set — needs calibration over time
- Graph must be current; stale graph = stale gate

## Related ADRs
- ADR-068 (GSD + Ralph Loop)
- ADR-106 (Gate+Rerank activation)
- ADR-112 (No silent reasoning fallback)
