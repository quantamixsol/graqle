# CogniGraph MCP Integration for Claude Code

CogniGraph exposes a Model Context Protocol (MCP) server that gives Claude Code
graph-powered context engineering tools. Instead of reading large flat files
(20-60K tokens), Claude Code calls CogniGraph tools to get focused, governed
context in 300-500 tokens.

---

## Prerequisites

- Python 3.10 or later
- pip (or uv/pipx)
- A project with source code to scan

Install CogniGraph:

```bash
pip install cognigraph
```

Verify the CLI is available:

```bash
kogni version
```

---

## Quick Setup

Run `kogni init` in your project root. This is the recommended approach -- it
creates all configuration files in one step:

```bash
cd /path/to/your/project
kogni init
```

The interactive wizard will:

1. Ask you to choose a backend (Anthropic, OpenAI, Bedrock, or custom)
2. Ask you to pick a model
3. Ask for API key configuration

It then automatically creates:

| File | Purpose |
|------|---------|
| `cognigraph.yaml` | Model backend, graph connector, activation strategy |
| `cognigraph.json` | Knowledge graph (built from repository scan) |
| `.mcp.json` | MCP server registration for Claude Code |
| `CLAUDE.md` | Governance protocols (GCC, GSD, Ralph Loop) |
| `.gcc/` | Context controller directory structure |

After `kogni init` completes, restart Claude Code (or reload MCP servers) and
the `cognigraph` tools will be available.

### Non-interactive setup

For CI or scripted environments:

```bash
kogni init --backend anthropic \
           --model claude-haiku-4-5-20251001 \
           --api-key-env ANTHROPIC_API_KEY \
           --no-interactive
```

---

## Manual Setup

If you already have a project configured and only need the MCP integration,
add the server entry to your `.mcp.json` (project-level) or Claude Code's
global MCP configuration.

### Project-level `.mcp.json`

Create or edit `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "cognigraph": {
      "type": "stdio",
      "command": "kogni",
      "args": ["mcp", "serve", "--config", "cognigraph.yaml"]
    }
  }
}
```

If `.mcp.json` already exists with other servers, add the `"cognigraph"` key
inside the existing `"mcpServers"` object.

### Minimal configuration (default config path)

If your `cognigraph.yaml` is in the project root, you can omit the config flag:

```json
{
  "mcpServers": {
    "cognigraph": {
      "command": "kogni",
      "args": ["mcp", "serve"]
    }
  }
}
```

### What you need alongside `.mcp.json`

The MCP server expects:

1. **`cognigraph.yaml`** -- model and graph configuration. Created by `kogni init`
   or manually:

   ```yaml
   model:
     backend: anthropic
     model: claude-haiku-4-5-20251001
     api_key: ${ANTHROPIC_API_KEY}
   graph:
     connector: networkx
   activation:
     strategy: pcst
     max_nodes: 20
   orchestration:
     max_rounds: 3
     convergence_threshold: 0.92
   ```

2. **`cognigraph.json`** -- the knowledge graph. Generate it with:

   ```bash
   kogni scan repo .
   ```

   Or let `kogni init` create it during setup.

---

## Available Tools

The MCP server exposes 7 tools over JSON-RPC stdio transport. Three are
available in the Free tier; four require a Pro license.

| # | Tool | Description | Tier |
|---|------|-------------|------|
| 1 | `kogni_context` | Smart context loading for session start. Returns relevant KG nodes, active branch info, and applicable lessons in ~300-500 tokens. | Free |
| 2 | `kogni_inspect` | Inspect the project knowledge graph structure. Show nodes, edges, stats, or details for a specific node. | Free |
| 3 | `kogni_reason` | Graph-of-agents reasoning. Each relevant node becomes an agent; they exchange messages and produce a synthesized answer. | Free |
| 4 | `kogni_preflight` | Governance preflight check before code changes. Returns relevant lessons, past mistakes, ADRs, and safety boundary warnings. | Pro |
| 5 | `kogni_lessons` | Query lessons and past mistakes relevant to a specific operation. Filters by severity. | Pro |
| 6 | `kogni_impact` | Trace downstream impact of a proposed change through the dependency graph. Shows affected components and risk levels. | Pro |
| 7 | `kogni_learn` | Record a development outcome for Bayesian graph learning. Strengthens or weakens edges based on results. | Pro |

