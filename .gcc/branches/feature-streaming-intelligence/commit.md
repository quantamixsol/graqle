### BRANCH CREATED — 2026-03-15T15:00:00Z
**Name:** feature-streaming-intelligence
**Parent:** main
**Purpose:** Implement ADR-105 — Streaming Intelligence Pipeline + 3-Layer Quality Gate
**Success Criteria:**
1. `graq init` delivers first value in <3 seconds, full intelligence in <60 seconds
2. Per-file validation guarantees ≥95% chunk coverage by construction
3. Layer B inline headers present in source files (0% AI bypass)
4. Layer C pre-commit hook catches constraint violations
5. Dogfooded on Graqle SDK itself with measurable evidence

---

### COMMIT 1 — 2026-03-15T15:00:00Z
**Milestone:** ADR-105 written and accepted
**State:** WORKING
**Files Changed:**
- CREATED: docs/ADR-105-streaming-intelligence-quality-gate.md — full strategic shift ADR
- CREATED: .gcc/main.md — global roadmap
- CREATED: .gcc/registry.md — branch registry
- CREATED: .gcc/branches/feature-streaming-intelligence/commit.md — this file
- CREATED: .gsm/decisions/ADR-105.md — GSM decision record
- CREATED: .gsm/index.md — GSM master index
**Key Decisions:**
- Q in Graqle = Quality Gate (not Query)
- 3-layer architecture: B (embedded) + A (reasoning) + C (enforcement)
- Streaming per-file validation with 6 gates
- 60-second first value design
- TAMR+ governance patterns mapped to development domain
**Next:**
- [ ] GSD PLAN: Break Phase 1 into atomic tasks with Ralph-ready criteria
- [ ] Build graqle/intelligence/pipeline.py (streaming processor)
- [ ] Build graqle/intelligence/validators.py (6 validation gates)
- [ ] Build graqle/intelligence/compiler.py (module packet generator)
**Blockers:** None

---

### COMMIT 2 — 2026-03-15T16:30:00Z
**Milestone:** Wave 1 + Wave 2 complete — full intelligence pipeline with 68 tests
**State:** WORKING
**Files Changed:**
- CREATED: graqle/intelligence/__init__.py — module init with public exports
- CREATED: graqle/intelligence/models.py — 10 Pydantic models (FileIntelligenceUnit, ValidatedNode, ValidatedEdge, ModulePacket, CoverageReport, CuriosityInsight, etc.)
- CREATED: graqle/intelligence/validators.py — 6 validation gates with auto-repair + run_all_gates orchestrator
- CREATED: graqle/intelligence/scorecard.py — RunningScorecard with 5 curiosity-peak insight categories
- CREATED: graqle/intelligence/pipeline.py — structural_pass, import_graph_pass, compile_module_packet, process_file_lightweight, stream_intelligence
- CREATED: tests/test_intelligence/test_models.py — 15 tests for data models
- CREATED: tests/test_intelligence/test_validators.py — 19 tests for 6 validation gates
- CREATED: tests/test_intelligence/test_scorecard.py — 16 tests for scorecard + curiosity insights
- CREATED: tests/test_intelligence/test_pipeline.py — 18 tests for pipeline (dogfooded on SDK)
**Key Decisions:**
- Lightweight regex extraction for streaming speed (not full AST) — full RepoScanner layered on later
- Module name derivation strips .py/.js/.ts suffix (not rstrip which eats chars)
- Curiosity insights fire after 1st file (needs baseline for superlatives)
- Risk formula: 0.4*consumers + 0.3*functions + 0.2*dependencies + 0.1*edge_density
**Evidence (dogfooding):**
- structural_pass on SDK: <3s, finds 196+ Python files ✓
- import_graph_pass: identifies graph.py as most-imported (49 consumers) ✓
- process_file on settings.py: zero hollow nodes, all chunks validated ✓
- stream_intelligence: generates insights (MOST IMPORTED, LARGEST, etc.) ✓
- 68 new tests all green, 1,705+ total tests pass ✓
**Next:**
- [ ] Wave 3: Intelligence emitter (JSON output)
- [ ] Wave 3: Inline header generator + eject
- [ ] Wave 3: CLAUDE.md auto-section generator
- [ ] Wave 3: `graq init` command (orchestrator)
- [ ] Wave 3: Studio dashboard WebSocket
**Blockers:** None

