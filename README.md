<div align="center">

<img alt="GraQle — AI writes code. GraQle makes it safe." src="https://raw.githubusercontent.com/quantamixsol/graqle/master/assets/hero-dark-hq.png" width="800">

# GraQle — the EU AI Act–aligned governance substrate for AI you *build* and AI you *run*

> **Govern how your AI writes code — and cryptographically prove what your deployed AI decides.** One substrate, two surfaces: build-time reasoning + governance, and a run-time tamper-evidence layer for production decisions (loan, hiring, triage). Article-by-Article, version-pinned, CI-pinnable.
> Scan any codebase into a knowledge graph; every module becomes a reasoning agent and every change is impact-analysed and audit-logged. Then attach `attest()` to your deployed model and every decision becomes a tamper-evidence-ready, third-party-verifiable record.

[![PyPI](https://img.shields.io/pypi/v/graqle?color=%2306b6d4&label=PyPI)](https://pypi.org/project/graqle/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-06b6d4.svg)](https://python.org)
[![EU AI Act–aligned](https://img.shields.io/badge/EU%20AI%20Act-aligned-22c55e.svg)](./docs/compliance/eu-ai-act/)
[![Tests](https://img.shields.io/badge/tests-5%2C900%2B-06b6d4.svg)]()
[![LLM Backends](https://img.shields.io/badge/backends-14-06b6d4.svg)]()
[![Model Agnostic](https://img.shields.io/badge/model-agnostic-06b6d4.svg)]()

```bash
pip install graqle && graq scan repo . && graq run "find every security bug in this codebase"
```

[Website](https://graqle.com) · [EU AI Act docs](./docs/compliance/eu-ai-act/) · [VS Code Extension](https://marketplace.visualstudio.com/items?itemName=graqle.graqle-vscode) · [PyPI](https://pypi.org/project/graqle/) · [Changelog](./CHANGELOG.md)

<!-- mcp-name: io.github.quantamixsol/graqle -->

</div>

---

## 🇪🇺 EU AI Act–aligned (v0.58.0, Wave 3 substrate)

**Articles 6, 9, 12, 13, 14, 15, 25, 50 become applicable on 2026-08-02.** GraQle gives your high-risk AI system the signals, audit trail, and disclosure primitives it needs — so the parts of your compliance file you can quote from us, you can quote *today*.

```bash
# One switch flips every EU-AI-Act-aware subsystem at once
graq compliance switch on        # shell snippet → eval to enable
graq compliance switch status    # what's actually armed, in one envelope
graq compliance switch off       # symmetric disable

# Per-subsystem CLI surface
graq compliance status                                    # legacy + new subsystems block
graq compliance export --since 2026-08-01 --sha256-sidecar  # Article 12 evidence
graq compliance baseline-doc generate --output baseline.jsonl  # Q16.1 baseline
graq compliance periodic-assessment run --period-start ... --period-end ...  # Q16.3
graq compliance feedback record --rating 5 --note "..."   # Q16.5 observation
graq compliance eur-lex-check                             # weekly drift guard
```

| Article | What GraQle ships | Where |
|---|---|---|
| **Art 4** — AI literacy | Integration guidance for providers + deployers | [docs/compliance/eu-ai-act/](./docs/compliance/eu-ai-act/article-04-ai-literacy.md) |
| **Art 9** — Risk management | Q16.3 periodic-assessment artefacts with auto-remediation triggers | `graq compliance periodic-assessment run` |
| **Art 11** — Technical documentation | Q16.1 dated, content-addressed baseline document at deployment | `graq compliance baseline-doc generate` |
| **Art 12** — Record-keeping | JSONL audit export + SHA-256 tamper-detection sidecar | `graq compliance export` |
| **Art 13** — Deployer transparency | `graph_health` + `confidence` on every reasoning envelope | every `graq_reason` call |
| **Art 14** — Human oversight | **Confidence-gated refusal** of auto-apply + R25-EU11 claim-limits | `GRAQLE_EU_AI_ACT_MODE=on` + `graq_edit/apply/auto` |
| **Art 15** — Accuracy / robustness / cybersecurity | 17 named defences + 7 measurable claims | `graq compliance status --include-robustness` |
| **Art 25** — Value-chain responsibility | Intended-purpose + PCT (Proof-Claims Token) `x-ai-eu` extension namespace (11 fields incl. content-addressed `policy_version` since v0.58.0 / cr-017) | [Art 25 doc](./docs/compliance/eu-ai-act/article-25-value-chain.md) + `graq pct issue/validate` |
| **Art 43** — Conformity Assessment | Substrate evidence (baseline-doc + audit log + periodic assessment + robustness + Article 14 gate) for deployer's Annex VI internal-control file | [Art 43 doc](./docs/compliance/eu-ai-act/article-43-conformity-assessment.md) (since v0.58.0 / cr-019) |
| **Art 50** — Transparency for users | Auto banner + `ai_disclosure` machine field | `GRAQLE_EU_AI_ACT_MODE=on` |

**Three substantive non-claims kept legally clean:**

- GraQle is **NOT** itself a high-risk AI system (no Annex III category applies).
- GraQle is **NOT** a GPAI provider under Article 51 (we use third-party LLMs, we don't place one on the EU market).
- We **provide signals and audit primitives**. We never say *compliant* or *certified*. The discipline is enforced in code — `TestNonClaimsInvariants` blocks any release that introduces a `compliant`/`certified` field.

→ **[Full Article-by-Article mapping in docs/compliance/eu-ai-act/](./docs/compliance/eu-ai-act/)**

### Contributions welcome on the compliance docs

The EU AI Act docs are deliberately open to contribution — **corrections, translations (DE/FR/ES/IT have highest demand), compliance gap reports from deployers building Annex VI internal-control files, and cross-framework mappings (NIST AI RMF, ISO 42001, ENISA, etc.) are all welcome.** See [CONTRIBUTING-COMPLIANCE.md](./CONTRIBUTING-COMPLIANCE.md) for the contribution guide, the vocabulary discipline the CI enforces, and what kinds of changes go through which review path.

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

## Two surfaces, one substrate — govern how your AI is *built*, and what it *decides*

GraQle is an EU AI Act–aligned governance substrate with **two deployment surfaces** on the
same engine (knowledge graph → governed trace → RFC 6962 Merkle → ed25519 → Sigstore Rekor):

| | **Build-time** (author surface) | **Run-time** (production surface) |
|---|---|---|
| Governs | how your AI **writes code** | what your deployed AI **decides** |
| Trigger | a code change | a production decision (loan, hiring, triage, …) |
| Emits | reviewed, impact-analysed, audit-logged changes | a tamper-evident, third-party-verifiable record per decision |
| Status | **GA** | **GA** — `attest()` capture (v0.60.0) + FastAPI middleware / `@governed` (v0.61.0) on the v0.59.0 cryptographic substrate; anchoring worker next (ADR-221) |

**Run-time, today — attach GraQle to a deployed AI system in one line (v0.60.0):**

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

Each call produces a durable, PII-safe governed record whose Merkle leaf hash is computed
with the same shipped Layer 5 primitive the batcher uses — so a runtime record is
byte-compatible with the cryptographic substrate (RFC 8785 → RFC 6962 Merkle → ed25519 →
Sigstore Rekor). Capture adds **0 ms to the write path** (recording is out of band). See
[`examples/runtime_attest_production_decisions.py`](./examples/runtime_attest_production_decisions.py).

**The cryptographic substrate (v0.59.0):** a committed batch is Merkle-rooted, ed25519-signed,
and anchored to the public Sigstore Rekor transparency log — so **anyone can detect tampering
of an audit record with no access to your infrastructure**. End-to-end walkthrough (a loan
decision → lock → Merkle → sign → anchor → auditor verifies → tamper detected → key revoked):
[`examples/v059_cryptographic_governance_usecase.py`](./examples/v059_cryptographic_governance_usecase.py).

> Build-time governance proves *we hold ourselves to this standard* — GraQle is developed
> through its own governance. Run-time governance lets you hold *your deployed AI* to the
> same cryptographically-verifiable standard. Same substrate, both surfaces.

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

## What's new in v0.58.0

> Current release: **v0.58.1** — a documentation-only patch that refreshes this landing page to surface the v0.58.0 feature set (the package is byte-identical to v0.58.0).

**EU AI Act Wave 3 substrate + OPSF PCT alignment.** Four built-and-sentinel-approved items, all backward-compatible (functionally byte-identical to v0.57.4 in the default/unconfigured state — the new capability surface is inert until activated):

- **`GRAQLE_WORKTREE_ROOT` env var** (cr-016) — the MCP server path resolver now honours this as the highest-priority project-root source, unblocking parallel-worktree development for `graq_write` / `graq_generate` / `graq_edit`. Unset = byte-identical to v0.57.4.
- **Audit-log record schema v2 + content-addressed `policy_version`** (cr-017) — every `GovernedTrace` record carries `schema_version` and a SHA-256 `policy_version` binding to the active baseline-doc; the same `policy_version` is the 11th field on the `x-ai-eu` PCT extension (OPSF PCT v0.1 Comment 4 alignment). Absent/`None` fields serialise identically to v0.57.4.
- **Article 43 conformity-assessment docs** (cr-019) — new `docs/compliance/eu-ai-act/article-43-conformity-assessment.md` mapping GraQle's substrate to Annex VI internal-control requirements, plus `CONTRIBUTING-COMPLIANCE.md` inviting docs corrections, translations (DE/FR/ES/IT), and cross-framework mappings.
- **OPSF PCT v0.1 alignment** (cr-021) — release-notes plumbing aligning the shipped engineering with the OPSF PCT public-comment window.

The cryptographic tamper-evidence layer (RFC 6962 Merkle commitments + Sigstore Rekor external anchoring) ships next as **v0.59.0**.

→ [Full v0.58.0 changelog](./CHANGELOG.md#0580-2026-05-21--research-team-v058x-directive-eu-ai-act-wave-3-substrate-opsf-pct-alignment-parallel-worktree-dev-unblocked)

---

## What's new in v0.57.0

**EU AI Act Wave 2** — closes 9 of 10 marketing-vs-built gaps (CG-MKT-01..10), bringing the honesty score from 78/100 to ~98/100. Six new compliance modules + one consolidated visibility surface:

- **`graq compliance switch on|off|status`** — single UX entry-point for the EU AI Act mode toggle. `switch status` shows every EU-AI-Act-aware subsystem (Article 50 disclosure, Article 14 gate, claim-limits, baseline-doc, periodic-assessment, feedback-trend, EUR-Lex guard) in one envelope.
- **Article 14 human-review enforcement** — `graq edit/apply/auto` refuses auto-apply when confidence < threshold (default 0.75, placeholder pending R25-EU-CALIB-01) AND EU AI Act mode is on. Structured refusal envelope with `article_14_clauses: ["14(4)(c)", "14(4)(d)"]`.
- **R25-EU11 claim-limits v1.0** — typed vocabulary (17 canonical values, 6 categories) on every governance record. L08 SHACL + L19 audit-trail enforcement. Public attribution to Ricky Jones (TrinityOS).
- **VERITAS Q16.1 baseline-doc generator** — `graq compliance baseline-doc generate` produces a dated, content-addressed artefact (SHA-256). Maps to EU AI Act Article 11 + ISO 42001 Cl. 6.2.
- **VERITAS Q16.3 periodic-assessment** — `graq compliance periodic-assessment run` with auto-remediation triggers. Maps to Article 9 + ISO 42001 Cl. 9.1.
- **VERITAS Q16.5 OBSERVATION-ONLY drift watcher** — `graq compliance feedback record/ingest` + Welford running statistics. Patent-novelty boundary enforced by mandatory AST audit test per Q-PATENT 2026-05-22.
- **EUR-Lex weekly drift guard** — `graq compliance eur-lex-check` + GitHub Actions workflow re-fetches every cited EUR-Lex URL every Monday, opens issue on regulator-side drift.
- **PCT (Proof-Claims Token) Use B** — `graqle.pct.issuer/validator` + `x-ai-eu` extension namespace (10 fields). First-public-draft of the OPSF `x-ai-eu` namespace authored by Quantamix.

**Prior v0.56.0 surface preserved:** all 7 Article docs + CLI surfaces remain. Schema version stays at `"1"` — `graq compliance status --format json` is backward compatible (new `eu_ai_act_subsystems` field is additive).

→ [Full v0.57.0 changelog](./CHANGELOG.md#0570-2026-05-16---cr-010-eu-ai-act-wave-2)

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
