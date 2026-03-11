<div align="center">

# CogniGraph

### Graphs That Think — Self-Governing Development for Claude Code

Turn any codebase into a governed, self-improving reasoning network.<br/>
One command. Full governance. Zero cloud infrastructure.

[![PyPI version](https://badge.fury.io/py/cognigraph.svg)](https://pypi.org/project/cognigraph/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Tests: 332 passing](https://img.shields.io/badge/tests-332%20passing-brightgreen.svg)]()
[![MCP Compatible](https://img.shields.io/badge/MCP-compatible-8A2BE2.svg)]()
[![Patent: EP26162901.8](https://img.shields.io/badge/patent-EP26162901.8-orange.svg)](NOTICE)

</div>

---

> **What if your development environment learned from every mistake and never repeated one?**
>
> CogniGraph is the first self-governing development tool. It transforms any knowledge graph into a reasoning network where each node is an autonomous LLM agent — then wraps your Claude Code sessions in structured protocols that enforce spec-before-code, atomic commits, and autonomous fix-test-fix loops. Install it, run `kogni init`, and your dev environment starts getting smarter every session.

---

## Quick Start

```bash
pip install cognigraph[api]
cd your-project
kogni init
```

That's it. CogniGraph scans your repo, builds a knowledge graph, creates a governed `CLAUDE.md`, and registers an MCP server. Open Claude Code and you're running with:

- **GCC** — session continuity, branch management, auto-commits
- **GSD** — structured DISCUSS → PLAN → EXECUTE → VERIFY workflow
- **Ralph Loop** — autonomous fix-test-fix iteration with safety guards
- **MCP tools** — governed graph reasoning inside Claude Code

No cloud account. No infrastructure. Your machine, your API keys, your data.

---

## What You Get

| Tool | What it does |
|------|-------------|
| `kogni init` | Scans repo, builds KG, injects governance protocols into CLAUDE.md |
| `kogni_context` | 500-token focused context for any entity (replaces 20-60K brute-force loading) |
| `kogni_reason` | Governed multi-agent reasoning over your knowledge graph |
| `kogni_inspect` | Graph structure inspection — nodes, edges, hubs, types |
| `kogni_search` | Semantic search across all KG nodes |
| `kogni run` | CLI reasoning query against any graph |
| `kogni serve` | REST API server with API key auth |

---

## How It Works

```
pip install → kogni init → Claude Code opens → MCP tools available
                                    ↓
                         GCC protocols injected
                         (session memory, branch management, auto-commits)
                                    ↓
                         GSD workflow active
                         (spec before code, atomic commits, verification)
                                    ↓
                         Ralph Loop ready
                         (autonomous iteration with binary criteria)
                                    ↓
                         Graph learns from every session
                         (Bayesian edge updates, convergence tracking)
```

---

## 13 Patent-Protected Innovations

| # | Innovation | Module |
|---|-----------|--------|
| 1 | **PCST Activation** — sublinear subgraph selection | `cognigraph.activation.pcst` |
| 2 | **MasterObserver** — zero-cost transparency layer | `cognigraph.orchestration.observer` |
| 3 | **Convergent Message Passing** — similarity-based termination | `cognigraph.orchestration.convergence` |
| 4 | **Backend Fallback Chain** — heterogeneous inference with cost budgets | `cognigraph.backends.fallback` |
| 5 | **Hierarchical Aggregation** — centrality-based topology-aware synthesis | `cognigraph.orchestration.aggregation` |
| 6 | **SemanticSHACLGate** — 3-layer OWL-aware governance | `cognigraph.ontology.semantic_shacl_gate` |
| 7 | **Constrained F1** — joint answer quality + governance metric | `cognigraph.benchmarks.constrained_f1` |
| 8 | **OntologyGenerator** — automated OWL+SHACL from regulation text | `cognigraph.ontology.generator` |
| 9 | **Adaptive Activation** — dynamic Kmax from query complexity | `cognigraph.activation.adaptive` |
| 10 | **Online Graph Learning** — Bayesian edge weight updates | `cognigraph.learning.graph_learner` |
| 11 | **LoRA Auto-Selection** — per-entity adapter matching | `cognigraph.adapters.auto_select` |
| 12 | **TAMR+ Connector** — retrieval-to-reasoning pipeline | `cognigraph.connectors.tamr` |
| 13 | **MCP Plugin** — governed context engineering for Claude Code | `cognigraph.plugins.mcp_server` |

---

## The Three Protocols

### GCC — Global Context Controller

Your Claude Code sessions have memory now. GCC gives every session structured continuity:

```
Session starts → reads last commit + branch state (~700 tokens)
Work happens   → auto-commits every 30 minutes
Session ends   → checkpoints progress, clears session log
Next session   → resumes in under 60 seconds from last checkpoint
```

No more re-explaining your codebase. No more lost context between sessions.

### GSD — Get Shit Done

Spec before code. Every significant feature follows a structured workflow:

```
DISCUSS  →  What problem? What constraints? What's in scope?
PLAN     →  Atomic tasks, dependency graph, verification criteria
EXECUTE  →  One task = one commit, tests pass before moving on
VERIFY   →  3-source check: evidence vs plan vs success criteria
```

Scope creep gets captured in "deferred" — never mid-sprint.

### Ralph Loop — Autonomous Iteration

Feed a task with binary completion criteria. Ralph works until done or blocked:

```python
# Binary criteria: "All tests pass. Build succeeds. No console errors."
# Ralph iterates: fix → test → check → fix → test → check → DONE
# Safety: max 20 iterations, no force-push, no deploy to main
```

Each iteration produces a GCC commit. If blocked after N attempts, Ralph stops and reports what it tried.

---

## Backends

| Backend | Models | Install |
|---------|--------|---------|
| **Anthropic** | Claude Haiku / Sonnet / Opus | `pip install cognigraph[api]` |
| **OpenAI** | GPT-4o / GPT-4o-mini | `pip install cognigraph[api]` |
| **AWS Bedrock** | Any Bedrock model | `pip install cognigraph[api]` |
| **Ollama** | Any local model | `pip install cognigraph[api]` |
| **vLLM** | GPU inference + LoRA | `pip install cognigraph[gpu]` |
| **llama.cpp** | CPU GGUF models | `pip install cognigraph[cpu]` |

Smart routing sends complex queries to capable models and simple queries to cheap ones — all within your cost budget.

```python
from cognigraph.backends.fallback import BackendFallbackChain

chain = BackendFallbackChain([
    AnthropicBackend(model="claude-haiku-4-5-20251001"),
    OllamaBackend(model="qwen2.5:0.5b"),
])
# Tries Anthropic first → falls back to local Ollama automatically
```

---

## Free vs Pro

| Feature | Free | Pro |
|---------|------|-----|
| Innovations 1-5 (PCST, Observer, Convergence, Fallback, Aggregation) | Yes | Yes |
| Innovations 6-13 (SemanticSHACL, Graph Learning, LoRA, TAMR+, MCP) | — | Yes |
| GCC / GSD / Ralph protocols | Yes | Yes |
| `kogni init` + CLAUDE.md generation | Yes | Yes |
| MCP tools (context, reason, inspect, search) | Basic | Full |
| Online graph learning (Bayesian edge updates) | — | Yes |
| SemanticSHACLGate governance | — | Yes |
| LoRA auto-selection | — | Yes |
| REST API server | Yes | Yes |
| Commercial use | Yes | Yes |

---

## Governance

The **SemanticSHACLGate** enforces 3-layer semantic validation on every reasoning output:

1. **Framework Fidelity** — agents cite correct regulatory frameworks
2. **Scope Boundary** — responses stay within assigned domain
3. **Cross-Reference Integrity** — proper attribution for cross-framework mentions

**MultiGov-30 benchmark: 99.7% governance accuracy** (FF: 100%, SB: 100%, CR: 98.3%).

---

## Benchmarks

| Metric | CogniGraph | Single-Agent Baseline | Improvement |
|--------|-----------|----------------------|-------------|
| Constrained F1 | **0.757** | 0.328 | **+131%** |
| Governance Accuracy | **99.7%** | N/A | — |
| Token Efficiency | **500 tokens/query** | 20-60K tokens | **40-120x** |

---

## Python API

```python
from cognigraph import CogniGraph
from cognigraph.backends.api import AnthropicBackend

graph = CogniGraph.from_json("knowledge_graph.json")
graph.set_default_backend(AnthropicBackend(model="claude-haiku-4-5-20251001"))

result = graph.reason("How does GDPR conflict with the AI Act?")
print(result.answer)
print(f"Confidence: {result.confidence:.2f}")
print(f"Governance: {result.governance_score:.3f}")
print(f"Cost: ${result.cost_usd:.4f}")
```

---

## Patent & IP Notice

CogniGraph implements methods described in **European Patent Application EP26162901.8** (filed 6 March 2026, Quantamix Solutions B.V.). See [NOTICE](NOTICE) for full details.

Academic and research use is freely permitted under Apache 2.0.

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