---

## Usage Examples

Below are examples of how Claude Code invokes each tool through the MCP
protocol. These are the JSON arguments passed to each tool call.

### kogni_context (Free)

Load focused context at session start:

```json
{
  "task": "Fix the authentication Lambda",
  "level": "standard"
}
```

`level` options: `"minimal"` (~200 tokens), `"standard"` (~400 tokens),
`"deep"` (~800 tokens).

### kogni_inspect (Free)

Get graph statistics:

```json
{
  "stats": true
}
```

Inspect a specific node:

```json
{
  "node_id": "auth-lambda"
}
```

### kogni_reason (Free)

Run a reasoning query over the knowledge graph:

```json
{
  "question": "What services depend on the payments API?",
  "max_rounds": 3
}
```

`max_rounds` controls message-passing depth (1-5, default 2).

### kogni_preflight (Pro)

Check governance constraints before making changes:

```json
{
  "action": "Add CORS headers to the signup Lambda",
  "files": ["lambdas/signup/handler.py"]
}
```

### kogni_lessons (Pro)

Find relevant past mistakes:

```json
{
  "operation": "database migration",
  "severity_filter": "critical"
}
```

`severity_filter` options: `"all"`, `"critical"`, `"high"` (default).

### kogni_impact (Pro)

Trace downstream effects of a change:

```json
{
  "component": "cognito-user-pool",
  "change_type": "modify"
}
```

`change_type` options: `"modify"`, `"add"`, `"remove"`, `"deploy"`.

### kogni_learn (Pro)

Record an outcome after completing work:

```json
{
  "action": "Migrated auth from JWT to session tokens",
  "outcome": "success",
  "components": ["auth-lambda", "frontend-auth-hook", "cognito"],
  "lesson": "Session tokens require SameSite=None for cross-origin iframes"
}
```

`outcome` options: `"success"`, `"failure"`, `"partial"`.

---

## Troubleshooting

### "No graph found" or empty results

The MCP server auto-discovers graph files in this order:
`cognigraph.json`, `knowledge_graph.json`, `graph.json`.

If none exist, run:

```bash
kogni scan repo .
```

This scans your repository and writes `cognigraph.json`.

### Pro tools return license errors

Tools 4-7 (`kogni_preflight`, `kogni_lessons`, `kogni_impact`, `kogni_learn`)
require a Pro license. Without one, calling these tools returns an error
message explaining which feature is gated. The 3 Free tools work without
any license.

### `kogni` command not found

The `kogni` CLI is installed as a console script by pip. Common fixes:

- Ensure the package is installed in the same Python environment that your
  shell uses: `pip install cognigraph`
- If using a virtual environment, activate it before starting Claude Code,
  or use the full path to the `kogni` binary in `.mcp.json`:

  ```json
  {
    "mcpServers": {
      "cognigraph": {
        "command": "/path/to/venv/bin/kogni",
        "args": ["mcp", "serve"]
      }
    }
  }
  ```

- On Windows, the script may be at `Scripts\kogni.exe` inside your venv.

### MCP server starts but tools are not visible

1. Confirm `.mcp.json` is in the project root (the directory you opened in
   Claude Code).
2. Restart Claude Code or reload MCP servers after editing `.mcp.json`.
3. Check that `kogni mcp serve` runs without errors:

   ```bash
   kogni mcp serve --config cognigraph.yaml
   ```

   The server communicates over stdio. If it prints errors to stderr, those
   indicate configuration problems.

### Wrong Python version

CogniGraph requires Python 3.10+. Check with:

```bash
python --version
```

If your system Python is older, use `pyenv`, `conda`, or a virtual environment
with the correct version.

### Graph is stale after code changes

Re-scan the repository to rebuild the knowledge graph:

```bash
kogni scan repo .
```

Then restart the MCP server (Claude Code does this automatically when it
re-reads `.mcp.json`).
