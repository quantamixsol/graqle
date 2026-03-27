### COMMIT 5 — 2026-03-27T02:00:00Z
**Branch:** feature-coding-assistant
**Milestone:** Phase 4 + Phase 5 complete — Coding domain ontology expanded to ~90%+, 5 compound workflow tools, 108 MCP tools total. 174 targeted tests pass. graq_reason (78%) + graq_predict (93%) validation complete.
**State:** WORKING
**Files Changed:**
- MODIFIED: `graqle/ontology/domains/coding.py` — expanded: 4→12 skills, 5→14 entities, 4→16 relationships, 5→10 output gates; CodeMetric entity; test_coverage_gate
- MODIFIED: `graqle/plugins/mcp_dev_server.py` — additive: 5 new tools (graq_review, graq_debug, graq_scaffold, graq_workflow, graq_test) + 5 kogni_* aliases = 108 total; 5 handler methods; _WRITE_TOOLS extended; dispatch extended
- MODIFIED: `graqle/routing.py` — additive: 10 new MCP_TOOL_TO_TASK entries; test task type in TASK_RECOMMENDATIONS = 18 total
- MODIFIED: `tests/test_generation/test_phase4_tools.py` — expanded: graq_test + Phase5 ontology tests
- MODIFIED: `tests/test_generation/test_phase35_tools.py` — count 106→108
- MODIFIED: `tests/test_plugins/test_mcp_dev_server.py` — count 106→108, added graq_test
- MODIFIED: `tests/test_plugins/test_mcp_dev_server_v015.py` — count 106→108
- MODIFIED: `tests/test_plugins/test_phantom.py` — count 106→108
- MODIFIED: `tests/test_routing.py` — task count 17→18
- CREATED: `.gsm/decisions/ADR-117-compound-workflow-tools-and-graq-test.md`
**Key Decisions:**
- graq_predict 40/40 agent consensus (93% confidence): graq_test is keystone — enables CodeMetric + test_coverage_gate + graq_profile cascade
- Compound workflows enabled: bug_fix, scaffold_and_test, governed_refactor, review_and_fix
- graq_test parses pytest structured output → CodeMetric nodes → test_coverage_gate enforcement
- Hardcoded count lesson applied: all test files updated atomically before running suite
**Next:**
- [ ] graq_profile tool + PERFORMANCE_PROFILING skill
- [ ] Phase 4 CLI: graq generate, graq edit commands
- [ ] WorkflowOrchestrator with DAG/saga semantics (highest architectural gap)
**Blockers:** None
