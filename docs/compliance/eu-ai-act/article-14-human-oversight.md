# Article 14 — Human Oversight

> **Authoritative source:** [Article 14 — Regulation (EU) 2024/1689 on EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689) · [Article 14 — artificialintelligenceact.eu](https://artificialintelligenceact.eu/article/14/)
>
> **Applicability date:** 2026-08-02.
>
> **Applies to GraQle?** INDIRECTLY — GraQle is not a high-risk AI system, but we **provide the oversight UX primitives** that high-risk-system deployers using GraQle need to satisfy their Article 14 obligations.

> **Forward-reference notice:** The yellow CLI degraded-reasoning banner and the `confidence` score are **already shipped in v0.55.0** (via CR-004). The `--human-review-required` flag and `GRAQLE_EU_AI_ACT_MODE` env-var enforcement (§3) are **planned in PR-009d of this CR-009 batch**; until that PR lands, downstream pipelines should implement the confidence-threshold gate at the integration layer using the existing `confidence` field on every reasoning envelope.

## What the Article requires

> "High-risk AI systems shall be designed and developed in such a way... that they can be effectively overseen by natural persons during the period in which they are in use."

Specifically, human oversight measures must enable, as appropriate, the natural persons to whom oversight is assigned to:

- (a) Properly understand the relevant capacities and limitations of the high-risk AI system and monitor its operation, including detecting and addressing anomalies, dysfunctions, and unexpected performance.
- (b) Remain aware of automation bias.
- (c) Correctly interpret the system's output.
- (d) Decide not to use the system in a particular situation, or otherwise disregard, override, or reverse the output.
- (e) Intervene in the operation or interrupt it via a "stop" button.

For certain high-risk AI systems (e.g. those in Annex III(1) — remote biometric identification), the Article additionally requires that no action or decision is taken by the deployer based on identification unless that identification has been **separately verified and confirmed by at least two natural persons** with the necessary competence, training, and authority.

## What GraQle provides

### 1. The yellow `⚠ degraded reasoning` CLI banner (CR-004)

When `graph_health.degraded` is `true`, the `graq run` and `graq reason` CLI surfaces print a yellow banner BEFORE the answer:

```
⚠ degraded reasoning: chunks_unembedded=3127, falling back to keyword retrieval
```

This addresses Article 14(4)(c) (helping the human-in-the-loop correctly interpret the output) by surfacing the degradation signal **before** the human sees the answer. The banner is defended in four layers (200-char cap → secret-pattern redaction → ANSI strip → Rich markup escape).

### 2. The `confidence` score in every reasoning envelope (CR-004)

Every reasoning output carries an opaque confidence score in [0.0, 1.0]. This addresses Article 14(4)(b) (remaining aware of automation bias) by giving the deployer's pipeline a numerical signal it can route on:

- `confidence >= 0.75` (default high-bar): autonomous downstream use OK
- `0.65 <= confidence < 0.75`: log + caution
- `confidence < 0.65`: refuse autonomous use, prefer human review
- `confidence < 0.35`: refuse downstream use entirely

These thresholds are configurable via `GraqleConfig.governance.confidence_thresholds`.

### 3. The `--human-review-required` flag (PR-009d)

When the `GRAQLE_EU_AI_ACT_MODE=on` env var is set and a user runs:

```bash
graq edit --file foo.py --description "Refactor X" --auto
```

…the `--auto` flag is **honored only if the underlying reasoning confidence ≥ `human_review_required_threshold`** (default 0.75). Below the threshold:

```
⚠ Auto-apply refused: confidence 0.42 < human_review_required_threshold 0.75.
   Article 14(4)(c)+(d): output below threshold requires human review.
   Re-run without --auto to inspect the diff, or lower the threshold via
   --human-review-required-threshold (NOT recommended for high-risk pipelines).
```

This addresses Article 14(4)(d) (the human's ability to **decide not to use** the output).

### 4. The sentinel-review pattern (BAU CR process)

For developers of GraQle itself, every change goes through a multi-pass sentinel review (`graq_review focus=all` + `focus=security` + for CR-009 onward `focus=compliance`) before merge. This is **GraQle's internal Article 14 discipline applied to its own development** — a working example of how to operate AI-assisted development with human-in-the-loop oversight at every meaningful decision boundary.

### 5. Documentation of the oversight UX pattern

The full GraQle oversight UX is:

1. **Pre-call:** Configure `confidence_thresholds` and `human_review_required_threshold` per the risk profile of the integrating system.
2. **In-call:** Read `graph_health` and `confidence` on every envelope. Surface degradation visibly to the human.
3. **Post-call:** Persist the envelope to the audit log per [Article 12](./article-12-record-keeping.md). When a human overrides or disregards the output, log that as a structured event the deployer can later audit.

We recommend the deployer's high-risk AI system implements all three layers — GraQle provides the signals; the deployer wires the pipeline.

## How to quote this in your compliance file

When documenting your own Article 14 obligations as a deployer of a high-risk AI system that uses GraQle:

> "Our high-risk AI system uses GraQle ({version}) for code-reasoning support during {scenario}. The human-oversight measures we have implemented per Article 14 include: (a) routing every GraQle reasoning output through a confidence threshold gate (set to {threshold}) that requires explicit human review for outputs below the threshold; (b) surfacing the yellow `⚠ degraded reasoning` banner from GraQle's CLI to the human reviewer; (c) configuring `GRAQLE_EU_AI_ACT_MODE=on` with `--human-review-required` enforcement so that auto-apply via `graq edit --auto` is refused below the threshold; (d) logging every human override event into our Article 12 record-keeping evidence with the structured override schema documented at [github.com/quantamixsol/graqle/blob/master/docs/compliance/eu-ai-act/article-14-human-oversight.md](https://github.com/quantamixsol/graqle/blob/master/docs/compliance/eu-ai-act/article-14-human-oversight.md)."

## What GraQle does NOT do

To avoid overstating: GraQle does not implement the **"two natural persons" verification** required by Article 14(5) for the specific high-risk AI systems referred to in point 1 of Annex III (remote biometric identification). That is an obligation of the system whose use case falls under Annex III(1) — those use cases are not what GraQle is for. If your high-risk AI system falls into that category, you must implement the two-person verification at your system layer; GraQle's confidence + graph_health signals support but do not replace it.

## Related GraQle documents

- [Article 4 — AI Literacy](./article-04-ai-literacy.md) — the opportunities + risks the human needs to understand
- [Article 12 — Record-Keeping](./article-12-record-keeping.md) — how overrides + decisions are logged
- [Article 13 — Transparency to Deployers](./article-13-transparency-to-deployers.md) — the underlying transparency signals
- [Article 15 — Robustness](./article-15-robustness.md) — the robustness floor that confidence sits on top of

## Sources

- [Regulation (EU) 2024/1689 — EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689)
- [Article 14 — artificialintelligenceact.eu](https://artificialintelligenceact.eu/article/14/)
- [Annex III](https://artificialintelligenceact.eu/annex/3/) — the use cases where Article 14(5) two-person verification applies
