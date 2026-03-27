### COMMIT 8 — 2026-03-27T12:29:52Z
**Branch:** feature-coding-assistant
**Milestone:** Phase 8 complete — GOVERNANCE_BYPASS KG wiring, TOOL_EXECUTION audit trail, graq gate CLI + SARIF
**State:** WORKING

**Files Changed:**
- MODIFIED: graqle/plugins/mcp_dev_server.py — GOVERNANCE_BYPASS KG write in _handle_edit/_handle_generate; TOOL_EXECUTION audit node in handle_tool finally block
- MODIFIED: graqle/cli/main.py — new `graq gate` command (exit 0/1, --json, --sarif SARIF v2.1)
- CREATED: tests/test_generation/test_phase8_wiring.py — 20 tests
- CREATED: .gsm/decisions/ADR-120-phase8-wiring-gaps.md

**PCST/ChunkScorer Audit (ADR-112):**
- CLEAN. AdaptiveActivation is not used in the main areason() path.
- Main path (graph.py:1534): PCST is explicit opt-in only (strategy=="pcst").
- Default path is ChunkScorer (semantic/embedding) — not a fallback, the primary strategy.
- ADR-112 (no silent keyword fallback) is fully enforced in mcp_dev_server.py.

**Test counts:**
- Phase 8 tests: 20 (test_phase8_wiring.py)
- test_generation/ total: 262 passing
- Previous total: 529 (Phases 1-7)
- Running total: ~549 passing

**Feature branch:** feature/v0.38.0-governance pushed to GitHub (commit 7d1609b)

**Next:**
- Phase 9: WorkflowOrchestrator + CI/CD Gate (graq gate GH Actions + policy YAML)
- Phase 10: AST parsing + policy-as-code + expanded secret detection
