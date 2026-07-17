---
name: governed-bug-fix
description: Fix a bug through GraQle's governed workflow — investigate with the knowledge graph, check blast radius, plan, generate a reviewed diff, and teach the outcome back to the graph. Use when fixing bugs in a repository that has a GraQle knowledge graph (graqle.json / graqle.yaml present) and the GraQle MCP server connected.
---

# Governed Bug Fix (GraQle)

Fix bugs through GraQle's governance chain instead of ad-hoc editing. Every phase
uses a GraQle MCP tool; run the phases in order and do not skip any.

1. **Boot** — `graq_lifecycle(event="session_start")` once per session. Loads graph
   status and past lessons relevant to your task.
2. **Investigate** — `graq_reason(question=<the exact symptom>)` to reason over the
   graph, then `graq_inspect` on the affected file or module.
3. **Blast radius** — `graq_safety_check(component=<file>)`. If risk comes back
   CRITICAL, stop and confirm with the user before touching anything.
4. **Plan** — `graq_plan(goal=..., scope=...)` to get a governance-gated execution
   plan before any file changes.
5. **Generate** — `graq_generate(..., dry_run=true)`; show the user the diff and get
   approval before applying.
6. **Apply** — `graq_edit(dry_run=false)`; prefer `strategy="literal"` for exact,
   deterministic replacements.
7. **Review** — `graq_review` on the applied change. Fix findings and re-review until
   it approves with no blockers.
8. **Learn** — `graq_learn(mode="outcome", action=..., outcome=..., lesson=...)`.
   Never skip this: the graph must learn from every fix.

Guidelines:
- Reads are never gated — prefer `graq_context` over reading many files manually.
- If a tool returns low confidence, re-ask with more context from earlier phases;
  don't silently fall back to manual reasoning.
- Batch related small fixes into one plan/review cycle rather than skipping phases.
