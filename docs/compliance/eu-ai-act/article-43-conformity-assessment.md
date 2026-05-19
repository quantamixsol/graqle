# Article 43 — Conformity Assessment

> **Authoritative source:** [Article 43 — Regulation (EU) 2024/1689 on EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689) · [Article 43 — artificialintelligenceact.eu](https://artificialintelligenceact.eu/article/43/) · [Annex VI — internal control](https://artificialintelligenceact.eu/annex/6/)
>
> **Applicability date:** 2026-08-02 for high-risk AI systems.
>
> **Applies to GraQle?** **INDIRECTLY** — GraQle is **not itself the conformity-assessment subject**. The deployer or provider who places a high-risk AI system on the EU market remains the conformity-assessment subject. When GraQle is embedded in that high-risk AI system, GraQle's substrate (audit log, baseline document, periodic assessment, robustness attestation, Article 14 human-oversight gate, Article 50 disclosure, claim-limits) produces evidence the deployer composes into their Annex VI internal-control file.
>
> **GraQle does NOT perform conformity assessment.** GraQle produces evidence. The deployer assesses.

## What the Article requires

Article 43(1) sets out the conformity-assessment routes for high-risk AI systems. For most Annex III high-risk systems (and all Annex I systems other than biometric remote identification), the provider may choose **internal control** per **Annex VI** — a self-assessment route that does **not** require a notified body. For Annex III paragraph 1 systems (remote biometric identification), the provider must use the notified-body route per Annex VII.

This document addresses the **Annex VI internal-control route** because that is where GraQle's substrate evidence is most directly useful. GraQle's substrate is equally usable as evidence in the Annex VII notified-body route if the deployer elects that path, but the assessment procedure itself is the deployer's responsibility.

### Annex VI internal-control requirements

The provider must:

1. Establish and maintain a **quality management system** that meets Article 17 requirements.
2. Maintain **technical documentation** per Article 11 + Annex IV.
3. Establish a **risk-management system** per Article 9.
4. Operate a **record-keeping** system per Article 12.
5. Provide **transparency to deployers** per Article 13.
6. Ensure **human oversight** per Article 14.
7. Achieve appropriate **accuracy, robustness, and cybersecurity** per Article 15.
8. Operate **post-market monitoring** per Article 72.
9. Satisfy **transparency obligations to users** per Article 50 where applicable.
10. Maintain the **declaration of conformity** per Article 47.

The provider also affixes the CE marking per Article 48 — a separate compliance step the deployer performs against the assembled evidence package, not GraQle.

## What GraQle provides (substrate evidence mapping)

Each row below maps an Annex VI internal-control requirement to the GraQle subsystem that produces evidence relevant to that requirement.

| Annex VI requirement | GraQle subsystem | Evidence artefact | Where to find it |
|---|---|---|---|
| Quality management system (Art 17) | `graqle.compliance.baseline_doc` + `graqle.compliance.periodic_assessment` | `baseline_id` (SHA-256 of canonicalized baseline doc) + quality-metrics envelope from periodic assessment | [`baseline-document-schema.md`](baseline-document-schema.md) · `graq compliance baseline-doc generate` |
| Technical documentation (Art 11, Annex IV) | `graqle.compliance.baseline_doc` | Dated, version-pinned, content-addressed baseline document (PDF + JSONL formats) | `graq compliance baseline-doc generate --signoff --format pdf` |
| Risk-management system (Art 9) | `graqle.compliance.periodic_assessment` | Periodic-assessment output envelope: `mean_confidence`, `p95_confidence`, `n_degraded`, `n_outcome_not_ok`, `n_governance_refusals` + auto-created remediation candidates on threshold breach | `graq compliance periodic-assessment run --cadence monthly` |
| Record-keeping (Art 12) | `graqle.governance.trace_store` + `graqle.governance.middleware` + `graq compliance export` | Append-only JSONL audit log + canonical-form export with SHA-256 sidecar + **schema v2: every record carries a `policy_version` SHA-256 binding to the active baseline_id at write time (since v0.58.0 / cr-017)** | [`article-12-record-keeping.md`](article-12-record-keeping.md) · `graq compliance export --output <path>` |
| Transparency to deployers (Art 13) | `graqle.core.graph_health` | `graph_health` + `confidence` fields on every reasoning envelope (per-call, machine-readable) | [`article-13-transparency-to-deployers.md`](article-13-transparency-to-deployers.md) |
| Human oversight (Art 14) | `graqle.compliance.article_14_gate` | `ARTICLE_14_HUMAN_REVIEW_REQUIRED` refusal envelope with `article_14_clauses` + `threshold_status` (placeholder pending R25-EU-CALIB-01 calibration spike) | [`article-14-human-oversight.md`](article-14-human-oversight.md) |
| Accuracy / robustness / cybersecurity (Art 15) | `graqle.compliance.robustness` | 17-defence machine-readable attestation + 7 measurable claims + 4 cybersecurity negatives + explicit adversarial-input boundary statement | [`article-15-robustness.md`](article-15-robustness.md) |
| Transparency to users (Art 50) | `graqle.compliance.disclosure` | Once-per-process AI-disclosure banner + machine-readable `ai_disclosure` envelope field | [`article-50-transparency.md`](article-50-transparency.md) |
| Post-market monitoring (Art 72) | `graqle.compliance.evidence_state` | OBSERVATION-ONLY drift indicator: z-score against baseline, 2-sigma `DRIFT_ALARM_SIGMA` threshold (patent-fenced — drift is observation, never auto-recalibration trigger) | `graq compliance feedback record` |
| Provider obligations (consolidated view) | `graqle.compliance.switch_status` | Single envelope: `graq compliance switch status --format json` returns master-switch state + per-subsystem armed state for all 7 EU-AI-Act-aware subsystems | `graq compliance switch status` |
| Value-chain (Art 25, intended purpose) | `graqle.pct` + `graqle.pct.extensions.x_ai_eu` | OPSF PCT Use B issuer + validator (RS256 + kid header) + 11-field `x-ai-eu` extension namespace (since v0.58.0 / cr-017: field 11 `policy_version`) | [`article-25-value-chain.md`](article-25-value-chain.md) |
| AI literacy (Art 4) | Integration guidance | Per-call transparency, confidence, graph_health surfacing | [`article-04-ai-literacy.md`](article-04-ai-literacy.md) |

## Explicit non-claims

These non-claims are enforced in code by `tests/test_compliance/test_robustness.py::TestNonClaimsInvariants`. The README snapshot-lock CI gate refuses any wording that contradicts them:

1. **GraQle is NOT itself a high-risk AI system.** No Annex III category applies to a code-reasoning SDK. The deployer's high-risk AI system that *embeds* GraQle is the high-risk system; that system is the conformity-assessment subject, not GraQle.
2. **GraQle is NOT a GPAI provider under Article 51.** GraQle is a SDK that reasons over operator-owned graphs; it does not place a general-purpose AI model on the EU market.
3. **GraQle provides signals and audit primitives, not the deployer's Article 9 risk-management file.** The deployer composes the substrate evidence above into their own risk-management file. GraQle never "owns" the Article 9 obligation.
4. **GraQle does not perform conformity assessment itself.** The deployer (or provider of the embedding high-risk system) performs the conformity assessment. GraQle's substrate produces evidence the deployer uses; GraQle does not produce a declaration of conformity.

## How a deployer composes the Annex VI evidence package

A typical Annex VI internal-control file produced by a deployer who embeds GraQle in their high-risk AI system will contain:

1. The deployer's own **quality-management system** documentation (Article 17). GraQle's baseline-doc is a *component* of this; the deployer's QMS covers the broader system.

2. The deployer's **Annex IV technical documentation** package, citing GraQle's baseline_id as the content-addressed reference to the code-reasoning component.

3. The deployer's **Article 9 risk-management file**, citing GraQle's periodic-assessment output as one input to the risk register.

4. The deployer's **Article 12 audit-log retention policy** (≥ 6 months per Article 19), citing GraQle's audit log + export procedure + SHA-256 sidecar as the implementation. After v0.58.0 / cr-017, each record additionally carries `policy_version` so an auditor can verify which baseline-doc version was active at the moment of each governed AI decision.

5. The deployer's **Article 13 deployer-transparency documentation**, citing GraQle's per-call `graph_health` + `confidence` envelope as the implementation.

6. The deployer's **Article 14 human-oversight protocol**, citing GraQle's confidence-gated refusal envelope as the implementation. The deployer documents the threshold value they have set and their procedure for handling refusals.

7. The deployer's **Article 15 robustness attestation**, citing GraQle's 17-defence machine-readable attestation as one input. The deployer's own attestation covers the broader system including model-side defences.

8. The deployer's **Article 50 transparency-to-users statement**, citing GraQle's `ai_disclosure` envelope + once-per-process banner where applicable.

9. The deployer's **post-market monitoring plan** (Article 72), citing GraQle's evidence_state drift indicator as one signal in the monitoring pipeline.

10. The deployer's **declaration of conformity** (Article 47) and **CE marking** (Article 48), signed by the deployer's authorised representative — these are not produced by GraQle.

## Verification

A regulator or external auditor reviewing the assembled Annex VI file can independently verify the GraQle substrate evidence:

- **Audit-log integrity:** re-export from raw `.jsonl` files using `graq compliance export`; verify the new SHA-256 sidecar matches the one in the file.
- **Baseline document integrity:** re-compute `baseline_id = SHA-256(canonicalize(B))` from the baseline-doc JSONL; verify it matches the `baseline_id` referenced in each audit record's `policy_version` field (post-cr-017 records).
- **Periodic-assessment integrity:** re-run `graq compliance periodic-assessment run --cadence <same>` against the same time window; verify the metrics output matches.
- **Robustness attestation integrity:** the 17-defence machine-readable JSON is content-addressed and signed; verify the signature using the deployer's published public key.

## Cross-references

- [Article 12 — Record-Keeping](article-12-record-keeping.md) — the audit log that produces the most substantial Annex VI evidence component
- [Article 9 — Risk Management](#) — covered by `periodic_assessment` (no dedicated article-09 doc yet; tracked separately)
- [Article 11 — Technical Documentation](#) — covered by `baseline_doc` (no dedicated article-11 doc yet; tracked separately)
- [Article 14 — Human Oversight](article-14-human-oversight.md)
- [Article 15 — Robustness](article-15-robustness.md)
- [Article 25 — Value-Chain](article-25-value-chain.md) — for the OPSF PCT Use B layer
- [Article 50 — Transparency](article-50-transparency.md)
- [out-of-scope-articles.md](out-of-scope-articles.md) — explicit list of articles GraQle does not address (Article 5 prohibited practices, Article 10 data governance, etc.)
- [README.md](README.md) — the EU AI Act docs index

## Marketing posture

Per [ADR-MARKETING-001](../../../.gsm/decisions/ADR-MARKETING-001-graqle-eu-ai-act-positioning-constitution.md), GraQle is documented as **EU AI Act-aligned** — never *compliant*, never *certified*, never *guaranteed*. The CI gate at `tests/test_compliance/test_readme_snapshot_lock.py` enforces this vocabulary discipline. This document is no exception.

The four canonical positioning markers stay verbatim-locked across all EU AI Act documentation: *"EU AI Act-aligned"*, *"Articles 6, 9, 12, 13, 14, 15, 25, 50"*, *"NOT high-risk"*, *"NOT GPAI provider"*.
