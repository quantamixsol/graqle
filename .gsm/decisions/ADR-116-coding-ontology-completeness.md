# ADR-116: Coding Domain Ontology — Completeness Roadmap
**Date:** 2026-03-27 | **Status:** ACCEPTED (roadmap)
**Branch:** feature-coding-assistant | **Phase:** T3.5 analysis

## Context
graq_reason (78% confidence) assessed the current coding domain ontology: 4 skills, 5 entity types, 0 formalized relationships, 0 formalized output gates = ~25-30% complete.

## Current State
| Dimension | Current | Target | Coverage |
|-----------|---------|--------|----------|
| Skills | 4 | ~16 | ~25% |
| Entity Types | 5 | ~13 | ~38% |
| Relationships | 0 | ~12 | 0% |
| Output Gates | 0 | ~8 | 0% |

## Decision: Phased Expansion

### Phase 3.5 (done): Core tool layer
The 10 new tools (read/write/grep/glob/bash/git_*) ARE the Phase 3.5 skill enablement.

### Phase 4 (CLI): Add to ontology
**Add 8 skills:**
CODE_REVIEW, DEBUG, DEPENDENCY_ANALYSIS, SECURITY_AUDIT, COMPLEXITY_ANALYSIS,
DEAD_CODE_DETECTION, DOCUMENTATION, MIGRATION

**Add 8 entity types:**
CodeDependency, CodeConfig, CodeVariable, CodeSchema, CodeInterface,
CodeDecorator, CodeException, CodeChange (diff-tracking with provenance)

**Add 8 relationships:**
DEPENDS_ON, IMPORTS, CALLS, INHERITS_FROM, IMPLEMENTS, TESTS/TESTED_BY, RAISES, CONFIGURES

**Add 4 output gates:**
DiffPatch, DiagnosticList, ComplexityMetrics, SecurityReport

### Phase 5 (VS Code + WorkflowOrchestrator)
**Add remaining 4 skills:** PERFORMANCE_OPTIMIZATION, TYPE_INFERENCE, EXPLAIN, NAMING_CONVENTION_CHECK
**Add remaining 5 entity types:** CodeVariable, CodeImport, CodeSnippet, CodeRepository, CodeMetric
**Add remaining 4 relationships:** DECORATES, OVERRIDES, DOCUMENTS, CONFLICTS_WITH
**Add remaining 4 output gates:** CoverageGate, BreakingChangeGate, ConfidenceGate, ExplanationTrace

## Critical Gap: WorkflowOrchestrator
graq_predict (82% confidence) identified the single most critical missing piece:
**No DAG/saga/state machine** to coordinate multi-step workflows.
- Currently: each tool call is stateless
- Needed: `grep → read → fix → write → test → commit/rollback` as a governed transaction
- Also needed: typed ToolExecutionStatus (pass/fail/error), cost circuit-breaker, iteration caps

## Rule
Do NOT expand entity types or relationships until at least CODE_REVIEW and DEPENDENCY_ANALYSIS skills are added — those skills provide the primary consumers of the new entity/relationship types.
