# Article 13 — Transparency and Provision of Information to Deployers

> **Authoritative source:** [Article 13 — Regulation (EU) 2024/1689 on EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689) · [Chapter III — High-Risk AI Systems requirements (artificialintelligenceact.eu)](https://artificialintelligenceact.eu/section/3-2/)
>
> **Applicability date:** 2026-08-02.
>
> **Applies to GraQle?** INDIRECTLY — GraQle is not a high-risk AI system, but we **provide the transparency signals** that high-risk-system deployers using GraQle need to satisfy their Article 13 obligations.

> **Forward-reference notice:** The `graph_health` snapshot, `confidence` score, and yellow CLI degraded-reasoning banner referenced here are **already shipped in v0.55.0** (via CR-004). The MCP envelope `compliance` block (§5) is **planned in PR-009d of this CR-009 batch**; until that PR lands, customers can still consume `graph_health` and `confidence` via the existing envelope fields documented in [CHANGELOG § 0.55.0](https://github.com/quantamixsol/graqle/blob/master/CHANGELOG.md#0550-2026-05-14).

## What the Article requires

> "High-risk AI systems shall be designed and developed in such a way to ensure that their operation is sufficiently transparent to enable deployers to interpret the system's output and use it appropriately."

The instructions for use must include at minimum:

- The identity and contact details of the provider.
- The characteristics, capabilities, and limitations of performance, including:
  - The intended purpose
  - Levels of accuracy, robustness, cybersecurity
  - Foreseeable circumstances which may lead to risks to health, safety, fundamental rights
  - Performance regarding the persons or groups of persons on which the system is intended to be used
  - Specifications for input data
  - Information enabling deployers to interpret output
- The changes to the high-risk AI system and its performance pre-determined by the provider.
- Human oversight measures referred to in [Article 14](./article-14-human-oversight.md).
- Computational and hardware resources needed.
- Expected lifetime + maintenance + care measures.
- Description of mechanisms allowing deployers to properly collect, store, and interpret logs per [Article 12](./article-12-record-keeping.md).

## What GraQle provides

### 1. The `graph_health` snapshot (CR-004)

Every `graq_reason`, `graq_predict`, and `graq_safety_check` envelope carries a `graph_health` block:

```json
{
  "graph_health": {
    "node_count": 1234,
    "edge_count": 8901,
    "chunks_unembedded": 0,
    "percent_stale": 0.0,
    "activation_mode": "semantic",
    "degraded": false,
    "reason": null,
    "schema_version": "1"
  }
}
```

This is **exactly the kind of "information enabling deployers to interpret output"** that Article 13 requires. Fields:

| Field | What deployers can interpret |
|-------|------------------------------|
| `node_count`, `edge_count` | Whether the knowledge graph is well-populated. Low counts → low coverage → take output with caution. |
| `chunks_unembedded` | How many code chunks lack semantic embeddings. Non-zero → activation has fallen back. |
| `percent_stale` | Proportion of nodes whose semantic representation is older than recent edits. High → reasoning may not reflect latest code. |
| `activation_mode` | `semantic` / `keyword_fallback` / `hybrid` / `unknown` — the underlying retrieval mode. Keyword fallback indicates degraded retrieval. |
| `degraded` | The disjunction of the four signals → "trust this output less". |
| `reason` | Sanitised human-readable explanation when `degraded=true`. |
| `schema_version` | Audit-trail forward-compatibility. Currently `"1"`. |

The probe is **contractually never-raises** (3-deep defence) and adds < 5 ms p95 to envelope build (CI fail-gate).

### 2. The `confidence` score

Every reasoning output includes a `confidence` field in [0.0, 1.0], computed by `_compute_answer_confidence` in `graqle.plugins.mcp_server`. This is GraQle's structured answer-quality signal — separate from the underlying LLM's own confidence estimates.

The score is **opaque from a public-API perspective** — what matters to a deployer is the threshold semantics:

- `confidence >= 0.65` (CR-009 default): consider the output adequate for autonomous downstream use.
- `confidence < 0.65`: prefer human review (see [Article 14 — Human Oversight](./article-14-human-oversight.md)).
- `confidence < 0.35`: refuse autonomous downstream use.

Deployers can tune these thresholds via `GraqleConfig.governance.confidence_thresholds`.

### 3. The CLI yellow `⚠ degraded reasoning` banner

When `graph_health.degraded` is `true`, the `graq run` and `graq reason` CLI surfaces print a yellow banner before the answer:

```
⚠ degraded reasoning: chunks_unembedded=3127, falling back to keyword retrieval
```

This is the **user-visible transparency signal** for human-in-the-loop developers. The banner is defended in four layers:

1. 200-char reason cap (CR-004 PR-004a).
2. `_redact_secrets` + `_sanitise_reason` (CR-004 PR-004a) for project-root elision + secret pattern scrubbing.
3. ANSI CSI/OSC strip via `_sanitise_for_console` (CR-004 PR-004c).
4. Rich markup escape on the final print.

### 4. System card (this document set)

The intended purpose, capabilities, limitations, and risk surface of GraQle are documented in:

- [Article 4 — AI Literacy](./article-04-ai-literacy.md) — opportunities and risks
- [Article 14 — Human Oversight](./article-14-human-oversight.md) — oversight measures
- [Article 15 — Robustness](./article-15-robustness.md) — accuracy, robustness, cybersecurity claims
- [Article 25 — Value-Chain Responsibility](./article-25-value-chain.md) — input-data specifications + integration limits
- [README](./README.md) — provider identity and contact

### 5. Machine-readable system card endpoint (PR-009d)

When `GRAQLE_EU_AI_ACT_MODE=on` is set, every MCP envelope includes a top-level `compliance` block:

```json
{
  "compliance": {
    "articles_covered": ["4", "12", "13", "14", "15", "25", "50"],
    "system_card_url": "https://github.com/quantamixsol/graqle/blob/master/docs/compliance/eu-ai-act/README.md",
    "audit_log_export": "graq audit export --since <DATE>",
    "version": "0.55.0"
  }
}
```

This makes the GraQle compliance posture **machine-introspectable** — a customer's compliance pipeline can verify in CI that the version of GraQle they're using still covers the Articles they depend on.

## How to quote this in your compliance file

When documenting your own Article 13 obligations as a deployer of a high-risk AI system that uses GraQle:

> "Our high-risk AI system uses GraQle ({version}) for code-reasoning support during {scenario}. The interpretation guidance for GraQle's output is sourced from [github.com/quantamixsol/graqle/blob/master/docs/compliance/eu-ai-act/article-13-transparency-to-deployers.md](https://github.com/quantamixsol/graqle/blob/master/docs/compliance/eu-ai-act/article-13-transparency-to-deployers.md). Specifically, each reasoning call returns a `graph_health` snapshot and `confidence` score; we have configured our pipeline to treat `confidence < 0.65` outputs as requiring human review per Article 14, and to refuse downstream use of any output with `graph_health.degraded = true` until the underlying graph staleness is resolved. The `compliance.articles_covered` machine-readable field verifies in our CI that the version of GraQle in production still covers Articles 4, 12, 13, 14, 15, 25, 50."

## Related GraQle documents

- [Article 12 — Record-Keeping](./article-12-record-keeping.md) — how transparency signals are persisted to the audit log
- [Article 14 — Human Oversight](./article-14-human-oversight.md) — how transparency signals drive oversight
- [Article 15 — Robustness](./article-15-robustness.md) — accuracy / robustness / cybersecurity claims

## Sources

- [Regulation (EU) 2024/1689 — EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689)
- [Article 13 — Chapter III high-risk requirements](https://artificialintelligenceact.eu/section/3-2/)
- [Chapter III high-risk AI system](https://artificialintelligenceact.eu/chapter/3/)
