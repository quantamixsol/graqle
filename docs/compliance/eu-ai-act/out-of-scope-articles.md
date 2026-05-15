# Articles That Do NOT Apply to GraQle — Attestations

> Some Articles of [Regulation (EU) 2024/1689](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689) do not apply to GraQle by its current design. This document records the explicit, defensible attestation for each, so that a regulator or customer compliance team asking "what about Article X?" gets a direct answer.

## Article 5 — Prohibited AI Practices

> **Authoritative source:** [Article 5 — artificialintelligenceact.eu](https://artificialintelligenceact.eu/article/5/)
>
> **Applicability date:** 2025-02-02 (in force).

### What the Article prohibits

Article 5 prohibits the placing on the market / putting into service / use of AI systems that:

- (a) Deploy subliminal techniques beyond a person's consciousness with the objective or effect of materially distorting their behaviour.
- (b) Exploit vulnerabilities of specific groups due to age, disability, or socio-economic status.
- (c) Conduct social scoring leading to detrimental or unfavourable treatment.
- (d) Make risk assessments of natural persons to predict criminal offending.
- (e) Create or expand facial recognition databases through untargeted scraping of facial images from the internet or CCTV footage.
- (f) Infer emotions in workplaces and education institutions (with safety/medical carve-outs).
- (g) Biometrically categorise natural persons to deduce or infer race, political opinions, trade union membership, religious / philosophical beliefs, sex life, or sexual orientation.
- (h) Use real-time remote biometric identification systems in publicly accessible spaces for law-enforcement (with narrow carve-outs).

### GraQle attestation

**GraQle does NONE of the above.** GraQle is a developer tool that reads source code, builds a knowledge graph of the codebase, and reasons over that graph using third-party large language models to help software engineers understand and modify their code. The activities GraQle performs are:

- Reading source code files the developer has explicit access to.
- Building a typed graph of code structure (classes, functions, modules, imports, etc.).
- Issuing reasoning queries against that graph via LLM backends.
- Suggesting code edits.

None of these activities involve manipulation of natural persons' behaviour, exploitation of vulnerable groups, social scoring, criminal-offence prediction, facial recognition database construction, emotion inference in workplaces, biometric categorisation, or remote biometric identification in publicly accessible spaces.

This attestation is provided in good faith by the GraQle maintainers as of v0.55.0. If a future GraQle release introduces a feature that approaches any of the prohibited practices, that feature will be flagged in the CHANGELOG and this document will be updated.

---

## Article 53 — Obligations for Providers of General-Purpose AI Models

> **Authoritative source:** [Article 53 — artificialintelligenceact.eu](https://artificialintelligenceact.eu/article/53/) · [Article 53 — AI Act Service Desk](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-53)
>
> **Applicability date:** 2025-08-02 (in force).

### What the Article requires

Article 53 obligates **providers of general-purpose AI MODELS** (the foundation-model providers — Anthropic, OpenAI, Mistral, Meta, etc.) to:

- (1)(a) Draw up + keep up to date the technical documentation of the model, including its training and testing process and the results of its evaluation.
- (1)(b) Draw up + keep up to date and make available information and documentation to providers of AI systems who intend to integrate the GPAI model into their AI systems.
- (1)(c) Put in place a policy to comply with EU copyright law and related rights, in particular for text and data mining reservations expressed under [Directive (EU) 2019/790](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32019L0790) Article 4(3).
- (1)(d) Draw up + make publicly available a sufficiently detailed summary about the content used for training the GPAI model.

### GraQle attestation

**GraQle is NOT a general-purpose AI model provider.** GraQle is a tool that **uses** general-purpose AI models. We do not train, fine-tune, distil, distribute, or release foundation models.

GraQle integrates with the following GPAI model providers — each of whom is subject to their own Article 53 obligations:

| Provider | Models GraQle integrates | Article 53 disclosure location |
|----------|--------------------------|-------------------------------|
| Anthropic | Claude Sonnet / Opus / Haiku family | [anthropic.com](https://www.anthropic.com/) |
| OpenAI | GPT family + reasoning models | [openai.com](https://openai.com/) |
| AWS Bedrock | Claude / Titan / others (proxied) | Via each underlying provider |
| Google | Gemini family | [ai.google.dev](https://ai.google.dev/) |
| Mistral AI | Mistral / Mixtral family | [mistral.ai](https://www.mistral.ai/) |
| Groq | Hosted open models | Via each underlying open-model provider |
| DeepSeek | DeepSeek family | [deepseek.com](https://www.deepseek.com/) |
| Together | Hosted open models | Via each underlying open-model provider |
| Ollama | Locally-run open models (Llama, Qwen, etc.) | Via each underlying open-model provider |
| OpenRouter | Multi-provider routing | Each underlying provider |
| Fireworks | Hosted open / fine-tuned models | Via each underlying provider |
| Cohere | Command family | [cohere.com](https://cohere.com/) |
| vLLM | Locally-served open models | Via each underlying open-model provider |
| Custom | User-configured endpoints | Customer-determined |

GraQle's role in your value chain is that of an **AI-system provider/deployer (downstream user)** of these GPAI models. We:

- **Consume** the providers' Article 53 documentation (their training-data summaries, copyright policies, instructions-for-use).
- **Forward** which model was used in a given reasoning call to our audit log + `ai_disclosure` envelope field, so customers can trace from a GraQle output back to the underlying GPAI provider's Article 53 documentation.
- **Do not republish** the providers' training-data claims. If a customer needs the GPAI provider's Article 53 documentation, they should obtain it directly from the provider.

This attestation is provided in good faith by the GraQle maintainers as of v0.55.0. If a future GraQle release introduces a foundation model authored or trained by GraQle, that release will be flagged in the CHANGELOG and an Article 53 obligations document will be added.

---

## Article 55 — Obligations for Providers of GPAI Models with Systemic Risk

> **Authoritative source:** [Article 55 — artificialintelligenceact.eu](https://artificialintelligenceact.eu/article/55/)
>
> **Applicability date:** 2025-08-02 (in force).

### GraQle attestation

**Not applicable.** GraQle is not a GPAI model provider; therefore, by definition, GraQle is not a provider of a GPAI model with systemic risk. The systemic-risk obligations of Article 55 (model evaluations, adversarial testing, incident reporting, cybersecurity) fall on the underlying GPAI providers, not on us.

---

## Articles 16–22 — Provider QMS, Conformity Assessment, Registration (for High-Risk AI System Providers)

### GraQle attestation

**Not applicable to GraQle in its current form,** because GraQle is not a high-risk AI system (see [Article 6 / Annex III classification rationale](./README.md#positioning-statement) in the index). Customers embedding GraQle in their own high-risk AI systems become the high-risk-system providers per Article 25 and assume Articles 16–22 obligations for their own system.

---

## Annex VII — Conformity Assessment by Notified Body

### GraQle attestation

**Out of scope for CR-009 Wave 1.** A notified-body conformity assessment per Annex VII is required only for certain high-risk AI systems and is a months-long process requiring an accredited assessment partner. GraQle is not a high-risk AI system and therefore has no Annex VII obligation. If a customer demand emerges for GraQle to undergo a voluntary conformity assessment to support their own high-risk-system certification, that work would be a separate CR (provisional name CR-010-wave-2-conformity-readiness) — not in scope here.

---

## Updates to this document

This document will be updated whenever:

- A new GraQle release introduces a feature that approaches a previously-out-of-scope Article.
- The Commission publishes a guideline that materially changes the interpretation of any of the cited Articles.
- A customer asks a question that reveals a gap in this attestation surface.

CHANGELOG entries that trigger a refresh of this document will be tagged `compliance-attestation`.

## Sources

- [Regulation (EU) 2024/1689 — EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689)
- [Article 5](https://artificialintelligenceact.eu/article/5/)
- [Article 53](https://artificialintelligenceact.eu/article/53/)
- [Article 55](https://artificialintelligenceact.eu/article/55/)
- [General-Purpose AI Models Q&A](https://digital-strategy.ec.europa.eu/en/faqs/general-purpose-ai-models-ai-act-questions-answers)
- [Guidelines for GPAI providers](https://digital-strategy.ec.europa.eu/en/policies/guidelines-gpai-providers)
