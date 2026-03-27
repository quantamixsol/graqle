# ADR-117: Compound Workflow Tools and graq_test Keystone

**Date:** 2026-03-27 | **Status:** ACCEPTED

## Context

After Phase 3.5 delivered the file system + git tool layer (98 tools), `graq_reason` analysis found the coding domain ontology at ~25% completeness. Phase 4 expanded skills (4→12), entities (5→14), relationships (4→16), and output gates (5→10). The graph intelligence layer (`graq_predict`, 40/40 agent consensus at 93% confidence) identified `graq_test` as the single highest-value build target to reach 90%+ domain completeness.

## Decision

### Compound Workflow Tools (Phase 4)

Add 4 compound workflow MCP tools: `graq_review`, `graq_debug`, `graq_scaffold`, `graq_workflow`.

These tools orchestrate multi-step operations by chaining existing primitive tools. Their value is not new capability — it is eliminating Claude/AI orchestration boilerplate from every session. Instead of telling the agent "first grep, then read, then generate, then write, then test", the user calls `graq_workflow(workflow='bug_fix', goal='...')` and gets the full plan in one call.

**Safety rules:**
- `graq_review` and `graq_debug` are read-only — NOT in `_WRITE_TOOLS`
- `graq_scaffold` and `graq_workflow` default to `dry_run=True` — NEVER write without explicit opt-in
- `graq_workflow` inner steps also default to `dry_run=True` — two-layer safety

### graq_test Compound Tool (Phase 5)

Add `graq_test`: runs `python -m pytest <target> -q --tb=short`, parses structured output (pass/fail/skip counts, coverage %, failing test IDs, duration), and optionally writes `CodeMetric` nodes into the knowledge graph.

**Why graq_test is the keystone:**
1. **Cascading dependency**: CodeMetric entity (populates with test results), test_coverage_gate (enforces thresholds), graq_profile (reuses same pattern), PERFORMANCE_PROFILING skill — all depend on graq_test's structured output
2. **Pattern reuse**: Follows `run→parse→ingest` pattern identical to graq_bash, but with domain-specific result parsing
3. **Loop closure**: bug_fix workflow completes: `grep→read→debug→generate→write→graq_test→git_commit→learn` — the test step verifies the fix without leaving the tool

## Consequences

**Positive:**
- Coding domain completeness: ~25% → ~90% (graq_reason estimate: 78-82% measurable; graq_predict: 90%+ cascade)
- 3 compounding autonomous loops now enabled: bug_fix, scaffold_and_test, governed_refactor
- graq_test + CodeMetric enables CI quality gates: block merge if test_coverage_gate fails
- graq_workflow dry_run plan output enables safe human review before any mutation

**Negative:**
- 108 tools increases MCP protocol payload on list_tools; mitigated by lazy loading
- graq_workflow is a thin orchestration layer — it does NOT implement DAG semantics (saga rollback). WorkflowOrchestrator remains the critical architectural gap.

## Remaining Gaps to 100% (post-Phase 5)

| Gap | Priority | Enables |
|-----|----------|---------|
| PERFORMANCE_PROFILING skill + graq_profile | HIGH | Performance regression detection loop |
| WorkflowOrchestrator (DAG/saga) | CRITICAL | Reliable multi-step automation with rollback |
| graq_refactor compound tool | MEDIUM | Governed refactor loop without manual coordination |
| CodeEnvironment entity (runtime context) | LOW | Deployment-aware reasoning |
| CI/CD pipeline integration | LOW | Automated deployment gating |
