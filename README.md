<div align="center">

<img alt="GraQle — AI writes code. GraQle makes it safe." src="https://raw.githubusercontent.com/quantamixsol/graqle/master/assets/hero-dark-hq.png" width="800">

# GraQle — EU AI Act–aligned reasoning for code

> **The first developer reasoning SDK that ships a structured EU AI Act compliance surface — Article-by-Article, version-pinned, CI-pinnable.**
> Scan any codebase into a knowledge graph. Every module becomes a reasoning agent. Every change is impact-analysed, audit-logged, and disclosure-ready.

[![PyPI](https://img.shields.io/pypi/v/graqle?color=%2306b6d4&label=PyPI)](https://pypi.org/project/graqle/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-06b6d4.svg)](https://python.org)
[![EU AI Act–aligned](https://img.shields.io/badge/EU%20AI%20Act-aligned-22c55e.svg)](./docs/compliance/eu-ai-act/)
[![Tests](https://img.shields.io/badge/tests-5%2C500%2B-06b6d4.svg)]()
[![LLM Backends](https://img.shields.io/badge/backends-14-06b6d4.svg)]()
[![Model Agnostic](https://img.shields.io/badge/model-agnostic-06b6d4.svg)]()

```bash
pip install graqle && graq scan repo . && graq run "find every security bug in this codebase"
```

[Website](https://graqle.com) · [EU AI Act docs](./docs/compliance/eu-ai-act/) · [VS Code Extension](https://marketplace.visualstudio.com/items?itemName=graqle.graqle-vscode) · [PyPI](https://pypi.org/project/graqle/) · [Changelog](./CHANGELOG.md)

<!-- mcp-name: io.github.quantamixsol/graqle -->

</div>

---

## 🇪🇺 EU AI Act–aligned (v0.56.0, Wave 1)

**Articles 6, 9, 12, 13, 14, 15, 25, 50 become applicable on 2026-08-02.** GraQle gives your high-risk AI system the signals, audit trail, and disclosure primitives it needs — so the parts of your compliance file you can quote from us, you can quote *today*.

```bash
# 1. Where do we stand on the AI Act?
graq compliance status --include-robustness --format json
# → version-pinned JSON: articles_covered, audit_trail, defences, claims

# 2. Pull last month's audit trail as Article 12 evidence
graq compliance export --since 2026-08-01 --until 2026-08-31 \
    -o august.jsonl --sha256-sidecar
# → JSONL evidence + SHA-256 sidecar for tamper detection

# 3. Arm Article 50(1) AI-disclosure surfaces
export GRAQLE_EU_AI_ACT_MODE=on
# → once-per-session banner + ai_disclosure block on every MCP envelope
```

| Article | What GraQle ships | Where |
|---|---|---|
| **Art 4** — AI literacy | Integration guidance for providers + deployers | [docs/compliance/eu-ai-act/](./docs/compliance/eu-ai-act/article-04-ai-literacy.md) |
| **Art 12** — Record-keeping | JSONL audit export + SHA-256 tamper-detection sidecar | `graq compliance export` |
| **Art 13** — Deployer transparency | `graph_health` + `confidence` on every reasoning envelope | every `graq_reason` call |
| **Art 14** — Human oversight | Confidence-threshold gating + ⚠ degraded-reasoning banner | CLI + `GraqleConfig.governance` |
| **Art 15** — Accuracy / robustness / cybersecurity | 17 named defences + 7 measurable claims | `graq compliance status --include-robustness` |
| **Art 25** — Value-chain responsibility | Intended-purpose statement + this doc set | [Art 25 doc](./docs/compliance/eu-ai-act/article-25-value-chain.md) |
| **Art 50** — Transparency for users | Auto banner + `ai_disclosure` machine field | `GRAQLE_EU_AI_ACT_MODE=on` |

**Three substantive non-claims kept legally clean:**

- GraQle is **NOT** itself a high-risk AI system (no Annex III category applies).
- GraQle is **NOT** a GPAI provider under Article 51 (we use third-party LLMs, we don't place one on the EU market).
- We **provide signals and audit primitives**. We never say *compliant* or *certified*. The discipline is enforced in code — `TestNonClaimsInvariants` blocks any release that introduces a `compliant`/`certified` field.

→ **[Full Article-by-Article mapping in docs/compliance/eu-ai-act/](./docs/compliance/eu-ai-act/)**

---

## What is GraQle

A **governance-led multi-agent reasoning system for code.** Scan any codebase into a persistent knowledge graph. Every module becomes a reasoning agent. Agents decompose, debate, and synthesize answers with clearance-level governance. Every change is impact-analysed, gate-checked, and taught back — automatically.

> *AI assistants see files. GraQle sees architecture. That's why it catches the bugs they can't.*

**Built for high-end engineering teams who need:**

- **Cross-file reasoning** that LLMs can't do alone (impact analysis, lesson recall, dependency-aware refactor).
- **Auditable AI decisions** with confidence scores, evidence trails, and tamper-detectable logs.
- **EU AI Act–aligned** behaviour out of the box — for European customers, regulated deployments, and analyst-grade due diligence.
- **Model-agnostic operation** — 14 LLM backends, offline-capable via Ollama, runs entirely on your machine by default.

---

## 90-second proof

```bash
# 1. Scan any codebase into a knowledge graph
graq scan repo .
# → 5,579 nodes, 19,916 edges — full architecture mapped in seconds

# 2. Ask GraQle to audit it
graq run "find every authentication bypass risk"
# → Graph-of-agents activates across 50 nodes
# → Traces cross-file attack chain: MD5 (models.py) → expired tokens
#    never checked (auth.py) → cancel endpoint with zero auth (app.py)
# → Confidence: 0.89 | Evidence: 3-file chain | Cost: ~$0.001

# 3. Fix it — GraQle shows exact before/after for each file

# 4. Teach it back — the graph never forgets
graq learn "cancel endpoint must require admin auth"
# → Lesson persists. Every future audit activates this rule.
```

---

## How it works

1. **Scan** → AST + dependency analysis builds a typed graph (functions, classes, modules, imports, calls).
2. **Activate** → Pre-reason safety layer scores each node for relevance, confidence, and risk **before** the LLM runs.
3. **Reason** → Multiple agents debate. Outputs carry `confidence`, `graph_health`, `active_nodes`, evidence.
4. **Gate** → Governance gates (CG-01..CG-20) intercept write-class operations. Plans required. Risks surfaced.
5. **Audit** → Every tool call is logged to `.graqle/governance/audit/` with redaction + secret scanning.
6. **Learn** → Lessons become weighted edges. The graph remembers across sessions, teams, git operations.

---

## Model agnostic

Anthropic · OpenAI · AWS Bedrock · Ollama · Gemini · Groq · DeepSeek · Together · Mistral · OpenRouter · Fireworks · Cohere · Azure OpenAI · custom HTTP.

```yaml
# graqle.yaml — smart task routing
backends:
  reasoning:  anthropic/claude-sonnet-4-6   # quality work
  embedding:  bedrock/titan-v2              # cheap + fast
  summaries:  ollama/llama3                 # local + free
```

Runs **fully offline** with Ollama. No telemetry. Code stays on your machine. API keys stay in your local `graqle.yaml`.

---

## Governance gate — activate full GraQle autonomy

```bash
graq gate-install      # one-time, project-local
```

Routes every native write/edit/bash through GraQle's governance gates. Plans required for risky changes. Trade-secret scanning on git commits. Path-traversal hardening on subprocess capture. CG-01 through CG-20 — all on, all auditable.

→ [Governance Gate spec](./docs/governance-gate.md)

---

## MCP-first

```jsonc
// .mcp/config.json
{ "graqle": { "command": "graq", "args": ["mcp", "serve"] } }
```

**76+ MCP tools** — every operation Claude Code / Cursor / VS Code Copilot needs is exposed as a governed tool with confidence scores, evidence pointers, and audit-trail entries. No prompt engineering, no glue code.

---

## Security & integrity

| | |
|---|---|
| **No telemetry** | GraQle does not phone home, collect usage data, or send analytics. |
| **No code upload** | Source never leaves your machine unless you opt in to cloud sync. |
| **Secret scanning** | 200+ regex patterns + Shannon-entropy detection + AST scan on every output candidate. |
| **PyPI Trusted Publishing** | OIDC-only — no long-lived API tokens in our pipeline. |
| **Sigstore signatures** | Every wheel signed by our GitHub Actions identity. Verify with `graq trustctl verify --version <v>`. |
| **CycloneDX SBOM** | Attached to every GitHub Release. |
| **`.pth`-file guard** | Publish pipeline rejects any wheel containing `.pth` files (the 2024 LiteLLM-class attack vector). |
| **Reproducible builds** | `SOURCE_DATE_EPOCH`-pinned, rebuild from tagged source and compare checksums. |

→ Full disclosure policy: [SECURITY.md](./SECURITY.md) · Report vulnerabilities to **security@quantamixsolutions.com**

---

## What's new in v0.56.0

**EU AI Act Wave 1** — 7 articles documented, 3 new CLI surfaces (`graq compliance status`, `graq compliance export`, `--include-robustness`), Article 50(1) runtime disclosure (banner + envelope), Article 15 machine-readable robustness attestation (17 defences, 7 claims).

**Prior reliability work carried forward from v0.55.0:** reasoning honesty (CR-004 graph_health probe), cross-project WRITE_COLLISION fix (CR-008 SaveStatus enum), config resolver default ON (CR-002), edge-loss shrink guard (CR-003), graq_bash TOCTOU-safe stdout_path (CR-005a).

→ [Full changelog](./CHANGELOG.md)

---

## Pricing

| Tier | What you get |
|---|---|
| **Free** | 500-node graphs · 3 reasoning queries / month · unlimited graph viz · core SDK · governance gates · EU AI Act surfaces |
| **Pro — $19/mo** | Unlimited nodes · unlimited queries · cloud sync · priority models |
| **Team — $29/dev/mo** | Shared KGs · team-wide lessons · audit log retention · SOC2 evidence pack |
| **Enterprise** | On-prem · custom backends · dedicated support · regulated-deployment SLAs · [contact us](mailto:sales@quantamixsolutions.com) |

---

## Patent & license

Core methods are patent-pending (EP26167849.4, EP26162901.8). The SDK source is fully auditable under the GraQle License — see [LICENSE](./LICENSE). Reimplementation of the patented methods outside this SDK requires a separate patent license.

→ [github.com/quantamixsol/graqle](https://github.com/quantamixsol/graqle) — issues, discussions, contributions welcome.

---

<div align="center">

**GraQle is built by [Quantamix Solutions](https://quantamixsolutions.com).**
*Graphs that think. EU AI Act–aligned by design.*

</div>