---

### COMMIT 3 — 2026-03-15T18:00:00Z
**Milestone:** Wave 3 complete — full output layer with 67 tests + dogfooded on SDK (363 modules in 58.1s)
**State:** WORKING
**Files Changed:**
- CREATED: graqle/intelligence/emitter.py — IntelligenceEmitter writes per-module JSON, module_index, impact_matrix, scorecard
- CREATED: graqle/intelligence/headers.py — Layer B inline headers: generate/inject/eject for Python/JS/TS (600 byte limit)
- CREATED: graqle/intelligence/claude_section.py — CLAUDE.md auto-section with module risk map, auto-detects Claude/Cursor/Copilot/Windsurf
- CREATED: graqle/intelligence/compile.py — `graq compile` CLI: 4-phase streaming pipeline with Rich progress + Quality Gate Scorecard
- MODIFIED: graqle/intelligence/__init__.py — added Wave 3 public exports
- MODIFIED: graqle/cli/main.py — registered compile_command as `graq compile`
- CREATED: tests/test_intelligence/test_emitter.py — 9 tests
- CREATED: tests/test_intelligence/test_headers.py — 25 tests
- CREATED: tests/test_intelligence/test_claude_section.py — 23 tests
- CREATED: tests/test_intelligence/test_compile.py — 10 tests
**Key Decisions:**
- compile_intelligence() is the single entry point for the full pipeline
- Inline headers limited to 600 bytes to avoid source file bloat
- AI tool detection covers Claude, Cursor, Copilot, Windsurf — tool-agnostic
- Eject is first-class (clean removal of all injected intelligence)
**Evidence (dogfooding on Graqle SDK):**
- 363 modules compiled in 58.1s (under 60s target) ✓
- 5,819 nodes, 6,735 edges ✓
- 100.0% chunk coverage, 100.0% description coverage ✓
- 0 degraded nodes, 1,919 auto-repairs (all healed) ✓
- 120 curiosity-peak insights generated ✓
- 135 intelligence tests all green ✓
**Next:**
- [ ] Wave 3, Task 3.5: Studio WebSocket + Dashboard
- [ ] Phase 2: graq_gate MCP tool (serve pre-compiled packets)
- [ ] Phase 3: Layer C enforcement (pre-commit hooks)
- [ ] Second-pass edge resolution (75% → 95%+ edge integrity)
**Blockers:** None

---

### COMMIT 4 — 2026-03-15T19:30:00Z
**Milestone:** Wave 4 complete — Edge resolver (100% integrity) + graq_gate MCP + graq verify + pre-commit hooks
**State:** WORKING
**Files Changed:**
- MODIFIED: graqle/intelligence/pipeline.py — added resolve_pending_edges() second-pass edge resolver
- MODIFIED: graqle/intelligence/compile.py — integrated edge resolution phase + --hooks/--unhook flags
- MODIFIED: graqle/intelligence/scorecard.py — added recalculate_edge_coverage()
- CREATED: graqle/intelligence/gate.py — IntelligenceGate: serves pre-compiled packets <100ms (Layer A)
- CREATED: graqle/intelligence/verify.py — graq verify: checks changes against intelligence (Layer C)
- CREATED: graqle/intelligence/hooks.py — pre-commit hook install/uninstall (Layer C enforcement)
- MODIFIED: graqle/plugins/mcp_dev_server.py — registered graq_gate + kogni_gate MCP tool
- MODIFIED: graqle/cli/main.py — registered graq verify CLI command
- CREATED: tests/test_intelligence/test_gate.py — 15 tests (incl. <100ms response time test)
- CREATED: tests/test_intelligence/test_verify.py — 9 tests
- CREATED: tests/test_intelligence/test_hooks.py — 11 tests
**Key Decisions:**
- Gate logic extracted to graqle/intelligence/gate.py (not monolith MCP handler) — KG-parseable
- Edge resolver removes external imports from edge count (not dangling, just external)
- graq verify reads pre-compiled JSON (<1s) — doesn't re-scan
- Pre-commit hook uses bounded markers (install/uninstall cleanly)
- Architecture cures itself: using Graqle improves the codebase for Graqle
**Evidence (dogfooding on Graqle SDK):**
- Edge integrity: 75.3% → 100.0% (525 cross-module edges resolved) ✓
- Health: CRITICAL → HEALTHY ✓
- 100% chunk coverage, 100% description coverage maintained ✓
- graq_gate response time: <100ms confirmed in test ✓
- graq verify correctly identifies CRITICAL risk modules ✓
- Pre-commit hooks install/uninstall cleanly ✓
- 170 intelligence tests all green ✓
**Next:**
- [x] Phase 4: Governance/DRACE scoring — DONE (COMMIT 5)
- [ ] Phase 4: Studio ReasoningTrailViewer + GovernanceHeatmap
- [ ] Phase 5: DGP protocol specification
- [ ] Self-healing architecture footprint (graqle.yaml auto-detection)
**Blockers:** None

