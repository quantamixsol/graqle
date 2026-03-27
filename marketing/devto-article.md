---
title: "I built a knowledge graph engine that makes AI coding tools 100x more efficient"
published: true
tags: showdev, python, ai, opensource
---

Your AI coding assistant reads 60 files to answer "what depends on auth?" That's 50,000 tokens, 2 minutes of processing, and it's still guessing.

**The problem isn't the model. It's the context.**

AI tools see files, not architecture. They don't know that `auth.py` has 11 transitive dependents, that changing it is HIGH risk, or that your team learned three months ago to never skip refresh token rotation.

## Introducing GraQle

GraQle builds a **knowledge graph** from your codebase. Every module becomes a node. Every import, call, and dependency becomes an edge. Instead of reading raw files, your AI queries the graph.

**The result:** 500 tokens instead of 50,000. 5 seconds instead of 2 minutes. Precise answers instead of guesses.

## Quick Start (60 seconds)

```bash
pip install graqle
graq scan repo .
graq run "what depends on auth?"
```

That's it. Your codebase now has a queryable knowledge graph.

## What You Can Do

### Dependency analysis
```bash
graq run "explain the payment flow end to end"
graq context auth-module    # 500-token focused context
```

### Impact analysis before changes
```bash
graq impact auth.py
# → 3 direct consumers, 11 transitive dependencies, risk: HIGH
```

See what breaks *before* you break it.

### Safety checks before refactoring
```bash
graq preflight "refactor the database layer"
# → Warnings: 4 modules depend on connection pool, 2 have no tests
```

### Institutional memory
```bash
graq learn "auth module requires refresh token rotation — never skip it"
graq lessons auth
# → Returns lessons learned, ranked by relevance
```

The graph *remembers* what your team learns. New devs and AI assistants inherit it.

## MCP Integration (One Command)

```bash
graq init              # Claude Code
graq init --ide cursor # Cursor
graq init --ide vscode # VS Code + Copilot
graq init --ide windsurf # Windsurf
```

Your AI now has 16 architecture-aware tools. No workflow change — it uses them automatically.

## 14 LLM Backends

Anthropic, OpenAI, Ollama, AWS Bedrock, Google Gemini, Groq, DeepSeek, Together, Mistral, OpenRouter, Fireworks, Cohere, plus Custom.

**Works fully offline** with Ollama. Your code never leaves your machine.

## The Numbers

| Metric | Without GraQle | With GraQle |
|--------|---------------|-------------|
| Tokens per question | 50,000 | 500 |
| Cost per question | ~$0.15 | ~$0.0003 |
| Response time | 2 minutes | 5 seconds |
| Cross-session memory | None | Persistent graph |
| Confidence | "I think..." | Score + evidence chain |

## How It Works

1. **Scan:** `graq scan repo .` parses your codebase and builds a NetworkX graph
2. **Query:** Questions are routed through a task classification system to the optimal LLM backend
3. **Reason:** Multi-agent reasoning traverses the graph for precise, structured answers
4. **Learn:** `graq learn` adds institutional memory nodes to the graph
5. **Persist:** The graph saves to disk and loads instantly on next use

## Try It

```bash
pip install graqle && graq scan repo . && graq run "explain the architecture"
```

- **GitHub:** [quantamixsol/graqle](https://github.com/quantamixsol/graqle)
- **PyPI:** [graqle](https://pypi.org/project/graqle/)
- **Website:** [graqle.com](https://graqle.com)

2,000+ tests. Two EU patents. Production-stable since v0.28.

I'd love to hear what you'd want an architecture-aware AI to understand about *your* codebase. Drop a comment!
