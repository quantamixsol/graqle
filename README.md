<!-- mcp-name: com.graqle/graqle -->
<div align="center">

# gra**Q**le

**Query your architecture, not your files.**

The dev intelligence layer that turns any codebase into a self-learning knowledge graph.<br/>
2,000+ tests. 396 modules compiled. 201 skills. Zero cloud required.

[![PyPI](https://img.shields.io/pypi/v/graqle?color=%2306b6d4&label=PyPI)](https://pypi.org/project/graqle/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-06b6d4.svg)](https://python.org)
[![Tests: 2000+ passing](https://img.shields.io/badge/tests-2000%2B%20passing-06b6d4.svg)]()
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache_2.0-06b6d4.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-compatible-06b6d4.svg)]()

[Website](https://graqle.com) · [PyPI](https://pypi.org/project/graqle/) · [GitHub](https://github.com/quantamixsol/graqle) · [Changelog](CHANGELOG.md)

</div>

---

## 3 commands. That's it.

```bash
pip install graqle[api]
graq init
graq reason "what breaks if I change auth?"
```

**3 nodes activated. 500 tokens. 5 seconds. $0.0003.**

Not 60 files. Not 50,000 tokens. Not $0.15. Not guessing.

---

## What Graqle does

Your AI assistant reads files one at a time. It doesn't understand your architecture — it reads text.

Graqle builds a **knowledge graph** of your entire codebase. Every module becomes a reasoning agent. When you ask a question, only the relevant nodes activate, reason about their domain, and synthesize one answer.

```
pip install graqle → graq init → Knowledge Graph
                                       │
             ┌──────────┬──────────────┼──────────┐
             ▼          ▼              ▼          ▼
           CLI      Python SDK     MCP Server  Studio UI
        (terminal)  (scripts)      (any IDE)   (dashboard)
```

**The graph is the product.** Your machine, your API keys, your data.

---

## What's new in v0.26.0

### Intelligence Compilation

Graqle now **compiles** your knowledge graph into actionable intelligence:

```bash
graq compile                    # Compile intelligence from your graph
```

This produces a `.graqle/intelligence/` directory with:
- **396 module packets** — risk scores, impact radius, consumers, dependencies
- **135 insights** — warnings, suggestions, connections, superlatives
- **Risk heatmap data** — LOW/MEDIUM/HIGH/CRITICAL per module
- **CLAUDE.md auto-injection** — your AI assistant learns your architecture automatically

### Governance Gate (DRACE)

Every reasoning session is scored on 5 axes: **D**ata quality, **R**elevance, **A**ccuracy, **C**ompleteness, **E**vidence strength.

```bash
graq verify                     # Pre-commit governance check
```

- Hash-chained audit trails (tamper-evident)
- Evidence chains linking decisions to source
- Scope gates preventing out-of-domain reasoning
- Auto-recompile when intelligence goes stale

### Multi-Signal Activation (Neo4j)

Gate + Rerank: semantic score gates everything, topology signals only amplify.

```
final = semantic × (1 + authority + memory + link + freshness)
```

Max amplification: 1.45×. An irrelevant node can never sneak through.

### Self-Learning Loop

```
graq learn → graph grows → git commit → auto-recompile → CLAUDE.md updates → AI gets smarter
```

The graph remembers which nodes produce useful answers. Gets better with every query.

### Studio Dashboards

6 new visual dashboards: Intelligence, Governance, Health, Learning, Control, Share.

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
# Reasoning
graq reason "what depends on auth?"          # Graph reasoning
graq context auth-lambda                      # 500-token focused context
graq inspect --stats                          # Graph statistics
graq "what is safe to refactor?"              # Natural language (auto-routed)

# Build & compile
graq init                                     # Scan repo, build graph, wire IDE
graq scan repo .                              # Rescan codebase
graq scan all .                               # Code + JSON + documents
graq compile                                  # Compile intelligence layer
graq verify                                   # Governance gate + staleness check

# Teach
graq learn node "auth-service" --type SERVICE
graq learn edge "Payments" "auth" -r DEPENDS_ON
graq learn discover --from "auth-service"     # Auto-discover connections
graq learn doc architecture.pdf               # Document ingestion

# Studio & server
graq studio                                   # Launch visual dashboard
graq serve                                    # Start REST API
graq doctor                                   # Health check
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

## Studio Dashboard

```bash
graq studio                        # Opens http://127.0.0.1:8888/studio/
```

| Page | What you see |
|------|-------------|
| **Intelligence** | Risk heatmap, module packets, 135 insights, impact matrix |
| **Governance** | DRACE radar chart, audit timeline, evidence chains, shareable badge |
| **Health** | Streak calendar, improvement suggestions, graph health trends |
| **Learning** | Skill activations, domain breakdown, recompile history |
| **Graph Explorer** | Interactive force-directed graph with intelligence overlay |
| **Control** | Multi-instance management, cross-repo insights |

---

## 14 backends, one config line

```yaml
# graqle.yaml
model:
  backend: groq    # or: anthropic, openai, bedrock, gemini, ollama, deepseek, mistral, ...
```

| Backend | Cost | Setup |
|---------|------|-------|
| **Ollama** | **$0** (local) | `backend: ollama` |
| **Anthropic** | ~$0.001/query | `backend: anthropic` |
| **OpenAI** | ~$0.001/query | `backend: openai` |
| **AWS Bedrock** | AWS pricing | `backend: bedrock` |
| **Google Gemini** | ~$0.0001/query | `backend: gemini` |
| **Groq** | ~$0.0005/query | `backend: groq` |
| **DeepSeek** | ~$0.0001/query | `backend: deepseek` |
| **Mistral** | ~$0.0002/query | `backend: mistral` |
| **Together** | ~$0.0005/query | `backend: together` |
| **OpenRouter** | Varies | `backend: openrouter` |
| **Fireworks** | ~$0.0005/query | `backend: fireworks` |
| **Cohere** | ~$0.0003/query | `backend: cohere` |
| **vLLM** | Your GPU | `backend: local` |
| **llama.cpp** | **$0** (CPU) | `backend: local` |

### Task-based routing

Different models for different tasks. Fast models for lookups, smart models for reasoning:

```yaml
routing:
  default_provider: groq
  rules:
    - task: reason
      provider: anthropic
      model: claude-sonnet-4-6
    - task: context
      provider: groq
      model: llama-3.1-8b-instant
```

---

## Auto-scaling backend

Graqle starts with JSON/NetworkX (zero deps). When your graph grows:

| Graph size | Backend | What happens |
|-----------|---------|-------------|
| < 5,000 nodes | JSON/NetworkX | Default. Instant. Zero config. |
| 5,000+ nodes | Neo4j | Auto-recommended. Migration handled. |
| Team/Enterprise | Neo4j + GDS | Vector search, PageRank, Adamic-Adar proximity. |

```bash
pip install graqle[neo4j]     # Adds neo4j driver — same API, just faster
```

---

## Document-aware intelligence

Graqle connects **code** to **documents** to **configs** in one graph.

| Source | Formats | What it extracts |
|--------|---------|-----------------|
| **Code** | Python, TypeScript, JavaScript, Go, Rust, Java | Functions, classes, modules, imports, call graphs |
| **Documents** | PDF, DOCX, PPTX, XLSX, Markdown, TXT | Sections, decisions, requirements, stakeholders |
| **JSON** | package.json, OpenAPI, tsconfig, CDK, SAM | Dependencies, endpoints, infrastructure resources |

Auto-linking: exact match, fuzzy match, semantic match, LLM-assisted. Cross-source deduplication. Contradiction detection.

---

## The numbers

| Metric | Graqle | Reading files |
|--------|--------|---------------|
| Tokens per query | **500** | 50,000 |
| Cost per query | **$0.0003** | $0.15 |
| Time to answer | **<5 seconds** | 20 minutes |
| Tests passing | **2,000+** | — |
| Modules compiled | **396** | — |
| Skills available | **201** | — |

---

## Installation

```bash
pip install graqle              # Minimal (no API keys needed)
pip install graqle[api]         # + Anthropic, OpenAI, Bedrock
pip install graqle[docs]        # + PDF, DOCX, PPTX, XLSX
pip install graqle[neo4j]       # + Neo4j graph database
pip install graqle[all]         # Everything
```

| Extra | What it adds |
|-------|-------------|
| `api` | anthropic, openai, boto3 |
| `docs` | pdfplumber, python-docx, python-pptx, openpyxl |
| `neo4j` | neo4j driver |
| `embeddings` | sentence-transformers |
| `gpu` | torch, transformers, peft, vllm |
| `cpu` | llama-cpp-python |
| `studio` | fastapi, uvicorn, jinja2 |
| `dev` | pytest, ruff, mypy, coverage |

---

## 15 Innovations (Patent EP26162901.8)

Every innovation is free under Apache 2.0.

| # | Innovation | Why it matters |
|---|-----------|----------------|
| 1 | Chunk-level semantic scoring | Finds the exact function, not the file |
| 2 | Zero-cost transparency | See which agents activated and why |
| 3 | Convergent message passing | Agents discuss until they agree |
| 4 | Backend fallback chain | Auto-switches models on failure |
| 5 | Topology-aware synthesis | Answers reflect graph structure |
| 6 | 3-layer governance (DRACE) | Domain boundaries on every output |
| 7 | Formula-based compliance | Quantitative scores, not pass/fail |
| 8 | Auto-generate ontologies | OWL+SHACL from your codebase |
| 9 | Adaptive activation | 3 nodes for simple, 50 for complex |
| 10 | Cross-query learning | Remembers what works for which patterns |
| 11 | Per-entity model selection | Security nodes use capable models |
| 12 | Retrieval-to-reasoning pipeline | Documents → graph reasoning |
| 13 | Hybrid skill matching | Regex precision + semantic flexibility |
| 14 | Neo4j vector + graph search | Embedding similarity + graph traversal in one query |
| 15 | Activation memory | Persistent cross-session node effectiveness |

---

## Quick start

```bash
# Python project
pip install graqle[api] && cd my-project && graq init
graq reason "what depends on the database module?"

# With documents
pip install graqle[api,docs]
graq scan all . && graq scan wait
graq reason "what does the architecture doc say about auth?"

# Claude Code (auto-wired)
graq init    # Claude Code now has graq_context, graq_reason, graq_impact, etc.

# Cursor
graq init --ide cursor
```

---

## Pricing

**Free for individuals. Always.**

| | Free ($0) | Pro ($19/mo) | Team ($29/dev/mo) |
|---|:---:|:---:|:---:|
| All 15 innovations | Yes | Yes | Yes |
| CLI + SDK + MCP + API | Yes | Yes | Yes |
| 14 LLM backends | Yes | Yes | Yes |
| Document scanning | Yes | Yes | Yes |
| Intelligence compilation | Yes | Yes | Yes |
| Studio dashboards | Basic | Full | Full + team |
| Governance (DRACE) | Current session | 30-session history | Unlimited |
| Audit trails | 3 sessions | 20 sessions | Unlimited |
| Health streaks | 7 days | Full year | Team streaks |
| Commercial use | Yes | Yes | Yes |

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

```bash
git clone https://github.com/quantamixsol/graqle
cd graqle
pip install -e ".[dev]"
pytest                         # 2,000+ tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, and PR guidelines.

## License

[Apache 2.0](LICENSE) — use it commercially, modify it freely, keep the attribution.
