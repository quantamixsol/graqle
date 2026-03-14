<div align="center">

# gra**Q**le

**Query your architecture, not your files.**

Turn any codebase into a knowledge graph where every module is a reasoning agent.<br/>
The **Q** stands for Query, Quality, and Quantified reasoning. Zero cloud. Any IDE. Any AI.

[![PyPI](https://img.shields.io/pypi/v/graqle?color=%2306b6d4&label=PyPI)](https://pypi.org/project/graqle/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-06b6d4.svg)](https://python.org)
[![Tests: 1655 passing](https://img.shields.io/badge/tests-1655%20passing-06b6d4.svg)]()
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache_2.0-06b6d4.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-compatible-06b6d4.svg)]()

[Website](https://graqle.com) · [PyPI](https://pypi.org/project/graqle/) · [GitHub](https://github.com/quantamixsol/graqle) · [Changelog](CHANGELOG.md)

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

## What's new in v0.22.0

**Multi-provider LLM support + task-based model routing.** Use the right model for the right task — at the right cost.

- **10 LLM providers** — Anthropic, OpenAI, Bedrock, Ollama, Gemini, Groq, DeepSeek, Mistral, Together, OpenRouter, Fireworks, Cohere. One config line: `backend: groq`.
- **Google Gemini backend** — Native `generateContent` API support. Not a wrapper — proper Gemini integration with per-model pricing.
- **Task-based routing** — Map task types (context, reason, preflight, impact, lessons, learn) to different providers. Fast lookups → Groq. Deep reasoning → Anthropic. Your rules, your choice.
- **Built-in recommendations** — `graq doctor` detects configured providers and suggests which models suit which tasks. Never auto-switches — you decide.
- **Provider presets** — `create_provider_backend("groq")` auto-resolves endpoint, env var, and per-model pricing. Zero config for 7 OpenAI-compatible providers.

**1,655 tests passing.** See the full [Changelog](CHANGELOG.md).

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

### Reasoning & context

```bash
graq reason "what depends on auth?"          # Graph reasoning
graq context auth-lambda                      # 500-token focused context
graq inspect --stats                          # Graph statistics
graq "what is safe to refactor?"              # Natural language (auto-routed)
```

### Build & scan

```bash
graq init                                     # Scan repo, build graph, wire IDE
graq scan repo .                              # Rescan codebase (code AST)
graq scan all .                               # Code + JSON + documents
graq scan docs .                              # Documents only
graq scan json .                              # JSON configs only
graq scan file report.pdf                     # Single file
graq scan status                              # Background scan progress
graq scan wait                                # Block until background done
graq scan cancel                              # Stop background scan
graq rebuild --force                          # Rebuild all chunks
```

### Teach the graph

```bash
graq learn node "auth-service" --type SERVICE
graq learn entity "Payments" --type SERVICE
graq learn knowledge "Auth uses RSA-256" --domain technical
graq learn edge "Payments" "auth-service" -r DEPENDS_ON
graq learn discover --from "auth-service"     # Auto-discover connections
graq learn doc architecture.pdf               # On-demand document ingestion
graq learn doc ./compliance-docs/             # Bulk directory ingestion
```

### Multi-project

```bash
graq link merge proj1/kg.json proj2/kg.json   # Merge knowledge graphs
graq link edge crawlq/sdk myapp/retrieval     # Cross-project edges
```

### Dashboard & server

```bash
graq studio                                   # Launch local web UI
graq serve                                    # Start REST API
graq serve --read-only                        # Safe for subagents
```

### Utilities

```bash
graq doctor                                   # Health check
graq setup-guide                              # Backend setup
graq learned                                  # List taught knowledge
graq self-update                              # Upgrade (handles exe locks)
graq --version                                # Show version
```

## Python SDK

```python
from graqle.core.graph import Graqle
from graqle.backends.api import AnthropicBackend

graph = Graqle.from_json("graqle.json")
graph.set_default_backend(
    AnthropicBackend(model="claude-sonnet-4-6")
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

### Document scanning (SDK)

```python
from graqle.scanner.docs import DocumentScanner
from graqle.scanner.json_parser import JSONScanner

# Scan documents into existing graph
scanner = DocumentScanner(graph_nodes, graph_edges)
result = scanner.scan_directory("./docs")
print(f"Added {result.nodes_added} nodes, {result.edges_added} edges")

# Scan JSON configs
json_scanner = JSONScanner(graph_nodes, graph_edges)
json_result = json_scanner.scan_directory(".")
print(f"Found {json_result.files_scanned} JSON knowledge files")
```

### Deduplication (SDK)

```python
from graqle.scanner.dedup import DedupOrchestrator

dedup = DedupOrchestrator(graph_nodes, graph_edges)
report = dedup.run()
print(f"Merged {report.canonical_merges + report.unifier_merges} duplicates")
print(f"Found {len(report.contradictions)} contradictions")
```

### Auto-detection (SDK)

```python
from graqle.scanner.autodetect import detect_environment

env = detect_environment(".")
print(f"Backend: {env.backend} ({env.region})")
print(f"Languages: {env.languages}")
print(f"IDE: {env.ide}")
print(f"Capacity: {env.capacity} ({env.ram_gb}GB RAM)")
```

### Backend upgrade check (SDK)

```python
from graqle.connectors.upgrade import assess_upgrade

assessment = assess_upgrade(
    node_count=len(graph.nodes),
    edge_count=len(graph.edges),
    current_backend="networkx",
)
if assessment.should_upgrade:
    print(assessment.summary)
    # "Recommended: upgrade from networkx → neo4j. Reason: Graph has 6,200 nodes"
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
```

| Page | URL | What it does |
|------|-----|-------------|
| **Dashboard** | `/studio/` | Overview: node/edge counts, type distribution, metrics |
| **Graph Explorer** | `/studio/graph` | Interactive D3 force-directed visualization |
| **Reasoning** | `/studio/reasoning` | Live reasoning with SSE streaming |
| **Metrics** | `/studio/metrics` | Token usage, cost tracking, ROI calculations |
| **Settings** | `/studio/settings` | Model config, Neo4j connection, graph reload |

## MCP Tools

Available automatically in Claude Code, Cursor, VS Code, and Windsurf after `graq init`:

| Tool | What it does |
|------|-------------|
| `graq_context` | 500-token focused context (replaces reading entire files) |
| `graq_reason` | Multi-agent graph reasoning |
| `graq_impact` | "What breaks if I change X?" |
| `graq_preflight` | Pre-change safety check (surfaces decisions & requirements) |
| `graq_lessons` | Surface past mistakes before you repeat them |
| `graq_learn` | Teach the graph new knowledge |
| `graq_inspect` | Graph structure inspection |
| `graq_reload` | Hot-reload graph without restarting |

---

## Document-Aware Intelligence

Graqle is the first tool that connects **code intelligence** to **document intelligence** in one graph.

### What it scans

| Source | Format | What it extracts |
|--------|--------|-----------------|
| **Code** | Python, TypeScript, JavaScript, Go, Rust, Java | Functions, classes, modules, imports, call graphs |
| **Documents** | PDF, DOCX, PPTX, XLSX, Markdown, TXT | Sections, decisions, requirements, procedures, stakeholders |
| **JSON configs** | package.json, openapi.json, tsconfig, CDK, SAM | Dependencies, API endpoints, infrastructure resources, tool rules |

### Scanning order

```
Phase 1 (immediate):   Code AST scan → user starts working
Phase 2 (foreground):  JSON configs → bridge nodes created (fast)
Phase 3 (background):  Documents → linked to code AND JSON nodes
```

### Auto-linking

Documents are automatically linked to code:

1. **Exact match** (free) — `auth_service.py` mentioned in doc → `REFERENCED_IN` edge
2. **Fuzzy match** (free) — `AuthService` in doc ↔ `auth_service.py` in code
3. **Semantic match** (opt-in) — embedding similarity > threshold → edge
4. **LLM-assisted** (opt-in, budget-controlled) — structured relationship extraction

### Cross-source deduplication

When the same entity appears across code, docs, and configs:

```
Code:    verify_token()     ─┐
Doc:     "verifyToken"       ├── Unified into single node
Config:  verify-token        ─┘  (code is authoritative)
```

Source priority: Code > API spec > JSON config > User-taught > Documents.

### Contradiction detection

Finds stale docs nobody knew were wrong:

```
CONFIG  config/auth.json   timeout = 3600
DOC     docs/security.pdf  timeout = 1800
→ CONTRADICTION: numeric mismatch on "timeout"
```

---

## Auto-Scaling Backend

Graqle starts with JSON/NetworkX (zero deps, instant). When your graph grows:

| Graph size | Backend | What happens |
|-----------|---------|-------------|
| < 5,000 nodes | JSON/NetworkX | Default. Instant. Zero config. |
| 5,000+ nodes | Neo4j Community | **Auto-recommended.** Migration handled. Backup created. |
| Team/Enterprise | Neo4j / Neptune | Opt-in. Shared graphs, vector search, GDS analytics. |

The upgrade is transparent — same API, same CLI, same MCP tools. Just faster.

```bash
pip install graqle[neo4j]     # Adds neo4j driver
# Graqle auto-detects threshold and migrates
```

---

## Configuration

### Zero config (default — works for 80% of users)

```bash
pip install graqle && graq init    # Auto-detects everything
```

### Light config (power users)

```yaml
# graqle.yaml — only override what you need
model:
  backend: bedrock
  model: anthropic.claude-sonnet-4-6
  region: eu-central-1

scan:
  docs:
    extensions: [".pdf", ".md", ".txt"]
    linking:
      semantic: true           # Enable embedding-based linking
  json:
    categories:
      DATA_FILE: true          # Include data files (off by default)

cost:
  budget_per_query: 0.10
```

### Full config reference

<details>
<summary>Click to expand</summary>

```yaml
model:
  backend: local               # local, anthropic, openai, bedrock, gemini, groq, deepseek, mistral, +5 more
  model: Qwen/Qwen2.5-0.5B-Instruct
  quantization: none
  device: auto
  api_key: ${ANTHROPIC_API_KEY}
  region: ${AWS_DEFAULT_REGION}

graph:
  connector: networkx          # networkx, neo4j
  uri: bolt://localhost:7687
  username: neo4j
  password: ${NEO4J_PASSWORD}

activation:
  strategy: chunk              # chunk, pcst, full, top_k
  max_nodes: 50
  embedding_model: sentence-transformers/all-MiniLM-L6-v2

orchestration:
  max_rounds: 5
  min_rounds: 2
  convergence_threshold: 0.95

observer:
  enabled: true
  detect_conflicts: true
  detect_patterns: true
  use_llm_analysis: false

cost:
  budget_per_query: 0.10
  prefer_local: true
  fallback_to_api: true

scan:
  docs:
    enabled: true
    background: true
    extensions: [".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt"]
    exclude_patterns: []
    max_file_size_mb: 50.0
    chunk_max_chars: 1500
    chunk_overlap_chars: 100
    incremental: true
    linking:
      exact: true
      fuzzy: true
      semantic: false
      llm_assisted: false
      semantic_threshold: 0.70
      fuzzy_threshold: 0.60
    redaction:
      enabled: true
      redact_api_keys: true
      redact_passwords: true
      redact_tokens: true
  json:
    enabled: true
    auto_detect: true
    max_file_size_mb: 10.0
    categories:
      DEPENDENCY_MANIFEST: true
      API_SPEC: true
      TOOL_CONFIG: true
      APP_CONFIG: true
      INFRA_CONFIG: true
      SCHEMA_FILE: true
      DATA_FILE: false

logging:
  level: INFO
  trace_messages: true
  trace_dir: ./traces
```

</details>

---

## Why this works (and others don't)

Most "AI code tools" read files one at a time. That's fundamentally the wrong approach for architectural questions — you can't understand a system by reading files in isolation.

Graqle is different because:

**It understands relationships, not just text.** Your codebase is a graph of dependencies, ownership, and data flow. Graqle models that structure and reasons over it — so "what depends on auth?" traces actual dependency chains instead of grep-ing for the word "auth".

**It connects code to docs to configs.** When your ADR says "use JWT" but your config has "session auth", Graqle finds the contradiction. When your OpenAPI spec defines `/api/auth/login`, Graqle links it to your `auth_handler.py`. One graph, all sources.

**It's 541x cheaper.** Not estimated — measured. Reading 60 files costs ~50K tokens per query. Activating 3 graph nodes costs ~500. Over hundreds of queries per day, that's the difference between $50 and $0.09.

**It tells you what it doesn't know.** Every answer includes a confidence score calibrated for graph size. When confidence is low, Graqle explains which knowledge is missing — it doesn't guess and hope you don't notice.

**It scales itself.** Start with zero deps on a laptop. When your graph hits 5,000 nodes, Graqle auto-migrates to Neo4j — no config, no downtime, just a notification.

**It keeps learning.** The graph auto-discovers new connections, remembers which nodes produce useful answers for which query patterns, and gets smarter with every interaction. Your dev environment develops institutional memory.

---

## The numbers

| Metric | Graqle | Reading files | Difference |
|--------|--------|---------------|------------|
| Tokens per query | **500** | 50,000 | **100x fewer** |
| Cost per query | **$0.0003** | $0.15 | **541x cheaper** |
| Time to answer | **<5 seconds** | 20 minutes | — |
| Governance accuracy | **99.7%** | N/A | — |
| Tests passing | **1,484** | — | — |

---

## Installation

### Minimal (no API keys needed)

```bash
pip install graqle
```

### With LLM backends

```bash
pip install graqle[api]            # Anthropic + OpenAI + Bedrock
```

### With document scanning

```bash
pip install graqle[docs]           # PDF, DOCX, PPTX, XLSX
```

### Full install

```bash
pip install graqle[all]            # Everything: api, docs, neo4j, embeddings, gpu, studio
```

### Optional groups

| Group | What it adds | Use case |
|-------|-------------|----------|
| `api` | anthropic, openai, boto3 | Cloud LLM backends |
| `docs` | pdfplumber, python-docx, python-pptx, openpyxl | Rich document parsing |
| `neo4j` | neo4j driver | Graph database backend |
| `embeddings` | sentence-transformers | Local embedding models |
| `gpu` | torch, transformers, peft, vllm | GPU inference + LoRA |
| `cpu` | llama-cpp-python | CPU inference (GGUF models) |
| `studio` | fastapi, uvicorn, jinja2 | Visual dashboard |
| `dev` | pytest, ruff, mypy, coverage | Development |

---

## Backends

Use whatever model you want. Mix providers per task type — fast models for lookups, smart models for reasoning.

| Backend | Models | Cost | Setup |
|---------|--------|------|-------|
| **Ollama** | Qwen, Llama, Mistral (local) | **$0** | `backend: ollama` |
| **Anthropic** | Claude Sonnet / Haiku / Opus | ~$0.001/query | `backend: anthropic` |
| **OpenAI** | GPT-4o / GPT-4o-mini | ~$0.001/query | `backend: openai` |
| **AWS Bedrock** | Claude, Titan, Llama | AWS pricing | `backend: bedrock` |
| **Google Gemini** | Gemini 2.5 Pro / 2.0 Flash | ~$0.0001/query | `backend: gemini` |
| **Groq** | Llama 3.3 70B, Mixtral (fast) | ~$0.0005/query | `backend: groq` |
| **DeepSeek** | DeepSeek Chat / Reasoner | ~$0.0001/query | `backend: deepseek` |
| **Mistral** | Mistral Small / Large | ~$0.0002/query | `backend: mistral` |
| **Together** | Llama, Qwen, Mixtral | ~$0.0005/query | `backend: together` |
| **OpenRouter** | 100+ models via one key | Varies | `backend: openrouter` |
| **Fireworks** | Llama, Mixtral (fast) | ~$0.0005/query | `backend: fireworks` |
| **Cohere** | Command R / R+ | ~$0.0003/query | `backend: cohere` |
| **vLLM** | GPU inference + LoRA | Your GPU | `backend: local` |
| **llama.cpp** | GGUF models (CPU) | **$0** | `backend: local` |

```bash
graq setup-guide              # See all options
graq setup-guide ollama       # Free, local, no API key
graq doctor                   # Verify everything works + detect providers
```

### Task-based routing (v0.22.0)

Map different providers to different task types in `graqle.yaml`:

```yaml
routing:
  default_provider: groq
  rules:
    - task: reason
      provider: anthropic
      model: claude-sonnet-4-6
      reason: "Deep reasoning needs the best model"
    - task: context
      provider: groq
      model: llama-3.1-8b-instant
      reason: "Lookups are simple — use fast/cheap"
    - task: impact
      provider: deepseek
      model: deepseek-chat
```

Or via SDK:

```python
from graqle.backends.providers import create_provider_backend

groq = create_provider_backend("groq", model="llama-3.3-70b-versatile")
graph.set_default_backend(groq)
```

---

## Architecture

```
graqle/
├── core/                      # Graph engine
│   ├── graph.py               # Graqle class — main entry point
│   ├── node.py                # CogniNode — autonomous reasoning agent
│   └── edge.py                # CogniEdge — with message queue
├── backends/                  # LLM backends (Anthropic, OpenAI, Bedrock, Ollama, Gemini, Groq, DeepSeek, +7 more)
├── connectors/                # Graph storage (JSON, NetworkX, Neo4j)
│   └── upgrade.py             # Auto-upgrade advisor (5K node threshold)
├── scanner/                   # Multi-source scanning
│   ├── parsers/               # 6-format document parsers
│   ├── extractors/            # JSON category extractors (5 types)
│   ├── dedup/                 # 3-layer deduplication engine
│   ├── docs.py                # DocumentScanner orchestrator
│   ├── json_parser.py         # JSON classifier + scanner
│   ├── chunker.py             # Heading-aware document chunker
│   ├── linker.py              # Auto-linking (exact → fuzzy → semantic → LLM)
│   ├── manifest.py            # Incremental scan tracking
│   ├── background.py          # Background scan manager
│   ├── privacy.py             # PII/secrets redaction
│   ├── quality.py             # Document quality gate
│   ├── autodetect.py          # Environment auto-detection
│   └── nl_router.py           # Natural language query router
├── activation/                # Subgraph activation (Chunk, PCST, Top-K)
├── orchestration/             # Message passing + convergence
├── governance/                # SHACL/OWL validation
├── plugins/                   # MCP server
├── server/                    # REST API + Lambda handler
├── routing.py                 # Task-based model routing (v0.22)
├── cli/                       # CLI commands
└── config/                    # Pydantic settings + YAML loading
```

---

## Pricing

**Free for individuals. Always.**

| | Open Source | Team | Enterprise |
|---|:---:|:---:|:---:|
| **Price** | **$0 forever** | $29/dev/month | Custom |
| All 15 innovations | Yes | Yes | Yes |
| All MCP tools | Yes | Yes | Yes |
| Document scanning | Yes | Yes | Yes |
| JSON ingestion | Yes | Yes | Yes |
| Deduplication | Yes | Yes | Yes |
| All backends | Yes | Yes | Yes |
| CLI + SDK + API | Yes | Yes | Yes |
| Unlimited queries | Yes | Yes | Yes |
| Commercial use | Yes | Yes | Yes |
| Auto-scale to Neo4j | Yes | Yes | Yes |
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

## Quick start recipes

### Scan a Python project

```bash
pip install graqle[api]
cd my-python-project
graq init
graq reason "what depends on the database module?"
```

### Scan with documents

```bash
pip install graqle[api,docs]
cd my-project
graq scan all .               # Code + JSON + PDFs/DOCX (background)
graq scan wait                # Wait for doc scan to finish
graq reason "what does the architecture doc say about auth?"
```

### Ingest heavy docs on demand

```bash
graq learn doc ./compliance/        # Bulk ingest directory
graq learn doc architecture.pdf     # Single file
graq reason "what compliance requirements affect payments?"
```

### Use with Claude Code

```bash
graq init                     # Auto-writes .mcp.json
# Claude Code now has graq_context, graq_reason, graq_impact, etc.
```

### Use with Cursor

```bash
graq init --ide cursor        # Writes .cursor/mcp.json
# Cursor now has all Graqle MCP tools
```

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

```bash
git clone https://github.com/quantamixsol/graqle
cd graqle
pip install -e ".[dev]"
pytest                         # 1,655 tests
```

## License

[Apache 2.0](LICENSE) — use it commercially, modify it freely, keep the attribution.
