# PCT Extension Namespaces — GraQle

This directory holds Python implementations of PCT extension namespaces
GraQle ships. Each namespace mirrors the OPSF naming convention
`x-{framework}:{field}` (see `opsf-org/pct-spec@develop/extensions/`).

## `x-ai-eu` — EU AI Act extension (Quantamix-authored)

**Status (2026-05-23):** Authored by Quantamix Solutions. Implementation
shipped vendored in GraQle private repo per ADR-205 + ADR-RT-001. NOT
YET proposed to OPSF; proposal opens 24-48h after the technical call
with Peter Borner per Option 2A.

**Fields (10, per ADR-205 §2.2):**

| Field | Type | Required | Description |
|---|---|---|---|
| `x-ai-eu:article_6_classification` | enum | OPTIONAL | Article 6 risk-classification. One of: `non_high_risk`, `annex_iii_high_risk`, `annex_i_high_risk`, `gpai_model`, `gpai_systemic_risk`. |
| `x-ai-eu:article_9_risk_management_ref` | URI | CONDITIONAL | Required when `article_6_classification` is `annex_iii_high_risk` or `annex_i_high_risk`. Reference to the operator's Article 9 risk-management file. |
| `x-ai-eu:article_12_audit_log_pointer` | URI | OPTIONAL | Reference to the operator's Article 12 audit log (e.g. `graq compliance export` evidence file URL). |
| `x-ai-eu:article_13_transparency_doc_ref` | URI | OPTIONAL | Reference to operator's Article 13 deployer-transparency documentation. |
| `x-ai-eu:article_14_human_oversight_mode` | enum | OPTIONAL | One of `disabled`, `monitor`, `gated`. Corresponds to whether human oversight is per-call, sample-based, or always-required. |
| `x-ai-eu:article_50_disclosure_mode` | enum | OPTIONAL | One of `auto_banner`, `machine_only`, `suppress_with_logged_reason`. Corresponds to the GraQle `GRAQLE_EU_AI_ACT_MODE` + `GRAQLE_AI_DISCLOSURE` env-var pair. |
| `x-ai-eu:articles_covered` | array of strings | RECOMMENDED | Subset of `["4", "12", "13", "14", "15", "25", "50"]`. Mirrors GraQle's `compliance.articles_covered` envelope field. |
| `x-ai-eu:gpai_provider_flag` | boolean | OPTIONAL | `false` for GraQle deployments (GraQle does not place a GPAI on the EU market). Future-proof for customers who DO place GPAI. |
| `x-ai-eu:annex_iii_category` | enum | CONDITIONAL | Required when `article_6_classification == "annex_iii_high_risk"`. One of the 8 Annex III categories. |
| `x-ai-eu:cr_lookup_id` | string | OPTIONAL | Pointer to a structured EU AI Act compliance dossier ID maintained by the operator. |

## OPSF acceptance process (planned, NOT YET initiated)

Per ADR-RT-001 §4 Q2 + ADR-205 §3.1:

1. Technical call with Peter Borner (OPSF) — Research Team owns scheduling (Tue 26 / Wed 27 May target).
2. Within 24-48 hours of the call (conditional on the call going well), Quantamix opens a PR against `opsf-org/pct-spec` adding:
   - `extensions/x-ai-eu.md` — namespace docs in the OPSF directory format (mirrors `extensions/x-ai-int.md` etc.)
   - `examples/scenario-X-ai-eu-<scope>.json` — at least 2 example scenarios demonstrating the namespace in use.
3. If the call surfaces concerns or naming preferences, the OPSF PR is held; the namespace ships in GraQle private vendoring until resolved.

## License

The `x-ai-eu` namespace specification is Quantamix-authored. Per
ADR-RT-001 §4 acceptance, the namespace is voluntarily contributed
under CC BY 4.0 (matching the PCT v0.1 spec license) once accepted into
the OPSF repo. The GraQle Python implementation in `x_ai_eu.py` is
Apache 2.0 (matching the rest of the GraQle SDK).
