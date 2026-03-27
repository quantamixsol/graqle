### COMMIT 7 — 2026-03-27T05:00:00Z
**Branch:** feature-coding-assistant
**Milestone:** Phase 7 complete — Governance enforcement + graq_profile. GovernanceMiddleware wired into _handle_edit/_handle_generate. graq_profile tool + CodeMetric KG nodes. 14 skills, 12 output gates, 112 MCP tools total. 529 tests passing.
**State:** WORKING

**Files Changed:**
- CREATED: `graqle/core/governance.py` — GovernanceMiddleware (3-tier gate: TS-BLOCK/T1/T2/T3), GovernanceConfig, GateResult, GovernanceBypassNode
- CREATED: `graqle/core/profiler.py` — Profiler, NodeProfilingTrace, StepRecord, ProfileSummary, ProfileConfig
- MODIFIED: `graqle/plugins/mcp_dev_server.py` — governance wired into _handle_edit/_handle_generate; graq_profile + _handle_profile() + kogni_profile = 112 tools total
- MODIFIED: `graqle/ontology/domains/coding.py` — +PERFORMANCE_PROFILING skill (14 total), +validate_profile_output gate (12 total)
- MODIFIED: `graqle/routing.py` — +profile task type (20 total)
- CREATED: `tests/test_generation/test_governance.py` — 44 tests
- CREATED: `tests/test_generation/test_profiler.py` — 35 tests
- MODIFIED: 7 test count files (110→112, skill 13→14, gate 11→12, task 19→20)
- CREATED: `.gsm/decisions/ADR-119-governance-enforcement.md`

**Key Decisions:**
- TS-BLOCK unconditional — no bypass possible
- T1 secret-aware — secret_found overrides auto-pass
- GovernanceMiddleware at Step 1b in both write handlers
- Thresholds tunable via GovernanceConfig
- GOVERNANCE_BYPASS KG nodes enable post-hoc calibration

**Next:**
- [ ] TOOL_EXECUTION audit trail KG nodes
- [ ] WorkflowOrchestrator DAG engine
- [ ] GOVERNANCE_BYPASS KG write in handlers
- [ ] Calibration endpoint in graq_learn
- [ ] graq_profile sub-phase hooks
- [ ] v0.38.0 release tag

**Blockers:** None
