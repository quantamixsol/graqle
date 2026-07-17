# GraQle — Claude Code Plugin

> Query your architecture, not your files.

Graph-powered codebase reasoning, impact analysis, and governed edits for Claude
Code, backed by the [GraQle SDK](https://github.com/quantamixsol/graqle).

## Install

```
pip install graqle                                   # prerequisite (provides `graq`)
/plugin marketplace add quantamixsol/graqle          # in Claude Code
/plugin install graqle@graqle
```

## What you get

- **MCP server** (`graq mcp serve`, stdio) — `graq_context`, `graq_reason`,
  `graq_impact`, `graq_inspect`, `graq_lessons`, `graq_learn`, `graq_graph_health`
  and the wider `graq_*` tool family for graph-powered reasoning over your repo.
- **Skills** — `governed-bug-fix` (fix bugs through GraQle's governed workflow)
  and `graph-onboard` (scan a repo into a knowledge graph and ask it questions).
- **Governance gate hook** (optional) — a PreToolUse hook that steers native
  file/shell tools toward their governed `graq_*` equivalents.

## Governance gate modes

> ⚠️ **The default install is ADVISORY-ONLY.** In the default `warn` mode the
> gate prints guidance to stderr and **never blocks any tool call**. Fail-closed
> enforcement is an explicit opt-in (`GRAQLE_GATE_MODE=enforce`). Enforcement is
> opt-in because a plugin hook activates for everyone who installs the plugin,
> and blocking native tools by default would break first-run for new users.

| Setting | Behavior |
|---|---|
| `GRAQLE_GATE_MODE=warn` (default) | Advisory stderr notice; all tools allowed |
| `GRAQLE_GATE_MODE=enforce` | Fail-closed: native tools with `graq_*` equivalents are blocked (exit 2), including on malformed hook payloads |
| `GRAQLE_GATE_MODE=off` | Gate disabled |
| `GRAQLE_CLIENT_MODE=vscode` | Bypass for the GraQle VS Code extension (honored in all modes, parity with `graq gate-install`). An env-declared client signal, not a security boundary — client-side gates are advisory; GraQle's server-side governance runs inside the `graq_*` tools regardless |

The hook invokes `python`. If your platform only provides `python3`, change the
command in `hooks/hooks.json` to:

```json
{ "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/graqle-gate.py\"" }
```

A missing interpreter never blocks tool use — the hook fails open as a
non-blocking hook error.

## First run

If the repo has no `graqle.json` yet, use the `graph-onboard` skill or run
`graq scan repo .` once. See [QUICKSTART](../../../QUICKSTART.md) for details.
