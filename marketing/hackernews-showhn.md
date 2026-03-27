# Hacker News — Show HN Post

## Title
Show HN: GraQle – Knowledge graphs for codebases, so AI tools reason over architecture

## URL
https://github.com/quantamixsol/graqle

> Always link to GitHub, not the marketing site. HN audience prefers repos.

## First Comment (Post immediately after submitting)

```
I've been building GraQle for the past year to solve a specific problem: AI coding tools are structurally blind. They read files — sometimes 60 of them — to answer a question that a dependency graph answers in one traversal.

GraQle builds a knowledge graph from your codebase. Every module is a node, every import/call/dependency is an edge. When you (or your AI tool) asks "what depends on auth?", it queries the graph instead of grep-ing through files.

What this gives you:
- `graq scan repo .` builds the graph from any Python/JS/TS codebase
- `graq run "question"` does multi-agent reasoning over the graph
- `graq impact auth.py` shows the full blast radius before you touch anything
- `graq learn "lesson"` stores institutional memory in the graph
- `graq init` wires up an MCP server with 16 tools for Claude Code, Cursor, or VS Code

The practical difference: a dependency question costs ~500 tokens and 5 seconds instead of ~50,000 tokens and 2 minutes. The graph also persists across sessions, so your AI doesn't forget what it learned.

It supports 14 LLM backends (Anthropic, OpenAI, Ollama, Bedrock, Gemini, Groq, etc.) and works fully offline. No cloud dependency required.

Install: `pip install graqle`

I'd appreciate feedback on the approach. Specifically interested in whether the knowledge graph model captures enough of your codebase's structure to be useful in practice.
```

## HN-Specific Tips
- Do NOT ask for upvotes
- Do NOT post from a company account (use personal HN account)
- Respond to every comment within 2 hours
- Be genuine about limitations
- If asked about open source: "Proprietary license but free tier is generous (500 nodes, unlimited graph viz)"
- If asked about competition: Acknowledge existing tools honestly, explain the graph-based approach as the differentiator
