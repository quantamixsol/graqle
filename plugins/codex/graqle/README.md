# GraQle — Codex Plugin

> Query your architecture, not your files.

Graph-powered codebase reasoning, impact analysis, and governed edits for the
OpenAI Codex CLI, backed by the [GraQle SDK](https://github.com/quantamixsol/graqle).

## Install

```
pip install graqle          # prerequisite (provides `graq`)
graq mcp install codex      # registers the GraQle MCP server with Codex
graq mcp doctor codex       # verify: registered -> enabled -> server starts -> tools/list
```

Or add this repository as a repo-scoped plugin marketplace (see
`.agents/plugins/marketplace.json` at the repo root) and install the `graqle`
plugin from it.

## What you get

- **MCP server** (`graq mcp serve`, stdio) — `graq_context`, `graq_reason`,
  `graq_impact`, `graq_inspect`, `graq_lessons`, `graq_learn`, `graq_graph_health`
  and the wider `graq_*` tool family for graph-powered reasoning over your repo.
- **Skills** — `governed-bug-fix` (fix bugs through GraQle's governed workflow)
  and `graph-onboard` (scan a repo into a knowledge graph and ask it questions).

## Governance note

Codex has no pre-tool-call hook mechanism equivalent to Claude Code's PreToolUse,
so GraQle's client-side governance gate is not packaged here — following the
workflow skills is advisory. GraQle's own governance (patent scan, edit gates,
protected paths, audit logging) runs **inside** the `graq_*` tools and applies
regardless of client.

## First run

If the repo has no `graqle.json` yet, use the `graph-onboard` skill or run
`graq scan repo .` once. Verify the full chain with `graq mcp doctor codex`.
