### COMMIT 8 — 2026-03-27T12:00:00Z
**Branch:** feature-coding-assistant
**Milestone:** Phase 8 complete — GOVERNANCE_BYPASS + TOOL_EXECUTION KG audit nodes, graq gate CLI command (binary exit 0/1, --json, --sarif SARIF v2.1), WorkflowOrchestrator wired in mcp_dev_server. 20 Phase 8 tests pass.
**State:** WORKING
**Files Changed:**
- MODIFIED: `graqle/plugins/mcp_dev_server.py` — GOVERNANCE_BYPASS KG write in _handle_edit/_handle_generate; TOOL_EXECUTION audit node in handle_tool finally block; _handle_workflow wires WorkflowOrchestrator for governed_* types
- MODIFIED: `graqle/cli/main.py` — gate_command added: binary exit 0/1, --diff, --risk, --impact-radius, --approved-by, --justification, --actor, --json, --fail/--no-fail, --sarif (SARIF v2.1)
- CREATED: `tests/test_generation/test_phase8_wiring.py` — 20 tests
- CREATED: `.gsm/decisions/ADR-120-phase8-wiring-gaps.md` — wiring gap rationale
**Key Decisions:**
- GOVERNANCE_BYPASS write uses try/except pass — audit trail MUST NEVER fail primary operation
- TOOL_EXECUTION node in finally block — captures latency even on exception
- gate_command exits 1 on blocked — binary exit for CI
- --sarif emits SARIF v2.1 for GitHub Advanced Security
**Next:**
- [x] Phase 9: WorkflowOrchestrator, GovernancePolicyConfig, governance-gate.yml
**Blockers:** None
