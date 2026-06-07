<div align="center">

<img alt="GraQle — Query your architecture. Prove your AI's decisions." src="https://raw.githubusercontent.com/quantamixsol/graqle/master/assets/hero-dark-hq.png" width="800">

# GraQle — query your architecture, prove your AI's decisions

> Index any codebase as a knowledge graph so AI agents reason about **architecture** instead of grepping files. Every decision they make — at build-time or in production — gets a cryptographic receipt anchored to a public transparency log. One Python package, two surfaces: **dev intelligence** for engineers, **runtime governance** for regulators.

[![PyPI](https://img.shields.io/pypi/v/graqle?color=%2306b6d4&label=PyPI)](https://pypi.org/project/graqle/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-06b6d4.svg)](https://python.org)
[![LLM Backends](https://img.shields.io/badge/backends-14-06b6d4.svg)]()
[![Model Agnostic](https://img.shields.io/badge/model-agnostic-06b6d4.svg)]()
[![EU AI Act–aligned](https://img.shields.io/badge/EU%20AI%20Act-aligned-22c55e.svg)](./docs/compliance/eu-ai-act/)
[![Patent-pending](https://img.shields.io/badge/patent-pending%20EP26167849.4-7c3aed.svg)](#patent--license)

```bash
pip install graqle
```

[Website](https://graqle.com) · [Quickstart](#90-second-quickstart) · [Runtime governance](#run-time--attach-governance-to-a-deployed-ai-in-one-line) · [EU AI Act docs](./docs/compliance/eu-ai-act/) · [Changelog](./CHANGELOG.md) · [VS Code Extension](https://marketplace.visualstudio.com/items?itemName=graqle.graqle-vscode)

<!-- mcp-name: io.github.quantamixsol/graqle -->

</div>

---

## Two surfaces, one substrate

|  | **Build-time** (dev intelligence) | **Run-time** (production governance) |
|---|---|---|
| Governs | how your AI **writes code** | what your deployed AI **decides** |
| Trigger | a code change | a production decision (loan, hiring, triage, …) |
| Emits | reviewed, impact-analysed, audit-logged changes | a tamper-evident, third-party-verifiable record per decision |
| Built on | typed code knowledge graph + multi-agent reasoning | Layer 5 cryptographic substrate (RFC 8785 JCS → RFC 6962 Merkle → ed25519 → Sigstore Rekor) |
| Status | **GA** | **GA** — `attest()` capture (v0.60.0) + FastAPI middleware / `@governed` (v0.61.0) + continuous anchoring worker `graqle govern serve` (**v0.62.0**) |

> **Build-time governance proves *we hold ourselves to this standard* — GraQle is developed through its own governance. Run-time governance lets you hold *your deployed AI* to the same cryptographically-verifiable standard. Same substrate, both surfaces.**

---

## 90-second quickstart

### Build-time — query your codebase as a graph

```bash
# 1. Scan any codebase into a knowledge graph
graq scan repo .
# → typed graph: functions, classes, modules, imports, calls — full architecture mapped in seconds

# 2. Ask GraQle to audit it
graq run "find every authentication bypass risk"
# → Graph-of-agents activates across relevant nodes
# → Traces cross-file attack chains the LLM alone cannot see
# → Returns: confidence score + evidence trail + active nodes + tool hints

# 3. Fix it — GraQle shows exact before/after for each file (governed)

# 4. Teach it back — the graph never forgets
graq learn "cancel endpoint must require admin auth"
# → Lesson persists. Every future audit activates this rule.
```

### Run-time — attach governance to a deployed AI in one line

```python
from graqle.governance.runtime import GovernedRuntime

gov = GovernedRuntime(salt="your-deploy-salt")

def score_application(app):
    decision = model.predict(app)                # your deployed AI, untouched
    gov.attest(                                  # <-- the one added line
        domain="loan", model_id="credit-risk-v4",
        inputs={"applicant_ref": gov.pseudonymize_ref(app.id)},   # PII-safe
        output={"decision": decision.label, "reason_code": decision.reason},
    )
    return decision
```

Each call produces a durable, PII-safe governed record. Its leaf hash is computed with the same shipped primitive the build-time batcher uses, so a runtime record is byte-compatible with the cryptographic substrate (RFC 8785 JCS → RFC 6962 Merkle → ed25519 → Sigstore Rekor). Capture is out-of-band — it adds **0 ms to your write path**.

See [`examples/runtime_attest_production_decisions.py`](./examples/runtime_attest_production_decisions.py) and [`examples/runtime_govern_serve_anchoring.py`](./examples/runtime_govern_serve_anchoring.py).

### Run it as a continuous service (v0.62.0)

```bash
# Long-lived anchoring worker — flushes batches + drains the replay queue every tick
graqle govern serve --config graqle.yaml

# Cron-style one-shot tick (single flush + single replay-drain)
graqle govern serve --once

# Article-72-style monitoring snapshot — JSON suitable for any external monitor
graqle govern health
# → { "running": true, "ticks": 47, "records_anchored": 3120, "replay_queue_depth": 0, ... }
```

The serve loop writes `.graqle/govern.health.json` atomically after every tick — pipe it into your existing monitoring (Prometheus, Datadog, an oncall dashboard, a simple curl).

> **Independently verifiable, by anyone.** Committed batches anchor to the public Sigstore Rekor transparency log. Any third party can verify a record — auditor, regulator, counter-party — **without access to your infrastructure, or ours.** Verification doesn't depend on Quantamix staying online.

---

## 💰 Token economics — a worked case study

A 4-developer team on a 50,000-node enterprise codebase **burns ~$40 per developer per day** on flat-file AI-coding tokens in 2026. The same team using GraQle's substrate:

| Scenario | Annual (4 devs) | Saving |
|---|---|---|
| Flat-file baseline (Cursor / Claude Code default) | **$42,240** | — |
| GraQle + frontier API (Sonnet 4.6) | **$19,874** | **−53%** |
| GraQle + local SLM (Year 2, 90% migrated) | **$5,174** | **−88%** |

Every number is auditable. Every assumption is sourced (Anthropic pricing, Cursor power-user data, Microsoft's killed Claude Code pilot, NCBI biomedical-KG research showing >50% token reduction, Qwen3-Coder SWE-Bench benchmarks). Scale linearly to a 40-developer enterprise: **~$224k/year saved in Year 1, ~$371k/year in Year 2**.

Plus six things Cursor / Copilot / Codex do not offer at any subscription tier: cryptographic audit trail, EU AI Act Article 26 readiness (€15M fine exposure), patent-defensible substrate, survive-vendor-disappearance, multi-agent governance, public Sigstore Rekor anchoring.

→ **[Read the full case study](./docs/case-study-token-economics.md)** — math, sources, and a `bash` snippet to re-run it on your own team's numbers.

---

## What is GraQle

A **governance-led multi-agent reasoning system for code**, with a built-in cryptographic audit substrate for the AI you ship to production. Scan any codebase into a persistent knowledge graph. Every module becomes a reasoning agent. Agents decompose, debate, and synthesize answers with clearance-level governance. Every change — and every production decision — is impact-analysed, gate-checked, and cryptographically committed.

> *AI assistants see files. GraQle sees architecture. That's why it catches the cross-file bugs they can't, and why its audit trail survives every level of tampering.*

**Built for engineering teams who need:**

- **Cross-file reasoning** — impact analysis, lesson recall, dependency-aware refactor (the kind of thing that requires reading 5 files; we read the graph instead).
- **Auditable AI decisions** — confidence scores, evidence trails, tamper-evident logs anchored to a public transparency log.
- **EU AI Act–aligned behaviour out of the box** — for European customers, regulated deployments, and analyst-grade due diligence.
- **Model-agnostic operation** — 14 LLM backends, offline-capable via Ollama, runs entirely on your machine by default. No telemetry. Code stays on your machine.

---

## How it works

1. **Scan** → AST + dependency analysis builds a typed graph (functions, classes, modules, imports, calls).
2. **Activate** → A pre-reasoning safety layer scores each node for relevance, confidence, and risk **before** the LLM runs.
3. **Reason** → Multiple agents debate. Outputs carry `confidence`, `graph_health`, `active_nodes`, evidence pointers.
4. **Gate** → Governance gates (CG-01..CG-20) intercept write-class operations. Plans required. Risks surfaced. Trade-secret + path-traversal hardening enforced.
5. **Audit** → Every tool call is logged to `.graqle/governance/audit/` with redaction + secret scanning.
6. **Commit** → For runtime decisions, the audit record gets canonicalised (RFC 8785), Merkle-rooted (RFC 6962), ed25519-signed, and anchored to the public Sigstore Rekor log.
7. **Learn** → Lessons become weighted edges. The graph remembers across sessions, teams, and git operations.

The pipeline runs through five named phases — **ANCHOR → ACTIVATE → GENERATE → VALIDATE → COMMIT**. Each phase is governance-gated, evidence-attached, and audit-logged.

API defaults: `confidence_threshold=0.65` (refusal floor), `gate_threshold=0.60` (gate-status floor). Both are configurable per-call.

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

## Governance gate — drop-in for Claude Code, Cursor, VS Code

```bash
graq init              # sets up a governed project (writes the constitution → CLAUDE.md)
graq gate-install      # one-time, project-local — enforce it for Claude Code
```

**`graq init` writes the GraQle constitution into your project**, so your AI tool
behaves like a disciplined senior engineer from the very first command: governed
tools only (every change is checked), a defined *investigate → plan → review →
apply → learn* workflow, built-in token-cost rules, and the project's known
pitfalls baked in. One rulebook — shipped as
[`graqle/data/constitution/`](./graqle/data/constitution/) — renders for every
client, so editing it once keeps Claude Code, Cursor, and VS Code in sync.

`gate-install` then routes every native write/edit/bash through GraQle's governance gates and adds a `permissions` backstop to `.claude/settings.json`. Plans required for risky changes. Trade-secret scanning on git commits. Path-traversal hardening on subprocess capture. CG-01 through CG-20 — all on, all auditable.

→ [Governance Gate spec](./docs/governance-gate.md)

---

## MCP-first

```jsonc
// .mcp/config.json
{ "graqle": { "command": "graq", "args": ["mcp", "serve"] } }
```

**76+ MCP tools** — every operation Claude Code / Cursor / VS Code Copilot needs is exposed as a governed tool with confidence scores, evidence pointers, and audit-trail entries. No prompt engineering, no glue code.

---

## 🇪🇺 EU AI Act–aligned

**Articles 6, 9, 12, 13, 14, 15, 25, 50 become applicable on 2026-08-02.** GraQle gives your high-risk AI system the signals, audit trail, and disclosure primitives it needs — so the parts of your compliance file you can quote from us, you can quote *today*.

```bash
# One switch flips every EU-AI-Act-aware subsystem at once
graq compliance switch on        # shell snippet → eval to enable
graq compliance switch status    # what's actually armed, in one envelope
graq compliance switch off       # symmetric disable

# Per-subsystem CLI surface
graq compliance status                                      # legacy + new subsystems block
graq compliance export --since 2026-08-01 --sha256-sidecar  # Article 12 evidence
graq compliance baseline-doc generate --output baseline.jsonl  # Q16.1 baseline
graq compliance periodic-assessment run --period-start ... --period-end ...  # Q16.3
graq compliance feedback record --rating 5 --note "..."     # Q16.5 observation
graq compliance eur-lex-check                               # weekly drift guard
```

| Article | What GraQle provides | Where |
|---|---|---|
| **Art 4** — AI literacy | Integration guidance for providers + deployers | [Art 4 doc](./docs/compliance/eu-ai-act/article-04-ai-literacy.md) |
| **Art 9** — Risk management | Periodic-assessment artefacts with auto-remediation triggers | `graq compliance periodic-assessment run` |
| **Art 11** — Technical documentation | Dated, content-addressed baseline document at deployment | `graq compliance baseline-doc generate` |
| **Art 12** — Record-keeping | JSONL audit export + SHA-256 tamper-detection sidecar | `graq compliance export` |
| **Art 13** — Deployer transparency | `graph_health` + `confidence` on every reasoning envelope | every `graq_reason` call |
| **Art 14** — Human oversight | **Confidence-gated refusal** of auto-apply + claim-limits vocabulary | `GRAQLE_EU_AI_ACT_MODE=on` + `graq edit/apply/auto` |
| **Art 15** — Accuracy / robustness / cybersecurity | 17 named defences + 7 measurable claims | `graq compliance status --include-robustness` |
| **Art 25** — Value-chain responsibility | Intended-purpose declarations + PCT (Proof-Claims Token) `x-ai-eu` extension (11 fields) | [Art 25 doc](./docs/compliance/eu-ai-act/article-25-value-chain.md) + `graq pct issue/validate` |
| **Art 43** — Conformity assessment | Substrate evidence inputs (baseline-doc + audit log + periodic assessment + robustness + Article 14 gate) for the *deployer's* Annex VI internal-control file | [Art 43 doc](./docs/compliance/eu-ai-act/article-43-conformity-assessment.md) |
| **Art 50** — Transparency for users | Auto banner + `ai_disclosure` machine field | `GRAQLE_EU_AI_ACT_MODE=on` |
| **Art 72** — Post-market monitoring | `graqle govern serve` continuous anchoring + `graqle govern health` snapshot | **v0.62.0** |

**Three substantive non-claims kept legally clean:**

- GraQle is **NOT** itself a high-risk AI system (no Annex III category applies).
- GraQle is **NOT** a GPAI provider under Article 51 (we use third-party LLMs, we don't place one on the EU market).
- We **provide signals, audit primitives, and conformity-assessment evidence inputs**. We never say *compliant* or *certified*. The discipline is enforced in code — `TestNonClaimsInvariants` blocks any release that introduces a `compliant`/`certified` field.

→ **[Full Article-by-Article mapping in docs/compliance/eu-ai-act/](./docs/compliance/eu-ai-act/)**

### Contributions welcome on the compliance docs

The EU AI Act docs are deliberately open to contribution — **corrections, translations (DE/FR/ES/IT have highest demand), compliance gap reports from deployers building Annex VI internal-control files, and cross-framework mappings (NIST AI RMF, ISO 42001, ENISA, etc.) are all welcome.** See [CONTRIBUTING-COMPLIANCE.md](./CONTRIBUTING-COMPLIANCE.md) for the contribution guide, the vocabulary discipline the CI enforces, and what kinds of changes go through which review path.

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
| **`.pth`-file guard** | Publish pipeline rejects any wheel containing `.pth` files (the LiteLLM-class attack vector). |
| **Reproducible builds** | `SOURCE_DATE_EPOCH`-pinned, rebuild from tagged source and compare checksums. |
| **Survive-disappearance** | Production audit records anchor to public Sigstore Rekor — verifiable even if Quantamix disappears. |

→ Full disclosure policy: [SECURITY.md](./SECURITY.md) · Report vulnerabilities to **security@quantamixsolutions.com**

---

## What's new in v0.71.0

**A governed first run.** `graq init` now sets up a governed development
experience out of the box. The full GraQle rulebook — the **constitution** —
ships as a single source of truth and is rendered into your AI tool's instruction
file, so a brand-new user pair-programs with a disciplined senior engineer from
the first command instead of a generic assistant.

- **The constitution** ([`graqle/data/constitution/`](./graqle/data/constitution/)) — governed-tools-only rules, the 9-phase workflow, the full MCP tool inventory, token-cost rules, learned-behaviour workarounds, and a configurable (off-by-default) EU AI Act section. Modular Markdown fragments; edit once, every client stays in sync.
- **`graq init`** assembles and renders it into `CLAUDE.md`, with a fail-safe fallback so init never breaks on a stripped wheel.
- **`graq gate-install`** adds a non-destructive `permissions` backstop to `.claude/settings.json` (deny native write/exec, allow the governed `graq_*` tools) behind the existing PreToolUse hook.

> `AGENTS.md` (Codex) and `.cursorrules` / `.windsurfrules` rendering follow in the next release.

→ [Full v0.71.0 changelog](./CHANGELOG.md)

---

## Recent releases

- **v0.62.0** — Runtime R2: `graqle govern serve` continuous anchoring worker + `govern health` Article-72 monitoring snapshot.
- **v0.61.0** — Runtime R1: FastAPI middleware + `@governed` decorator. Drop-in governance for any FastAPI app.
- **v0.60.0** — Runtime R0 Mode A: `GovernedRuntime.attest()` and PII-safe `pseudonymize_ref()`.
- **v0.59.0** — Layer 5 cryptographic substrate GA: RFC 8785 canonicalisation + RFC 6962 Merkle commitments + ed25519 signatures + Sigstore Rekor anchoring + local replay queue.
- **v0.58.0** — EU AI Act Wave 3 substrate (Article 43 conformity-assessment evidence) + OPSF PCT alignment + `GRAQLE_WORKTREE_ROOT` for parallel-worktree dev.
- **v0.57.0** — EU AI Act Wave 2: `graq compliance switch` single entry-point, Article 14 confidence-gated refusal, claim-limits vocabulary, EUR-Lex drift guard.

→ [Full changelog](./CHANGELOG.md)

---

## Pricing

| Tier | What you get |
|---|---|
| **Free** | Local-only graphs · core SDK · governance gates · EU AI Act surfaces · `attest()` runtime · `govern serve` anchoring (self-hosted, anchored to public Rekor) |
| **Pro — $19/mo** | Cloud sync · priority models · hosted Rekor relay |
| **Team — $29/dev/mo** | Shared KGs · team-wide lessons · audit log retention · SOC 2 evidence pack |
| **Enterprise** | On-prem · custom backends · dedicated support · regulated-deployment SLAs · [contact us](mailto:sales@quantamixsolutions.com) |

The free tier is real: the verifier, the runtime attestation path, and the continuous anchoring worker are all in the open-source SDK. Paid tiers add operational scale, team features, and a managed Rekor relay.

---

## Patent & license

Core methods are patent-pending: **EP26167849.4** (filed 2026-03-25), **EP26162901.8** (CIP), and **EP26166054.2** (CogniGraph divisional). The SDK source is fully auditable under the GraQle License — see [LICENSE](./LICENSE). Reimplementation of the patented methods outside this SDK requires a separate patent license.

→ [github.com/quantamixsol/graqle](https://github.com/quantamixsol/graqle) — issues, discussions, contributions welcome.

---

<div align="center">

**GraQle is built by [Quantamix Solutions](https://quantamixsolutions.com).**
*Query your architecture. Prove your AI's decisions.*

</div>
