# Try Graqle in 60 Seconds

> Turn any codebase into a knowledge graph. Query your architecture, not your files.

## Step 1: Install

```bash
pip install graqle
```

## Step 2: Scan Your Project

```bash
cd your-project
graq scan repo .
```

This builds a knowledge graph from your codebase — modules, dependencies, risk levels, everything.

## Step 3: Ask Questions

```bash
graq run "what are the most coupled modules in this codebase?"
graq run "what breaks if I change the auth module?"
graq run "show me architectural hotspots"
```

## Step 4: Add to Claude Code (MCP)

```bash
graq mcp serve
```

Then add to your Claude Code settings (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "graqle": {
      "command": "graq",
      "args": ["mcp", "serve"]
    }
  }
}
```

Now Claude Code has 7 new tools: `graq_context`, `graq_reason`, `graq_impact`, `graq_preflight`, `graq_lessons`, `graq_learn`, `graq_inspect`.

## Step 5: Try It

In Claude Code, just ask:

```
"Use graqle to analyze what would break if I refactor the database layer"
"Use graq_impact on the auth module"
"Run graq_preflight before I change the API routes"
```

## Optional: Launch the Studio Dashboard

```bash
graq serve --port 8077
# Open http://localhost:3000 (if running graqle-studio frontend)
# Or visit https://graqle.com/dashboard
```

## Optional: Companion Plugins

```bash
graq plugins list                        # See available plugins
graq plugins install superpowers         # TDD + code review methodology
graq plugins install ui-ux-promax        # Design intelligence (57 styles, 95 palettes)
```

## What You Get

- **Knowledge Graph** — every module, function, dependency mapped
- **Risk Scoring** — LOW/MEDIUM/HIGH/CRITICAL per module
- **Impact Analysis** — "if I change X, what breaks?"
- **Preflight Checks** — safety warnings before you code
- **Lessons** — past mistakes surfaced before you repeat them
- **Self-Evolving** — `graq learn` teaches the graph new concepts

## Links

- PyPI: https://pypi.org/project/graqle/
- GitHub: https://github.com/quantamixsol/graqle
- Studio: https://graqle.com

---

*Built by [Quantamix Solutions](https://github.com/quantamixsol). Apache 2.0 licensed.*
