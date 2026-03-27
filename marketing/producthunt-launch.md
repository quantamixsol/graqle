# Product Hunt Launch — GraQle

## Product Name
GraQle

## Tagline (60 chars max)
Code intelligence that understands your architecture.

## Short Description (260 chars)
GraQle builds a knowledge graph from any codebase so your AI tools reason over structure, not strings. Dependency analysis, impact analysis, institutional memory. Works with Claude Code, Cursor, VS Code Copilot. 14 LLM backends. Fully offline.

## Tags
1. Developer Tools
2. Artificial Intelligence
3. Open Source

## Website URL
https://graqle.com

## GitHub URL
https://github.com/quantamixsol/graqle

## Gallery Images Needed (minimum 3)
1. **CLI demo** — screenshot of `graq scan repo .` + `graq run "what depends on auth?"`
2. **Impact analysis** — screenshot of `graq impact auth.py` showing blast radius
3. **MCP in IDE** — screenshot of GraQle tools working inside Claude Code or Cursor
4. **Before/After** — side-by-side: 50,000 tokens vs 500 tokens comparison graphic
5. **Studio dashboard** — screenshot of graqle.com/dashboard

## Maker's First Comment (CRITICAL — 70% of winners have this)

```
Hey Product Hunt! 👋

I'm Harish, and I built GraQle because I was frustrated watching AI coding tools burn 50,000 tokens reading 60 files just to answer "what depends on auth?"

The problem isn't the AI model — it's the context. AI tools see files, not architecture.

GraQle fixes this by building a knowledge graph from your codebase. Every module becomes a node, every dependency becomes an edge. When your AI asks a question, it queries the graph — getting precise, structured context in 500 tokens instead of 50,000.

**What makes GraQle different:**
- 🔍 `graq scan repo .` — builds the graph in seconds
- 🧠 `graq run "question"` — architecture-aware reasoning
- 💥 `graq impact auth.py` — see what breaks before you break it
- 📚 `graq learn` — the graph remembers what your team learns
- 🔌 One-command MCP integration for Claude Code, Cursor, and VS Code Copilot
- 🏠 Fully offline — your code never leaves your machine
- ⚡ 14 LLM backends — use whatever model you want

**Try it now:**
```bash
pip install graqle && graq scan repo . && graq run "explain the architecture"
```

We're live on PyPI (v0.31.3) with 2,000+ tests passing. Two EU patents filed.

Would love your feedback! What would you want your AI coding assistant to understand about your codebase?
```

## Launch Timing
- **Best days:** Tuesday, Wednesday, or Thursday
- **Best time:** Schedule for 12:01 AM PST
- **Pre-launch:** Engage on PH for 1-2 weeks before launch (upvote/comment on other products)

## Pre-Launch Checklist
- [ ] Create product page on Product Hunt
- [ ] Upload 3-5 gallery images (real screenshots, no stock photos)
- [ ] Write tagline + description
- [ ] Prepare first comment
- [ ] Schedule launch date (1-4 weeks out)
- [ ] Share upcoming launch page with supporters
- [ ] Prepare "we're live on PH!" posts for X, LinkedIn, Reddit
