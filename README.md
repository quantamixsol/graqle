<div align="center">

# CogniGraph

### Dev Intelligence Layer — Graphs That Think

Turn any codebase into a reasoning-ready knowledge graph.<br/>
One command. Any IDE. Any AI tool. Zero cloud infrastructure.

[![PyPI version](https://badge.fury.io/py/cognigraph.svg)](https://pypi.org/project/cognigraph/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Tests: 763 passing](https://img.shields.io/badge/tests-763%20passing-brightgreen.svg)]()
[![MCP Compatible](https://img.shields.io/badge/MCP-compatible-8A2BE2.svg)]()
[![Patent: EP26162901.8](https://img.shields.io/badge/patent-EP26162901.8-orange.svg)](NOTICE)

</div>

---

> **What if your development environment understood your entire codebase — and kept learning?**
>
> CogniGraph transforms any codebase into a knowledge graph where every module, service, and config is a node backed by an autonomous LLM agent. Query it from any IDE, any AI tool, or plain terminal. One `pip install`, one `kogni init`, and your dev environment becomes intelligent.

---

## Quick Start

```bash
pip install cognigraph[api]
cd your-project
kogni init
```

That's it. CogniGraph scans your repo, builds a knowledge graph, and configures your IDE. Works with:

| IDE / Tool | Integration | Command |
|-----------|-------------|---------|
| **Claude Code** | MCP server + CLAUDE.md | `kogni init` (auto-detected) |
| **Cursor** | MCP server + .cursorrules | `kogni init --ide cursor` |
| **VS Code + Copilot** | MCP server + copilot-instructions | `kogni init --ide vscode` |
| **Windsurf** | MCP server + .windsurfrules | `kogni init --ide windsurf` |
| **Codex / Replit / JetBrains** | CLI + Python SDK | `kogni init --ide generic` |
| **Plain terminal** | Full CLI | `kogni init --ide generic` |
| **CI/CD pipelines** | Python SDK | `pip install cognigraph` |

No cloud account. No infrastructure. Your machine, your API keys, your data.

---

## What You Get

### CLI (any terminal, any IDE)
```bash
kogni run "What depends on the auth service?"     # Graph reasoning
kogni context auth-lambda                           # 500-token focused context
kogni inspect --stats                               # Graph statistics
kogni scan repo .                                   # Rebuild knowledge graph
kogni rebuild                                        # Rebuild chunks from source files
kogni rebuild --force                                # Force re-read ALL source files
kogni doctor                                        # Health check
kogni setup-guide                                   # Backend setup help
kogni register                                       # Register for updates (optional)
kogni activate <key>                                 # Activate team/enterprise license
kogni billing                                        # View tier & usage
```

### Python SDK (any Python environment)
```python
from cognigraph import CogniGraph

# Load graph — auto-creates backend from cognigraph.yaml config
graph = CogniGraph.from_json("cognigraph.json", config="cognigraph.yaml")

result = graph.reason("How does GDPR conflict with the AI Act?")
print(result.answer)          # Multi-agent synthesized answer
print(f"Cost: ${result.cost_usd:.4f}")  # Transparent cost tracking

# Rebuild chunks from source files (e.g., after code changes)
graph.rebuild_chunks(force=True)
```

### REST API (any HTTP client — Copilot, Postman, custom tools, bots)
```bash
# Start the server
kogni serve                          # localhost:8000

# Query from anything that speaks HTTP
curl -X POST http://localhost:8000/reason \
  -H "Content-Type: application/json" \
  -d '{"query": "What depends on the auth service?"}'
```
```json
{
  "answer": "The auth service is depended on by...",
  "confidence": 0.87,
  "cost_usd": 0.0023,
  "latency_ms": 1250.5
}
```

**Endpoints:** `/reason` (single query), `/reason/batch` (up to 50), `/graph/stats`, `/nodes/{id}`, `/health`<br/>
**Auth:** API key via `X-API-Key` header or Bearer token<br/>
**Docs:** Interactive Swagger UI at `http://localhost:8000/docs`<br/>
**Full reference:** [docs/api-reference.md](docs/api-reference.md)

### MCP Tools (Claude Code, Cursor, VS Code, Windsurf)
| Tool | Purpose |
|------|---------|
| `kogni_context` | 500-token focused context (replaces 20-60K file reads) |
| `kogni_reason` | Multi-agent graph reasoning |
| `kogni_inspect` | Graph structure inspection |
| `kogni_preflight` | Pre-change safety check |
| `kogni_impact` | "What breaks if I change X?" |
| `kogni_lessons` | Surface past mistakes before you repeat them |
| `kogni_learn` | Teach the graph new knowledge |

---

## How It Works

```
Your Codebase ──→ kogni init ──→ Knowledge Graph (cognigraph.json)
                                        │
         ┌──────────┬──────────┬────────┼────────┐
         ▼          ▼          ▼        ▼        ▼
       CLI      REST API    Python   MCP      Direct
    (terminal)  (HTTP)      SDK      Server   JSON read
         │          │          │        │        │
         ▼          ▼          ▼        ▼        ▼
    Any IDE    Any tool     Scripts  Claude   Custom
    terminal   Copilot      CI/CD   Cursor   parsers
               Postman      Jupyter VS Code
               Slack bots   Replit  Windsurf
```

**The knowledge graph is the product.** Once built, query it however you want:

| Access Method | Use When | Example |
|--------------|----------|---------|
| `kogni run` | Quick terminal query | `kogni run "what calls payments?"` |
| `kogni serve` | Any HTTP client needs access | `curl localhost:8000/reason` |
| Python SDK | Scripts, notebooks, pipelines | `graph.reason("query")` |
| MCP Server | AI-powered IDE with MCP support | Auto-available after `kogni init` |
| Read JSON | Custom integration, any language | Parse `cognigraph.json` directly |

**Model-agnostic.** Use free local models (Ollama), cloud APIs (Anthropic, OpenAI), or enterprise backends (AWS Bedrock). Smart routing sends complex queries to capable models and simple ones to cheap models, all within your cost budget.

---

## 15 Innovations (Patent EP26162901.8)

| # | Innovation | What it does |
|---|-----------|-------------|
| 1 | **ChunkScorer Activation** | Per-chunk semantic scoring — each chunk scored independently against query (v0.10.0, replaces PCST) |
| 2 | **MasterObserver** | Zero-cost transparency layer for reasoning traces |
| 3 | **Convergent Message Passing** | Agents talk until they agree, then stop |
| 4 | **Backend Fallback Chain** | Auto-fallback across models with cost budgets |
| 5 | **Hierarchical Aggregation** | Topology-aware answer synthesis |
| 6 | **SemanticSHACLGate** | 3-layer OWL-aware governance validation |
| 7 | **Constrained F1** | Joint quality + governance evaluation metric |
| 8 | **OntologyGenerator** | Auto-generate OWL+SHACL from documents |
| 9 | **Adaptive Activation** | Dynamic node selection from query complexity |
| 10 | **Online Graph Learning** | Bayesian edge weight updates from usage |
| 11 | **LoRA Auto-Selection** | Per-entity adapter matching |
| 12 | **TAMR+ Connector** | Retrieval-to-reasoning pipeline |
| 13 | **Multi-Resolution Embeddings** | Hybrid skill matching (regex + semantic) |
| 14 | **CypherActivation** | Neo4j vector search on chunk embeddings — bypasses graph algorithms entirely (opt-in) |
| 15 | **Activation Memory** | Cross-query learning — remembers which nodes were useful for which query patterns (v0.12.0) |

All 15 innovations are **free for every developer**. No license key required.

---

## Backends

| Backend | Models | Cost | Install |
|---------|--------|------|---------|
| **Ollama** | Any local model (Qwen, Llama, etc.) | **$0** (local) | `pip install cognigraph[api]` |
| **Anthropic** | Claude Haiku / Sonnet / Opus | $5 free credits | `pip install cognigraph[api]` |
| **OpenAI** | GPT-4o / GPT-4o-mini | $5 free credits | `pip install cognigraph[api]` |
| **AWS Bedrock** | Claude, Titan, Llama, Mistral | AWS Free Tier | `pip install cognigraph[api]` |
| **vLLM** | GPU inference + LoRA | $0 (your GPU) | `pip install cognigraph[gpu]` |
| **llama.cpp** | CPU GGUF models | $0 (your CPU) | `pip install cognigraph[cpu]` |

```bash
kogni setup-guide              # See all options with setup steps
kogni setup-guide ollama       # Free, local, no API key needed
kogni setup-guide anthropic    # Best quality, $5 free credits
kogni doctor                   # Verify everything works
```

---

## Pricing — 100% Free for Developers

CogniGraph follows the **open-core model**: everything a solo developer needs is free forever. We monetize team and enterprise collaboration features.

| | Community (Free) | Team | Enterprise |
|---|:---:|:---:|:---:|
| **Price** | **$0 forever** | $29/dev/month | Custom |
| All 15 innovations | ✓ | ✓ | ✓ |
| All MCP tools (7 tools) | ✓ | ✓ | ✓ |
| All backends (Ollama, Anthropic, OpenAI, Bedrock, vLLM) | ✓ | ✓ | ✓ |
| CLI + Python SDK + REST API | ✓ | ✓ | ✓ |
| Unlimited queries | ✓ | ✓ | ✓ |
| Auto-growing knowledge graph | ✓ | ✓ | ✓ |
| Session continuity workspace | ✓ | ✓ | ✓ |
| SemanticSHACL governance | ✓ | ✓ | ✓ |
| Multi-IDE support | ✓ | ✓ | ✓ |
| Commercial use | ✓ | ✓ | ✓ |
| Shared KG sync across team | — | ✓ | ✓ |
| Multi-developer coordination | — | ✓ | ✓ |
| Team analytics & insights | — | ✓ | ✓ |
| Custom ontologies | — | ✓ | ✓ |
| Private deployment | — | — | ✓ |
| Compliance & audit trail | — | — | ✓ |
| SLA support | — | — | ✓ |

**Why free?** We believe every developer deserves intelligent tooling regardless of budget. The innovations that save you tokens and time should not be behind a paywall. Teams pay for collaboration — individuals never pay.

---

## Benchmarks

| Metric | CogniGraph | Single-Agent Baseline | Improvement |
|--------|-----------|----------------------|-------------|
| Constrained F1 | **0.757** | 0.328 | **+131%** |
| Governance Accuracy | **99.7%** | N/A | — |
| Token Efficiency | **500 tokens/query** | 20-60K tokens | **40-120x** |

---

## Governance

**Governance is self-imposed** — boundary conditions defined in your codebase (ADRs, architecture docs, dependency rules, scope boundaries) become enforced constraints on every reasoning output. No external compliance system needed — the constraints live where the code lives.

The **SemanticSHACLGate** enforces 3-layer semantic validation:

1. **Framework Fidelity** — agents cite their own domain correctly (security modules talk security, not UI)
2. **Scope Boundary** — responses stay within assigned boundaries (as defined by your ADRs, architecture docs, or custom constraints)
3. **Cross-Reference Integrity** — proper attribution when crossing domain boundaries

**How it works in practice:**
- Dependencies in `package.json` / `requirements.txt` → boundary constraints
- ADRs (Architecture Decision Records) → reasoning rules
- Module boundaries → scope constraints
- Import relationships → valid cross-reference paths

```python
# Example: register your codebase's architecture as governance constraints
from cognigraph.ontology.semantic_shacl_gate import SemanticConstraint

constraint = SemanticConstraint(
    own_framework_markers=["authentication", "JWT", "session"],
    in_scope_topics=["auth flows", "token validation", "session management"],
    out_of_scope_topics=["UI rendering", "analytics"],
    reasoning_rules=["Always cite specific security patterns when discussing auth"],
)
```

See [examples/governance_example.py](examples/governance_example.py) for a complete working example.

**MultiGov-30 benchmark: 99.7% governance accuracy** (FF: 100%, SB: 100%, CR: 98.3%).

---

## Patent & IP Notice

CogniGraph implements methods described in **European Patent Application EP26162901.8** (filed 6 March 2026, Quantamix Solutions B.V.). See [NOTICE](NOTICE) for details.

All 14 innovations are free to use under Apache 2.0. The patent protects the specific methods — you can use CogniGraph freely in any project, commercial or otherwise.

---

## What's New in v0.12.1

**The "Last Mile" Release — every tester bug fixed, adaptive features now actually adapt.**

All remaining bugs from the v0.12.0 feedback report resolved:

### Bug Fixes
- **Bug 27: Studio node detail routes** — Nodes with `/` or `:` in IDs (85% of scanned nodes) now accessible. Changed `{node_id}` → `{node_id:path}` in all API + Studio routes.
- **Bug 5: QueryComplexityScorer always "simple"** — Thresholds lowered from 0.3/0.6/0.8 to 0.15/0.35/0.55. Added dev-specific entity markers (service, component, endpoint, auth, etc.) and depth patterns (what depends on, where is used, explain how). "How does the auth service work?" now scores **moderate**, not simple.
- **Bug 26: ActivationMemory boosts not wired** — `get_boosts()` now called during ChunkScorer activation, passing memory-guided boosts to node scoring. Cross-query learning is no longer session-only.
- **Bug 28: Examples not in pip package** — `examples/` directory now force-included in wheel via hatch build config.
- **Bug 7: Init overwrites cognigraph.yaml** — Now deep-merges new defaults into existing config. User's API keys, Neo4j credentials, and custom model overrides are preserved.
- **Bug 11: `kogni serve` missing FastAPI check** — Now checks for both `uvicorn` AND `fastapi` before starting, with clear install instructions.
- **Bug 25: Budget ceiling config exposed** — `dynamic_ceiling` and `hard_ceiling_multiplier` now in init template so users can configure them.

**763 tests passing** (3 new regression tests for adaptive scoring + init merge logic).

---

## What's New in v0.12.0

**The "Adapts" Release — Cross-query learning, observer overhaul, adaptive activation.**

Based on detailed external testing across 8 versions (v0.7.6 → v0.10.3), this release addresses every tester feedback point:

### Observer Overhaul (fixes "0% health" / "100+ false conflicts")
- **Conflict detection redesigned:** Perspective diversity is no longer punished as contradiction. With 20 nodes reasoning in parallel, most discuss different aspects — only flag when nodes make opposing claims about the same topic with explicit negation language.
- **3-tier detection:** Explicit (CONTRADICTION type), Strong (mutual reference + negation phrase), One-directional (small node sets only).
- **Health score redesigned:** Capped per-category penalties prevent health from reaching 0%. Critical anomalies penalized more, perspective diversity less.
- **Adaptive anomaly thresholds:** Confidence variance thresholds scale with node count — natural at 20 nodes, suspicious at 3.

### Adaptive Node Count (fixes "always activates max_nodes")
- **QueryComplexityScorer wired into ChunkScorer:** Simple queries activate `max_nodes/4`, moderate `max_nodes/2`, complex `max_nodes*0.75`, expert uses full `max_nodes`.
- **Cost savings:** Simple queries ("what is X?") now use ~4 nodes instead of 50, reducing cost by 90%.

### Cross-Query Learning (new — "Activation Memory")
- **ActivationMemory:** Tracks which nodes produced useful results for which query patterns. Over time, nodes that consistently contribute high-confidence answers get activation boosts for similar future queries.
- **Keyword-based pattern matching:** Records query keywords per node, computes overlap for future queries.
- **Persistent:** Saved to `.cognigraph/activation_memory.json`, survives across sessions.
- **Innovation #15:** Listed in the patent innovations table.

### Scanner: Call-Graph Edges
- **DEFINES edges:** Scanner now extracts function/class definitions and creates `DEFINES` edges from file → function nodes.
- **Richer graph:** Graph score moves from 8/10 → 9/10 with function-level nodes.

### REST API Defaults Fixed
- **Observer enabled by default:** Rule-based observer (zero LLM cost) now runs by default, providing transparency in every query.

### Governance Examples
- **New:** `examples/governance_example.py` — working SHACL governance constraints for a software engineering codebase (not just regulatory domains).

**15 new tests.** **760 tests passing** (up from 745).

---

## What's New in v0.11.0

**CogniGraph Studio — interactive dashboard:**
- Studio dashboard at `/studio/` with D3 graph explorer, live reasoning trace, metrics analytics, and settings UI.

---

## What's New in v0.10.3

**Quality over cost — budget is now a soft limit:**

- **Budget no longer kills reasoning:** Previously, exceeding `budget_per_query` would hard-stop reasoning mid-flow, producing incomplete answers. Now the budget is a **soft warning** — reasoning always completes convergence. Hard stop only triggers at **3x budget AND after at least 2 rounds**, ensuring quality is never sacrificed for cost.
- **Philosophy:** A graph that thinks should never stop thinking because of a dollar. The budget guides, it doesn't constrain.
- **`kogni init` budget updated** to `$0.10` (was `$0.05`).

---

## What's New in v0.10.2

**Critical CLI fix + connection pool + budget tuning:**

- **Bug 20 fix (P1):** CLI `--strategy` no longer hardcodes `"pcst"`. Now reads from `cognigraph.yaml` config (defaults to `"chunk"`). Previously, `kogni run` silently used PCST even when config said `chunk` — making the ChunkScorer fix invisible to CLI users.
- **Bug 21 fix (P2):** Bedrock connection pool increased from 10 → 50 with adaptive retry mode. Fixes `Connection pool is full, discarding connection` warnings when 20 nodes reason in parallel.
- **Bug 19 documented:** `ReasoningResult.content` is a backward-compatible alias for `.answer` (renamed in v0.9.0). Both work — `.answer` is canonical, `.content` is kept for migration.
- **Budget default raised:** `budget_per_query` increased from `$0.01` → `$0.10` to support ChunkScorer with 20 active nodes without hitting `cost_budget_exceeded`.
- **Example config updated:** `cognigraph.example.yaml` now defaults to `strategy: chunk` and `max_nodes: 20`.

---

## What's New in v0.10.1

**Innovation table updated** — README now accurately reflects v0.10.0 architecture:

- **Innovation #1 updated:** "PCST Activation" → **"ChunkScorer Activation"** — per-chunk semantic scoring is the actual default since v0.10.0
- **Innovation #14 added:** **"CypherActivation"** — Neo4j vector search on chunk embeddings, bypasses graph algorithms entirely (opt-in, shipped in v0.9.0)
- **Innovation count:** 13 → **14** (updated across all references)

---

## What's New in v0.10.0

**ChunkScorer replaces PCST as default activation** — The #1 blocker (Bug 1, P0) is fixed:

- **ChunkScorer (new default):** Each chunk gets its own embedding and is scored independently against the query. A query about "ProductList function" directly matches the chunk containing that function, regardless of what else the file contains. No more activating `tailwind.config.ts` instead of `Products.tsx`.
- **PCST demoted to legacy:** Still available via `strategy: "pcst"` in config, but no longer the default. PCST's graph-structure bias toward hub nodes was fundamentally wrong for code search.
- **Multiple nodes activated:** ChunkScorer returns all nodes above `min_score` threshold (configurable), not just 1. Message-passing between agents actually works now.
- **Bug 7 fix:** Bedrock auth detection now uses `boto3.Session().get_credentials()` — works with IAM profiles, SSO, env vars, and `~/.aws/credentials`.
- **Bug 9 fix:** Added control character escaping to JSON repair chain (LLMs produce literal newlines in strings).
- **Bug 19 fix:** `ReasoningResult.content` backward-compat property added (alias for `.answer`).
- **Default strategy changed:** `activation.strategy` defaults to `"chunk"` (was `"pcst"`).

**9 new tests** for ChunkScorer. **745 tests passing** (up from 736).

---

## What's New in v0.9.0

**Neo4j Backend + Critical Bug Fixes** — CogniGraph now supports Neo4j as a first-class backend alongside JSON/NetworkX:

- **Neo4j backend:** `CogniGraph.from_neo4j()` / `to_neo4j()` for loading and exporting graphs
- **CypherActivation:** Vector search on chunk embeddings via Cypher replaces PCST for Neo4j mode — faster and more accurate node activation
- **Schema management:** `create_schema()` creates constraints + vector index on `:Chunk` nodes
- **Chunk-level storage:** `:CogniNode`→`:HAS_CHUNK`→`:Chunk` with optional embeddings
- **Bug 1 (P0) fix:** Chunk-aware scoring now uses 500 chars from top 5 chunks with function/class prioritization (was 200 chars from 3 chunks)
- **Bug 18 fix:** Confidence calibration now uses relevance-weighted scoring instead of simple averaging
- **Bug 7 fix:** Bedrock `api_key_env` corrected to `AWS_ACCESS_KEY_ID`
- **Bug 9 fix:** JSON repair now strips comments before fixing quotes/commas
- **Bug 14 fix:** `out/` directory added to scan skip list
- **Bug 16 fix:** SkillAdmin embedding log messages no longer repeat per query
- **Bug 17 fix:** `kogni doctor` checks both `kogni` and `cognigraph` MCP keys

**37 new tests** (8 chunk scoring + 5 confidence calibration + 13 Neo4j connector + 7 CypherActivation + 4 graph Neo4j). **736 tests passing** (up from 699).

---

## What's New in v0.8.0

**Context-Aware Query Reformulator (ADR-104)** — Queries are now automatically enhanced with conversation context before PCST activation:
- Auto-hardened in Claude Code / Cursor / Codex (zero extra cost — uses existing conversation context)
- Pronoun resolution: "what does this do?" → resolves "this" from chat history
- Attachment support: screenshots, error logs, diagrams are described and woven into queries
- File + symbol injection: current file and active symbols ground vague queries
- LLM mode for standalone SDK users (configurable, optional)
- Fail-open: if reformulation fails, original query passes through unchanged

**49 new tests** for query reformulation. **699 tests passing** (up from 650).

---

## What's New in v0.7.9

**Content-Aware PCST Activation (ADR-103)** — 3-layer fix ensures PCST always selects content-bearing nodes over empty structural connectors (directories, namespaces):
- Layer 1: `log₂(2 + chunk_count)` content richness multiplier in relevance scoring
- Layer 2: Post-PCST filter replaces zero-chunk nodes with content-bearing neighbours
- Layer 3: Direct file lookup bypass when query mentions a specific filename

**6 Bug Fixes:**
- Bedrock config writes `region` instead of `api_key` (P2)
- `kogni grow --full` respects SKIP_DIRS exclusions (P2)
- `kogni doctor` detects MCP registration for all IDEs (P2)
- `kogni init` prompts before overwriting cognigraph.yaml (P3)
- SkillAdmin duplicate logging prevented (P3)
- 33 new tests for content-aware PCST activation

**650 tests passing** (up from 617).

---

## What's New in v0.7.7

**Chunk Pipeline (breaking fix)** — Every node now auto-loads evidence chunks from source files at graph load time. Hand-built KGs that previously had zero chunks now get full evidence for reasoning. New `kogni rebuild` command and `graph.rebuild_chunks()` API.

**13 Bug Fixes** — All issues from end-to-end testing resolved:
- Agents no longer refuse queries with "outside my domain" (P0)
- REST API Pydantic forward reference crash fixed (P0)
- Server auto-creates real backend from config instead of MockBackend (P0)
- `from_json()` accepts config path as string (P1)
- Auto-backend creation when no backend set (P1)
- Bedrock cross-region inference profile guidance (P2)
- Metrics no longer double-count token savings (P2)
- JSON repair for LLM ontology generation (5 strategies) (P2)
- NetworkX FutureWarning suppressed (P3)
- MCP server reports correct version (P3)

**Lead Generation** — `kogni register`, `kogni activate`, `kogni billing` commands. Stripe webhook handler for automated license delivery.

**617 tests passing** (up from 554).

---

## Citation

```bibtex
@article{kumar2026cognigraph,
  title   = {CogniGraph: Governed Intelligence through Graph-of-Agents Reasoning
             over Knowledge Graph Topologies with Semantic SHACL Validation},
  author  = {Kumar, Harish},
  year    = {2026},
  institution = {Quantamix Solutions B.V.},
  note    = {European Patent Application EP26162901.8},
  url     = {https://github.com/quantamixsol/cognigraph}
}
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, and PR guidelines.

## License

[Apache 2.0](LICENSE) — use it commercially, modify it freely, just keep the attribution.
