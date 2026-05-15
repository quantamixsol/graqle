# Article 25 — Responsibilities Along the AI Value Chain

> **Authoritative source:** [Article 25 — Regulation (EU) 2024/1689 on EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689) · [Article 25 — artificialintelligenceact.eu](https://artificialintelligenceact.eu/article/25/)
>
> **Applicability date:** 2026-08-02.
>
> **Applies to GraQle?** YES — when GraQle is a component of your high-risk AI system, Article 25 governs how responsibility is allocated between GraQle (as upstream supplier) and you (as the system provider).

## What the Article requires

Article 25 governs the allocation of responsibilities along the AI value chain. Key provisions:

- A distributor, importer, deployer, or other third party **shall be considered a provider** of a high-risk AI system and shall be subject to the provider obligations if any of the following conditions are met:
  - They put their name or trademark on a high-risk AI system that has already been placed on the market.
  - They make a **substantial modification** to a high-risk AI system that has already been placed on the market.
  - They modify the intended purpose of an AI system, including a general-purpose AI system, in a way that makes it a high-risk AI system.

- The provider that placed the original high-risk AI system on the market **shall no longer be considered the provider** of that specific AI system for the purposes of the Regulation, when one of the above conditions is met.

- Providers of high-risk AI systems and third parties supplying AI systems, tools, services, components, or processes that are used or integrated in a high-risk AI system shall, **by written agreement**, specify the information, capabilities, technical access, and other assistance required to enable the provider to comply with the obligations of the Regulation.

## What GraQle provides

### 1. GraQle's pinned position in your value chain

When your AI system embeds GraQle, GraQle is:

- **An upstream tool / component**, not a provider of your high-risk system.
- **Not** a general-purpose AI MODEL — that's the underlying LLM provider (Anthropic, OpenAI, etc.), which has its own Article 53 obligations.
- **A tool that uses general-purpose AI models** to reason over your codebase.

Your responsibilities as the deployer / system-provider embedding GraQle:

- You **are** the provider of your high-risk system under Article 25 if your system meets the Article 6 / Annex III classification.
- You **must satisfy** Articles 9, 12, 13, 14, 15, 16 (etc.) for your system.
- GraQle **helps you satisfy them** by providing the signals catalogued in this `docs/compliance/eu-ai-act/` directory.

### 2. Intended-purpose statement

**GraQle's intended purpose:** *"A developer tool that reads source code, builds a knowledge graph of the codebase, and answers developer questions over that graph using third-party large language models. Used by software engineers to accelerate code comprehension, impact analysis, and suggested-edit workflows."*

If you modify GraQle's intended purpose — e.g. you embed GraQle in a system that reasons about people's personal data, biometric data, or in any of the Annex III high-risk use cases — **you become the provider** of that high-risk system per Article 25(1)(c), and you assume the full Article 9–16 obligations for it. GraQle's documentation here can be cited, but it does not transfer the obligation.

### 3. Substantial modification

A "substantial modification" of GraQle that would trigger your provider obligation under Article 25(1)(b) includes:

- Repackaging GraQle and selling it as a commercial high-risk AI product without re-running the full Article 9–16 conformity work.
- Wrapping GraQle's outputs in autonomous downstream decision-making in any Annex III use case.
- Bundling GraQle into a regulated medical device, vehicle, or other Annex I product without the OEM conformity assessment.

**What is NOT a substantial modification:**

- Using GraQle as documented in `docs/compliance/eu-ai-act/`.
- Configuring `GraqleConfig` options for your environment.
- Calling GraQle from your CI / IDE / agent pipeline.

### 4. Limits-of-use disclaimer

GraQle is **not appropriate** for use in any of the following without additional human oversight + your own Article 9–16 conformity work:

- Autonomous decision-making affecting natural persons' rights (employment, education, lending, law enforcement, biometric, immigration, justice administration, democratic processes).
- Safety-critical systems where the AI output drives a safety-relevant action without human approval.
- Critical infrastructure operation.
- Use in any Annex III(1) — Annex III(8) high-risk category as the sole or primary decision-making layer.

This disclaimer is repeated in the CLI startup banner (when `GRAQLE_EU_AI_ACT_MODE=on`) and in the README.

### 5. Written agreement availability

If your high-risk AI system embeds GraQle and you need a written agreement specifying the information, capabilities, technical access, and assistance GraQle will provide per Article 25(4), contact: **compliance@graqle.com**.

In the absence of a custom written agreement, this `docs/compliance/eu-ai-act/` directory serves as GraQle's standing public disclosure of the information, capabilities, and technical access GraQle commits to provide.

## How to quote this in your compliance file

When documenting your own Article 25 allocation in your high-risk AI system value chain:

> "Our high-risk AI system uses GraQle ({version}) as an upstream developer tool / component for code-reasoning support. Per the value-chain allocation documented at [github.com/quantamixsol/graqle/blob/master/docs/compliance/eu-ai-act/article-25-value-chain.md](https://github.com/quantamixsol/graqle/blob/master/docs/compliance/eu-ai-act/article-25-value-chain.md), GraQle is positioned as a general-purpose developer tool and is not a high-risk AI system itself; we, as the integrator + system provider for {our system name}, retain provider obligations under Article 25 for our system. We have not made a substantial modification to GraQle's intended purpose (as defined in §2 of the linked document); we use GraQle for {scenario}, which falls within the documented intended-purpose envelope. The technical signals and information GraQle provides to enable our Article 9–15 obligations are catalogued in the Article 4 / 12 / 13 / 14 / 15 documents in the same directory."

## What GraQle does NOT do

To avoid overstating: GraQle does not provide a notified-body conformity assessment per Annex VII, does not provide CE marking, and does not enrol in any EU AI Office voluntary commitments on your behalf. Those are your obligations as the high-risk system provider. GraQle's `docs/compliance/eu-ai-act/` directory is a transparency offering — not a substitute for your own conformity work.

## Related GraQle documents

- [README — Positioning Statement](./README.md) — the broader positioning context
- [Article 4 — AI Literacy](./article-04-ai-literacy.md) — what GraQle is and is not
- [Article 13 — Transparency to Deployers](./article-13-transparency-to-deployers.md) — the information GraQle commits to provide

## Sources

- [Regulation (EU) 2024/1689 — EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689)
- [Article 25 — artificialintelligenceact.eu](https://artificialintelligenceact.eu/article/25/)
- [Annex III high-risk use cases](https://artificialintelligenceact.eu/annex/3/)
- [Annex I regulated products](https://artificialintelligenceact.eu/annex/1/)
