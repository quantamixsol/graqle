# PR: awesome-python — Add GraQle

## Target Repo
https://github.com/vinta/awesome-python

## Category
**Code Analysis** (or **Developer Tools** if that exists)

## PR Title
Add graqle — architecture-aware code intelligence with knowledge graphs

## Entry to Add

Under **Code Analysis** section:

```markdown
- [graqle](https://github.com/quantamixsol/graqle) - Build a knowledge graph from any codebase for dependency analysis, impact analysis, and architecture-aware AI reasoning. 14 LLM backends, MCP server for Claude/Cursor/Copilot.
```

## PR Description

```markdown
## What is graqle?

[graqle](https://pypi.org/project/graqle/) is a Python SDK + CLI that builds a knowledge graph from any codebase. Instead of reading raw files, AI tools query the graph for precise, structured context — 500 tokens instead of 50,000.

### Key features
- `graq scan repo .` — builds a knowledge graph from any Python/JS/TS codebase
- `graq run "question"` — architecture-aware reasoning over the graph
- `graq impact auth.py` — full blast-radius analysis before changes
- `graq init` — MCP server with 16 tools for Claude Code, Cursor, VS Code Copilot
- 14 LLM backends (Anthropic, OpenAI, Ollama, Bedrock, Gemini, etc.)
- Fully offline capable (zero mandatory cloud dependencies)

### Why it qualifies
- **Active**: commits within last week, v0.31.3 on PyPI
- **Stable**: Production/Stable on PyPI, 2,000+ tests passing
- **Documented**: comprehensive README with examples, CLI reference, SDK docs
- **Unique**: only tool that combines knowledge graphs + MCP + multi-agent reasoning for code analysis
- **Python-first**: 100% Python SDK

### Links
- PyPI: https://pypi.org/project/graqle/
- GitHub: https://github.com/quantamixsol/graqle
- Website: https://graqle.com
- Patent: EP26162901.8 (European Patent Office)
```

## How to Submit
1. Fork `vinta/awesome-python`
2. Edit `README.md`
3. Find the **Code Analysis** section
4. Add the entry in alphabetical order
5. Open PR with the description above
