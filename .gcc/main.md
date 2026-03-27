# Graqle SDK — Global Roadmap

## Vision
Dev Intelligence Layer — Graph + Quality Gate for development.
The Q in Graqle = Quality Gate that every code change passes through.

## Current Version: v0.37.0 (next: v0.38.0)

## Strategic Direction: Governed AI Coding Assistant
Transform graqle from read-only reasoning into a governed AI coding assistant.
Branch: feature-coding-assistant | Target: v0.38.0

## Active Work — feature-coding-assistant (Phases 1–9 DONE, Phase 10 pending)
- [x] Phase 1: graq_generate MCP tool (68 tests)
- [x] Phase 2: graq_edit + atomic file writer (90 tests)
- [x] Phase 3: Backend streaming (agenerate_stream on all 14 backends)
- [x] Phase 3.5: File system + git tool layer (98→108 tools)
- [x] Phase 4: Compound workflow tools + coding ontology ~90% (112 tools)
- [x] Phase 5: graq_plan Plan-as-Graph primitive
- [x] Phase 6: graq_profile + PERFORMANCE_PROFILING skill
- [x] Phase 7: GovernanceMiddleware 3-tier gate (TS-BLOCK/T1/T2/T3)
- [x] Phase 8: GOVERNANCE_BYPASS + TOOL_EXECUTION KG nodes; graq gate CLI (SARIF v2.1)
- [x] Phase 9: WorkflowOrchestrator 7-stage state machine; GovernancePolicyConfig; governance-gate.yml CI
- [ ] **Phase 10**: tree-sitter AST, policy-as-code DSL, 200+ secret patterns, RBAC, adversarial tests
- [ ] v0.38.0 release tag + PyPI publish

## Completed (v0.24-v0.37)
- [x] JS/TS full coverage (JSAnalyzer rewrite)
- [x] 14 backend providers
- [x] 112 MCP tools (graq_* + kogni_* aliases)
- [x] ADR-105 (Streaming Intelligence), ADR-106 (Gate+Rerank), ADR-107 (Staleness)
- [x] ADR-111–120 (coding assistant phases 1–8)
