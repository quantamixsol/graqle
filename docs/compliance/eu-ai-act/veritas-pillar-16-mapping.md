# VERITAS Pillar 16 Part 1 — Mapping to GraQle's Shipped Surface

> **Authoritative source for VERITAS scope:** [VERITAS Framework — Pillar 16 Part 1 (Semantic Drift Detection, Baseline Historical Data), Q16.1–Q16.5](https://www.linkedin.com/in/andriimatiash/) — Andrii Matiash, published 12 May 2026.
>
> **Authoritative source for GraQle's compliance surface:** [`graqle/compliance/`](../../../graqle/compliance/) + [`docs/compliance/eu-ai-act/`](./README.md).
>
> **Internal binding ADR:** [ADR-MARKETING-002 — VERITAS Reference Protocol](https://github.com/quantamixsol/graqle/blob/master/.gsm/decisions/ADR-MARKETING-002-summary.md) (mirror summary in this repo). Primary lives in `c:\Users\haris\Brand_Collaboration\.gsm\decisions\ADR-MARKETING-002-veritas-reference-protocol.md`.
>
> **Last reviewed:** 2026-05-15 against GraQle SDK v0.56.0.

---

## 0. What this document is — and what it is not

This document **publicly maps** Andrii Matiash's published VERITAS Pillar 16 Part 1 sub-questions (Q16.1–Q16.5) to GraQle's shipped + planned compliance surface. A customer's compliance team can read this side-by-side with Andrii's published Part 1 and see, sub-question by sub-question, which GraQle artefact addresses the methodology requirement.

It is **NOT**:
- A claim that GraQle implements VERITAS. VERITAS is Andrii's framework. GraQle's substrate composes against it where the published scope permits.
- A claim that GraQle covers VERITAS sub-questions outside Q16.1–Q16.5 (Pillars 1–15 and Pillar 16 Parts 2–5 are not yet public per Andrii's 15 May 2026 DM — see ADR-MARKETING-002 §2).
- A claim that GraQle covers Q16.1, Q16.3, or Q16.5 in production today. The substrate addresses Q16.2 and Q16.4 fully; the other three are partial / research backlog (see §3 below).

---

## 1. The published VERITAS Pillar 16 Part 1 scope (verbatim from Andrii's 12 May 2026 publication)

VERITAS Pillar 16 Part 1 is titled **"Semantic Drift Detection — Baseline Historical Data."** It poses five sub-questions a regulator should have been asking AI deployers since 2024.

| Sub-question | Scope (Andrii's words, published 12 May 2026) |
|---|---|
| **Q16.1** | Quality baseline documentation at deployment with quantitative performance metrics, test archives, version records, formal stakeholder sign-off |
| **Q16.2** | Historical request/response log retention with PII masking, structured schema, defined retrievability timeframes |
| **Q16.3** | Periodic quality assessments with documented cadence, written outputs, tracked remediation actions |
| **Q16.4** | Historical sample data retrieval capability with documented procedures and privacy-compliant data handling |
| **Q16.5** | User feedback trend tracking with structured collection, trend analysis, linkage to quality assessments |

**Regulatory mappings Andrii published for Part 1:** EU AI Act Art. 11, 12, 17, 26, 72, 74 · ISO 42001 Cl. 6.2, 9.1, 10.1 · ISO/IEC 42006:2025 · NIST AI RMF MEASURE 2.x · ISAE 3000 Revised · GDPR Art. 5, 6, 28, 83, 89.

---

## 2. The 3-layer composition (per ADR-001 OATS Framework)

| Layer | Owner | What it produces |
|---|---|---|
| **Methodology** | Andrii Matiash (VERITAS Pillar 16 Part 1) | The five sub-questions a regulator should ask before approving deployment |
| **Architecture** *(this repo)* | Quantamix Solutions (GraQle SDK) | The artefacts that answer those sub-questions at inference time |
| **Standards** | Peter Borner / OPSF (PCT) | The externally-verifiable signed bundle format for the artefacts |

GraQle owns the **architecture layer** only. We do not absorb Andrii's methodology layer. We do not absorb Peter's standards layer.

---

## 3. The mapping table

| VERITAS sub-question | GraQle Article-by-Article surface | Coverage status | Where in GraQle |
|---|---|---|---|
| **Q16.1** Baseline documentation at deployment | EU AI Act Article 11 (technical documentation) — manual today, automation planned | **PARTIAL** | `docs/compliance/eu-ai-act/` shipped (9 files); automated baseline-doc generator is research backlog item **RQ-04** — Lambda `L20 eu_periodic_assessment` |
| **Q16.2** Historical request/response log retention with PII masking + structured schema + retrievability | EU AI Act Article 12 (record-keeping) | **SHIPPED (v0.56.0)** | `graq compliance export --since YYYY-MM-DD -o evidence.jsonl --sha256-sidecar` — JSONL evidence + SHA-256 tamper-detection sidecar. PII masking via `graqle/core/secret_patterns.py` (200+ patterns, Shannon-entropy detection, AST scan). Retrievability bounded by `--since`/`--until` ISO-date filters. |
| **Q16.3** Periodic quality assessments with documented cadence + written outputs + tracked remediation | EU AI Act Article 17 (Quality Management System) | **GAP — research backlog RQ-04** | Not yet built. Planned: Lambda `L20 eu_periodic_assessment` produces dated assessment artefacts with cadence configured per deployer. Tracking issue: see [`graqle-sdk-cr009/.gcc/OPEN-TRACKER-CAPABILITY-GAPS.md`](https://github.com/quantamixsol/graqle/blob/master/.gcc/OPEN-TRACKER-CAPABILITY-GAPS.md) entry **CG-MKT-03**. |
| **Q16.4** Historical sample data retrieval with procedures + privacy-compliant handling | EU AI Act Article 12 + GDPR Art. 15 (right of access) | **SHIPPED (v0.56.0)** | `graq compliance export --since YYYY-MM-DD --until YYYY-MM-DD` — bounded date-range retrieval. Canonical-form JSONL output (`sort_keys=True` + compact separators) gives deterministic re-export; SHA-256 sidecar gives tamper detection. Per `tests/test_compliance/test_compliance_export_cli.py::TestDeterminism`: re-exporting the same input window produces byte-identical output. |
| **Q16.5** User feedback trend tracking + trend analysis + linkage to quality assessments | EU AI Act Article 17 + ISO 42001 Cl. 9.1 | **GAP — research backlog RQ-04 + RQ-13** | Not yet built. Planned: `RQ-13 EvidenceStateSnapshot` + L20 trend-aggregation surface. Tracking issue: **CG-MKT-04**. |

### Status legend

- **SHIPPED (v0.56.0)** — present on `master`, on PyPI, with passing tests, addressable by a customer running `pip install graqle==0.56.0` today.
- **PARTIAL** — substrate exists, the documented automation/coverage is on the research backlog.
- **GAP** — not yet built. Tracked in the SDK's open-tracker with a target CR.

---

## 4. What this means for a customer's compliance team

If you are filing a compliance dossier under EU AI Act Article 9 (risk-management file) or ISO 42001 Cl. 9.1, and you want to cite **Andrii's VERITAS Pillar 16 Part 1** as your methodology framework, here is what you can quote today (v0.56.0):

### What you can cite right now (Q16.2 + Q16.4)

> *"Our high-risk AI system uses GraQle (`v0.56.0`) for AI-assisted code reasoning. The historical request/response log retention required by VERITAS Q16.2 and the privacy-compliant historical retrieval required by Q16.4 are produced by GraQle's `graq compliance export` command, which emits canonical-form JSONL evidence with a SHA-256 tamper-detection sidecar. The byte-deterministic re-export property is enforced by `tests/test_compliance/test_compliance_export_cli.py::TestDeterminism::test_same_input_produces_identical_output` in the GraQle repository. The PII masking required by Q16.2 is performed by `graqle/core/secret_patterns.py` (200+ regex patterns, Shannon-entropy detection, AST structural scan)."*

This is **safe to cite verbatim** in a regulator-facing document.

### What you cannot yet cite (Q16.1 + Q16.3 + Q16.5)

These are deployer-side obligations that GraQle's substrate does **not yet** automate. You must produce these artefacts yourself today, or wait until CR-010 / RQ-04 / RQ-13 ship. Tracking: [`OPEN-TRACKER-CAPABILITY-GAPS.md`](https://github.com/quantamixsol/graqle/blob/master/.gcc/OPEN-TRACKER-CAPABILITY-GAPS.md).

---

## 5. Composition seam — what binds GraQle to VERITAS Part 1 (and only Part 1)

Per [ADR-MARKETING-002 — VERITAS Reference Protocol](https://github.com/quantamixsol/graqle/blob/master/.gsm/decisions/ADR-MARKETING-002-summary.md):

1. GraQle's substrate is **permitted to claim** coverage of **Q16.2 and Q16.4 only**.
2. GraQle's substrate is **permitted to claim** partial coverage of **Q16.1** (documentation present; automation planned).
3. GraQle's substrate is **NOT permitted to claim** coverage of **Q16.3 or Q16.5** — those are research backlog. Until CR-010 / RQ-04 / RQ-13 ship, the language permitted is "the substrate is being extended to support Q16.3 and Q16.5 — currently in research."
4. GraQle does **NOT** claim coverage of any VERITAS scope outside Pillar 16 Part 1 — Pillars 1–15 and Pillar 16 Parts 2–5 are not yet public per Andrii's 15 May 2026 DM.

---

## 6. When this mapping changes

- **Andrii publishes Part 2/3/4/5 of Pillar 16** → ADR-MARKETING-002 §1 gets updated → this mapping doc gets a new section.
- **CR-010 ships RQ-04 (periodic assessment Lambda)** → this doc moves Q16.3 from GAP → SHIPPED.
- **CR-010 ships RQ-13 (EvidenceStateSnapshot)** → this doc moves Q16.5 from GAP → SHIPPED.
- **EU AI Act regulation amends** → the regulatory-mappings line in §1 gets revisited.

This is a **living mapping**. It does not get deleted or forked. It gets updated in place.

---

## 7. Sources

- [Andrii Matiash on LinkedIn](https://www.linkedin.com/in/andriimatiash/) — VERITAS Framework author.
- [Regulation (EU) 2024/1689 — EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689) — EU AI Act authoritative source.
- [GraQle SDK — `graqle/compliance/`](../../../graqle/compliance/) — the substrate this doc maps from.
- [`docs/compliance/eu-ai-act/`](./README.md) — Article-by-Article index this doc complements.
- [`ADR-MARKETING-002`](https://github.com/quantamixsol/graqle/blob/master/.gsm/decisions/ADR-MARKETING-002-summary.md) — internal protocol governing this mapping.

---

## 8. Acknowledgement

VERITAS Pillar 16 Part 1 is Andrii Matiash's published methodology framework. GraQle is grateful to Andrii for the precision of the published scope (Q16.1–Q16.5) and for the explicit boundary set in his 15 May 2026 DM. This mapping doc honours that boundary by claiming coverage only where it is shipped, marking partial coverage where the substrate is incomplete, and naming the gaps where the methodology runs ahead of the architecture.

The composition is a trust transaction between two senior practitioners. We treat it as such.