---

### COMMIT 5 — 2026-03-15T19:30:00Z
**Milestone:** Wave 5 — Full Governance Layer (TAMR+ TRACE → DRACE pipeline)
**State:** DONE
**Files Changed:**
- CREATED: graqle/intelligence/governance/scope_gate.py — Scope boundary validation (from TAMR+ semantic_shacl_gate.py)
- CREATED: graqle/intelligence/governance/middleware.py — Thin audit wrapper for MCP tool calls
- MODIFIED: graqle/intelligence/governance/drace.py — FULL REWRITE: typed pillar evaluators (DependencyInput, ReasoningInput, AuditabilityInput, ConstraintInput, ExplainabilityInput) replacing raw text heuristics. Now mirrors TAMR+ TRACE pipeline architecture.
- MODIFIED: graqle/intelligence/governance/__init__.py — Exports for all governance types + evaluators
- MODIFIED: graqle/plugins/mcp_dev_server.py — graq_gate audit logging, graq_drace tool, governance middleware init
- CREATED: tests/test_intelligence/test_audit.py — 22 tests (entries, sessions, chain integrity, persistence)
- CREATED: tests/test_intelligence/test_drace.py — 44 tests (typed evaluators + backwards-compat interface)
- CREATED: tests/test_intelligence/test_evidence.py — 17 tests (items, chains, store, gate-to-evidence)
- CREATED: tests/test_intelligence/test_scope_gate.py — 22 tests (matching, validation, persistence)
- CREATED: tests/test_intelligence/test_governance_middleware.py — 10 tests (session lifecycle, chain integrity, DRACE scoring)
**Key Decisions:**
- DRACE rewritten as typed pipeline (not text heuristics) to match TAMR+ TRACE architecture
- Each TRACE pillar (T→D, R→R, A→A, C→C, E→E) gets a dedicated evaluator function receiving typed input models
- Governance middleware is a thin wrapper (not inline in MCP handlers) per user directive to avoid monolith handlers
- Blocking scope violations cap C-pillar at 0.3 (mirrors TAMR+ compliance failure caps)
- graq_drace MCP tool exposes audit trail sessions + DRACE scores to AI tools
**Evidence:**
- 115 governance tests passing in 0.44s
- Dogfood: audit trail 6 entries, SHA-256 chain valid, DRACE 0.727 (raw) / 0.986 (typed)
- Evidence chain: 5 decisions, 15 evidence items, 100% ratio
- Scope gate: correctly BLOCKs out-of-scope changes
**Next:**
- [ ] Phase 4: Studio ReasoningTrailViewer + GovernanceHeatmap components
- [ ] Phase 5: DGP (Dev Governance Protocol) specification
- [ ] Wire scope gate into graq verify pre-commit hook
- [ ] Self-healing architecture footprint (graqle.yaml auto-detection)
**Blockers:** None
