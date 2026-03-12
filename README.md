<div align="center">

# CogniGraph

### Dev Intelligence Layer — Graphs That Think

Turn any codebase into a reasoning-ready knowledge graph.<br/>
One command. Any IDE. Any AI tool. Zero cloud infrastructure.

[![PyPI version](https://badge.fury.io/py/cognigraph.svg)](https://pypi.org/project/cognigraph/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Tests: 554 passing](https://img.shields.io/badge/tests-554%20passing-brightgreen.svg)]()
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
kogni doctor                                        # Health check
kogni setup-guide                                   # Backend setup help
```

### Python SDK (any Python environment)
```python
from cognigraph import CogniGraph
from cognigraph.backends.api import AnthropicBackend

graph = CogniGraph.from_json("cognigraph.json")
graph.set_default_backend(AnthropicBackend(model="claude-haiku-4-5-20251001"))

result = graph.reason("How does GDPR conflict with the AI Act?")
print(result.answer)          # Multi-agent synthesized answer
print(f"Cost: ${result.cost_usd:.4f}")  # Transparent cost tracking
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

## 13 Innovations (Patent EP26162901.8)

| # | Innovation | What it does |
|---|-----------|-------------|
| 1 | **PCST Activation** | Sublinear subgraph selection — only wake relevant nodes |
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

All 13 innovations are **free for every developer**. No license key required.

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
| All 13 innovations | ✓ | ✓ | ✓ |
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

The **SemanticSHACLGate** enforces 3-layer semantic validation on every reasoning output:

1. **Framework Fidelity** — agents cite correct regulatory frameworks
2. **Scope Boundary** — responses stay within assigned domain
3. **Cross-Reference Integrity** — proper attribution across domains

**MultiGov-30 benchmark: 99.7% governance accuracy** (FF: 100%, SB: 100%, CR: 98.3%).

---

## Patent & IP Notice

CogniGraph implements methods described in **European Patent Application EP26162901.8** (filed 6 March 2026, Quantamix Solutions B.V.). See [NOTICE](NOTICE) for details.

All 13 innovations are free to use under Apache 2.0. The patent protects the specific methods — you can use CogniGraph freely in any project, commercial or otherwise.

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
