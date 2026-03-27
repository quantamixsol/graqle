# ADR-120: Phase 8 — Wiring Gaps (Audit Trail + CLI Gate)
**Date:** 2026-03-27 | **Status:** ACCEPTED

## Context
Phase 7 established the GovernanceMiddleware 3-tier gate and wrote the gate result to `_handle_edit` / `_handle_generate`, but three wiring gaps remained:

1. **GOVERNANCE_BYPASS KG nodes** — `build_bypass_node()` existed but was never called. T2/T3 bypass decisions left no audit trail.
2. **TOOL_EXECUTION audit nodes** — Every tool invocation was invisible in the KG. No actor identity, no latency, no error flag.
3. **`graq gate` CLI** — No way to run the governance gate outside the MCP server. CI/CD pipelines had no binary exit-code enforcement point.

## Decision

### 1. GOVERNANCE_BYPASS KG write
After the `_gate.blocked` check in `_handle_edit` and `_handle_generate`, add:
```python
if _gate.bypass_allowed:
    _bypass = _gov.build_bypass_node(_gate, ...)
    bypass_node = CogniNode(id=_bypass.bypass_id, node_type="GOVERNANCE_BYPASS", ...)
    graph.add_node(bypass_node)
    self._save_graph(graph)
```
Wrapped in `try/except` — audit writes never block the operation.

### 2. TOOL_EXECUTION audit node in `handle_tool`
In the `finally` block of the tool dispatch, write a lightweight `TOOL_EXECUTION` KG node:
- Fields: `tool`, `actor`, `latency_ms`, `had_error`, `entity_type="TOOL_EXECUTION"`
- Node ID: `tool_exec_{name}_{timestamp}`
- Fire-and-forget: `try/except` ensures audit writes never affect output

### 3. `graq gate` CLI command
New `@app.command("gate")` in `graqle/cli/main.py`:
- Args: `file_path`, `--diff`, `--content`, `--risk`, `--impact-radius`, `--approved-by`, `--justification`, `--actor`
- Exit code 0 = PASS, exit code 1 = BLOCKED (controlled by `--fail/--no-fail`)
- Formats: human-readable (default), `--json`, `--sarif` (SARIF v2.1 for GitHub Advanced Security)
- No graph required — pure governance check, zero dependencies on graqle.yaml

## Consequences

**Positive:**
- Every T2/T3 bypass now has a KG node → enables weekly threshold calibration via `graq_learn`
- Full tool invocation audit trail → actor accountability for all MCP calls
- `graq gate` enables CI/CD pipelines to enforce governance before merge (binary exit code)
- SARIF output enables GitHub Advanced Security integration without additional tooling

**Negative / Trade-offs:**
- `handle_tool` now calls `_load_graph()` + `_save_graph()` on every tool invocation (TOOL_EXECUTION write). This adds ~5-20ms per call on small graphs. Acceptable for auditability; can be made opt-in via config later.
- GOVERNANCE_BYPASS writes call `_save_graph()` which re-serializes the full graph. On large graphs this may add latency to edit/generate.

## Open Questions
- Make TOOL_EXECUTION writes opt-in via `graqle.yaml: governance: audit_tool_calls: true` (to avoid latency on large graphs)
- SARIF integration with GitHub Actions: needs a composite action to upload results
- `graq gate --diff-from-git HEAD` shortcut for common CI use case
