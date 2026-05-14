# Article 4 — AI Literacy

> **Authoritative source:** [Article 4 — Regulation (EU) 2024/1689 on EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689) · [Article 4 — AI Act Service Desk](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-4) · [Article 4 — artificialintelligenceact.eu](https://artificialintelligenceact.eu/article/4/)
>
> **Applicability date:** 2025-02-02 (already in force).
>
> **Applies to GraQle?** YES — directly, because Article 4 applies to providers and deployers of ALL AI systems.

## What the Article requires

> "Providers and deployers of AI systems shall take measures to ensure, to their best extent, a sufficient level of AI literacy of their staff and other persons dealing with the operation and use of AI systems on their behalf, taking into account their technical knowledge, experience, education and training and the context the AI systems are to be used in."

AI literacy is defined in [Article 3(56)](https://artificialintelligenceact.eu/article/3/) as *"skills, knowledge and understanding that allow providers, deployers and affected persons to make an informed deployment of AI systems, as well as to gain awareness about the opportunities and risks of AI and possible harm it can cause."*

## What GraQle provides

### 1. Honest description of what GraQle is and is not

GraQle is a **developer tool** that:

- **Reads** your codebase, indexes it as a knowledge graph (typed nodes + typed edges), and lets you ask questions over it.
- **Reasons** using third-party large language models (Anthropic Claude, OpenAI GPT, AWS Bedrock, Ollama, Gemini, Groq, DeepSeek, Together, Mistral, OpenRouter, Fireworks, Cohere, vLLM, custom providers).
- **Suggests** code edits via `graq_edit`, `graq_generate`, `graq_apply`.

GraQle does **NOT**:

- Make autonomous decisions affecting natural persons (no employment, lending, education, biometric, or law-enforcement decision-making — see [Article 5](./out-of-scope-articles.md) + [Annex III](https://artificialintelligenceact.eu/annex/3/)).
- Train or release foundation models. The underlying models are provided by third parties subject to their own [Article 53](./out-of-scope-articles.md) obligations.
- Operate without a human in the loop. Every output is meant to be reviewed by the developer issuing the query.

### 2. Opportunities and risks (the AI Literacy core)

**Opportunities**

- Faster comprehension of unfamiliar codebases (impact analysis, dependency tracing, hub-module identification).
- Reduction in "context-window flailing" where a developer / AI assistant reads dozens of files to answer one question — GraQle reads the graph once and reasons over it.
- Audit trails (`graqle.governance.audit_log`) that capture every reasoning call for downstream compliance work.

**Risks**

- **Hallucination of code that doesn't exist.** Mitigation: `graph_health.degraded` signal (CR-004), `confidence` score in every envelope, yellow `⚠ degraded reasoning` CLI banner when the graph is in poor shape.
- **Stale knowledge graph misleading reasoning.** Mitigation: `chunks_unembedded` and `percent_stale` fields in `graph_health` signal staleness; CI `verify` step + CR-003 edge-loss guards prevent silent shrinkage.
- **Sensitive content (paths, secrets, credentials) leaking into outputs.** Mitigation: `graqle.core.secret_patterns` scans output for 200+ patterns; project-root elision; home-dir replacement; reason strings capped at 200 chars.
- **Over-reliance on automated suggestions.** Mitigation: `--human-review-required` configuration (PR-009d) refuses auto-apply when confidence is below threshold.

### 3. Staff and contributor training measures

The maintainers of GraQle (the team contributing to `quantamixsol/graqle`) follow the **BAU Change Request process** ([CR-001 charter](https://github.com/quantamixsol/graqle/tree/master/.gsm/external/Change%20Requests)):

- Every non-trivial change is documented as a CR with explicit scope, evidence, PR strategy, test strategy, rollback procedure, and acceptance criteria.
- Every PR goes through a multi-pass sentinel review (`focus=all` + `focus=security`, plus for CR-009 onward a `focus=compliance` pass).
- A sole-approver gate ensures no change ships without explicit human sign-off.

The team's working knowledge is captured in the project's [feedback and lessons system](https://github.com/quantamixsol/graqle/blob/master/.gsm/external/Change%20Requests/CR-001-bau-charter.md) — this is the practical "training" surface.

### 4. AI literacy for downstream users

For developers integrating GraQle into their workflows or AI systems:

- Read this entire `docs/compliance/eu-ai-act/` directory.
- Read the [CHANGELOG](https://github.com/quantamixsol/graqle/blob/master/CHANGELOG.md) for the release you depend on — especially the "Breaking changes" sections.
- Run `graq compliance status` (PR-009b) for a structured rundown of which Articles GraQle currently provides signals for.

## How to quote this in your compliance file

When documenting your own Article 4 obligations as a downstream provider/deployer of an AI system that uses GraQle:

> "Our team has taken AI literacy measures as required under Article 4 of Regulation (EU) 2024/1689. For each third-party AI tool we depend on, we maintain documentation of its capabilities, limitations, and risk surface. For GraQle ({version}), this documentation is sourced from [github.com/quantamixsol/graqle/blob/master/docs/compliance/eu-ai-act/article-04-ai-literacy.md](https://github.com/quantamixsol/graqle/blob/master/docs/compliance/eu-ai-act/article-04-ai-literacy.md) — including the explicit positioning that GraQle is NOT a high-risk AI system, the catalogue of opportunities + risks, and the catalogue of mitigations the tool provides."

## Related GraQle documents

- [Article 12 — Record-Keeping](./article-12-record-keeping.md) — how the audit log captures every reasoning interaction
- [Article 13 — Transparency to Deployers](./article-13-transparency-to-deployers.md) — the `graph_health` snapshot and confidence scores
- [Article 14 — Human Oversight](./article-14-human-oversight.md) — the `--human-review-required` flag and yellow degraded-reasoning banner

## Sources

- [Regulation (EU) 2024/1689 — EUR-Lex consolidated text](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689)
- [Article 4 — AI Act Service Desk](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-4)
- [Article 4 — artificialintelligenceact.eu](https://artificialintelligenceact.eu/article/4/)
- [Article 3 definitions](https://artificialintelligenceact.eu/article/3/) (Article 3(56) — AI literacy definition)
