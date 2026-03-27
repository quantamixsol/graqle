# Reddit Posts — GraQle

> **Rules:** No vote manipulation. No spam. Be genuine. Respond to every comment. Post to each sub only once. Wait 24-48h between posts to different subs.

---

## r/Python — "Show-off Sunday" or regular post

**Title:** I built a knowledge graph engine for codebases — gives AI tools architecture-aware reasoning (graqle on PyPI)

```
I've been working on GraQle, a Python SDK that builds knowledge graphs from codebases. The idea: instead of AI tools reading 60 files to answer "what depends on auth?", they query a graph and get a precise answer in 500 tokens.

**What it does:**
- `graq scan repo .` — builds a dependency graph from Python/JS/TS codebases
- `graq run "question"` — multi-agent reasoning over the graph
- `graq impact module.py` — full blast radius before you change anything
- `graq learn "lesson"` — institutional memory that persists across sessions
- `graq init` — one-command MCP server for Claude Code, Cursor, or VS Code

**The practical win:** A dependency question goes from ~50K tokens + 2 min to ~500 tokens + 5 sec.

**Tech stack:**
- Pure Python, NetworkX for the graph, Pydantic for models
- 14 LLM backends (Anthropic, OpenAI, Ollama, Bedrock, Gemini, etc.)
- Works fully offline with Ollama
- 2,000+ tests passing

Install: `pip install graqle`

GitHub: https://github.com/quantamixsol/graqle

Would love feedback from the Python community. What would you want a tool like this to understand about your codebase?
```

---

## r/programming

**Title:** Knowledge graphs for codebases: how reducing AI context from 50K to 500 tokens changes everything

```
I built GraQle because I noticed a pattern: AI coding tools spend most of their token budget reading files they don't need. A question like "what depends on the auth module?" triggers 60 file reads when a dependency graph answers it in one traversal.

GraQle builds a knowledge graph from your codebase (nodes = modules, edges = dependencies/imports/calls) and exposes it as an MCP server with 16 tools that any AI coding assistant can use.

The result: architecture questions cost ~500 tokens instead of ~50K. The graph persists across sessions, so your AI retains context between conversations.

Works with Claude Code, Cursor, VS Code Copilot. 14 LLM backends including fully offline options.

GitHub: https://github.com/quantamixsol/graqle
```

---

## r/MachineLearning

**Title:** [P] GraQle: Multi-agent graph reasoning over codebase knowledge graphs

```
Sharing a project that applies graph-based reasoning to code intelligence.

GraQle builds a knowledge graph from codebases (NetworkX-based) where modules are nodes and dependencies/imports/calls are edges. It then runs multi-agent reasoning over this graph using a task routing system that dispatches different query types to different LLM backends.

Architecture highlights:
- 8 task types routed to different providers via config
- Multiplicative gate+rerank activation for query routing
- Confidence scoring with evidence chains
- 14 backend providers (Anthropic, OpenAI, Ollama, Bedrock, etc.)
- MCP server exposes 16 tools for IDE integration

The graph structure captures: module dependencies, function call chains, import relationships, risk scores, impact radii, and institutional memory (learned lessons).

Two EU patents filed on the reasoning approach (EP26162901.8, EP26166054.2).

GitHub: https://github.com/quantamixsol/graqle
PyPI: pip install graqle
```

---

## r/ClaudeAI

**Title:** Built an MCP server that gives Claude architecture-aware reasoning over your codebase

```
I built GraQle — an MCP server that builds a knowledge graph from your codebase and gives Claude Code 16 tools to reason over it.

Instead of Claude reading 60 files to understand dependencies, it queries the graph. One command setup:

    pip install graqle && graq scan repo . && graq init

This wires up tools like:
- `graq_context` — focused context for any module (~500 tokens)
- `graq_reason` — multi-agent reasoning over the graph
- `graq_impact` — blast radius analysis
- `graq_preflight` — safety checks before refactoring
- `graq_learn` — teach the graph lessons that persist

The graph persists between sessions, so Claude remembers your architecture across conversations.

Supports 14 LLM backends and works fully offline with Ollama.

GitHub: https://github.com/quantamixsol/graqle
```

---

## r/LocalLLaMA

**Title:** GraQle — knowledge graph for codebases that works fully offline with Ollama

```
Built a tool that creates a knowledge graph from your codebase and lets you query it with any local LLM.

graq scan repo . && graq run "what depends on auth?"

With Ollama backend, everything stays on your machine. No API keys needed. The graph reduces context from ~50K tokens to ~500, which is especially important when running smaller local models with limited context windows.

14 backends supported: Ollama, Anthropic, OpenAI, Bedrock, Gemini, Groq, DeepSeek, Together, Mistral, OpenRouter, Fireworks, Cohere, plus Custom.

pip install graqle

GitHub: https://github.com/quantamixsol/graqle
```

---

## r/opensource

**Title:** GraQle — code intelligence layer that builds knowledge graphs from codebases

```
Sharing GraQle, a Python SDK that builds knowledge graphs from codebases for architecture-aware reasoning.

The core idea: your AI tools should understand dependencies and architecture, not just read files. GraQle builds a graph (NetworkX), exposes it via MCP protocol, and works with Claude Code, Cursor, and VS Code Copilot.

Features: dependency analysis, impact analysis, institutional memory, governed reasoning with confidence scores. 14 LLM backends. Fully offline with Ollama.

Free tier: 500 nodes, 3 queries/month, unlimited graph visualization.

GitHub: https://github.com/quantamixsol/graqle
PyPI: pip install graqle
```

---

## r/commandline

**Title:** graq — CLI that builds knowledge graphs from codebases and answers architecture questions

```
Built a CLI tool called graq that scans codebases and builds dependency graphs you can query:

    graq scan repo .
    graq run "what depends on the auth module?"
    graq impact auth.py
    graq preflight "refactor the database layer"
    graq learn "never skip refresh token rotation in auth"

pip install graqle

It's a Python CLI using Typer. Supports 14 LLM backends including fully offline options with Ollama.

GitHub: https://github.com/quantamixsol/graqle
```

---

## r/cursor and r/vscode

**Title:** MCP server that gives your IDE architecture-aware code intelligence (GraQle)

```
Built an MCP server that builds a knowledge graph from your codebase and provides 16 tools for code intelligence.

One command setup:

    pip install graqle
    graq scan repo .
    graq init --ide cursor   # or --ide vscode

Your AI assistant now has tools for dependency analysis, impact analysis, institutional memory, and architecture-aware reasoning — all from the graph instead of reading files.

GitHub: https://github.com/quantamixsol/graqle
```
