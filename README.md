<div align="center">

<img alt="GraQle — Query your architecture, not your files" src="https://raw.githubusercontent.com/quantamixsol/graqle/master/assets/hero-dark-hq.png" width="800">

# Query your architecture, not your files.

Your codebase is not a collection of files. It is a network of relationships, assumptions, and hidden dependencies. GraQle turns that network into a persistent knowledge graph — then lets you reason over it, gate changes against it, and teach it what your team knows.

[![PyPI](https://img.shields.io/pypi/v/graqle?color=%2306b6d4&label=PyPI)](https://pypi.org/project/graqle/)
[![Downloads](https://img.shields.io/pypi/dw/graqle?color=%2306b6d4&label=downloads%2Fweek)](https://pypi.org/project/graqle/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-06b6d4.svg)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-1%2C655%2B%20passing-06b6d4.svg)]()
[![LLM Backends](https://img.shields.io/badge/backends-14-06b6d4.svg)]()
[![MCP Tools](https://img.shields.io/badge/MCP%20tools-35%2B-06b6d4.svg)]()
[![VS Code](https://img.shields.io/badge/VS%20Code-Extension-06b6d4.svg)](https://marketplace.visualstudio.com/items?itemName=graqle.graqle)

```bash
pip install graqle && graq scan repo . && graq run "what are the riskiest modules in this codebase?"
```

[Website](https://graqle.com) · [VS Code Extension](https://marketplace.visualstudio.com/items?itemName=graqle.graqle-vscode) · [PyPI](https://pypi.org/project/graqle/) · [Changelog](https://github.com/quantamixsol/graqle/blob/master/CHANGELOG.md) · [Security](https://github.com/quantamixsol/graqle/blob/master/SECURITY.md)

<!-- mcp-name: io.github.quantamixsol/graqle -->

</div>

---

## Get started in 60 seconds

```bash
# Install
pip install graqle

# Scan your codebase into a knowledge graph
graq scan repo .

# Ask it anything
graq run "find every cross-file security vulnerability"
```

That is it. Three commands. Your entire architecture — modules, dependencies, assumption chains, hidden coupling — mapped into a typed knowledge graph with 13 node types and 10 edge types.

---

## Why GraQle exists

Every AI coding tool works at the **file level**. Copilot sees one file. Cursor sees one file. Claude Code sees one file at a time.

**Bugs do not live in files. They live between files.**

```
app.py ──imports──> services.py
    |                    |
    assumes auth         assumes auth
    checked here ────>   checked here
                 
    Neither checks. Both assume the other does.
    Invisible to every single-file tool.
    Visible to GraQle in 90 seconds.
```

GraQle maps the relationships. Every module becomes a node. Every dependency becomes an edge. Every lesson your team learns persists as a weighted edge that activates on future queries. The graph compounds knowledge over time — the longer you use it, the smarter it gets about your specific architecture.

---

## What you can do

### Reason across your entire architecture

```bash
$ graq reason "what happens if I refactor the auth layer?"

Activated 14 nodes across 3 modules
Reasoning confidence: HIGH
Blast radius: auth.py -> services.py -> api.py -> middleware.py
                                     -> tests/test_auth.py (NO TESTS for token refresh)
Lessons activated: 2
  - "cancel endpoint must always require auth token" (learned 2026-03-28)
  - "auth changes require middleware regression test" (learned 2026-03-15)
```

### Gate changes before they ship

```bash
$ graq preflight "add payment processing to checkout"

Impact: 6 modules affected
Risk: MEDIUM
Lessons: "payment module must never call user service directly"
Similar: billing.py already has charge() — consider reusing
Gate status: CLEAR — proceed with caution
```

### Trace blast radius instantly

```bash
$ graq impact auth.py

auth.py (CRITICAL — 26 consumers)
  -> middleware.py (34 dependents)
  -> api.py (19 dependents)  
  -> services.py (8 dependents)
  -> tests/test_auth.py
  -> tests/test_middleware.py
Total blast radius: 42 modules
```

### Teach it what your team knows

```bash
$ graq learn "the payments table uses soft deletes — never call DELETE directly"

Lesson written to graph.
This lesson will activate on any future query touching payments, billing, or database operations.

$ graq lessons payments
1. "payments table uses soft deletes — never call DELETE directly" (2026-04-01)
2. "Stripe webhook handler must be idempotent" (2026-03-22)
3. "payment amounts stored in cents, not dollars" (2026-03-10)
```

Lessons persist across sessions, team members, and git branches. Copilot forgets. GraQle remembers.

---

## MCP integration — works with every AI IDE

GraQle exposes 35+ architecture-aware tools via the [Model Context Protocol](https://modelcontextprotocol.io). Your AI assistant uses them automatically.

```bash
# Claude Code — auto-wires everything
graq init

# Cursor
graq init --ide cursor

# VS Code
graq init --ide vscode

# Windsurf
graq init --ide windsurf

# Any MCP client
graq mcp serve
```

### Core tools your AI gets access to

| Tool | What it does |
|:-----|:------------|
| `graq_reason` | Multi-agent graph reasoning with confidence scoring |
| `graq_impact` | Blast radius — full dependency traversal |
| `graq_preflight` | Pre-change safety gate with lessons and risk assessment |
| `graq_context` | Focused architectural context for any module |
| `graq_learn` | Teach the graph — persists across sessions |
| `graq_lessons` | Surface relevant past mistakes |
| `graq_predict` | Confidence-gated architectural prediction |
| `graq_gate` | Binary governance gate — PASS / FAIL with evidence |
| `graq_inspect` | Graph stats and health status |
| `graq_generate` | Architecture-aware code generation |
| `graq_review` | Graph-powered code review |

When your AI calls `graq_reason`, it is not just prompting an LLM. It is activating a subgraph of relevant nodes, running multi-agent reasoning across the activated topology, scoring confidence against the graph's accumulated knowledge, and returning evidence-backed answers. The graph is the reasoning architecture.

---

## 14 backend providers — use any LLM

GraQle is model-agnostic. One line in `graqle.yaml` switches providers. Use your own API keys, your own AWS account, or run fully offline with Ollama.

| Provider | Notes |
|:---------|:------|
| **Anthropic** | Claude Opus, Sonnet, Haiku |
| **AWS Bedrock** | Uses your existing IAM — no new credentials |
| **OpenAI** | GPT-4o, GPT-4, o1, o3 |
| **Ollama** | Fully offline, air-gapped, zero cost |
| **Groq** | Sub-second inference |
| **Google Gemini** | Gemini Pro, Flash |
| **DeepSeek** | DeepSeek-V3, R1 |
| **Mistral** | Mistral Large, Medium |
| **Together AI** | Open-source models at scale |
| **Fireworks AI** | Low-latency inference |
| **Cohere** | Command R+ |
| **OpenRouter** | Multi-provider routing |
| **vLLM** | Self-hosted open models |
| **Custom** | Any OpenAI-compatible endpoint |

```yaml
# graqle.yaml — smart task routing
model:
  backend: anthropic
  model: claude-sonnet-4-6

routing:
  rules:
    - task: reason
      provider: bedrock
      model: eu.anthropic.claude-opus-4-6-v1
      profile: your-aws-profile
    - task: context
      provider: groq
      model: llama-3.3-70b-versatile
```

Route different tasks to different providers. Heavy reasoning to Opus. Fast lookups to Groq. Offline dev to Ollama. All from the same config file.

---

## VS Code extension (v0.3.0)

The [GraQle VS Code extension](https://marketplace.visualstudio.com/items?itemName=graqle.graqle) brings the full SDK into your editor.

- **Inline impact analysis** — see blast radius without leaving your file
- **Preflight on save** — gate checks before you commit
- **Graph explorer** — visual knowledge graph in a sidebar panel
- **Security hardened** — HMAC-signed communication, project-scoped graphs
- **Free tier works without auth** — no account required to start

```
ext install graqle.graqle
```

The extension uses the same SDK and the same knowledge graph. Everything you teach via CLI is available in VS Code, and vice versa.

---

## Full CLI reference

<details>
<summary><b>Scan and Build</b></summary>

| Command | Description |
|---------|-------------|
| `graq init` | Scan repo, build graph, auto-wire IDE |
| `graq scan repo .` | Scan codebase into knowledge graph |
| `graq scan docs ./docs` | Ingest PDF, DOCX, PPTX, Markdown |
| `graq compile` | Compute risk scores and insights |
| `graq verify` | Run governance gate checks |
| `graq doctor` | Health check — graph integrity, backend, config |
| `graq grow` | Incremental rescan (runs on git commit via hook) |

</details>

<details>
<summary><b>Reason and Query</b></summary>

| Command | Description |
|---------|-------------|
| `graq run "question"` | Natural language query — auto-routed |
| `graq reason "question"` | Multi-agent graph reasoning |
| `graq context module` | Focused context for any module |
| `graq impact module` | Blast radius — what breaks if this changes |
| `graq preflight "change"` | Pre-change gate with risk assessment |
| `graq predict "query"` | Confidence-gated prediction |
| `graq lessons topic` | Past mistakes relevant to current query |

</details>

<details>
<summary><b>Teach and Learn</b></summary>

| Command | Description |
|---------|-------------|
| `graq learn "fact"` | Teach the graph — persists across sessions |
| `graq learn node "name"` | Add a named node |
| `graq learn edge "A" "B"` | Add a typed relationship |
| `graq learned` | List everything the graph has been taught |

</details>

<details>
<summary><b>Cloud and Sync</b></summary>

| Command | Description |
|---------|-------------|
| `graq login --api-key <YOUR_API_KEY>` | Authenticate with GraQle cloud |
| `graq cloud push` | Push graph to cloud — team sync |
| `graq cloud pull --merge` | Pull graph — preserves local lessons |
| `graq studio` | Visual dashboard |
| `graq serve` | REST API server |
| `graq mcp serve` | MCP server for any compatible client |

</details>

<details>
<summary><b>SCORCH — UX Friction Auditing</b></summary>

| Command | Description |
|---------|-------------|
| `graq scorch run` | Full 12-dimension UX audit |
| `graq scorch behavioral` | Behavioral UX tests — zero AI cost |
| `graq scorch a11y` | WCAG 2.1 accessibility |
| `graq scorch perf` | Core Web Vitals |
| `graq scorch security` | CSP, XSS, exposed keys, auth flow |
| `graq scorch mobile` | Touch targets and viewport |
| `graq scorch conversion` | CTA and trust signals |
| `graq scorch seo` | SEO and Open Graph |
| `graq scorch diff` | Before/after regression detection |

</details>

<details>
<summary><b>Phantom — Browser Automation</b></summary>

```bash
pip install graqle[phantom] && python -m playwright install chromium
```

| Command | Description |
|---------|-------------|
| `graq phantom browse URL` | Open browser, screenshot + DOM summary |
| `graq phantom audit URL` | Multi-dimension audit on any live page |
| `graq phantom discover URL` | Auto-crawl all navigable pages |
| `graq phantom flow file.json` | Execute multi-step user journey |

</details>

---

## Pricing

| | **Free** | **Pro** | **Team** | **Enterprise** |
|:--|:--:|:--:|:--:|:--:|
| | $0/mo | $19/mo | $29/dev/mo | Custom |
| CLI + SDK + MCP tools | Unlimited | Unlimited | Unlimited | Unlimited |
| All 14 backends | Yes | Yes | Yes | Yes |
| Knowledge graph nodes | 500 | 25,000 | Unlimited | Unlimited |
| Cloud projects | 1 | 3 | Unlimited | Unlimited |
| SCORCH vision audits | -- | Yes | Yes | Yes |
| Phantom browser tools | -- | Yes | Yes | Yes |
| Cross-project graphs | -- | Yes | Yes | Yes |
| Team shared graphs | -- | -- | Yes | Yes |
| SSO + audit logs | -- | -- | -- | Yes |
| On-premise deployment | -- | -- | -- | Yes |

**[Start free at graqle.com](https://graqle.com)**

---

## Security and privacy

- **Local by default.** All processing runs on your machine. No telemetry. No phone-home.
- **Your API keys.** LLM calls go directly to your provider. Never proxied through us.
- **Cloud is opt-in.** Uploads graph structure only — never source code.
- **Air-gapped mode.** `GRAQLE_OFFLINE=1` for zero network calls.

### Supply-chain integrity

| Protection | Details |
|-----------|---------|
| PyPI Trusted Publishing | GitHub Actions OIDC — no long-lived API tokens |
| Sigstore signatures | Every wheel signed; bundle on every GitHub Release |
| CycloneDX SBOM | Full bill of materials for every release |
| pip-audit in CI | CVE scan on every PR — blocks on CRITICAL/HIGH |
| .pth file guard | Blocks publish if wheel contains `.pth` files |
| Reproducible builds | `SOURCE_DATE_EPOCH` pinned — rebuild and compare checksums |

```bash
pip install "graqle[security]"
graq trustctl verify
```

---

## How GraQle is different

| Capability | Copilot / Cursor | LangChain / CrewAI | LlamaIndex | **GraQle** |
|:-----------|:--:|:--:|:--:|:--:|
| Cross-file relationship awareness | -- | -- | -- | Yes |
| Persistent architectural memory | Resets each session | Stateless | Stateless | Compounds over time |
| Blast radius before change | -- | -- | -- | Full dependency traversal |
| Governance gate | -- | Prompt rules | -- | Graph-enforced |
| Learns from every interaction | -- | -- | -- | Weighted lesson edges |
| Works offline / air-gapped | -- | -- | -- | Yes (Ollama) |
| Self-improves over time | -- | -- | -- | Closed developmental loop |

The difference is structural: GraQle maintains a persistent typed knowledge graph where the topology governs which agents reason, edges encode what was learned, and results mutate the same graph that governs future reasoning. This is not something you can replicate with prompt engineering.

---

## Research

GraQle is backed by 7 published research specifications (R2 through R11) and patent-pending technology (EP26167849.4). The SDK is the production implementation of peer-reviewed graph-of-agents reasoning architectures.

Built by a research team that uses GraQle to develop GraQle — the SDK's own 15,000+ node knowledge graph powers its own development, testing, and release process.

---

## FAQ

<details>
<summary><b>How is this different from Copilot or Cursor?</b></summary>

They generate code one file at a time. GraQle maps the relationships between all files, reasons across the full graph, and gates changes against accumulated architectural knowledge. They are not competitors — GraQle is the safety layer beneath them.

</details>

<details>
<summary><b>Does my code leave my machine?</b></summary>

Never. All graph processing is local. Cloud sync uploads graph structure only, never source code. Use `GRAQLE_OFFLINE=1` for fully air-gapped operation.

</details>

<details>
<summary><b>Can I use my own LLM or AWS account?</b></summary>

Yes. 14 backends. One line in `graqle.yaml` switches providers. AWS Bedrock uses your existing IAM profile. Ollama runs fully offline at zero cost.

</details>

<details>
<summary><b>How long does scanning take?</b></summary>

Under 30 seconds for most codebases. Large monorepos (10K+ files) take 1-2 minutes. The graph persists — subsequent scans are incremental via `graq grow`.

</details>

<details>
<summary><b>What languages are supported?</b></summary>

Python and TypeScript have full AST-level scanning. JavaScript, Java, Go, Rust, and C# have structural scanning. Markdown, PDF, DOCX, and PPTX can be ingested as documentation nodes.

</details>

---

## Patent and license

European Patent Applications EP26162901.8 and EP26166054.2 — Quantamix Solutions B.V.

Free to use under the [license terms](https://github.com/quantamixsol/graqle/blob/master/LICENSE). See [SECURITY.md](https://github.com/quantamixsol/graqle/blob/master/SECURITY.md) for supply-chain documentation.

```bibtex
@article{kumar2026graqle,
  title   = {GraQle: Governed Intelligence through Graph-of-Agents Reasoning},
  author  = {Kumar, Harish},
  year    = {2026},
  institution = {Quantamix Solutions B.V.},
  url     = {https://github.com/quantamixsol/graqle}
}
```

---

<div align="center">

**Query your architecture, not your files.**

```bash
pip install graqle && graq init
```

[Star this repo](https://github.com/quantamixsol/graqle) | [Install VS Code extension](https://marketplace.visualstudio.com/items?itemName=graqle.graqle) | [Visit graqle.com](https://graqle.com)

Built by [Quantamix Solutions B.V.](https://quantamixsolutions.com) -- Uithoorn, The Netherlands

</div>
