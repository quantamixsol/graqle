# Baseline Document Schema v1.0 (R25-EU04 Q16.1)

> **Status:** SHIPPED — `graqle.compliance.baseline_doc` (PR-010d, 2026-05-16)
> **Spec source:** R25-EU04 § "Q16.1" (Research-Team binding spec)
> **VERITAS anchor:** [Andrii Matiash — Pillar 16 Part 1, Q16.1](https://www.linkedin.com/in/andriimatiash/) published 2026-05-12.
> **Regulatory anchors:** EU AI Act **Article 11** (technical documentation at deployment) + ISO 42001 **Cl. 6.2** (AI management system planning).

---

## What this is

A **dated, version-pinned baseline document** produced at SDK install or upgrade time that captures the SDK's posture in numbers an auditor can quote:

> "At time *t*, version *v* of GraQle had *N* governance gates active, *M* robustness defences active, *p95_latency* ms, *p95_envelope_size* bytes, *test_count* tests, *pass_rate* pass-rate. The baseline is content-addressed as *baseline_id*."

A deployer running an EU AI Act / ISO 42001 audit can produce the baseline at deployment time, hand it to their auditor, and reference the same `baseline_id` in every later periodic-assessment artefact (Q16.3, ships in PR-010e).

---

## Schema

```json
{
  "sdk_version":              "0.56.0",
  "generated_at_iso":         "2026-05-16T03:42:11Z",
  "quantitative_metrics": {
    "test_count":                  "NOT_YET_AVAILABLE",
    "pass_rate":                   "NOT_YET_AVAILABLE",
    "p95_latency_ms":              "NOT_YET_AVAILABLE",
    "p95_envelope_size_bytes":     "NOT_YET_AVAILABLE",
    "n_governance_gates_active":   5,
    "n_defences_active":           7
  },
  "test_archive_ref":         "NOT_YET_AVAILABLE",
  "version_records": {
    "git_sha":          "a855ed32",
    "pypi_version":     "0.56.0",
    "sigstore_digest":  "NOT_YET_AVAILABLE"
  },
  "stakeholder_signoff":      null,
  "articles_covered":         ["4", "11", "12", "13", "14", "15", "25", "50"],
  "iso_42001_clauses":        ["6.2", "9.1"],
  "proof_format_version":     "R25-EU08-v1.0",
  "baseline_id":              "<sha256 of canonical(B)>"
}
```

### Field reference

| Field | Type | Required | Source |
|-------|------|----------|--------|
| `sdk_version` | str | Y | `graqle.__version__` |
| `generated_at_iso` | str (ISO 8601, `Z` UTC) | Y | `datetime.now(timezone.utc)` at build time |
| `quantitative_metrics` | object | Y | See § Quantitative metrics |
| `test_archive_ref` | str (SHA-256 hex) | Y | CI test-run record SHA — operator supplies; `NOT_YET_AVAILABLE` otherwise |
| `version_records` | object | Y | See § Version records |
| `stakeholder_signoff` | str \| null | N | Email / identity of human countersigner. `null` until signed. |
| `articles_covered` | list[str] | Y | EU AI Act article numbers GraQle attests to (default v1.0 list) |
| `iso_42001_clauses` | list[str] | Y | ISO 42001 clauses supported (default `["6.2", "9.1"]`) |
| `proof_format_version` | str | Y | Always `"R25-EU08-v1.0"` for this writer. Bumping requires an ADR. |
| `baseline_id` | str (SHA-256 hex) | Y (derived) | `SHA-256(canonicalize(B))` where canonicalisation is `json.dumps(sort_keys=True, separators=(",", ":"))` |

### Quantitative metrics

| Key | Today | Source-of-truth |
|-----|-------|-----------------|
| `test_count` | `NOT_YET_AVAILABLE` | Operator CI run record (via `test_archive_ref`); live `pytest --collect-only` is too heavy for CLI |
| `pass_rate` | `NOT_YET_AVAILABLE` | Operator CI run record |
| `p95_latency_ms` | `NOT_YET_AVAILABLE` | R18 trace-corpus aggregation, ships with Q16.3 (PR-010e) |
| `p95_envelope_size_bytes` | `NOT_YET_AVAILABLE` | Same |
| `n_governance_gates_active` | int (live count) | Static enumeration of CG-01..CG-08 + CG-MKT-01 + CG-MKT-10 |
| `n_defences_active` | int (live count) | `graqle.compliance.robustness.build_robustness_attestation()` |

The sentinel `"NOT_YET_AVAILABLE"` is a **fail-loud marker**: an auditor reading the artefact sees explicitly which metric the operator must supply via CI integration, rather than seeing `0` or `null` (which would be ambiguous between "absent" and "actually zero"). The sentinel is one of:

- `"NOT_YET_AVAILABLE"` — module is wired but the upstream feed is not yet connected.
- An integer / float — the live measurement at build time.

### Version records

| Key | Today | Source-of-truth |
|-----|-------|-----------------|
| `git_sha` | live | `git rev-parse HEAD` in the build CWD |
| `pypi_version` | live | `graqle.__version__` |
| `sigstore_digest` | `NOT_YET_AVAILABLE` | Ships with R25-EU01 v2 |

---

## Content-addressing

The `baseline_id` is computed as:

    baseline_id = SHA-256(canonicalize(B)).hexdigest()

where `canonicalize` is `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")` — the same canonicalisation the PCT issuer uses (see [`graqle.pct.issuer`](../../graqle/pct/issuer.py)).

**Determinism**: identical inputs (same SDK version, same metrics, same signoff, same articles, same clauses) produce the **same** `baseline_id`. Two `build_baseline_document()` calls at different timestamps produce *different* `baseline_id`s because `generated_at_iso` differs — that's intentional.

If a future audit ever needs strict RFC 8785 JCS (number normalisation per ECMA-262, Unicode normalisation NFC), the upgrade is local to one helper `_canonicalize()` in `graqle/compliance/baseline_doc.py`. Every emitter and the `baseline_id` property go through that single function.

---

## CLI surface

```bash
# Generate a baseline document at deployment time
graq compliance baseline-doc generate \
    --output  .graqle/baseline-docs/baseline-2026-05-16.jsonl \
    --signoff "alice@deployer.example" \
    --format  jsonl

# Optional PDF emitter (requires pip install reportlab>=4.0)
graq compliance baseline-doc generate \
    --output  baseline-2026-05-16.pdf \
    --format  pdf
```

The JSONL format is **append-only** so a deployer can accumulate baselines across many SDK upgrades in a single log file. Each line is one self-contained baseline document.

---

## Use from Python

```python
from pathlib import Path
from graqle.compliance.baseline_doc import (
    BaselineDocument,
    build_baseline_document,
    to_jsonl,
    to_pdf,
)

# Build at deploy time
doc = build_baseline_document(signoff="alice@deployer.example")
print(doc.baseline_id)      # content-addressed identifier
print(doc.sdk_version)

# Emit
to_jsonl(doc, Path(".graqle/baseline-docs/baseline.jsonl"))
to_pdf(doc, Path("baseline.pdf"))   # raises if reportlab not installed
```

---

## Regulatory mapping

| Regulation | Clause | How this artefact addresses it |
|------------|--------|--------------------------------|
| **EU AI Act** | Article 11 (technical documentation) | The baseline document IS the deployment-time technical-documentation artefact; the deployer attaches it to their Annex IV file. |
| **EU AI Act** | Article 12 (record keeping) | The append-only JSONL log is part of the deployer's Article 12 evidence corpus alongside `graq compliance export`. |
| **EU AI Act** | Article 14 (human oversight) | The `stakeholder_signoff` field is the explicit countersignature point — a baseline left unsigned is "draft for review", a baseline signed is "approved by named human". |
| **ISO 42001** | Cl. 6.2 (AI management system planning) | The dated artefact establishes the planning baseline against which Cl. 9.1 monitoring is measured. |
| **ISO 42001** | Cl. 9.1 (monitoring, measurement, analysis, evaluation) | Periodic-assessment artefacts (ships in PR-010e) reference this baseline's `baseline_id` so Cl. 9.1 evidence chains back to Cl. 6.2 evidence. |

---

## Closes

- CG-MKT-02 (VERITAS Q16.1 PARTIAL → **SHIPPED**)

## See also

- [`graqle.compliance.baseline_doc`](../../graqle/compliance/baseline_doc.py)
- R25-EU04 Phase M1 (Research repo, R25-EU04-operational-discipline-veritas-q16.md)
- Sibling: [`docs/compliance/eu-ai-act/veritas-pillar-16-mapping.md`](veritas-pillar-16-mapping.md) — the cross-walk between VERITAS Q16.1–Q16.5 and GraQle's shipped + planned surface.
- Sibling spec (ships in PR-010e): `periodic-assessment-schema.md` for Q16.3.
- Companion gate: [`graqle.compliance.article_14_gate`](../../graqle/compliance/article_14_gate.py) (CG-MKT-01).
