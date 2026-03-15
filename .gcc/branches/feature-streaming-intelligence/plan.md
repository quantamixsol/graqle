# GSD PLAN: Phase 1 — Streaming Intelligence Pipeline

**Branch:** feature-streaming-intelligence
**Ralph Max Iterations:** 20 per task
**Total Tasks:** 12
**Estimated Phases:** 3 waves (dependency-ordered)

---

## Wave 1: Foundation (no dependencies — can Ralph in parallel)

### Task 1.1: FileIntelligenceUnit Data Model [S]
**File:** `graqle/intelligence/models.py`
**What:** Define Pydantic models for FileIntelligenceUnit, ValidatedNode, ValidatedEdge,
ModulePacket, CoverageReport, ValidationResult.
**Ralph Criteria:** `python -c "from graqle.intelligence.models import FileIntelligenceUnit, ModulePacket"` succeeds. All models have complete type annotations. pytest test file passes.
**Verification:** Import test + instantiation test with sample data.

### Task 1.2: 6 Validation Gates [M]
**File:** `graqle/intelligence/validators.py`
**What:** Implement 6 validation gate functions, each taking a partial node/edge set and
returning ValidationResult with auto-repair actions applied.
- Gate 1: parse_integrity — check AST success, fallback to raw chunking
- Gate 2: node_completeness — label, type, description, chunks all present
- Gate 3: chunk_quality — meaningful content, not boilerplate, has type/line range
- Gate 4: edge_integrity — both endpoints exist, registered type, no self-loops
- Gate 5: relationship_completeness — expected edges present (CONTAINS, DEFINES, IMPORTS)
- Gate 6: intelligence_compilation — module packet producible

**Ralph Criteria:** All 6 gates have pytest tests. Each gate has ≥3 test cases (pass, fail+autorepair, fail+degrade). Tests run green: `pytest tests/test_intelligence/test_validators.py -x`.
**Verification:** Run validators on a sample scan.py node set — expect 0 hollow nodes.

### Task 1.3: Running Scorecard [S]
**File:** `graqle/intelligence/scorecard.py`
**What:** Accumulator that tracks per-file validation results and produces live coverage
percentages. Emits curiosity-peak insights (see Curiosity Peak Design below).
**Ralph Criteria:** Scorecard accumulates 10 sample files, produces correct percentages. `scorecard.insights` returns ≥1 insight per 3 files processed. Tests pass.
**Verification:** Unit tests with mock file results.

---

## Wave 2: Pipeline (depends on Wave 1)

### Task 2.1: Fast Structural Pass [S]
**File:** `graqle/intelligence/pipeline.py`
**What:** `structural_pass(root: Path)` — file listing + size + extension counting.
Returns project shape in <3 seconds for 1000 files. No code parsing.
**Ralph Criteria:** `structural_pass(Path("graqle-sdk"))` completes in <3s and returns correct file counts. Test against known SDK structure.
**Verification:** Time the call. Verify counts match `find graqle/ -name "*.py" | wc -l`.

### Task 2.2: Import Graph Pass [S]
**File:** `graqle/intelligence/pipeline.py`
**What:** `import_graph_pass(files: list[Path])` — regex scan of import/from lines.
Returns dependency dict {file: [imports]}. Computes import counts per file.
**Ralph Criteria:** `import_graph_pass(sdk_files)` identifies core/graph.py as most-imported. Completes in <10s for 50 files. Tests pass.
**Verification:** Verify core/graph.py has highest import count in SDK.

### Task 2.3: Priority Scan Order [S]
**File:** `graqle/intelligence/pipeline.py`
**What:** `prioritize_files(files, import_counts)` — sort files by import count descending.
Most-connected files scan first, delivering 80% intelligence value in first 20% of files.
**Ralph Criteria:** First 10 files in priority order include core/graph.py, config/settings.py, cli/commands/scan.py. Test passes.
**Verification:** Check priority order against known SDK structure.

### Task 2.4: Streaming File Processor [L]
**File:** `graqle/intelligence/pipeline.py`
**What:** `async process_file(file_path, graph, scorecard)` — scans one file using existing
RepoScanner internals, runs 6 validation gates, produces FileIntelligenceUnit, updates
scorecard, yields events for dashboard.
**Ralph Criteria:** `process_file("graqle/activation/chunk_scorer.py")` returns FileIntelligenceUnit with ≥95% coverage. All chunks valid. All edges valid. Module packet populated. Test passes.
**Verification:** Run on 5 representative SDK files, check all produce valid units.

### Task 2.5: Intelligence Compiler [M]
**File:** `graqle/intelligence/compiler.py`
**What:** `compile_module(file_unit, graph)` — produces ModulePacket JSON with consumers,
dependencies, public interfaces, risk score, impact radius.
`compile_impact_matrix(all_packets)` — produces cross-module impact map.
**Ralph Criteria:** Module packet for chunk_scorer.py lists core.graph as consumer. Impact matrix has ≥20 entries for SDK. All packets serializable to JSON. Tests pass.
**Verification:** JSON output matches expected schema. Impact matrix identifies graph.py as highest-impact.

---

## Wave 3: Output + Experience (depends on Wave 2)

### Task 3.1: Intelligence Emitter [M]
**File:** `graqle/intelligence/emitter.py`
**What:** `IntelligenceEmitter` class that writes to all output targets:
- `.graqle/intelligence/modules/` — module packet JSONs
- `.graqle/intelligence/impact_matrix.json`
- `.graqle/intelligence/module_index.json`
- `.graqle/scorecard.json`
**Ralph Criteria:** After emitting 47 SDK modules, all JSON files exist and are valid. `module_index.json` lists all modules. `scorecard.json` shows ≥95% coverage. Tests pass.
**Verification:** File existence + JSON parse + schema validation.

