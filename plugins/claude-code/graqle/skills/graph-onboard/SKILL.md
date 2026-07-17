---
name: graph-onboard
description: Set up GraQle on a repository — scan it into a knowledge graph, verify graph health, and run the first graph-powered question. Use when GraQle is installed but no graqle.json exists yet, or when the user asks to onboard, scan, or index the repo with GraQle.
---

# Graph Onboard (GraQle)

Take a repository from zero to a queryable knowledge graph.

1. **Check the install** — run `graq doctor` in the shell. If `graq` is not found,
   install with `pip install graqle` first.
2. **Scan** — `graq scan repo .` from the repository root. This builds `graqle.json`
   (nodes for modules, functions, classes, endpoints and their dependency edges).
   The first full scan is never blocked by licensing caps, whatever the repo
   size (scan time itself scales with the repo).
3. **Configure the backend** — `graqle.yaml` controls which LLM provider powers
   reasoning (Anthropic by default; bring your own key via environment variables).
4. **Verify** — `graq_inspect` for node/edge counts and hub nodes, and
   `graq_graph_health` for embedding/cache status. If chunks are unembedded,
   follow its recommendation before relying on semantic recall.
5. **First question** — `graq_reason(question="What are the highest-risk modules in
   this repo and why?")` to demonstrate graph-powered reasoning.
6. **Keep it growing** — call `graq_learn` after completing tasks, and let
   `graq init` install git hooks so the graph stays in sync with the code.
