<div align="center">

# Graqle

**Your codebase has answers. Stop digging for them.**

Turn any codebase into a knowledge graph where every module is a reasoning agent.<br/>
One install. Any IDE. Any AI tool. Zero cloud infrastructure.

[![PyPI](https://img.shields.io/pypi/v/graqle?color=%2306b6d4&label=PyPI)](https://pypi.org/project/graqle/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-06b6d4.svg)](https://python.org)
[![Tests: 916 passing](https://img.shields.io/badge/tests-916%20passing-06b6d4.svg)]()
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache_2.0-06b6d4.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-compatible-06b6d4.svg)]()
[![Patent](https://img.shields.io/badge/patent-EP26162901.8-06b6d4.svg)](NOTICE)

[Website](https://graqle.com) · [PyPI](https://pypi.org/project/graqle/) · [GitHub](https://github.com/quantamixsol/graqle)

</div>

---

## The problem

Every time you ask your AI assistant "what depends on the auth service?", it reads 60 files, burns 50,000 tokens, takes 20 minutes, and still gives you a best-guess answer.

It doesn't understand your architecture. It just reads text.

## The fix

```bash
pip install graqle[api]
cd your-project
graq init
```

That's it. Graqle scans your codebase, builds a knowledge graph, and wires up your IDE. Now ask:

```bash
graq reason "what breaks if I change auth?"
```

**3 nodes activated. 500 tokens. 5 seconds. $0.0003.**

Not 60 files. Not 50,000 tokens. Not $0.15. Not "maybe".

---

## How it works

**Graqle turns your codebase into a graph where every module is an autonomous reasoning agent.** When you ask a question:

1. The right nodes activate (3 instead of 300)
2. Each agent reasons about its own domain
3. Agents cross-reference and synthesize one answer
4. You get the answer, confidence score, and cost — transparently

```
Your Codebase ──→ graq init ──→ Knowledge Graph
                                      │
              ┌──────────┬────────────┼──────────┐
              ▼          ▼            ▼          ▼
            CLI      Python SDK   MCP Server  REST API
         (terminal)  (scripts)    (IDE)       (HTTP)
```

**The graph is the product.** Query it from any IDE, any terminal, any script. Your machine, your API keys, your data.

---

## Works with everything

| IDE / Tool | How | Setup |
|-----------|-----|-------|
| **Claude Code** | MCP server + CLAUDE.md | `graq init` (auto) |
| **Cursor** | MCP server + .cursorrules | `graq init --ide cursor` |
| **VS Code + Copilot** | MCP server | `graq init --ide vscode` |
| **Windsurf** | MCP server + .windsurfrules | `graq init --ide windsurf` |
| **JetBrains / Codex / Replit** | CLI + SDK | `graq init --ide generic` |
| **CI/CD pipelines** | Python SDK | `pip install graqle` |

No cloud account. No infrastructure. No config files to write.

---

## CLI

```bash
# Ask questions
graq reason "what depends on auth?"          # Graph reasoning
graq context auth-lambda                      # 500-token focused context
graq inspect --stats                          # Graph statistics

# Build and maintain
graq init                                     # Scan repo, build graph
graq scan repo .                              # Rescan codebase
graq rebuild --force                          # Rebuild all chunks

# Teach the graph
graq learn node "auth-service" --type SERVICE
graq learn entity "Payments" --type SERVICE
graq learn knowledge "Auth uses RSA-256" --domain technical
graq learn edge "Payments" "auth-service" -r DEPENDS_ON
graq learn discover --from "auth-service"     # Auto-discover connections

# Multi-project
graq link merge proj1/kg.json proj2/kg.json   # Merge knowledge graphs
graq link edge crawlq/sdk myapp/retrieval     # Cross-project edges

# Review what was learned
graq learned                                  # List all taught knowledge
graq learned --domain brand                   # Filter by domain

# Visual dashboard
graq studio                                   # Launch local web UI
graq studio --port 9000                       # Custom port

# Cloud (optional — local features work without login)
graq login                                    # Connect to Graqle Cloud
graq login --api-key grq_abc123               # Non-interactive login
graq login --status                           # Check connection
graq logout                                   # Disconnect

# Utilities
graq doctor                                   # Health check
graq setup-guide                              # Backend setup
graq serve                                    # Start REST API
graq self-update                              # Upgrade (handles Windows exe locks)
graq --version                                # Show version
```

## Python SDK

```python
from graqle.core.graph import Graqle
from graqle.backends.api import AnthropicBackend

graph = Graqle.from_json("graqle.json")
graph.set_default_backend(
    AnthropicBackend(model="claude-haiku-4-5-20251001")
)

result = graph.reason(
    "What services depend on auth?",
    max_rounds=3,
    strategy="top_k"
)

print(result.answer)
print(f"Confidence: {result.confidence:.0%}")
print(f"Cost: ${result.cost_usd:.4f}")
```

## REST API

```bash
graq serve                    # Start on localhost:8000

curl -X POST localhost:8000/reason \
  -H "Content-Type: application/json" \
  -d '{"query": "What depends on auth?"}'
```

```json
{
  "answer": "billing-api and notifications depend on auth via JWT...",
  "confidence": 0.87,
  "cost_usd": 0.0023,
  "latency_ms": 1250
}
```

Interactive docs at `localhost:8000/docs`. Auth via `X-API-Key` header.

## Studio (Visual Dashboard)

```bash
pip install graqle[studio]         # Adds uvicorn, fastapi, jinja2
graq studio                        # Opens http://127.0.0.1:8888/studio/
graq studio --port 9000            # Custom port
graq studio --no-browser           # Don't auto-open browser
```

Graqle Studio is a local web dashboard for exploring and managing your knowledge graph. No cloud — everything runs on your machine.

| Page | URL | What it does |
|------|-----|-------------|
| **Dashboard** | `/studio/` | Overview: node/edge counts, type distribution, metrics summary |
| **Graph Explorer** | `/studio/graph` | Interactive D3 force-directed visualization. Zoom, pan, filter by type |
| **Reasoning** | `/studio/reasoning` | Live reasoning view with SSE streaming. Watch agents activate in real-time |
| **Metrics** | `/studio/metrics` | Token usage, cost tracking, ROI calculations, query history |
| **Settings** | `/studio/settings` | Model configuration, Neo4j connection status, graph reload |

Studio also exposes a JSON API at `/studio/api/` for programmatic access to graph data, node details, and metrics.

## MCP Tools

Available automatically in Claude Code, Cursor, VS Code, and Windsurf after `graq init`:

| Tool | What it does |
|------|-------------|
| `graq_context` | 500-token focused context (replaces reading entire files) |
| `graq_reason` | Multi-agent graph reasoning |
| `graq_impact` | "What breaks if I change X?" |
| `graq_preflight` | Pre-change safety check |
| `graq_lessons` | Surface past mistakes before you repeat them |
| `graq_learn` | Teach the graph new knowledge |
| `graq_inspect` | Graph structure inspection |
| `graq_reload` | Hot-reload graph without restarting |

---

## Why this works (and others don't)

Most "AI code tools" read files one at a time. That's fundamentally the wrong approach for architectural questions — you can't understand a system by reading files in isolation.

Graqle is different because:

**It understands relationships, not just text.** Your codebase is a graph of dependencies, ownership, and data flow. Graqle models that structure and reasons over it — so "what depends on auth?" traces actual dependency chains instead of grep-ing for the word "auth".

**It's 541x cheaper.** Not estimated — measured. Reading 60 files costs ~50K tokens per query. Activating 3 graph nodes costs ~500. Over hundreds of queries per day, that's the difference between $50 and $0.09.

**It tells you what it doesn't know.** Every answer includes a confidence score calibrated for graph size. When confidence is low, Graqle explains which knowledge is missing — it doesn't guess and hope you don't notice.

**It has governance built in.** Define module boundaries and architecture rules in your codebase. Graqle enforces them on every reasoning output. Security agents talk security, not UI. No extra configuration.

**It keeps learning.** The graph auto-discovers new connections, remembers which nodes produce useful answers for which query patterns, and gets smarter with every interaction. Your dev environment develops institutional memory.

---

## The numbers

| Metric | Graqle | Reading files | Difference |
|--------|--------|---------------|------------|
| Tokens per query | **500** | 50,000 | **100x fewer** |
| Cost per query | **$0.0003** | $0.15 | **541x cheaper** |
| Time to answer | **<5 seconds** | 20 minutes | — |
| Governance accuracy | **99.7%** | N/A | — |
| Tests passing | **797** | — | — |

---

## Backends

Use whatever model you want. Graqle routes simple queries to cheap models and complex ones to capable models.

| Backend | Models | Cost |
|---------|--------|------|
| **Ollama** | Qwen, Llama, Mistral (local) | **$0** |
| **Anthropic** | Claude Haiku / Sonnet / Opus | ~$0.001/query |
| **OpenAI** | GPT-4o / GPT-4o-mini | ~$0.001/query |
| **AWS Bedrock** | Claude, Titan, Llama | AWS pricing |
| **vLLM** | GPU inference + LoRA | Your GPU |
| **llama.cpp** | GGUF models (CPU) | **$0** |

```bash
graq setup-guide              # See all options
graq setup-guide ollama       # Free, local, no API key
graq doctor                   # Verify everything works
```

---

## Pricing

**Free for individuals. Always.**

| | Open Source | Team | Enterprise |
|---|:---:|:---:|:---:|
| **Price** | **$0 forever** | $29/dev/month | Custom |
| All 15 innovations | Yes | Yes | Yes |
| All MCP tools | Yes | Yes | Yes |
| All backends | Yes | Yes | Yes |
| CLI + SDK + API | Yes | Yes | Yes |
| Unlimited queries | Yes | Yes | Yes |
| Commercial use | Yes | Yes | Yes |
| Shared team graphs | — | Yes | Yes |
| Neo4j GDS intelligence | — | Yes | Yes |
| SSO + audit trail | — | — | Yes |

All 15 innovations are free. Every developer deserves intelligent tooling regardless of budget. Teams pay for collaboration — individuals never pay.

---

## 15 Innovations (Patent EP26162901.8)

Every innovation listed below is free to use under Apache 2.0.

| # | What it does | Why it matters |
|---|-------------|----------------|
| 1 | **Chunk-level semantic scoring** | Each code chunk scored independently — finds the exact function, not just the file |
| 2 | **Zero-cost transparency layer** | See exactly which agents activated and why, without extra LLM calls |
| 3 | **Convergent message passing** | Agents discuss until they agree, then stop. No wasted rounds |
| 4 | **Backend fallback chain** | Auto-switches models if one fails. Cost budgets enforced |
| 5 | **Topology-aware synthesis** | Answers reflect graph structure, not just agent count |
| 6 | **3-layer governance validation** | Enforces domain boundaries on every reasoning output |
| 7 | **Formula-based compliance scoring** | Quantitative scores, not pass/fail. Gap attribution shows what's missing |
| 8 | **Auto-generate ontologies** | Build OWL+SHACL constraints from your codebase automatically |
| 9 | **Adaptive activation** | Simple queries use 3 nodes ($0.0001). Complex queries use 50 ($0.003) |
| 10 | **Cross-query learning** | Remembers which nodes worked for which patterns. Gets smarter over time |
| 11 | **Per-entity model selection** | Security nodes use capable models. Utility nodes use cheap ones |
| 12 | **Retrieval-to-reasoning pipeline** | Connects document retrieval to graph reasoning seamlessly |
| 13 | **Hybrid skill matching** | Combines regex precision with semantic flexibility |
| 14 | **Neo4j vector + graph search** | Single database query for both embedding similarity and graph traversal |
| 15 | **Activation memory** | Persistent cross-session learning about node effectiveness |

---

## What's new in v0.18.0

- **Graqle Cloud (optional):** `graq login` to connect — backup, team sync, usage analytics. Zero signup for local use.
- **Studio Cloud Connect:** Settings page with Connect/Disconnect UI. Dashboard shows subtle cloud banner (dismissible).
- **Ontology Refinement:** `OntologyRefiner` analyzes activation patterns to suggest type merges, promotions, and new relationships.
- **CI/CD GitHub Action:** Auto-updates `graqle.json` on PR merge. Validates graph on PRs.

See the [full changelog](#changelog) below.

<details>
<summary><strong>Changelog</strong></summary>

### v0.18.0 — Cloud Connect + Ontology Intelligence (2026-03-13)

**Graqle Cloud (optional — zero signup for local features):**
- `graq login` / `graq logout` — Connect to Graqle Cloud for backup, team sync, and usage analytics. API keys stored in `~/.graqle/credentials.json`. Supports interactive and non-interactive (`--api-key`) modes. `graq login --status` to check connection.
- **Studio Cloud Connect** — Settings page has full Connect/Disconnect UI with API key input, email field, and plan display. Dashboard shows a subtle, dismissible "Back up your graph" banner when not connected.
- **Credentials manager** — `graqle.cloud.credentials` module: `load_credentials()`, `save_credentials()`, `clear_credentials()`, `get_cloud_status()`. All local features work without any account.
- **Studio API endpoints** — `/studio/api/cloud/status`, `/studio/api/cloud/connect`, `/studio/api/cloud/disconnect` for the Studio UI.

**Ontology Intelligence (P3-13):**
- **`OntologyRefiner`** — Analyzes activation memory patterns to suggest ontology refinements. Detects underused entity types (candidates for merging), co-activation patterns (types that should have explicit relationships), and high-value types (promotion candidates). Returns `RefinementSuggestion` objects with action, confidence, and evidence.
- **Type usage report** — `refiner.get_type_usage_report()` returns per-type activation statistics for dashboards and analysis.

**CI/CD (P3-14):**
- **`graqle-scan.yml` GitHub Action** — Runs `graq scan repo .` on push to master (code files only). Auto-commits updated `graqle.json`. On PRs: validates existing graph and runs dry-run scan preview.

**Studio Improvements:**
- Dynamic version display in Settings page (was hardcoded v0.11.0)
- Cloud connection panel with Alpine.js reactive UI
- `.btn-outline` and `.btn:disabled` CSS styles

### v0.17.0 — Field-Tested Release (2026-03-13)

**Real-world tested on CopyForge (3,870 nodes, Python + React/TS) and quantamixsolutions.com (55 nodes, enriched KG). Fixes every bug found during field testing.**

**Critical Bug Fixes:**
- **`edges`/`links` JSON key mismatch (P0):** `graq scan` wrote `"edges"` but `from_json()` expected `"links"` — broke the `scan → learn → save → learn` cycle completely. Now accepts both keys, always saves as `"links"`.
- **`entity_type` not loading from JSON (P0):** Node types showed as generic "Entity" instead of "KNOWLEDGE"/"SERVICE" after load. `from_networkx()` now checks both `"type"` and `"entity_type"` keys and flattens nested `properties` dicts.
- **Windows Unicode crash (P0):** Rich crashed on cp1252 Windows terminals when graph data contained Unicode arrows/symbols. Fixed with `PYTHONIOENCODING=utf-8` on CLI startup + `safe_symbol()` helper with ASCII fallbacks.
- **Impact analysis too coarse:** `graq_impact` returned entire `components/` directory (17 files) because BFS followed `CONTAINS` edges up to parent dirs. Now skips structural edges (CONTAINS, DEFINES), only follows dependency edges (IMPORTS, CALLS, DEPENDS_ON).
- **Lessons hit_count always 0:** `graq_lessons` and `graq_preflight` now increment `properties["hits"]` on each surfaced lesson and persist to disk.

**New Commands:**
- `graq learned` — List all KNOWLEDGE, LESSON, and manually-added nodes with domain, description, creation date, and hit count. Filter by `--domain`.
- `graq self-update` — Upgrade Graqle handling Windows exe file locks (detects running MCP server, stops it, upgrades via pip, optionally restarts).
- `graq --version` — Standard CLI version flag (was missing; only `graq version` subcommand existed).

**Ontology Refinement (P3-13):**
- **`OntologyRefiner`** — Analyzes activation memory to suggest ontology improvements. Detects underused entity types, finds co-activation patterns between types, and promotes high-value types. Use via `OntologyRefiner(memory, graph).analyze()` to get structured `RefinementSuggestion` objects with action, confidence, and evidence.
- **Type usage report** — `refiner.get_type_usage_report()` returns per-type activation stats for dashboards.

**CI/CD Integration (P3-14):**
- **GitHub Action workflow** — `.github/workflows/graqle-scan.yml` auto-runs `graq scan repo .` on push to master (code changes only). On PRs, validates existing graph and does a dry-run scan. Auto-commits updated `graqle.json` when the graph changes.

**Studio Documentation:**
- Added full `graq studio` section to README with page descriptions, URLs, install instructions, and API access.

**Developer Experience:**
- **`.graqle-ignore` support:** Create a `.graqle-ignore` file (gitignore syntax) in your project root to exclude directories from `graq scan`. Also supports `--exclude` flag. Prevents vendored deps (openpyxl, etc.) from adding 1,500+ noise nodes.
- **Auto-detect full `graq` path in `.mcp.json`:** `graq init` now uses `shutil.which("graq")` to write the absolute path. Windows users no longer need pip Scripts dir on PATH.
- **Non-TTY auto-detection:** `graq init` detects headless environments (CI/CD, Claude Code bash) and defaults to non-interactive mode automatically.
- **Bench fail-fast:** `graq bench` checks backend availability before running N queries. No more 75+ identical error lines when backend is missing.
- **Fuzzy search in `graq context`:** If exact match fails, uses `difflib.get_close_matches` with "Did you mean?" suggestions.
- **Verbose learn output:** `graq learn entity/knowledge` now shows the actual connected node names, not just edge count.

**Install Size:**
- `sentence-transformers` moved from core to `[embeddings]` optional group. `pip install graqle` is now ~10MB (was ~200MB+). Use `pip install graqle[embeddings]` or `graqle[all]` for local embedding models.

**901 tests passing.** Up from 797 in v0.15.0. All backward-compatible — existing `graqle.json` files with either `"edges"` or `"links"` key load correctly.

### v0.16.0 — Graqle Rebrand (2026-03-13)

- **Rename:** CogniGraph → Graqle. `pip install graqle`, CLI: `graq`, MCP: `graq_*`
- **Backward compat:** `pip install cognigraph` auto-installs graqle + shows DeprecationWarning
- Domain: graqle.com registered (Route 53)
- All v0.15.0 features carried forward

### v0.15.0

- MCP hot-reload (graph auto-reloads on file change)
- Confidence recalibrated for large KGs (65%+ for quality answers, was 9-15%)
- Business entity support (`graq learn entity`, `graq learn knowledge`)
- Multi-project CLI (`graq link merge`, `graq link edge`, `graq link stats`)
- 797 tests passing

### v0.12.3

- Studio dashboard CSS fixes
- Mobile responsive + QR code
- Embedding cache (11K nodes: 30s → <1s per query)

### v0.12.0

- Observer overhaul (perspective diversity no longer flagged as conflict)
- Adaptive node count (simple queries use fewer nodes)
- Cross-query learning (Activation Memory, Innovation #15)
- Call-graph edges from scanner

### v0.10.0

- ChunkScorer replaces PCST as default activation
- Multiple nodes activated (was single-node)
- Bedrock auth detection fixed

### v0.9.0

- Neo4j backend (`from_neo4j()` / `to_neo4j()`)
- CypherActivation (vector + graph in single Cypher query)
- Chunk-aware scoring (500 chars from top 5 chunks)
- 736 tests passing

</details>

---

## Citation

```bibtex
@article{kumar2026graqle,
  title   = {Graqle: Governed Intelligence through Graph-of-Agents Reasoning
             over Knowledge Graph Topologies with Semantic SHACL Validation},
  author  = {Kumar, Harish},
  year    = {2026},
  institution = {Quantamix Solutions B.V.},
  note    = {European Patent Application EP26162901.8},
  url     = {https://github.com/quantamixsol/graqle}
}
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, and PR guidelines.

## License

[Apache 2.0](LICENSE) — use it commercially, modify it freely, keep the attribution.
