<div align="center">

# gra**Q**le

### Code intelligence that understands your architecture.

Your AI reads files. Graqle gives it a knowledge graph of your entire codebase —
dependencies, impact paths, and institutional memory — so it reasons over structure, not strings.

[![PyPI](https://img.shields.io/pypi/v/graqle?color=%2306b6d4&label=PyPI)](https://pypi.org/project/graqle/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-06b6d4.svg)](https://python.org)
[![Tests: 2020 passing](https://img.shields.io/badge/tests-1%2C700%2B%20passing-06b6d4.svg)]()
[![License](https://img.shields.io/badge/license-Proprietary-06b6d4.svg)](https://github.com/quantamixsol/graqle/blob/master/LICENSE)
[![Patent: EP26162901.8](https://img.shields.io/badge/Patent-EP26162901.8-orange.svg)](https://quantamixsolutions.com/patents)
[![Patent: EP26166054.2](https://img.shields.io/badge/Patent-EP26166054.2-orange.svg)](https://quantamixsolutions.com/patents)
[![Downloads](https://img.shields.io/pypi/dm/graqle?color=06b6d4)](https://pypi.org/project/graqle/)
[![GitHub stars](https://img.shields.io/github/stars/quantamixsol/graqle?style=social)](https://github.com/quantamixsol/graqle)

```bash
pip install graqle && graq scan repo . && graq run "what depends on auth?"
```

[Website](https://graqle.com) · [Dashboard](https://graqle.com/dashboard) · [PyPI](https://pypi.org/project/graqle/) · [Changelog](CHANGELOG.md)

</div>

---

## Table of Contents

- [Why Graqle](#why-graqle)
- [Quick Start](#quick-start-60-seconds)
- [What You Can Do](#what-you-can-do)
- [IDE Integration (MCP)](#ide-integration-mcp)
- [14 LLM Backends](#14-llm-backends)
- [Architecture](#architecture)
- [What Graqle Understands](#what-graqle-understands)
- [Installation Options](#installation-options)
- [CLI Reference](#cli-reference)
- [SCORCH — UX Friction Auditing](#scorch--ux-friction-auditing)
- [Python SDK](#python-sdk)
- [Cloud Sync](#cloud-sync)
- [Pricing](#pricing)
- [System Requirements](#system-requirements)
- [Security & Privacy](#security--privacy)
- [Contributing](#contributing)
- [FAQ](#faq)
- [License & Innovation](#license--innovation)

---

## Why Graqle

### The problem

AI coding tools are fast but structurally blind. They see files, not architecture. They read 60 files to answer a dependency question — burning 50,000 tokens, taking minutes, and still guessing. They forget everything between sessions. They cannot tell you what breaks before you break it.

This is not a model problem. It is a context problem.

### The solution

Graqle builds a knowledge graph from your codebase that any AI tool can reason over. Every module becomes a node. Every import, call, and dependency becomes an edge. Instead of reading raw files, your AI queries the graph — getting precise, structured context in 500 tokens instead of 50,000.

The graph tracks dependencies, maps impact paths, remembers lessons, and improves with every query you run.

### Before and after

| | Without Graqle | With Graqle |
|---|---|---|
| **"What depends on auth?"** | AI reads 60 files, guesses | Graph traversal, exact answer in 5s |
| **Tokens per question** | 50,000 | 500 |
| **Cost per question** | ~$0.15 | ~$0.0003 |
| **Impact analysis** | Manual grep + hope | `graq impact auth.py` — full blast radius |
| **Institutional memory** | Buried in Slack threads | `graq learn` — the graph remembers |
| **Cross-session context** | Lost when chat resets | Persistent knowledge graph |
| **Confidence in answers** | "I think..." | Confidence score + evidence chain |

### Who uses Graqle

- **Individual developers** working with AI coding assistants who want better answers, faster
- **Engineering teams** who need dependency analysis and impact tracking across shared codebases
- **Open source maintainers** who want contributors to understand architecture without reading every file
- **Tech leads and architects** who need governed AI reasoning with audit trails

---

## Quick Start (60 seconds)

**Prerequisites:** Python 3.10+

```bash
# Install
pip install graqle

# Scan your codebase and build the knowledge graph
graq scan repo .

# Ask anything about your architecture
graq run "what does the auth module depend on?"
```

Connect to your IDE in one command:

```bash
graq init                          # Claude Code — auto-wires MCP tools
graq init --ide cursor             # Cursor — MCP + .cursorrules
graq init --ide vscode             # VS Code + Copilot
graq init --ide windsurf           # Windsurf — MCP + .windsurfrules
```

Your AI now has architecture-aware tools. No workflow change — it uses them automatically.

---

## What You Can Do

### Understand your codebase

```bash
graq run "explain the payment flow end to end"
graq context auth-module           # 500-token focused context for any module
```

Ask architectural questions in plain English. Graqle reasons over the dependency graph, not raw files.

### Analyze impact before changes

```bash
graq impact auth.py
# → Shows: 3 direct consumers, 11 transitive dependencies, risk: HIGH
```

See every affected module before you touch a line of code. No more "I didn't realize that was connected."

### Get safety checks before refactoring

```bash
graq preflight "refactor the database layer"
# → Warnings: 4 modules depend on connection pool, 2 have no tests
```

Governance-aware preflight checks surface risks before you commit, not after you deploy.

### Build institutional memory

```bash
graq learn "auth module requires refresh token rotation — never skip it"
graq lessons auth
# → Returns lessons learned, ranked by relevance
```

The graph remembers what your team learns. New developers and AI assistants inherit that knowledge automatically.

### Connect your AI tools

```bash
graq init                          # MCP server with 16 tools for Claude, Cursor, Copilot
```

Your AI assistant gets graph-powered reasoning, impact analysis, and safety checks — all through the standard MCP protocol.

### Cross-project analysis

```bash
graq link merge ../backend ../frontend    # Merge graphs from multiple repos
graq link infer                           # Discover cross-project dependencies
graq link stats                           # See how your projects connect
```

Monorepo or multi-repo — Graqle maps relationships across boundaries.

### Compile intelligence

```bash
graq compile
# → Risk scores, impact radii, 135+ actionable insights, CLAUDE.md auto-injection
```

One command produces a full intelligence report: risk heatmaps, module rankings, and auto-generated context files your AI tools consume directly.

### Audit UX friction automatically

```bash
pip install "graqle[scorch]" && python -m playwright install chromium
graq scorch run --url http://localhost:3000
# → 5-phase audit: screenshots, CSS metrics, 12 behavioral tests, Claude Vision, journey score
# → Findings auto-added to your knowledge graph
```

SCORCH v3 — Graqle's first-party UX audit plugin. 12 behavioral friction tests, 6 archetype classifications, and Claude Vision journey psychology. Runs from CLI, MCP, or Python. [Full details below](#scorch--ux-friction-auditing).

---

## IDE Integration (MCP)

Graqle implements the [Model Context Protocol](https://modelcontextprotocol.io/) so any MCP-compatible IDE can query your knowledge graph directly.

### Setup

**Claude Code** — add to `~/.claude/claude_code_config.json`:
```json
{
  "mcpServers": {
    "graqle": {
      "command": "graq",
      "args": ["mcp", "serve"]
    }
  }
}
```

**Cursor** — add to `.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "graqle": {
      "command": "graq",
      "args": ["mcp", "serve"]
    }
  }
}
```

**VS Code + Copilot** — add to `.vscode/mcp.json`:
```json
{
  "servers": {
    "graqle": {
      "command": "graq",
      "args": ["mcp", "serve"]
    }
  }
}
```

**If `graq` is not on your PATH** (common on Windows / WSL / virtualenv), use the universal Python fallback:
```json
{
  "mcpServers": {
    "graqle": {
      "command": "python",
      "args": ["-m", "graqle.cli.main", "mcp", "serve"]
    }
  }
}
```

Or skip manual config entirely: `graq init` auto-detects your IDE and wires everything.

### Available MCP Tools

| Tool | Description | Tier |
|------|-------------|------|
| `graq_context` | Focused context for a module (~500 tokens) | Free |
| `graq_inspect` | Graph structure: nodes, edges, stats | Free |
| `graq_reason` | Multi-agent graph reasoning | Free |
| `graq_reason_batch` | Batch reasoning over multiple queries | Free |
| `graq_preflight` | Governance check before code changes | Pro |
| `graq_lessons` | Query relevant lessons and past mistakes | Pro |
| `graq_impact` | Trace downstream impact through the dependency graph | Pro |
| `graq_safety_check` | Pre-change safety analysis with risk scoring | Pro |
| `graq_learn` | Record outcomes for graph learning | Pro |
| `graq_reload` | Hot-reload the knowledge graph | Free |
| `graq_audit` | Retrieve audit trail for any reasoning session | Pro |
| `graq_gate` | Governance gate check (pass/fail) | Pro |
| `graq_drace` | Quality scoring across 5 governance dimensions | Pro |
| `graq_runtime` | Runtime configuration and diagnostics | Free |
| `graq_route` | Task routing information across backends | Free |
| `graq_lifecycle` | Module lifecycle and deprecation tracking | Pro |
| `graq_scorch_audit` | Full SCORCH v3 UX audit (5-phase pipeline) | Pro |
| `graq_scorch_behavioral` | 12 behavioral UX friction tests (no AI cost) | Free |
| `graq_scorch_report` | Read and summarize a SCORCH audit report | Free |

---

## 14 LLM Backends

One config line switches your reasoning backend. Use your own API keys or run fully offline.

```yaml
# graqle.yaml
model:
  backend: anthropic    # or: openai, groq, ollama, bedrock, gemini, deepseek, ...
```

| Backend | Best For | Pricing |
|---------|----------|---------|
| **Ollama / llama.cpp** | Offline, air-gapped, privacy | $0 (local) |
| **Groq** | Speed — sub-second responses | ~$0.0005/query |
| **DeepSeek** | Budget-conscious teams | ~$0.0001/query |
| **Anthropic** | Complex reasoning (Claude) | ~$0.001/query |
| **OpenAI** | GPT-4o, broad compatibility | ~$0.001/query |
| **Google Gemini** | Long context windows | ~$0.0001/query |
| **AWS Bedrock** | Enterprise, IAM integration | AWS pricing |
| **Together** | Open-source model hosting | ~$0.0003/query |
| **Mistral** | European data residency | ~$0.0003/query |
| **Fireworks** | Fast open-source inference | ~$0.0003/query |
| **Cohere** | Enterprise RAG workflows | ~$0.0005/query |
| **OpenRouter** | Model marketplace, any model | Varies |
| **vLLM** | Self-hosted GPU inference | $0 (self-hosted) |
| **Custom** | Any OpenAI-compatible endpoint | Your pricing |

**Smart routing** — assign different providers to different task types:

```yaml
routing:
  default_provider: groq              # Fast + cheap for lookups
  rules:
    - task: reason
      provider: anthropic             # Claude for deep reasoning
    - task: context
      provider: groq                  # Groq for instant context retrieval
```

---

## Architecture

```
Your Code                    Knowledge Graph               AI Reasoning
┌─────────────┐             ┌──────────────────┐          ┌─────────────────┐
│ Python      │  graq scan  │  Nodes (modules) │  query   │ Graph-of-Agents │
│ TypeScript  │ ──────────> │  Edges (depends) │ ───────> │ Multi-round     │
│ Config      │             │  Skills (201)    │          │ Confidence-scored│
│ Docs        │             │  Lessons         │          │ Audit-trailed   │
└─────────────┘             └──────────────────┘          └─────────────────┘
                                    │
                              graq learn
                                    │
                            Graph evolves with
                            every interaction
```

Every file becomes a node. Every import, call, and dependency becomes an edge. When you ask a question, only the relevant nodes activate, reason about their domain, and synthesize one precise answer — with a confidence score and full evidence chain.

The graph is not static. `graq learn` feeds outcomes back into edge weights. The more you use Graqle, the better it understands your codebase.

---

## What Graqle Understands

### Languages

| Language | Support |
|----------|---------|
| Python | Full — imports, classes, functions, decorators, type hints |
| JavaScript / TypeScript | Full — imports, exports, JSX, async patterns |
| React / JSX / TSX | Full — components, hooks, props, context |
| Go | Structural — packages, imports, function signatures |
| Rust | Structural — modules, use declarations, traits |
| Java | Structural — packages, imports, class hierarchy |

### Frameworks

FastAPI, Django, Flask, Next.js, React, Express, NestJS — Graqle recognizes framework-specific patterns like route decorators, middleware chains, and dependency injection.

### Relationships Tracked

Imports, function calls, class inheritance, API endpoint definitions, environment variable usage, configuration references, package dependencies, cross-file type references.

### Documents

PDF, DOCX, PPTX, XLSX, Markdown — `graq scan docs ./docs` ingests documentation into the graph alongside code, linking architecture decisions to the modules they describe.

---

## Installation Options

```bash
pip install graqle                    # Core SDK + CLI (zero cloud dependencies)
pip install "graqle[api]"             # + Anthropic, OpenAI, Bedrock providers
pip install "graqle[docs]"            # + PDF, DOCX, PPTX, XLSX parsing
pip install "graqle[neo4j]"           # + Neo4j graph backend (for large codebases)
pip install "graqle[embeddings]"      # + Sentence transformers for semantic search
pip install "graqle[scorch]"          # + SCORCH v3: AI-powered UX friction auditing
pip install "graqle[all]"             # Everything
```

For development:

```bash
git clone https://github.com/quantamixsol/graqle && cd graqle
pip install -e ".[dev,api]"
pytest                                # 1,700+ tests
```

**Upgrading:**

```bash
graq self-update                      # Recommended — handles MCP server locks on Windows
pip install --upgrade graqle          # Alternative — may require stopping MCP server first
graq migrate                          # After upgrade: rename legacy cognigraph files to graqle
```

Auto-scales: starts with JSON + NetworkX (zero infrastructure), recommends Neo4j at 5,000+ nodes.

---

## CLI Reference

### Scan & Build

| Command | Description |
|---------|-------------|
| `graq init` | Scan repo, build graph, auto-wire IDE integration |
| `graq scan repo .` | Scan codebase into knowledge graph |
| `graq scan docs ./docs` | Ingest documents into the graph |
| `graq scan file path.py` | Scan a single file |
| `graq compile` | Compile intelligence: risk scores, insights, CLAUDE.md |
| `graq verify` | Run governance gate checks |

### Query & Reason

| Command | Description |
|---------|-------------|
| `graq run "question"` | Natural language query (auto-routed) |
| `graq reason "question"` | Multi-agent graph reasoning |
| `graq context module-name` | Focused 500-token context |
| `graq impact module-name` | Downstream impact analysis |
| `graq preflight "planned change"` | Pre-change safety check |
| `graq lessons topic` | Surface relevant lessons |

### Teach & Learn

| Command | Description |
|---------|-------------|
| `graq learn node "name" --type SERVICE` | Add a node to the graph |
| `graq learn edge "A" "B" -r DEPENDS_ON` | Add a relationship |
| `graq learn doc architecture.pdf` | Ingest a document |
| `graq learn discover .` | Auto-discover entities from code |
| `graq learned` | List what the graph has learned |

### Cross-Project

| Command | Description |
|---------|-------------|
| `graq link merge ../other-repo` | Merge graphs from multiple repos |
| `graq link infer` | Discover cross-project dependencies |
| `graq link stats` | Cross-project relationship statistics |

### Cloud & Infrastructure

| Command | Description |
|---------|-------------|
| `graq login --api-key grq_...` | Authenticate with graqle.com |
| `graq cloud push` | Upload graph to cloud |
| `graq cloud pull` | Download graph to local |
| `graq cloud status` | List cloud projects |
| `graq studio` | Open visual dashboard |
| `graq serve` | Start REST API server |
| `graq mcp serve` | Start MCP server for IDE integration |
| `graq doctor` | Health check and diagnostics |
| `graq self-update` | Upgrade to latest version (handles MCP server locks on Windows) |
| `graq migrate` | Migrate legacy cognigraph files to graqle branding |

### SCORCH — UX Friction Auditing

| Command | Description |
|---------|-------------|
| `graq scorch run` | Full 5-phase audit (screenshots + CSS + behavioral + Vision + report) |
| `graq scorch behavioral` | 12 behavioral UX tests only (fast, no AI cost) |
| `graq scorch config --init` | Create default SCORCH config file |
| `graq scorch report` | View the latest audit report |

---

## SCORCH — UX Friction Auditing

**New in v0.30** — SCORCH v3 is Graqle's first-party plugin for AI-powered UX friction auditing. It finds the invisible UX issues that make users quit — not just visual bugs, but broken user journeys.

```bash
pip install "graqle[scorch]" && python -m playwright install chromium
graq scorch run --url http://localhost:3000 --page / --page /pricing
```

### 5-Phase Pipeline

| Phase | What It Does | Cost |
|-------|-------------|------|
| **1. Screenshots** | Full-page captures at mobile, tablet, desktop | Free |
| **2. CSS Metrics** | Font sizes, touch targets, overflow, contrast | Free |
| **2.5. Behavioral UX** | 12 automated friction pattern tests | Free |
| **3. Claude Vision** | AI analysis + Journey Psychology scoring | ~$0.05/page |
| **4. Report** | Combined JSON + Markdown report with pass/fail | Free |

### 12 Behavioral Friction Tests

Every test maps to real user frustration — not theoretical heuristics:

| Test | What It Catches |
|------|----------------|
| Dead Clicks | Buttons/links that look clickable but do nothing |
| Silent Submissions | Forms that submit without any visible feedback |
| Unexplained Jargon | Acronyms without tooltips or definitions |
| Ghost Elements | Empty containers with borders but no content |
| Missing Next-Step CTA | Pages that end without telling the user what to do next |
| Copy-Paste Friction | Content in non-selectable elements |
| Missing Inline Editor | AI-generated text with no edit/copy affordance |
| Incomplete Generation | Truncated AI output with no "show more" |
| Feature Discoverability | Interactive elements hidden behind display:none |
| Flow Continuity | Dead-end pages with no back link or navigation |
| Upsell Integrity | Upgrade prompts shown for already-owned tiers |
| Action-Response Feedback | Buttons without loading states or confirmation |

### 6 Friction Archetypes

SCORCH classifies every issue into one of six universal UX failure patterns:

1. **No Visible Response** — *"Is it working?"* — User acts but nothing changes
2. **Response Mismatch** — *"Not what I asked for"* — UI promises X, delivers Y
3. **Unusable Output** — *"Now what do I do with this?"* — Results the user can't act on
4. **User Stranded** — *"Okay... now what?"* — Process completes but no next step
5. **User Confused** — *"I'm lost"* — User doesn't understand the UI
6. **UI Contradicts State** — *"That's wrong"* — UI shows incorrect information

### MCP Integration

SCORCH exposes 3 tools via the Graqle MCP server — your AI assistant can audit UX directly:

| MCP Tool | Description |
|----------|-------------|
| `graq_scorch_audit` | Full 5-phase audit with pass/fail, journey score, issue list |
| `graq_scorch_behavioral` | Fast behavioral-only scan (no AI cost) |
| `graq_scorch_report` | Read and summarize an existing audit report |

### Auto KG Enrichment

Critical and major findings are automatically added to your Graqle knowledge graph as `FRICTION_FINDING` nodes. This means your AI assistant knows about UX issues when reasoning about your codebase — connecting code changes to UX impact.

### Behavioral-Only Mode (Free, No AI)

Don't want to use Claude Vision? Run just the 12 behavioral tests — zero AI cost, instant results:

```bash
graq scorch behavioral --url http://localhost:3000 --page / --page /dashboard
```

---

## Python SDK

```python
from graqle.core.graph import Graqle
from graqle.backends.api import AnthropicBackend

graph = Graqle.from_json("graqle.json")
graph.set_default_backend(AnthropicBackend(model="claude-sonnet-4-6"))

result = graph.reason("What services depend on auth?", max_rounds=3)
print(result.answer)                  # Graph-reasoned answer
print(f"{result.confidence:.0%}")     # Confidence score
print(f"${result.cost_usd:.4f}")      # Token cost
```

Full programmatic access to scanning, reasoning, impact analysis, and graph manipulation.

---

## Cloud Sync

New in v0.29 — sync knowledge graphs across machines and team members.

```bash
graq login --api-key grq_your_key       # Get key at graqle.com/dashboard/account
graq cloud push                         # Graph appears on graqle.com/dashboard
graq cloud pull                         # Download on any machine
graq cloud status                       # See all your projects
```

Push from your laptop, pull on your workstation. Share with your team. View and explore on [graqle.com/dashboard](https://graqle.com/dashboard).

Cloud sync uploads the graph structure only — never your source code.

---

## Pricing

The SDK is 100% open source and always free. Cloud features are optional.

| | Free ($0) | Pro ($19/mo) | Team ($29/dev/mo) |
|---|:---:|:---:|:---:|
| CLI + SDK + MCP server | Unlimited | Unlimited | Unlimited |
| All 14 LLM backends | Yes | Yes | Yes |
| Intelligence + governance | Yes | Yes | Yes |
| SCORCH behavioral tests | Yes | Yes | Yes |
| SCORCH Vision + Journey | -- | Yes | Yes |
| Graph nodes | 500 | 25,000 | Unlimited |
| Cloud projects | 1 | 3 | Unlimited |
| Reasoning sessions | 3/month | 100/month | Unlimited |
| Cross-project analysis | -- | Yes | Yes |
| Team shared graphs | -- | -- | Yes |
| Priority support | -- | Yes | Yes |

**[Start free at graqle.com](https://graqle.com)**

---

## System Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| Python | 3.10+ | 3.12+ |
| RAM | 2 GB | 4 GB (large codebases) |
| Disk | ~100 MB (SDK + deps) | ~500 MB (with embeddings) |
| OS | Windows, macOS, Linux | Any |

No Docker, no database, no cloud account required for local use. Neo4j is optional for codebases above 5,000 nodes.

---

## Security & Privacy

- **Local by default.** All scanning, graph building, and reasoning runs on your machine.
- **No telemetry.** Graqle does not phone home or collect usage data.
- **Your API keys.** LLM calls go directly from your machine to your chosen provider.
- **Cloud is opt-in.** `graq cloud push` uploads graph structure only — never source code.
- **Auditable.** Source code is fully readable. See [SECURITY.md](SECURITY.md) for our security model.

---

## Patent Notice

Graqle implements methods covered by European Patent Applications
EP26162901.8 and EP26166054.2, owned by Quantamix Solutions B.V.

Use of graqle is permitted under the license terms. Reimplementation
of the patented methods outside this software requires a separate
patent license. See [LICENSE](LICENSE) for details.

---

## Contributing

```bash
git clone https://github.com/quantamixsol/graqle && cd graqle
pip install -e ".[dev]" && pytest     # 1,700+ tests
```

We welcome contributions: bug fixes, new backend integrations, language scanner improvements, and documentation. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## FAQ

**Why not just use Cursor / Claude Code / Copilot directly?**
Graqle does not replace your AI tool — it makes it dramatically better. Your AI reads files one at a time and guesses at relationships. With Graqle, it queries a knowledge graph that maps your entire architecture. Same AI, 100x fewer tokens, answers grounded in actual dependency structure. Plugs in via MCP with zero workflow change.

**Does my code leave my machine?**
Never. All processing is local. LLM calls go directly to your chosen provider using your API keys. Cloud sync is opt-in and only uploads graph structure — never source code.

**How is this different from Sourcegraph or static analysis?**
Static analysis tells you what code exists. Graqle tells you how it connects, what breaks when it changes, and what your team has learned about it. It is a reasoning layer, not a search engine. Every answer comes with a confidence score and evidence chain.

**What about large monorepos?**
Graqle starts with JSON + NetworkX (zero infrastructure). At 5,000+ nodes, switch to Neo4j with one config line. Cross-project linking (`graq link merge`) works across repos. The graph scales — the interface stays the same.

**Can I use my own LLM?**
Yes. 14 backends out of the box — including Ollama and llama.cpp for fully offline, air-gapped operation. Any OpenAI-compatible endpoint works via the Custom backend. Use your own API keys, your own models, your own infrastructure.

**How long does the initial scan take?**
Under 30 seconds for most codebases. Large monorepos (10,000+ files) take 1-2 minutes. Incremental scans after the first are near-instant.

**Does Graqle work without an LLM?**
Yes. Scanning, graph building, impact analysis, and the visual dashboard all work without any LLM. You only need a backend configured for `graq reason` and `graq run` queries.

**Is this production-ready?**
1,700+ tests. 396 compiled modules. 14 backends. Used in production by the team that builds it. That said, the version is 0.x — the API is stable but we reserve the right to make breaking changes with major version bumps.

---

## License & Innovation

Graqle is free to use, integrate, and deploy. See [LICENSE](LICENSE) for full terms.

The SDK implements methods covered by European Patent Applications EP26162901.8 (18 claims) and EP26166054.2 (15 claims), owned by Quantamix Solutions B.V. Use of the SDK is licensed — reimplementation of the patented methods outside this software requires a separate patent license.

Built by [Quantamix Solutions B.V.](https://quantamixsolutions.com) — Uithoorn, The Netherlands.

### Citation

```bibtex
@article{kumar2026graqle,
  title   = {Graqle: Governed Intelligence through Graph-of-Agents Reasoning
             over Knowledge Graph Topologies with Semantic SHACL Validation},
  author  = {Kumar, Harish},
  year    = {2026},
  institution = {Quantamix Solutions B.V.},
  note    = {European Patent Applications EP26162901.8 and EP26166054.2},
  url     = {https://github.com/quantamixsol/graqle}
}
```

---

<div align="center">

**Your AI is only as good as the context you give it. Give it your architecture.**

```bash
pip install graqle && graq init
```

**[graqle.com](https://graqle.com)**

</div>
