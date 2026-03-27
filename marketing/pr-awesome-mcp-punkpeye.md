# PR: punkpeye/awesome-mcp-servers — Add GraQle

## Target Repo
https://github.com/punkpeye/awesome-mcp-servers

## Category
**Developer Tools** or **Knowledge & Memory**

## Entry to Add

```markdown
- [graqle](https://github.com/quantamixsol/graqle) 🐍 🏠 🍎 🪟 🐧 - Architecture-aware code intelligence MCP server. Builds knowledge graphs from codebases for dependency analysis, impact analysis, institutional memory, and governed AI reasoning. 16 MCP tools including context, reason, impact, preflight, learn, inspect. 14 LLM backends, fully offline capable.
```

## PR Title
Add graqle — code intelligence MCP server with knowledge graphs

## PR Description

```markdown
## graqle MCP Server

**graqle** provides 16 MCP tools that give AI coding assistants architecture-aware reasoning:

| Tool | Purpose |
|------|---------|
| `graq_context` | Focused context for any module (~500 tokens) |
| `graq_reason` | Multi-agent graph reasoning |
| `graq_impact` | Blast-radius analysis before changes |
| `graq_preflight` | Pre-change safety checks |
| `graq_learn` | Teach the graph (institutional memory) |
| `graq_lessons` | Retrieve past mistake patterns |
| `graq_inspect` | Graph statistics |
| `graq_gate` | Quality gate verification |
| `graq_audit` | Full architecture audit |

Plus `kogni_*` aliases for all tools.

### Setup
```bash
pip install graqle
graq scan repo .
graq mcp serve
```

Or one-command IDE integration:
```bash
graq init              # Claude Code
graq init --ide cursor # Cursor
graq init --ide vscode # VS Code + Copilot
```

### Links
- PyPI: https://pypi.org/project/graqle/
- GitHub: https://github.com/quantamixsol/graqle
- Website: https://graqle.com
```

## How to Submit
1. Fork `punkpeye/awesome-mcp-servers`
2. Check CONTRIBUTING.md for specific format requirements
3. Add entry under **Developer Tools** category
4. Open PR
