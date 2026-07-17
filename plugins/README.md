# GraQle Plugin Bundles

Repo-scoped plugin bundles for AI coding agents.

| Bundle | Client | Install |
|---|---|---|
| [`claude-code/graqle/`](claude-code/graqle/) | Claude Code | `/plugin marketplace add quantamixsol/graqle` → `/plugin install graqle@graqle` |
| [`codex/graqle/`](codex/graqle/) | OpenAI Codex CLI | repo-scoped marketplace add, or `graq mcp install codex` |

Both bundles expose the GraQle MCP server over stdio (`graq mcp serve`) and ship
the same workflow skills (`governed-bug-fix`, `graph-onboard`).

**Prerequisite:** `pip install graqle` (the bundles are thin clients over the
installed SDK — they contain no SDK code).

The official MCP Registry listing is `io.github.quantamixsol/graqle` (manifest:
`server.json` at the repo root).
