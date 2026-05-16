# Claim-Limits Taxonomy v1.0 (R25-EU11)

> **Status:** SHIPPED — `graqle.compliance.claim_limits` (PR-010c, 2026-05-16)
> **Spec source:** R25-EU11 (Research-Team binding spec)
> **Public-attribution anchor:** [Ricky Jones (TrinityOS) — LinkedIn 2026-05-13](https://www.linkedin.com/) formulation of the claim-limits concept. The 17-value canonical taxonomy is GraQle's first-public-draft expression of that concept.
> **EU AI Act anchors:** Article 14 (human oversight), Article 50 (transparency), Article 13 (transparency to deployers).

---

## What this is

A **declaration field** that travels on every GraQle governance record (`ResponseSnapshot`, `EvidenceStateSnapshot`, MCP envelope) answering one question:

> "What does this record explicitly **NOT** claim?"

The list is non-empty, default-deny: a write that omits the field, or supplies an empty list, is rejected by the L08 SHACL constraint `ClaimLimitsRequired` at write time. The L19 audit-trail layer rejects the same input independently — defence-in-depth.

A claim-limits declaration is **operator-facing transparency**, not user-facing disclosure. It lets a downstream auditor or regulator answer "what kinds of decision was this record never authorised to support?" without re-reading the system spec or guessing.

---

## Why it exists

EU AI Act Article 14 obliges deployers of high-risk AI systems to ensure *meaningful* human oversight. "Meaningful" requires that the human knows the scope and limits of the system's claims. Article 13(3)(b) requires the same scope clarity for deployer-facing transparency. Article 50 requires user-facing disclosure.

Today these obligations are usually discharged via free-text disclaimers buried in a system card. That is non-machine-readable, easy to drift, and impossible to audit at scale. The claim-limits field promotes those disclaimers to a typed, finite, versioned vocabulary that can be enforced at write time and audited at any time.

Public attribution: the *idea* of declaring claim limits as a typed first-class governance field was articulated publicly by Ricky Jones (TrinityOS) on LinkedIn on 2026-05-13. GraQle's contribution is the 17-value v1.0 canonical taxonomy, the L08 SHACL constraint, the L19 audit-trail integration, the runtime validator at `graqle.compliance.claim_limits`, and the public-namespace extension protocol (`x-*`).

---

## The v1.0 canonical taxonomy

17 values across 6 categories. The categories are organisational only — they do not appear in stored records; only the values do.

### Category 1 — Temporal (2 values)

Facts about *when* the underlying knowledge holds.

| Value | Meaning |
|-------|---------|
| `knowledge_cutoff_apparent` | The response reflects knowledge available up to the model's training cutoff. Events after that cutoff are not represented. |
| `real_time_data_unavailable` | No live data source was queried. The record cannot reflect state changes since the underlying knowledge cutoff. |

### Category 2 — Model dependency (2 values)

Facts about coupling to a specific LLM/backend.

| Value | Meaning |
|-------|---------|
| `model_specific_calibration` | Confidence calibration is specific to the LLM that produced this record. Comparable values from a different model should not be assumed equivalent. |
| `model_dependent_thresholds` | Any thresholds applied (gate, refusal, escalation) were chosen for this model's behaviour and may not generalise. |

### Category 3 — Data scope (4 values)

Provenance of the underlying data.

| Value | Meaning |
|-------|---------|
| `training_data_window` | The record reflects training-data corpus only; no operator-private corpus was consulted. |
| `training_data_jurisdiction` | Training data may be jurisdictionally biased — operator should consult Article 10 documentation for the model's training-data jurisdiction breakdown. |
| `public_data_only` | Only publicly available data was used. No customer / operator-private / regulated data was processed. |
| `no_pii_processed` | No personal data (GDPR meaning) was processed in producing this record. |

### Category 4 — Decision scope (4 values)

What kind of decision this record is NOT.

| Value | Meaning |
|-------|---------|
| `not_legal_advice` | The record is informational only and is not legal advice. |
| `not_medical_advice` | The record is informational only and is not medical advice. |
| `not_financial_advice` | The record is informational only and is not financial / investment advice. |
| `human_review_required` | The record's confidence is below the operator's Article 14 human-review threshold; a human must review before any downstream action is taken. |

### Category 5 — Trust boundary (2 values)

Confidence / verification posture.

| Value | Meaning |
|-------|---------|
| `low_confidence_synthesised` | The record was produced under low confidence; the operator should treat the output as a hypothesis, not a finding. |
| `cited_sources_not_verified` | If sources are cited, the citations have not been verified — the operator is responsible for source verification before publication. |

### Category 6 — Compliance scope (3 values)

Regulatory regime applicability.

| Value | Meaning |
|-------|---------|
| `eu_ai_act_article_14_oversight` | The record was produced under an Article 14 human-oversight configuration. |
| `eu_ai_act_article_50_disclosure` | The record carries an Article 50 user-facing AI-disclosure marker. |
| `gdpr_processor_only` | GraQle acted as a processor (not controller) under GDPR for this record. |

---

## Extension namespace (`x-*`)

Operators MAY declare vendor-specific claim limits under the `x-` namespace. The regex enforced at validation time is:

    ^x-[a-z0-9_-]{1,64}$

Example operator extensions:

- `x-acme-internal-use-only`
- `x-prod-tenant-only`
- `x-eu-region-locked`

Extensions are validated for shape but not semantics — operators are responsible for documenting their own extension vocabulary externally.

---

## Backfill sentinel

The single value `legacy_pre_R25_EU11` is reserved for the one-time migration of records produced before this taxonomy shipped. A backfill migration writes this sentinel exactly once per affected record. **New writes MUST NOT use the sentinel** — the runtime validator rejects it unless the migration script passes `allow_legacy_backfill=True` for the migration call site only.

---

## Enforcement points

Two layers of enforcement run on every write of a governance record:

1. **L08 SHACL constraint `ClaimLimitsRequired`** — schema-level rejection at the graph-write boundary. Lives in the ontology layer.
2. **L19 audit-trail rejection** — runtime rejection at the audit-write layer. Lives in `graqle.compliance.claim_limits.validator.require_non_empty_claim_limits`.

Both layers fail closed: an empty list, a missing field, or a list containing any non-canonical / non-extension value is rejected.

---

## Programmatic access

```python
from graqle.compliance.claim_limits import (
    CANONICAL_CLAIM_LIMITS,
    CLAIM_LIMITS_TAXONOMY_VERSION,
    ClaimLimitsValidationError,
    is_valid_claim_limit,
    require_non_empty_claim_limits,
)

# Validate a single value
assert is_valid_claim_limit("not_legal_advice")
assert is_valid_claim_limit("x-acme-internal-use-only")
assert not is_valid_claim_limit("legacy_pre_R25_EU11")  # backfill sentinel — invalid for new writes

# Validate a list (raising form — for write paths)
require_non_empty_claim_limits(["not_legal_advice", "low_confidence_synthesised"])

# Validate a list (non-raising form — for envelope building)
from graqle.compliance.claim_limits.validator import validate_for_write
result = validate_for_write([])  # ok=False, reasons=["claim_limits_empty"]
```

---

## Versioning policy

This is version **1.0**. Backward-incompatible changes (removing a canonical value, narrowing the extension regex) will bump the major version. Adding canonical values is a minor-version change (e.g. 1.0 → 1.1). The constant `CLAIM_LIMITS_TAXONOMY_VERSION` reflects the active version and is surfaced in every validation result.

---

## See also

- R25-EU11 spec — full design rationale (Research repo, not publicly mirrored).
- `graqle.compliance.claim_limits.taxonomy` — the runtime constants.
- `graqle.compliance.claim_limits.validator` — the L08 / L19 enforcement layer.
- `graqle.compliance.article_14_gate` — the companion Article 14 human-oversight gate (CG-MKT-01).
- ADR-205 — binding research-team decision on Article 14 surfacing.
