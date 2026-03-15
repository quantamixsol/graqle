# GSD CONTEXT: Streaming Intelligence & Quality Gate

## Problem Statement
Graqle is a passive MCP tool that AI coding tools bypass 70-80% of the time. The scan pipeline
produces KGs with quality gaps (dropped chunks, hollow nodes, dangling edges). Users wait 2-5
minutes with no visible progress before seeing any value, killing adoption.

## Scope

### In-Scope
- Streaming per-file scan pipeline with inline validation
- 6 validation gates guaranteeing 95%+ coverage by construction
- Intelligence compilation (module packets, impact matrix)
- Layer B: inline intelligence headers in source files
- Layer B: CLAUDE.md / .cursorrules auto-section
- Studio dashboard with live WebSocket updates
- `graq init` command combining scan + compile + dashboard
- 60-second first value experience
- Curiosity-peak design: each streamed file reveals an insight

### Out-of-Scope (Deferred)
- Layer A: graq_gate MCP tool enhancements (Phase 2)
- Layer C: pre-commit hooks and CI gates (Phase 3)
- Governance/DRACE scoring (Phase 4)
- Dev Governance Protocol spec (Phase 5)
- Neo4j integration for intelligence (future)
- Enterprise multi-repo governance (future)

### Deferred Ideas
- "Graqle Score" badge for GitHub repos (like coverage badges)
- IDE extension with inline governance annotations
- Auto-generated architectural diagrams from KG

## Constraints
- Zero changes to existing scan.py logic (additive only)
- All 1,655+ existing tests must pass
- No new heavy dependencies (no tree-sitter, no new ML models)
- Intelligence headers must be bounded by markers (graqle:intelligence)
- Dashboard is optional (--no-dashboard flag)
- Must work offline (no cloud dependency for core intelligence)

## Success Criteria (Binary — Ralph-Ready)
1. `graq init` on Graqle SDK prints project shape in <3 seconds
2. `graq init` on Graqle SDK shows dependency graph in <10 seconds
3. `graq init` on Graqle SDK completes full intelligence in <60 seconds
4. Validation scorecard shows ≥95% chunk coverage on Graqle SDK
5. Zero hollow nodes (every code node has ≥1 chunk)
6. Zero dangling edges (every edge has valid source + target)
7. Module packets exist for every Python module in .graqle/intelligence/
8. Impact matrix correctly identifies core/graph.py as highest-impact
9. CLAUDE.md auto-section contains module risk map
10. Studio dashboard opens and shows live scan progress
11. All 1,655+ existing tests pass
12. `graq compile --eject` cleanly removes all injected content

## Open Questions (Resolved)
- Q: Should graq init replace graq scan?
  A: No. graq init = scan + compile + dashboard (superset). graq scan stays for raw KG building.
- Q: Inline headers in non-# languages?
  A: Use language-appropriate comment syntax (// for JS/TS, /* */ for CSS). JSON files skip headers.
