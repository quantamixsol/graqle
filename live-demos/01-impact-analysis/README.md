# Demo 01 — Impact Analysis Before a Risky Change

## The scenario

You're about to refactor `graph.py` — the core data structure of graqle.
**How many modules will break? Which tests will fail? Is it safe to change?**

Without Graqle: grep + guess + hope.
With Graqle: architecture-aware answer in seconds.

## Full workflow (run this demo)

```bash
cd live-demos/01-impact-analysis
python run_demo.py
```

## What you'll see

1. **Build the graph** — `graq scan` indexes the codebase into graqle.json
2. **Impact query** — "What does changing graph.py break?" → 26 modules, HIGH risk
3. **Reasoning** — "Why is graph.py so central?" → multi-agent graph-of-agents answer
4. **Preflight gate** — governance check before the change
5. **Teach back** — outcome recorded so future reasoning improves

## Expected output

```
Step 1/5: Scanning codebase...
  26 modules depend on graph.py (CRITICAL impact radius)

Step 2/5: Impact analysis...
  Direct consumers: core/scanner.py, core/intelligence.py, plugins/mcp_dev_server.py ...
  Risk: HIGH — hub module, 26 consumers

Step 3/5: Reasoning — why is this so central?
  [72% confidence] graph.py is the shared data contract between all layers.
  Changing node/edge schema breaks serialization, scanner, and all 14 backends.

Step 4/5: Preflight gate...
  GATE: T2 — requires senior review. 3 past mistakes on this path.
  Lesson: Never rename node fields without a migration path.

Step 5/5: Teaching outcome...
  Lesson recorded to KG. Next query gets this context automatically.
```
