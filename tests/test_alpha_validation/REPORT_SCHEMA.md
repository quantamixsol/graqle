# alpha_report.json — schema

Written by `tests/test_alpha_validation/conftest.py::pytest_sessionfinish`
at the end of every harness run. Consumed by the release-gate decision:

- all 13 items `"status": "PASS"` → alpha cleared for public squash + PyPI
- any item `"status": "FAIL"` → alpha blocked, hotfix required

## Top-level

| Field | Type | Description |
|-------|------|-------------|
| `sdk_version` | string | `graqle.__version__` at the time of the run |
| `python_version` | string | e.g. `"3.11.15"` |
| `run_timestamp` | ISO 8601 UTC | When the harness started |
| `runtime_seconds` | float | Total wall-clock duration |
| `items` | array | 13 entries, one per gap |
| `summary` | object | Aggregate counters + gate verdict |

## `items[]` entries

| Field | Type | Notes |
|-------|------|-------|
| `id` | string | `"01-cg17"`, `"02-g2"`, ... `"13-smoke"` |
| `name` | string | Human-readable title |
| `status` | enum | `PASS` / `FAIL` / `SKIP` / `ERROR` |
| `assertions` | int | Number of assertions run |
| `duration_ms` | int | Milliseconds |
| `evidence` | object | Item-specific (see per-item schema below) |
| `failure_reason` | string | Populated only on FAIL |
| `tracker` | string or null | OT-NNN reference if a known-deferred issue |

## `summary`

| Field | Type | Notes |
|-------|------|-------|
| `total` | int | 13 |
| `passed` | int |  |
| `failed` | int |  |
| `skipped` | int | e.g. G3 when Marketplace API is rate-limited |
| `errored` | int | Unhandled exceptions |
| `gate_verdict` | enum | `CLEAR` / `INSUFFICIENT` |
| `blocked_release_targets` | array | e.g. `["pypi", "vscode-marketplace"]` on FAIL |

## Item-specific `evidence` shapes

### 01-cg17 — memory gate
```json
{"memory_path_written": "...", "blocked_native_attempts": 2, "index_updated": true}
```

### 02-g2 — release gate
```json
{"verdict": "CLEAR", "confidence": 0.87, "blockers": 0, "majors": 2}
```

### 03-adr205 — activation layer
```json
{"advisory_pass": true, "enforced_block": true, "safety_consulted": true}
```

### 04-adr206 — fast path
```json
{"classifier_decisions": 4, "path_containment_rejects": 2, "code_ext_rejected": true}
```

### 05-adr207 — zero violation
```json
{"dogfood_metadata_present": true, "violation_count_field_exists": true}
```

### 06-sdk-b1 — init scaffold
```json
{"project_types_tested": 6, "graq_md_written": 6, "templates_match": true}
```

### 07-wave1 — BLOCKER hardening
```json
{"fixes_verified": 7, "regression_tests_pass": true}
```

### 08-cg09 — bash gate
```json
{"native_bash_blocked": true, "graq_bash_allowed": true}
```

### 09-cg10 — read gate
```json
{"native_read_blocked": true, "graq_read_allowed": true, "global_scope": true}
```

### 10-cg11 — git gate
```json
{"native_git_routed": true, "graq_git_commit_called": true}
```

### 11-g3 — vsce check
```json
{"marketplace_reachable": true, "version_field_present": true, "rate_limited": false}
```

### 12-sdk-b5 — worktree inheritance
```json
{"worktree_detected": true, "main_repo_resolved": true, "graq_md_merged": true}
```

### 13-smoke — full roundtrip
```json
{"init_ok": true, "memory_write_ok": true, "plan_ok": true, "generate_ok": true, "review_ok": true}
```
