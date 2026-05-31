# End-to-End Auto-Grow (v0.63.0)

> Keep your knowledge graph current — and queryable — as you work, not just
> when you remember to rebuild it.

GraQle's promise is that the graph adapts and grows with your code. As of
v0.63.0, `graq grow` does the full job: it scans your changes, **embeds the new
chunks**, and **writes them to the backend your graph actually reads from**
(local JSON or Neo4j). That means new code is queryable by `graq reason` within
seconds of a change — not just present in a file on disk.

## The one command

```bash
graq grow                 # incremental scan + embed + write configured backend
graq grow --no-embed      # legacy behaviour: structure only, no embedding
graq grow --backend neo4j # force a backend (default: auto, from graqle.yaml)
graq grow --full          # full rescan + full re-embed (slower; rarely needed)
```

`--embed` is **on by default**. Embedding is **incremental** — only the nodes
that changed in this grow are re-embedded, so a typical commit stays fast even
on a large graph. Pass `--no-embed` to reproduce the pre-v0.63 behaviour.

## Three ways the graph stays current

All three funnel through the same `graq grow --embed` path — there is one
implementation, three triggers:

| Trigger | When it fires | How |
|---|---|---|
| **CLI** | You run it | `graq grow` |
| **Git hook** | Every `git commit` | post-commit hook (installed by `graq init`) |
| **MCP watcher** | You save a file in your IDE (no commit needed) | background watcher in the MCP server |

### 1. CLI — manual

Run `graq grow` whenever you want. Useful after a bulk change or to verify the
loop is working.

### 2. Git hook — on every commit

`graq init` installs a `post-commit` hook that runs `graq grow --embed` after
each commit. Errors are surfaced (the hook does **not** swallow them) but never
block a commit that has already happened. To install or refresh it on an
existing project, re-run `graq init`, or drop this in `.git/hooks/post-commit`
and `chmod +x` it:

```sh
#!/bin/sh
graq grow --embed
status=$?
if [ $status -ne 0 ]; then
  echo "[graqle post-commit] graq grow exited $status — commit landed, KG NOT updated." >&2
  echo "[graqle post-commit] Investigate with 'graq doctor' or re-run 'graq grow --embed'." >&2
fi
exit 0
```

### 3. MCP background watcher — on every save

When the GraQle MCP server is running, it can watch your project tree and run
`graq grow --embed` automatically a few seconds after you save a file — so the
graph is current even between commits. Install the optional dependency:

```bash
pip install 'graqle[watch]'
```

Tunable via environment variables (all optional):

| Variable | Default | Effect |
|---|---|---|
| `GRAQLE_DISABLE_BACKGROUND_GROW` | `0` | set to `1` to turn the watcher off |
| `GRAQLE_BG_GROW_DEBOUNCE` | `5` | seconds to batch saves before growing |
| `GRAQLE_BG_GROW_RATE_LIMIT` | (sensible default) | caps embedding work per hour |

If `watchdog` isn't installed, the watcher simply stays disabled — nothing
breaks.

## Backends

`--backend auto` (the default) reads `graph.connector` from your `graqle.yaml`:

- **local** (default) — updates `graqle.json` and refreshes the local embedding
  cache under `.graqle/`.
- **neo4j** — writes nodes, edges, and embedded chunks to your Neo4j instance,
  and still updates `graqle.json` as a local mirror.

If a Neo4j backend is selected but unreachable, `grow` logs that clearly and
falls back to writing `graqle.json` so your work is never lost; it reconciles on
the next successful run.

## Safety

- **Secrets are never embedded.** Content classified as sensitive is redacted
  before any embedding call, on both the local and Neo4j paths.
- **Failures are visible, not silent.** If embedding or a backend write fails,
  you see a clear message — `grow` does not hide errors behind `--quiet` or
  `2>/dev/null`.
- **The graph file shape is unchanged.** Embedding output is stored alongside
  (a local cache file / Neo4j chunk records), never by altering your
  `graqle.json` node/edge format.

## Teams (coming in a later release)

A shared graph kept in sync across several developers in near-real-time is a
larger problem than a single-developer auto-grow loop, and it's being designed
separately. For now, each developer's auto-grow keeps **their** graph current;
team-wide shared-graph sync is on the roadmap.

## Verify it's working

After editing a file that defines a new function `X` and letting a grow run
(commit, save, or `graq grow`):

```bash
graq run "what does X do?"
```

`X` should appear in the activated nodes within a minute. If it doesn't, run
`graq doctor` and check the grow output for errors.
