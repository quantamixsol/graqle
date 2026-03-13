<div align="center">

# Graqle

**Your codebase has answers. Stop digging for them.**

Turn any codebase into a knowledge graph where every module is a reasoning agent.<br/>
One install. Any IDE. Any AI tool. Zero cloud infrastructure.

[![PyPI](https://img.shields.io/pypi/v/graqle?color=%2306b6d4&label=PyPI)](https://pypi.org/project/graqle/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-06b6d4.svg)](https://python.org)
[![Tests: 797 passing](https://img.shields.io/badge/tests-797%20passing-06b6d4.svg)]()
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

# Utilities
graq doctor                                   # Health check
graq setup-guide                              # Backend setup
graq serve                                    # Start REST API
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

## What's new in v0.16.0

- **Full rebrand:** `cognigraph` → `graqle`, `kogni` → `graq`
- **Backward compatible:** `pip install cognigraph` still works (installs graqle automatically)
- **All v0.15.0 features carried forward:** MCP hot-reload, confidence recalibration, business entity support, multi-project CLI

See the [full changelog](#changelog) below.

<details>
<summary><strong>Changelog</strong></summary>

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
