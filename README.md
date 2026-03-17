<!-- mcp-name: com.graqle/graqle -->
<div align="center">

# gra**Q**le

### Give your AI a brain that understands your code.

Claude, Cursor, Copilot — they read files. Graqle gives them a knowledge graph
of your entire architecture. 500 tokens instead of 50,000. Real answers instead of guesses.

[![PyPI](https://img.shields.io/pypi/v/graqle?color=%2306b6d4&label=PyPI)](https://pypi.org/project/graqle/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-06b6d4.svg)](https://python.org)
[![Tests: 2009 passing](https://img.shields.io/badge/tests-2009%20passing-06b6d4.svg)]()
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache_2.0-06b6d4.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-compatible-06b6d4.svg)]()

[Website](https://graqle.com) · [Dashboard](https://graqle.com/dashboard) · [PyPI](https://pypi.org/project/graqle/) · [Changelog](CHANGELOG.md)

</div>

---

## The vibe coding wall

You're deep in flow. Claude/Cursor/Copilot is writing code. You ask: *"What breaks if I change auth?"*

Your AI reads 60 files. Burns 50,000 tokens. Takes 3 minutes. **And still guesses** — because reading files is not understanding architecture.

```bash
pip install graqle && graq init
```

**Your AI is now architecture-aware. 500 tokens. 5 seconds. $0.0003. Verified answer with confidence score.**

---

## How it works (30 seconds)

```
Step 1:  graq init                              # Scans your repo → builds knowledge graph → auto-wires MCP into your IDE
Step 2:  Ask your AI anything                   # Claude/Cursor/Copilot now uses graq_reason, graq_impact, graq_context
Step 3:  graq studio                            # See your architecture as an interactive visual dashboard
```

Graqle turns your codebase into a graph. Every module becomes a reasoning agent. When your AI asks a question, only the relevant nodes activate, reason about their domain, and synthesize one precise answer.

**Your machine. Your API keys. Your data. Works offline.**

---

## Your AI is fast. But is it right?

Vibe coding is incredible — until your AI breaks something it didn't understand. It reads files one at a time, has no idea what connects to what, and burns 50K tokens to give you a guess.

The answer isn't a smarter model. It's giving your model the right context.

| Your AI without Graqle | Your AI with Graqle |
|------------------------|-------------------|
| Reads random files hoping to find context | Queries a graph that **knows** the relationships |
| Burns 50K tokens per question | Uses 500 tokens (100x reduction) |
| Loses context when conversation gets long | Graph persists — context is never lost |
| Can't trace dependencies | `graq_impact` shows the full blast radius |
| Repeats past mistakes | `graq_lessons` surfaces them before you do |
| Forgets what you taught it | `graq_learn` — the graph remembers everything |
| Same answers no matter how much you use it | Self-learning — gets smarter with every query |

---

## Make your AI actually understand your code

### Your AI assistant, supercharged

One command and your AI gets 7 new superpowers via MCP. It stops reading files and starts querying a knowledge graph. Same AI, dramatically better answers.

| IDE | Setup | What happens |
|-----|-------|-------------|
| **Claude Code** | `graq init` | MCP tools auto-wired. Done. |
| **Cursor** | `graq init --ide cursor` | MCP + .cursorrules injected |
| **VS Code + Copilot** | `graq init --ide vscode` | MCP server configured |
| **Windsurf** | `graq init --ide windsurf` | MCP + .windsurfrules |
| **Any IDE** | `graq init --ide generic` | CLI works everywhere |

After `graq init`, your AI automatically gets these graph-powered tools:

| MCP Tool | What it does | Why vibe coders love it |
|----------|-------------|----------------------|
| `graq_context` | 500-token focused context | Replaces pasting files into chat |
| `graq_reason` | Multi-agent graph reasoning | Architecture answers, not file answers |
| `graq_impact` | "What breaks if I change X?" | No more accidental breakage |
| `graq_preflight` | Pre-change safety check | Confidence before committing |
| `graq_lessons` | Past mistakes | Stops you from repeating them |
| `graq_learn` | Teach the graph | It remembers what you tell it |
| `graq_inspect` | Graph stats | Know your codebase at a glance |

---

### 100x fewer tokens. 500x cheaper.

Your AI reads 60 files per question — 50,000 tokens, $0.15 each. Graqle gives it exactly the right 500 tokens of structured context. Same question, 100x less context, better answer. For a team of 10, that's $9,000/year saved.

| | Graqle | Reading files |
|---|:---:|:---:|
| Tokens per query | **500** | 50,000 |
| Cost per query | **$0.0003** | $0.15 |
| Time to answer | **5 sec** | 3+ min |
| Confidence scored | **Yes** | No |

---

### Confidence scores. Not vibes.

Every answer comes with a confidence percentage, which graph nodes were consulted, and exact token cost. When confidence is low, Graqle tells you what's missing — no more "I think this is how it works." You ship decisions based on evidence.

---

### Self-learning — the graph gets smarter

```
You code → graq learn → graph grows → auto-recompile → AI gets smarter → you code better → repeat
```

Other tools give static analysis. Graqle gives you a **living knowledge graph** that evolves with your codebase. It remembers which answers worked. Which nodes are most useful. Which patterns lead to bugs.

---

### Intelligence compilation

```bash
graq compile
```

One command. Your entire codebase analyzed:

- **Risk scores per module** — know which code is dangerous to touch
- **Impact radius** — how many modules break when this one changes
- **135 actionable insights** — warnings you'd never find manually
- **CLAUDE.md auto-injection** — your AI learns your architecture automatically

The difference between "AI that reads your code" and "AI that understands your system."

---

### Governed AI. Audit everything. (DRACE)

Every AI decision is scored on 5 axes: **D**ata quality, **R**elevance, **A**ccuracy, **C**ompleteness, **E**vidence.

- Tamper-evident audit trails (hash-chained)
- Evidence linking every answer to source code
- Scope gates preventing cross-domain hallucination
- `graq verify` — governance gate before you deploy

Your team lead asks: *"How do we know the AI isn't hallucinating?"*
You show them the DRACE dashboard.

---

### Your machine. Your keys. Your data.

Run offline with Ollama ($0). Use your own Claude, GPT-4, or Gemini keys. Deploy on Bedrock for enterprise. 14 backends, one config line. Graqle never phones home — your code stays on your infrastructure.

---

## Cloud sync (new in v0.29.0)

```bash
graq login --api-key grq_your_key             # Get key at graqle.com/dashboard/account
graq cloud push                               # Graph appears on graqle.com/dashboard
graq cloud pull                               # Download on any machine
graq cloud status                             # See all your projects
```

Your knowledge graph follows you. Push from your laptop, pull on your workstation. View it on [graqle.com/dashboard](https://graqle.com/dashboard). Share with your team.

---

## 14 backends, one config line

```yaml
# graqle.yaml
model:
  backend: groq    # or: anthropic, openai, bedrock, gemini, ollama, deepseek, ...
```

| Backend | Cost | Best for |
|---------|------|----------|
| **Ollama** | $0 (local) | Privacy, offline |
| **Groq** | ~$0.0005/q | Speed |
| **DeepSeek** | ~$0.0001/q | Budget |
| **Anthropic** | ~$0.001/q | Reasoning |
| **Gemini** | ~$0.0001/q | Long context |
| **OpenAI** | ~$0.001/q | GPT-4o |
| + 8 more | Various | Bedrock, Mistral, Together, Fireworks, Cohere, OpenRouter, vLLM, llama.cpp |

**Smart routing** — fast models for lookups, smart models for reasoning:

```yaml
routing:
  default_provider: groq                 # Fast + cheap for most queries
  rules:
    - task: reason
      provider: anthropic                # Claude for complex reasoning
    - task: context
      provider: groq                     # Groq for instant lookups
```

---

## Visual Studio (graqle.com)

```bash
graq studio                                   # Local dashboard
# or visit graqle.com/dashboard               # Cloud dashboard
```

| Dashboard | What you see |
|-----------|-------------|
| **Graph Explorer** | Interactive force graph — your architecture, visualized |
| **Intelligence** | Risk heatmap, module packets, insights |
| **Governance** | DRACE radar, audit timeline, evidence chains |
| **Reasoning** | Live sessions with streaming + confidence |
| **Control Plane** | All projects in one view |
| **Account** | API keys, connected projects, plan |

---

## The numbers

| Graqle stats | |
|---|---|
| Tests passing | 2,009 |
| Modules compiled | 396 |
| Skills available | 201 |
| LLM backends | 14 |
| Patented innovations | 15 |

---

## Complete CLI

```bash
# Reasoning
graq reason "what depends on auth?"          # Graph-powered reasoning
graq context auth-module                      # 500-token focused context
graq impact auth-module                       # What breaks if this changes?
graq "what is safe to refactor?"              # Natural language (auto-routed)

# Build & maintain
graq init                                     # Scan + build graph + wire IDE
graq scan repo .                              # Rescan codebase
graq compile                                  # Compile intelligence layer
graq verify                                   # Governance check

# Teach
graq learn node "auth-service" --type SERVICE
graq learn edge "payments" "auth" -r DEPENDS_ON
graq learn doc architecture.pdf               # Ingest documents

# Cloud (new in v0.29.0)
graq login --api-key grq_your_key             # Connect to cloud
graq cloud push                               # Upload graph
graq cloud pull                               # Download graph
graq cloud status                             # List projects

# Studio
graq studio                                   # Visual dashboard
graq serve                                    # REST API
graq doctor                                   # Health check
```

## Python SDK

```python
from graqle.core.graph import Graqle
from graqle.backends.api import AnthropicBackend

graph = Graqle.from_json("graqle.json")
graph.set_default_backend(AnthropicBackend(model="claude-sonnet-4-6"))

result = graph.reason("What services depend on auth?", max_rounds=3)
print(result.answer)            # Precise, graph-reasoned answer
print(f"{result.confidence:.0%} confidence, ${result.cost_usd:.4f}")
```

---

## Installation

```bash
pip install graqle              # Core — zero cloud dependencies
pip install graqle[api]         # + Anthropic, OpenAI, Bedrock
pip install graqle[docs]        # + PDF, DOCX, PPTX, XLSX
pip install graqle[neo4j]       # + Neo4j at scale
pip install graqle[all]         # Everything
```

Auto-scales: starts with JSON (zero deps), recommends Neo4j at 5,000+ nodes.

---

## What Graqle understands

| Source | Formats |
|--------|---------|
| **Code** | Python, TypeScript, JavaScript, Go, Rust, Java |
| **Documents** | PDF, DOCX, PPTX, XLSX, Markdown |
| **Configs** | package.json, OpenAPI, tsconfig, CDK, SAM |

Cross-source linking. Deduplication. Contradiction detection. Automatic.

---

## Pricing

**Free forever for individual developers.**

| | Free ($0) | Pro ($19/mo) | Team ($29/dev/mo) |
|---|:---:|:---:|:---:|
| CLI + SDK + MCP + Studio | Yes | Yes | Yes |
| All 14 backends | Yes | Yes | Yes |
| Intelligence + governance | Yes | Yes | Yes |
| Graph nodes | 500 | 25,000 | Unlimited |
| Cloud projects | 1 | 3 | Unlimited |
| Reasoning sessions | 3/month | 100/month | Unlimited |
| Team features | -- | -- | Shared graphs, leaderboard |

**[Start free at graqle.com](https://graqle.com)**

---

## FAQ

**I already use Cursor / Claude Code / Copilot. Why do I need this?**
Graqle doesn't replace your AI — it makes it dramatically better. Your AI reads files one at a time and guesses at relationships. With Graqle, it queries a knowledge graph that knows your architecture. Same AI, 100x fewer tokens, real answers. Zero workflow change — plugs in via MCP.

**How fast is the setup?**
Two commands: `pip install graqle && graq init`. Under 10 seconds. No config files, no schema, no cloud accounts. Scans your code, builds the graph, wires MCP tools into your IDE automatically.

**My AI already gives decent answers. What's different?**
Ask "what breaks if I change auth?" — your AI will read random files and guess. Graqle traverses the actual dependency graph, finds the 3 modules that consume auth, tells you exactly what breaks — with a confidence score. Searching vs understanding.

**Is it free? Actually free?**
Yes. Apache 2.0 — all 15 patented innovations, every MCP tool, all 14 backends. Free tier is the full product. We monetize team features. No trials. No credit card.

**Does my code leave my machine?**
Never. Runs entirely on your machine. No cloud. No telemetry. Use your own API keys or run offline with Ollama. Cloud sync is opt-in and only uploads the graph structure, never source code.

---

## 15 patented innovations, all open source

European Patent EP26162901.8. Every innovation is free under Apache 2.0.

Chunk-level scoring, convergent message passing, 3-layer governance, adaptive activation, cross-query learning, topology-aware synthesis, and 9 more. [Full list](CHANGELOG.md).

---

<div align="center">

### Your AI is only as good as the context you give it.

### Give it your architecture.

```bash
pip install graqle[api] && graq init
```

**[graqle.com](https://graqle.com)**

Made by [Quantamix Solutions B.V.](https://quantamixsolutions.com)

</div>

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
git clone https://github.com/quantamixsol/graqle && cd graqle
pip install -e ".[dev]" && pytest    # 2,009 tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

[Apache 2.0](LICENSE) — commercial use, modification, distribution. Keep attribution.