### Task 3.2: Inline Header Generator [M]
**File:** `graqle/intelligence/headers.py`
**What:** Generate and inject/eject intelligence comment headers in source files.
- Python: `# ── graqle:intelligence ──` ... `# ── /graqle:intelligence ──`
- JS/TS: `// ── graqle:intelligence ──` ... `// ── /graqle:intelligence ──`
- Bounded markers only. Never touches code outside markers.
- `inject(file_path, header_text)` and `eject(file_path)` functions.
**Ralph Criteria:** `inject()` adds header to chunk_scorer.py. `eject()` removes it cleanly. File is byte-identical before inject and after inject+eject cycle. Tests pass.
**Verification:** Diff before/after eject cycle = empty.

### Task 3.3: CLAUDE.md Auto-Section [S]
**File:** `graqle/intelligence/claude_section.py`
**What:** Generate `<!-- graqle:intelligence -->` section for CLAUDE.md / .cursorrules.
Contains module risk map, recent incidents, quality gate status.
Auto-detects AI tool from project markers.
**Ralph Criteria:** Section generated for Graqle SDK contains ≥5 modules in risk map. AI tool auto-detection finds "claude" for SDK. Bounded markers work (inject + eject cycle). Tests pass.
**Verification:** Generated section parseable, contains expected modules.

### Task 3.4: `graq init` Command [M]
**File:** `graqle/cli/commands/init.py`
**What:** Orchestrator command that runs the full streaming pipeline:
1. Structural pass → print project shape (3s)
2. Import graph → print dependency map (10s)
3. Priority-ordered deep scan → stream per file with scorecard (30-60s)
4. Compile intelligence → emit to all outputs
5. Inject headers if --inject flag
6. Write CLAUDE.md section
7. Print dashboard URL if Studio available
8. Print final scorecard

**Ralph Criteria:** `graq init` on SDK directory completes in <60s. Prints project shape within 3s. Prints dependency graph within 10s. Final scorecard shows ≥95% chunk coverage. `.graqle/intelligence/` directory populated. Exit code 0. Tests pass.
**Verification:** Full end-to-end run on Graqle SDK. Time each phase.

### Task 3.5: Studio WebSocket + Dashboard [M]
**File:** `graqle/studio/intelligence_ws.py` + Studio frontend component
**What:** WebSocket endpoint `/ws/intelligence` that streams scan events.
Studio page `/intelligence` that shows live module map, scorecard, intelligence feed.
**Ralph Criteria:** WebSocket sends events as files are scanned. Studio page renders module map with ≥5 nodes after 10s of scanning. Scorecard updates in real-time. Tests pass (backend WS test + frontend render test).
**Verification:** Open dashboard during `graq init`, see live updates.

---

## Curiosity Peak Design

Each streamed file should reveal an INSIGHT that peaks curiosity, not just "file scanned ✓":

```
✓ core/graph.py — 42 functions. THE MOST IMPORTED MODULE (14 consumers).
  Any change here ripples through the entire SDK.

✓ cli/commands/scan.py — 66 functions, 8 classes. YOUR LARGEST FILE.
  JSAnalyzer alone has 15 methods. Consider splitting?

✓ activation/chunk_scorer.py — INCIDENT HISTORY FOUND.
  v0.25.0: chunk coverage regression (27.3%). 3-tier fallback fixed it.

✓ config/settings.py — 14 configuration classes.
  GraqleConfig has 13 sub-configs. Most complex settings in the SDK.

✓ mcp/tools.py — 22 MCP tools registered.
  graq_context is called most frequently (from MCP logs).
```

**Insight Categories:**
1. **Superlatives** — "MOST imported", "LARGEST file", "MOST complex"
2. **Warnings** — "INCIDENT HISTORY found", "HIGH RISK — 12 consumers"
3. **Suggestions** — "Consider splitting?", "3 unused exports detected"
4. **Connections** — "This module connects 4 otherwise-isolated modules"
5. **History** — "Changed 12 times in last 30 days", "Last incident: ..."

Each category gets a different emoji/color in the terminal and dashboard.
The user can't look away because every 2 seconds they learn something new about their code.

---

## Dependency Graph

```
Wave 1 (parallel):
  [1.1 Models] ─┐
  [1.2 Validators] ─┤── all independent
  [1.3 Scorecard] ─┘

Wave 2 (sequential within, parallel across some):
  [2.1 Structural] → [2.3 Priority] → [2.4 Streaming Processor]
  [2.2 Import Graph] ↗                        ↓
                                        [2.5 Compiler]

Wave 3 (depends on Wave 2):
  [3.1 Emitter] ─┐
  [3.2 Headers] ─┤── can parallel
  [3.3 CLAUDE.md] ─┘
         ↓
  [3.4 graq init] (orchestrates all above)
         ↓
  [3.5 Dashboard] (optional, can develop in parallel)
```

## Ralph Execution Order

1. **Ralph Loop 1:** Tasks 1.1, 1.2, 1.3 (parallel, max 20 iterations each)
2. **Ralph Loop 2:** Tasks 2.1, 2.2, 2.3 (parallel, max 10 iterations each)
3. **Ralph Loop 3:** Task 2.4 (serial, max 20 iterations — largest task)
4. **Ralph Loop 4:** Task 2.5 (serial, max 15 iterations)
5. **Ralph Loop 5:** Tasks 3.1, 3.2, 3.3 (parallel, max 15 iterations each)
6. **Ralph Loop 6:** Task 3.4 (serial, max 20 iterations — integration)
7. **Ralph Loop 7:** Task 3.5 (serial, max 15 iterations — dashboard)

**Total estimated:** 12 tasks, 7 Ralph loops, ~3-5 sessions
