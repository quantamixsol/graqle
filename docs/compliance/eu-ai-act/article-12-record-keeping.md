# Article 12 — Record-Keeping

> **Authoritative source:** [Article 12 — Regulation (EU) 2024/1689 on EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689) · [Article 12 — artificialintelligenceact.eu](https://artificialintelligenceact.eu/article/12/)
>
> **Applicability date:** 2026-08-02 for high-risk AI systems.
>
> **Applies to GraQle?** INDIRECTLY — GraQle is not itself a high-risk AI system, but when GraQle is embedded in your high-risk AI system, **your** Article 12 obligations can be partially satisfied by quoting GraQle's audit-log capability.

> **Forward-reference notice:** Sections that refer to **PR-009c (`graq audit export`)** describe a feature planned in the same CR-009 batch as this document. The underlying audit log (`graqle.governance.audit_log`) and its schema are already shipped in v0.55.0. The `graq audit export` CLI surface ships when PR-009c lands on the public SDK. Until then, the audit log is consumable directly via `.graqle/governance/audit/*.jsonl`.

## What the Article requires

> "High-risk AI systems shall technically allow for the automatic recording of events (logs) over the lifetime of the system."

Specifically, the logs must enable:

- Identification of situations that may result in the AI system presenting a risk per [Article 79(1)](https://artificialintelligenceact.eu/article/79/) (risk of harm to health, safety, or fundamental rights), or a substantial modification per [Article 3(23)](https://artificialintelligenceact.eu/article/3/).
- Facilitation of post-market monitoring per [Article 72](https://artificialintelligenceact.eu/article/72/).
- Monitoring of operation for the providers of high-risk AI systems per [Article 26(5)](https://artificialintelligenceact.eu/article/26/) (deployer obligations).

For certain high-risk AI systems (those listed in Annex III paragraph 1, i.e., remote biometric identification), the logs must additionally record the period of use, the reference database, the input data that led to a match, and the identification of the natural persons involved in verifying the results.

## What GraQle provides

### 1. Built-in audit log

Every tool call through the GraQle MCP server, the `graq` CLI, or the SDK Python API goes through the **governance audit log**:

- **Location in code:** `graqle.governance.audit_log` (middleware in `graqle/governance/middleware.py`).
- **Backing store:** JSONL files under `.graqle/governance/audit/{YYYY-MM-DD}.jsonl` by default; configurable via `GraqleConfig.governance.audit_log_path`.
- **One record per tool call:** structured JSON with the fields enumerated in §2.

### 2. Audit log schema (v1)

Each record is a flat JSON object:

```json
{
  "schema_version": "1",
  "timestamp": "2026-05-15T14:32:11.481Z",
  "tool_name": "graq_reason",
  "session_id": "8f3c...",
  "caller": {
    "module": "cli.main",
    "function": "run",
    "line": 432
  },
  "inputs_redacted": {
    "query": "<redacted: secret>",
    "max_rounds": 3,
    "strategy": "hybrid"
  },
  "outcome": "OK",
  "confidence": 0.82,
  "graph_health": {
    "degraded": false,
    "schema_version": "1",
    "activation_mode": "semantic"
  },
  "elapsed_ms": 14823,
  "retry_attempts": 0,
  "persistence": "OK"
}
```

Fields:

| Field | Type | What it captures | Article 12 link |
|-------|------|------------------|-----------------|
| `schema_version` | string | Lock for forward compatibility | (foundation) |
| `timestamp` | ISO-8601 string (UTC, ms precision) | When the event occurred | Art 12(1) "over the lifetime" |
| `tool_name` | string | Which GraQle tool ran | Art 12(2)(a) "situations that may result in risk" |
| `session_id` | string (hashed) | Anonymised session correlator | Art 26(5) "monitoring of operation" |
| `caller` | object | Calling stack frame (module + function + line) | Art 12(2)(a) traceability |
| `inputs_redacted` | object | Tool args with [secret patterns](../../graqle/core/secret_patterns.py) redacted | Art 12 + PII guard |
| `outcome` | enum | `OK` / `WARN` / `ERROR` / `BLOCKED` | Art 79(1) risk-detection |
| `confidence` | float | Reasoning confidence score (CR-004) | Art 12 + Art 13 |
| `graph_health` | object | Graph health snapshot (CR-004) — `degraded`, `activation_mode`, `schema_version` | Art 12 + Art 13 + Art 15 |
| `elapsed_ms` | int | Tool latency | Art 12 + Art 15 robustness baseline |
| `retry_attempts` | int | Retries consumed inside `_write_with_lock` (CR-008) | Art 12 contention surface |
| `persistence` | enum | `SaveStatus` value (CR-008): `OK` / `NO_GRAPH_FILE` / `SHRINK_REFUSED` / `COLLISION` / `SAVE_FAILED` | Art 12 + Art 15 |

### 3. Integrity guarantees

- **Append-only writes** via `_write_with_lock` (fsync + atomic `os.replace`).
- **Per-day file rotation** prevents single-file unbounded growth.
- **No PII in input fields by default** — `secret_patterns.scan_for_secrets` is run on every input value before write; matches are replaced with `<redacted: type>`.
- **Reason strings capped at 200 chars** (CR-004 PR-004a) to bound disclosure.

### 4. Retention

- **Default retention:** infinite (logs accumulate). Configurable via `GraqleConfig.governance.audit_log_retention_days` (set to `0` for infinite).
- **Recommended for high-risk-system deployers:** at least 6 months (per [Article 19](https://artificialintelligenceact.eu/article/19/) provider record-keeping, ≥6 months unless other law applies; review your specific obligations).

### 5. Export for compliance evidence (`graq audit export`)

Shipped in **PR-009c** of CR-009. Surface:

```bash
graq audit export --since 2026-08-01 --format jsonl > my-art12-evidence.jsonl
graq audit export --since 2026-08-01 --until 2026-08-31 --format csv > monthly-evidence.csv
graq audit export --tool graq_reason --format jsonl  # filter to one tool
```

The export is byte-identical to the source JSONL — no transformation, no redaction beyond what the live log already redacts. Hashes of each line are written to a sidecar `.sha256` file so customers can prove their archive hasn't been tampered with.

## How to quote this in your compliance file

When documenting your own Article 12 obligations as a deployer of a high-risk AI system that incorporates GraQle reasoning:

> "Our high-risk AI system uses GraQle ({version}) for code-reasoning support during {scenario}. GraQle's built-in audit log (schema v1, see [github.com/quantamixsol/graqle/blob/master/docs/compliance/eu-ai-act/article-12-record-keeping.md](https://github.com/quantamixsol/graqle/blob/master/docs/compliance/eu-ai-act/article-12-record-keeping.md)) automatically captures every reasoning call with the timestamp, caller frame, redacted inputs, outcome, confidence, and graph-health signal. These logs are exported monthly via `graq audit export` and retained for {N} months in compliance with our Article 19 record-keeping obligations as the high-risk-system provider. We have configured an additional layer of application-level logging on top of GraQle's audit log to capture our system-specific event types per Article 12(2)."

## Dual-compliance cross-reference

GraQle's audit log structure aligns with:

- **SOC2 § CC7.2** ("The entity monitors system components and the operation of those components for anomalies that are indicative of malicious acts, natural disasters, and errors affecting the entity's ability to meet its objectives; anomalies are analyzed to determine whether they represent security events.").
- **ISO27001 § A.8.15** ("Logging — logs that record activities, exceptions, faults and other relevant events should be produced, stored, protected, and analysed").

Using GraQle's audit-log export to satisfy Article 12 simultaneously contributes evidence for these.

## Related GraQle documents

- [Article 13 — Transparency to Deployers](./article-13-transparency-to-deployers.md) — the `graph_health` and `confidence` fields that the audit log records
- [Article 15 — Accuracy, Robustness, Cybersecurity](./article-15-robustness.md) — how integrity is preserved
- [Article 25 — Value-Chain Responsibility](./article-25-value-chain.md) — how to delineate which Article 12 records are yours vs ours

## Sources

- [Regulation (EU) 2024/1689 — EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689)
- [Article 12 — artificialintelligenceact.eu](https://artificialintelligenceact.eu/article/12/)
- [Article 19 — Provider record-keeping](https://artificialintelligenceact.eu/article/19/)
- [Article 26 — Deployer obligations](https://artificialintelligenceact.eu/article/26/)
- [Article 72 — Post-market monitoring](https://artificialintelligenceact.eu/article/72/)
