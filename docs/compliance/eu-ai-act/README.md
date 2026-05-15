# GraQle × EU AI Act — Compliance Mapping

> **What you'll find here.** Every Article of [Regulation (EU) 2024/1689](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689) (the EU AI Act) that touches GraQle, mapped to the specific GraQle code, configuration, or output field that addresses it. **Compliance signals you can quote in your own Article 9 risk-management file.**

## Quick links

- **Authoritative regulation source:** [EUR-Lex consolidated text](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689) · [HTML](https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=OJ%3AL_202401689) · [PDF](https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=OJ:L_202401689)
- **GraQle release this document tracks:** v0.55.0+ (the "Reasoning Honesty + Cross-Project Reliability" release rolled up CR-002, CR-003, CR-004, CR-005a, CR-008 — every one of which produced a signal we cite below).
- **EU AI Office Service Desk:** [ai-act-service-desk.ec.europa.eu](https://ai-act-service-desk.ec.europa.eu/)

## Positioning statement

**GraQle is a general-purpose AI tool for developers.** It uses third-party AI models (Anthropic, OpenAI, AWS Bedrock, Ollama, Gemini, Groq, etc.) to reason over a knowledge graph of your codebase. GraQle:

- **Is NOT a high-risk AI system** per [Article 6](https://artificialintelligenceact.eu/article/6/) / Annex III — developer code-reasoning is not one of the listed high-risk use cases.
- **Is NOT a general-purpose AI MODEL provider** per [Article 53](https://artificialintelligenceact.eu/article/53/) — we don't train or release foundation models; we use them. (The providers of those underlying models bear Article 53 obligations.)
- **Is subject to [Article 4](https://artificialintelligenceact.eu/article/4/) (AI literacy)** because that applies to providers and deployers of ALL AI systems.
- **Is subject to [Article 50](https://artificialintelligenceact.eu/article/50/) (transparency for AI interaction)** because `graq_reason`, `graq_predict`, and `graq_chat_turn` interact with humans via AI-generated output.
- **Provides the compliance signals your high-risk AI system needs** (graph_health, confidence scores, audit trails, robustness defences) so that when GraQle is embedded into your high-risk system, your Articles 9 / 12 / 13 / 14 / 15 documentation can quote ours.

This is **"EU AI Act–aligned"** positioning. We do not claim certification. We do not claim compliance. We claim: **defensible documentation + code signals you can use in your own compliance work.**

## Articles covered

| Article | Topic | Applies to GraQle? | Document |
|---------|-------|--------------------|----------|
| **Article 4** | AI Literacy | YES — directly. In force since 2025-02-02. | [article-04-ai-literacy.md](./article-04-ai-literacy.md) |
| **Article 5** | Prohibited Practices | N/A (one-line attestation) | [out-of-scope-articles.md](./out-of-scope-articles.md) |
| **Article 6 / Annex III** | High-risk classification | NOT a high-risk system | (see positioning above) |
| **Article 9** | Risk Management System | INDIRECTLY (customer high-risk systems quote GraQle signals) | [article-13-transparency-to-deployers.md](./article-13-transparency-to-deployers.md) (linked) |
| **Article 12** | Record-Keeping | INDIRECTLY (customer record-keeping uses our audit logs) | [article-12-record-keeping.md](./article-12-record-keeping.md) |
| **Article 13** | Transparency to Deployers | INDIRECTLY (we provide the transparency signals) | [article-13-transparency-to-deployers.md](./article-13-transparency-to-deployers.md) |
| **Article 14** | Human Oversight | INDIRECTLY (we provide oversight UX primitives) | [article-14-human-oversight.md](./article-14-human-oversight.md) |
| **Article 15** | Accuracy, Robustness, Cybersecurity | INDIRECTLY (we provide defence-in-depth measures) | [article-15-robustness.md](./article-15-robustness.md) |
| **Article 25** | Responsibilities along the AI value chain | YES — when GraQle is a component of your high-risk system | [article-25-value-chain.md](./article-25-value-chain.md) |
| **Article 50** | Transparency for certain AI systems (applicable 2026-08-02) | YES — directly | [article-50-transparency.md](./article-50-transparency.md) |
| **Article 53** | GPAI model provider obligations | N/A (we're a downstream user of GPAI) | [out-of-scope-articles.md](./out-of-scope-articles.md) |

## Implementation timeline (anchors)

| Date | Effect |
|------|--------|
| 2024-08-01 | Regulation entered into force |
| **2025-02-02** | **Prohibited practices + AI literacy applicable (Articles 4–5)** |
| 2025-08-02 | Governance + GPAI obligations applicable |
| **2026-08-02** | **Full applicability — Articles 6–29, 50 enforceable** |
| 2028-08-02 | High-risk AI in regulated products (Annex I) |

See [Article 113 — Entry into Force and Application](https://artificialintelligenceact.eu/article/113/).

## How to use these documents

If you're integrating GraQle into your own AI system and you're working through your compliance documentation:

1. **Identify which Article(s) apply to your system** under the EU AI Act.
2. **Open the corresponding GraQle document above** to find the specific code path / output field / configuration option that supplies the signal you need.
3. **Quote the GraQle document** in your file. Each document is written to be quotable — short paragraphs, concrete file/line references, EUR-Lex back-links.

## Verifying the mapping

This documentation is regenerated and tested in CI. The test [`tests/test_compliance/test_eu_ai_act_docs_present.py`](../../../tests/test_compliance/test_eu_ai_act_docs_present.py) asserts:

- Every Article file listed in the table above exists on disk
- Every file has the required headings (`## What the Article requires`, `## What GraQle provides`, `## How to quote this in your compliance file`)
- Every file embeds the authoritative EUR-Lex link

If you find a stale claim, a broken link, or a feature change that drifted from the documentation, please open an issue at [github.com/quantamixsol/graqle/issues](https://github.com/quantamixsol/graqle/issues) tagged `compliance`.

## A note on dual compliance

Several signals GraQle exposes serve dual compliance purposes:

- **Article 12 record-keeping** cross-references **SOC2 § CC7.2** (system event logging).
- **Article 15 robustness** cross-references **ISO27001 § A.8.25** (secure development lifecycle).

We note these in the individual documents.

## Disclaimer

This documentation describes GraQle's design and outputs. It does not constitute legal advice. Your obligations under the EU AI Act depend on the specific use case you put GraQle into. When in doubt, consult a qualified legal advisor — particularly before relying on this documentation in a notified-body conformity assessment, market-surveillance investigation, or formal regulator filing.

**Sources actively tracked (last refreshed 2026-05-15):**
- [Consultation on draft Article 50 transparency guidelines (May 2026)](https://digital-strategy.ec.europa.eu/en/consultations/consultation-draft-guidelines-transparency-obligations-under-ai-act)
- [Code of Practice on AI-generated content marking (March 2026)](https://digital-strategy.ec.europa.eu/en/policies/code-practice-ai-generated-content)
- [GPAI Code of Practice](https://digital-strategy.ec.europa.eu/en/policies/contents-code-gpai)
