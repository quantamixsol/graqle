# Changelog

All notable changes to GraQle are documented in this file.

---

## 0.51.0 (2026-04-12)

### Added
- `graq gate-status` CLI command — reports gate health (installed / enforcing /
  interpreter valid / self-test passed). JSON output matches the ADR-154 Layer 2
  contract for the VS Code extension status chip.
- `graq lint-public` CLI command — scans all shipped files under `graqle/` for
  forbidden internal references (pattern tags, tracker IDs, product names, budget
  constants). Returns exit 0 if clean, exit 1 with violation list if not.
- ADR-154: VS Code extension integration spec (7-layer architecture, 7 new MCP
  tools, 9 CLI subcommands, 4-week rollout). First ADR committed to the tracked
  tree for cross-team visibility.
- `graq_write` new-file allowlist: CG-03 edit gate now allows `graq_write` on
  NEW code files (not yet on disk) and files under `.tmp_*` / `scripts/` /
  `tests/` paths. Existing hub code files remain edit-gated.

### Fixed
- Governance robustness hardening (6 pre-existing findings from v0.50.1 review):
  pattern-cache fail-closed semantics, env-var naming alignment + explicit base64
  decode + per-entry schema validation, persisted cumulative state validation,
  `risk_to_int` fail-safest (unknown/None/non-string maps to CRITICAL instead of
  MEDIUM), defensive credential-match attribute access, audit log parent-dir
  creation at init time.
- Systematic sanitization of 107 files across the entire `graqle/` package:
  381 forbidden internal references (ADR-N, TB-N, OT-NNN, CG-*, BLOCKER-N,
  TS-[1-4], product names) replaced with neutral descriptions. Distribution
  lint upgraded from advisory baseline (400) to hard gate (0).

### Internal
- 14 new governance regression tests in `tests/test_core/test_governance_postfix.py`.
- 13 KG lessons taught via `graq_learn` covering governance robustness, gates-on
  friction patterns, squash-merge rule, and Windows interpreter probe pattern.
- `graqle/storage/` module preserved as Phase 0 commit (parked for v0.51.1/v0.52.0).

---

## 0.50.1 (2026-04-12)

### Fixed
- Hardened the Windows installer for the governance gate. `graq gate-install`
  now probes for a working Python 3 interpreter (trying `sys.executable`,
  `python3`, `python`, `py -3`), skips the Windows Store Python stub, and
  substitutes the resolved interpreter into the generated `settings.json`.
  Also adds a `--fix-interpreter` flag to rewrite only the hook command
  string on existing installs.
- `graq gate-install` now runs a post-install self-test with a synthetic
  Bash tool payload and requires the hook to return exit 2 with
  "GATE BLOCKED" on stderr. A broken install can no longer silently
  complete; the command fails with a remediation hint instead.
- Governance gate hook now fails closed on unknown write-class tools.
  Previously, any Claude Code tool not in the explicit allowlist or
  blocklist fell through to exit 0. A regex heuristic
  (`^(Write|Edit|Delete|Exec|Run|Create|Update|Put|Post)`) now blocks
  such tools by default; unknown read-class tools still pass.
- `graq init` now auto-installs the Claude Code governance gate when
  Claude Code is detected (`.claude/` in project or home directory).
  Opt out with `--no-gate` or `GRAQLE_SKIP_GATE_INSTALL=1`. Operators
  no longer need to remember a second `graq gate-install` step.
- Fixed `from graqle import *` raising `AttributeError` because the
  package `__all__` listed `"GraQle"` while the class is `Graqle`.
- Sanitized internal references out of the shipped ChatAgentLoop v4
  built-in floor template and the TCG (Tool Capability Graph) seed
  for public distribution. User-visible tier names and public APIs
  are unchanged.

### Internal
- New `tests/test_distribution/test_no_internal_strings.py` — a
  public-disclosure regression lint that hard-fails on the v0.50.1
  sanitization targets and tracks a high-water advisory baseline for
  the rest of the package.
- Added `/GRAQ.md` at the SDK repo root as a walk-up extension for
  SDK-local developer rules. The file is not shipped in the wheel.
- Governance module internal helper renames: `_check_ts_leakage` →
  `_check_pattern_leakage`, `_TS_BLOCK_PATTERNS_DEFAULT` →
  `_BUILTIN_PATTERNS_DEFAULT`, and related. Backward-compat aliases
  preserve existing internal test imports.

---

### Round-2 remediation (2026-04-11) — research team review PR #49 (follow-up)

Addresses the 1 new BLOCKER (RO2-6) + 3 new MAJORs (RO2-1, RO2-3, RO2-4)
+ 2 MINORs (RO2-2, RO2-5) raised in the Round-2 research team review on
private PR #49. Operator directive: *"maintain our algorithm,
implementation rigour and business value while solving the points raised
by the research team."* All mechanism preserved. Algorithm integrity
verified: 9/9 classify_concern precedence cases pass after the fixes.

**RO2-6 (BLOCKER, now closed) — TCG seed reachability 25/67 → 67/67**
- The Round-1 expansion added 37 new TCGTool nodes but wired only a
  few MATCHES_INTENT edges, leaving 42/67 tools orphaned (unreachable
  from any intent or workflow pattern). Research team's programmatic
  graph-reachability audit caught this.
- Added 8 new TCGIntent nodes: `intent_visual_audit`,
  `intent_browser_automation`, `intent_production_deploy_check`,
  `intent_dependency_management`, `intent_autonomous_task`,
  `intent_knowledge_lookup`, `intent_review_pr`, `intent_trace_reasoning`.
- Added 3 new graduated TCGWorkflowPattern nodes:
  `workflow_visual_audit`, `workflow_autonomous_task`,
  `workflow_review_pr`.
- Added 57 new MATCHES_INTENT edges wiring every previously-orphan
  tool into at least one intent.
- Also backfilled core dev tools (`graq_edit`, `graq_bash`,
  `graq_git_log`) into their existing intents.
- **Reachability now 67/67 tools (100%)**, verified by the post-Round-2
  orphan audit script.

**RO2-4 (MAJOR, now closed) — banned-phrase guard self-defeat**
- The Round-1 `_BANNED_PROMPT_PHRASES` frozenset stored the literal
  patent-leaking sentences as plaintext strings in the shipped source.
  A competitor grepping the PyPI wheel could trivially discover the
  exact phrases the guard was meant to suppress.
- Replaced with `_BANNED_PHRASE_HASHES: frozenset[str]` — a set of
  SHA-1[:16] hex digests. The plaintext phrases never appear in
  shipped source.
- `_assert_no_banned_phrases` now computes a sliding window of 1..8
  word n-grams over each prompt, SHA-1 hashes each window, and
  compares against the hash set. Any match is a regression.
- Regression-tested: the guard still fires on `"Apply rule order
  strictly: safety > prerequisite > cost > ambiguity"` and on each
  legacy persona token (PROPOSER/ADVERSARY/ARBITER) even though none
  of these phrases appear as plaintext in the source.
- Added `test_banned_phrase_hashes_size` (shape check) +
  `test_banned_hash_guard_catches_strict_ordering_regression` +
  `test_banned_hash_guard_catches_persona_regression`.

**RO2-3 (MAJOR, now closed) — precedence comment leaks in debate.py**
- Scrubbed 3 locations where the English precedence chain
  ("safety comes first and wins over prerequisite > cost > ambiguity")
  was leaked in comments / docstrings:
  - `debate.py:209-213` — the `_CATEGORY_SIGNALS` comment. Replaced
    with generic "iteration order is the tie-breaker" language that
    does not state the specific ordering.
  - `debate.py:~299` — docstring inside `classify_concern`. Replaced
    with "is picked per the internal precedence policy".
  - Module docstring "Safety-first precedence with four categories" →
    "Four concern categories with a fixed internal ordering".
- All three scrubs preserve the documentation intent while removing
  the verbatim English chain.

**RO2-1 (MAJOR, now closed) — dead strict reader wired into TCG**
- Round-1 added `settings_loader.require_novelty_lift_min` but
  `tool_capability_graph.graduate_pattern` still read the module
  constant `PROBATION_NOVELTY_LIFT_MIN` directly, making the strict
  reader dead code.
- `ToolCapabilityGraph.__init__` now accepts an optional
  `settings: dict | None` parameter and stores the resolved threshold
  in `self._novelty_lift_min`. If `settings` is provided, the value is
  pulled via `settings_loader.load_novelty_lift_min`; otherwise the
  public default (0.2, intentionally non-operational) is used.
- `graduate_pattern` now reads `self._novelty_lift_min` on every call.
- `load_novelty_lift_min` + `require_novelty_lift_min` are now
  actually called in the hot path.

**RO2-2 (MINOR, now closed) — persona kwarg renamed to role**
- `ReasonFn` protocol: `persona: str` → `role: str`.
- All internal call sites updated.
- Docstring reference scrubbed.
- "Persona" was flagged as semantic cousin of the scrubbed vocabulary
  (core multi-agent debate terminology). Renaming to the neutral
  "role" label completes the vocabulary scrub.

**RO2-5 (MINOR, now closed) — phantom_screenshot tier adjusted**
- `graq_phantom_screenshot` governance tier GREEN → YELLOW.
- Side effect `read` → `net`.
- Rationale added to description: JS execution via remote page makes
  this a governed operation.

**Algorithm integrity verified (9/9 cases pass after fixes)**
- Safety precedence: `"destructive AND expensive AND slow"` → BLOCK
- Prerequisite > cost: `"missing prerequisite also expensive"` → REFINE
- Cost alone: `"this is expensive, high-latency"` → REFINE
- Ambiguity alone: `"ambiguous — unclear"` → REFINE
- Explicit none: `"CONCERN: none"` → PROCEED
- Affirmative safe: `"This action is non-destructive and safe."` → PROCEED
- Credentials rewrite: `"Uses credentials env-var name"` → PROCEED
- Safety alone: `"data loss ahead"` → BLOCK
- Irreversible: `"this is irreversible"` → BLOCK

**Mechanism preserved (non-negotiable per operator directive)**
- 3 parallel role calls via `asyncio.gather`
- Deterministic in-code override of the judge verdict
- 4-category internal ordering (enforced in `_CATEGORY_SIGNALS` list
  order)
- Round-refinement feedback loop
- `MAX_CHECK_ROUNDS = 2` hard ceiling
- `ReasonFn` protocol surface (kwarg name changed, semantics unchanged)

**Reachability verification**
- Pre-Round-1: 30 tools, 12 intents, 5 workflows, no orphans by
  construction
- Post-Round-1: 67 tools, 12 intents, 5 workflows — **42 orphans**
  (RO2-6 finding)
- Post-Round-2: **67 tools, 20 intents, 8 graduated workflows, 0
  orphans** — all tools reachable via at least one MATCHES_INTENT edge
  or workflow_pattern membership

**Tests:** `tests/test_chat/` 236 → **239 passing** (+3 new Round-2
regression tests). Hotfix suites (test_base_serialization.py,
test_continuation.py, test_areason_batch.py, test_aggregation.py)
unchanged at 9+19+9+7 = 44 passing. Zero regressions.

**Post-impl `graq_review` on debate.py with security focus:** **APPROVED
at 93% confidence**. All comments are INFO-level hygiene notes. No
OWASP Top 10 sinks, no secret exposure paths, no unsafe subprocess
calls. Hash-based guard ships without plaintext sensitive phrases.

---

### Round-1 remediation (2026-04-11) — research team review PR #49

Addresses the 2 BLOCKERs + 3 MAJORs raised in the research team review
on private PR #49. Operator waived BLOCKER-R1 conditional on scrubbing
patent-specific language from the debate subsystem while preserving
mechanism, algorithm, quality, and the core edge/moat. BLOCKER-R2 and
MAJOR-R1/R2/R3 are fully fixed.

**BLOCKER-R1 (waived + scrubbed) — debate.py language scrub**
- Renamed persona roles: `PROPOSER → CANDIDATE`, `ADVERSARY → CRITIC`,
  `ARBITER → JUDGE`. No verbatim "PROPOSER/ADVERSARY/ARBITER" strings
  appear anywhere in `graqle/chat/`.
- Rewrote all three role prompts. No prompt contains the banned
  sentence `"safety > prerequisite > cost > ambiguity"` — precedence
  now lives only in code (`classify_concern`), not in prompt text.
- Renamed constants: `_RULE_KEYWORDS → _CATEGORY_SIGNALS`,
  `MAX_DEBATE_ROUNDS → MAX_CHECK_ROUNDS`.
- Renamed functions: `deterministic_arbiter() → classify_concern()`,
  `run_debate() → resolve_concern()`.
- Renamed dataclasses: `DebateRecord → ConcernCheckRecord`,
  `DebateRound → ConcernCheckRound`, `PersonaResponse → RoleResponse`.
- Renamed RCAG node type: `NODE_TYPE_DEBATE_ROUND →
  NODE_TYPE_CHECK_ROUND` with backward-compat alias for in-session
  callers.
- Added `_BANNED_PROMPT_PHRASES` frozenset + `_assert_no_banned_phrases`
  import-time + runtime guard that fails fast on any regression
  reintroducing the scrubbed phrasing. Test suite re-asserts the guard.
- `backend_router.py` docstring scrubbed.
- **Mechanism preserved** (operator waiver condition): 3 parallel role
  calls via `asyncio.gather`, deterministic in-code override of the
  judge verdict, safety-first precedence with four categories
  (safety > prerequisite > cost > ambiguity in code), round-refinement
  feedback loop, `MAX_CHECK_ROUNDS = 2` hard ceiling.

**BLOCKER-R2 — TS-3 activation-threshold collision on 0.15**
- Changed public default of `PROBATION_NOVELTY_LIFT_MIN` from `0.15`
  to `0.2` in `graqle/chat/tool_capability_graph.py`. The old value
  collided exactly with the unpublished PSE `similarity_threshold`
  per research TS-3 finding.
- Updated seed JSON `_meta.schema_notes.probation_thresholds.novelty_lift_min`
  from `0.15` to `0.2` with an explicit annotation that the public
  default is non-operational and operators must override via
  `.graqle/settings.json`.
- Added `settings_loader.load_novelty_lift_min(settings)` strict
  reader and `settings_loader.require_novelty_lift_min(settings)`
  fail-loud variant. The strict reader returns `None` on missing key
  so the caller can fall back to the public default; the fail-loud
  variant raises `ValueError` if the key is absent. Pattern per
  `lesson_20260402T210613`: `config.get(KEY, default)` with a
  numerical default IS a hardcoded threshold disguised as config.
- Test docstring in `test_tool_capability_graph.py` updated to
  reflect the new default.

**MAJOR-R1 — TCG seed coverage expanded from 30 → 67 tools**
- Added 37 new `TCGTool` nodes covering: 4 governance (`graq_gov_gate`,
  `graq_safety_check`, `graq_audit`, `graq_runtime`), 8 phantom
  (`graq_phantom_browse / _click / _type / _screenshot / _audit /
  _session / _discover / _flow`), 13 scorch (`graq_scorch_audit /
  _report / _a11y / _perf / _seo / _mobile / _i18n / _security /
  _conversion / _brand / _auth_flow / _behavioral / _diff`), 6
  lifecycle + workflow (`graq_lifecycle`, `graq_drace`,
  `graq_workflow`, `graq_auto`, `graq_route`, `graq_correct`), and 6
  accessory (`graq_profile`, `graq_web_search`, `graq_plan`,
  `graq_github_pr`, `graq_github_diff`, `graq_todo`). Plus
  `graq_reload` under destructive tier.
- Wired 6 new `MATCHES_INTENT` edges so `intent_audit` now surfaces
  `graq_gov_gate`, `graq_safety_check`, `graq_audit`, `graq_runtime`;
  `intent_governed_refactor` surfaces `graq_gov_gate`; and
  `intent_review` surfaces `graq_safety_check`.
- Restores the "governance pre-disclosure" property promised in PR #49
  body and unblocks the R18 GETC trace-capture flow.

**MAJOR-R1b — auto-create probationary unknowns in reinforce_sequence**
- Added `ToolCapabilityGraph._auto_create_probationary_tool(tool_id)`
  helper that creates a YELLOW probationary `TCGTool` node with
  `governance_tier=YELLOW`, `safe_for_prediction=False`,
  `probation=True`, `auto_created=True`.
- Updated `reinforce_sequence` to auto-create probationary nodes for
  unseen `tool_*`-prefixed ids instead of silently skipping them. Non-
  tool_ prefixed ids are still silently ignored (intents, workflows,
  lessons).
- Predicted missing edges never surface auto-created tools because
  `predict_missing_edges` filters by `safe_for_prediction=True`.
- Keeps BLOCKER-2 valid: no `KogniDevServer.list_tools()` runtime
  bootstrap — learning still comes exclusively from observed usage.
- The docstring claim *"UNKNOWN until reinforce_sequence learns them"*
  is now factually correct.

**MAJOR-R2 — prediction bias toward seeded tools** — automatically
reduced by MAJOR-R1 expansion (67 tools vs 30 before) + auto-create
fallback. No separate code fix.

**MAJOR-R3 — arbiter substring matching is brittle**
- Replaced substring matching with a `_CATEGORY_SIGNALS` list of
  compiled regex patterns using word boundaries (`\bdestructive\b`,
  `\bunsafe\b`, etc.).
- Added `_has_negation` helper with a 20-char look-back window that
  checks for negation tokens (`not `, `no `, `non-`, `never `,
  `without `).
- Added `_has_affirmative_safety` fallback that recognises benign
  markers (`is safe`, `read-only`, `idempotent`, `no side effects`,
  `credentials env-var name` — the `lesson_patent_scrub` safe rewrite
  phrase).
- Four-way fallback decision:
  (1) explicit NONE → PROCEED,
  (2) negation-guarded safety match → BLOCK,
  (3) non-safety signal → REFINE,
  (4) no signal + affirmative marker → PROCEED,
  (5) no signal + no affirmative marker → REFINE (conservative default).
- All 4 false-positive phrases from the research review
  (`non-destructive`, `credentials env-var name`, `unsafe pattern we
  already fixed`, `ambiguous but safe`) now pass their regression
  tests.

**MINOR-R1** — documented (TB-F8 `mcp_dev_server.py` wiring is still a
v0.50.1 follow-up; snippet remains in
`.gcc/CHATAGENTLOOP-V4-COMPLETE.md`).

**MINOR-R4** — `graq_reason_batch` migration tracked as v0.50.1
optimization; no functional change.

**Security invariants added to debate.py**
- `tests/test_chat/test_debate.py` now asserts the module source
  contains no `import subprocess`, no `os.system`, no `os.environ`,
  no `os.getenv`, no legacy persona names at caps, and that every
  shipped prompt passes the banned-phrase guard.
- Added a secret-leakage test: a synthetic SECRET-like value in the
  question never appears in the streamed role outputs.

**Tests**
- `tests/test_chat/`: 214 → **236 passing** (added 22 new Round-1
  regression tests: 15 new debate.py cases, 7 new TCG cases)
- All 236 tests green in 1.28s

---

## v0.50.0 — 2026-04-11

**ChatAgentLoop v4 — Claude-Code-equivalent interactive chat layer (ADR-152).**

This is a feature jump (0.47.3 → 0.50.0) that ships the entire chat
agent loop the VS Code extension v0.6.0 will host: a three-graph
runtime architecture (GRAQ.md / TCG / RCAG), an LLM tool-use loop
that ranks over a TCG-activated subgraph instead of cold-picking from
~134 tools, durable pause/resume with CAS-locked state machine,
session-scoped permission caching, adversarial debate, polyglot
backend routing, hard-error continuation, and convention inference
as a first-class product feature. SDK-HF-01 (graq_generate missing
from generate-intent DAG) is structurally resolved — the extension's
dag.ts + intent.ts are deleted; tool selection moves to the SDK.

### Added
- **`graqle/chat/`** — new package, 8 SDK modules + 2 templates (~6500 LOC).
  - **`streaming.py`** (TB-F1) — ChatEvent envelope, ChatEventBuffer with
    monotonic per-turn sequencing, long-poll cursor helper.
  - **`turn_ledger.py`** (TB-F1) — append-only audit log at
    `.graqle/chat/ledger/turn_<id>.jsonl`.
  - **`settings_loader.py`** (TB-F1) — `.graqle/settings.json` policy
    loader with fail-closed jsonschema validation.
  - **`graq_md_loader.py`** (TB-F1) — multi-root GRAQ.md loader walking
    cwd UP to filesystem root, most-specific-wins conflict merge,
    user-content sandbox escaping.
  - **`templates/GRAQ_default.md`** (TB-F1) — built-in floor with 7
    scenario playbooks (codegen / debug / refactor / audit / review /
    write-new-artifact / convention-inference) + tool catalog.
  - **`tool_capability_graph.py`** (TB-F2) — `ToolCapabilityGraph`
    IS-A `Graqle` subclass with enrichment bypass, 30-tool/12-intent/
    5-workflow/20-lesson seed, intent classification + activation,
    edge reinforcement with [0.0, 10.0] clamp, probationary pattern
    mining (3 obs / 2 holdouts / 0.15 lift), 2-hop missing-edge
    prediction with destructive-edge safety filter, atomic save with
    .bak rollback.
  - **`templates/tcg_default.json`** (TB-F2) — canonical seed: 30 tools
    with governance tiers (GREEN/YELLOW/RED), 12 intents with keyword
    + preferred_sequence, 5 graduated workflow patterns including the
    `convention_inference` workflow that wires `graq_glob → graq_read
    → graq_write` for the `write-new-artifact` intent, 20 lessons,
    108 typed edges (MATCHES_INTENT / USED_AFTER / PART_OF /
    CAUSED_BY).
  - **`rcag.py`** (TB-F3) — `RuntimeChatActionGraph` IS-A `Graqle`,
    7 ephemeral node types (ToolCall, ToolResult, AssistantReasoning,
    GovernanceCheckpoint, DebateRound, ErrorNode, AttachmentContext),
    query augmentation with rolling 3-turn summary + partial
    reasoning, deterministic token-overlap activation fallback for
    unit tests (production wires through `_activate_subgraph(strategy
    ='chunk')`).
  - **`permission_manager.py`** (TB-F4) — `TurnState` enum, `TurnStore`
    with CAS state transitions under `asyncio.Lock`, idempotent
    resume via `tool_result_cache`, crash recovery via terminal
    tombstoning, `PermissionManager` with session-scoped cache keyed
    by `(tool_name, resource_scope, session_id)` plus revocation.
  - **`debate.py`** (TB-F5) — PROPOSER/ADVERSARY/ARBITER personas via
    `asyncio.gather` of three reason calls (will migrate to native
    `graq_reason_batch` now that CG-REASON-01 is fixed in v0.47.3),
    deterministic arbiter rule order safety > prerequisite > cost >
    ambiguity, max 2 rounds, debate chip streaming.
  - **`backend_router.py`** (TB-F6) — `BackendProfile`, `BackendRouter`,
    family detection by name prefix, 6 chat task types (chat_triage /
    chat_reasoning / chat_debate_proposer / chat_debate_adversary /
    chat_debate_arbiter / chat_format), family separation enforced
    only when 2+ families configured, minimal-polyglot degradation
    when only one backend is available.
  - **`agent_loop.py`** (TB-F7) — `ChatAgentLoop` integration point,
    10-step turn flow from ADR-152 §Decision, adaptive budget with
    burst override (25 → 100 ceiling), hard-error continuation via
    ErrorNode + synthetic tool_result, governance parallelism,
    pause/resume/cancel state transitions, CGI-compatible event
    emission shape (ADR-153 seed) so the future project-self-memory
    graph can fold turn events in via a classification pass.
  - **`mcp_handlers.py`** (TB-F8) — four chat handler functions
    (`handle_chat_turn`, `handle_chat_poll`, `handle_chat_resume`,
    `handle_chat_cancel`) that the MCP server will dispatch the
    `graq_chat_*` tools to. Kept in a separate module to minimize
    the hub-file edit surface in `mcp_dev_server.py` per
    CG-DIF-01/CG-DIF-02 — TB-N tracks the small registration block
    that wires them in.

### Tests
- **`tests/test_chat/`** — new directory, 214 tests passing in 1.29s.
  - test_streaming.py (TB-F1)
  - test_turn_ledger.py (TB-F1)
  - test_settings_loader.py (TB-F1)
  - test_graq_md_loader.py (TB-F1)
  - test_isolation.py (TB-F1; updated to allow the four shared core
    modules graqle.core.{graph,node,edge,types,message,state} for
    TB-F2 onward — everything else in graqle.core stays forbidden)
  - test_tool_capability_graph.py (TB-F2, 43 cases covering BLOCKER-1
    enrichment bypass / BLOCKER-2 single source of truth / MAJOR-2
    destructive-edge filter / MAJOR-3 probationary filter /
    MAJOR-4 atomic save rollback / MAJOR-5 negative paths /
    MINOR-1 weight clamp / MINOR-2 probation thresholds)
  - test_rcag.py (TB-F3, 19 cases)
  - test_permission_manager.py (TB-F4, 22 async cases)
  - test_debate.py (TB-F5, 15 cases including the deterministic rule
    order verification)
  - test_backend_router.py (TB-F6, 14 cases)
  - test_agent_loop.py (TB-F7, 11 async cases including the
    SDK-HF-01 structural regression guard
    `test_sdk_hf_01_codegen_picks_graq_generate` that asserts a
    codegen turn produces a tool_planned event for graq_generate
    AND the final turn_complete text contains a fenced python block)
  - test_mcp_handlers.py (TB-F8, 9 async cases)

### Hotfixes rolled into v0.50.0
- **CG-REASON-02** (v0.47.1) — BaseBackend deepcopy/pickle safety via
  `_TRANSIENT_BACKEND_ATTRS` drop on serialization, fixed the
  `cannot pickle '_thread.RLock' object` crash that was hard-downing
  every reasoning round on the openai backend.
- **SDK-HF-02** (v0.47.2) — synthesis truncation regression fixed via
  the new `generate_with_continuation` helper extracted from
  `CogniNode.reason` into `graqle/core/node.py`. The
  `Aggregator._weighted_synthesis` path now recovers from
  `stop_reason=max_tokens` the same way per-node responses do.
  CogniNode.reason() keeps its inline copy of the loop untouched
  (deferred to CG-OT028-01 follow-up).
- **CG-REASON-01** (v0.47.3) — `areason_batch` error fallback fixed via
  the new module-level `_make_error_result(query, exc)` helper that
  builds a valid `ReasoningResult` with all required fields plus
  `backend_status="failed"` / `backend_error` / `reasoning_mode=
  "error"`. Unblocks the native batch reasoning path for the
  ChatAgentLoop debate subsystem.

### Notes
- **SDK-HF-01 structurally resolved.** The extension's `dag.ts` +
  `intent.ts` are obsoleted by the SDK-side TCG. The LLM picks tools
  from a pre-activated TCG subgraph that puts `graq_generate` at
  position #2 (score 1.635) for `write a Python function...` queries
  on day one of the seed, before any user reinforcement. Verified
  by the `test_sdk_hf_01_codegen_picks_graq_generate` regression
  guard.
- **Convention inference is a first-class product feature.** The TCG
  ships with a `workflow_convention_inference` graduated workflow
  pattern wiring `graq_glob → graq_read → graq_write` for the
  `intent_write_new_artifact` intent. The built-in GRAQ.md template
  has a `## Scenario: write-new-artifact` playbook encoding the
  same behavior in natural language.
- **CGI-compatible event emission shape (ADR-153 seed).** Every
  ChatAgentLoop event carries the structural fields a future
  Cognigraph Implementation Graph would need (turn_id, session_id,
  parent_id, tool_name, status, latency_ms, debate_verdict,
  debate_reason, governance_tier, governance_decision). The
  ADR-153 design session (post-v0.50.0) can decide whether to fold
  terminal turn events into a persistent project-self-memory graph
  via a classification pass. No CGI node types or edge schemas are
  implemented in v0.50.0 — ADR-153 ships in v0.51.0 as a separate
  design wave.
- **Source-level isolation rule narrowed.** `tests/test_chat/
  test_isolation.py` now allows the chat package to import from
  `graqle.core.{graph,node,edge,types,message,state}` (the
  legitimate shared core); everything else in `graqle.core` /
  `graqle.backends` / `graqle.orchestration` / `graqle.reasoning` /
  `graqle.intelligence` / `graqle.plugins` / `graqle.connectors`
  stays forbidden. Source-level scan pattern per
  lesson_20260411T081005.
- **Test counts at ship time:**
  - tests/test_chat/: 214 passing in 1.29s (the v4 chat layer)
  - tests/test_backends/test_base_serialization.py: 9 (CG-REASON-02)
  - tests/test_core/test_continuation.py: 19 (SDK-HF-02 helper)
  - tests/test_core/test_areason_batch.py: 9 (CG-REASON-01)
  - tests/test_orchestration/test_aggregation.py: 7 (SDK-HF-02 wiring)
- **TB-F8 hub-file wiring deferred.** The four `mcp_handlers.handle_chat_*`
  functions are ready and tested standalone. The actual registration
  block in `graqle/plugins/mcp_dev_server.py` (8609 lines, impact
  radius 491) will be a small follow-up edit applied via
  `graq_apply` per the CG-DIF-02 hub-file safety rule. See
  `.gcc/CHATAGENTLOOP-V4-COMPLETE.md` for the registration snippet.
- **PyPI publish + git tag pending operator approval.** The build is
  staged at v0.50.0 but `python -m build && twine upload` is not
  run automatically.

---

## v0.47.3 — 2026-04-11

### Fixed
- **CG-REASON-01 (HIGH): `graq_reason_batch` constructor crash** in `graqle/core/graph.py:areason_batch` error fallback. The previous code constructed a `ReasoningResult` with `node_count=0` (a read-only `@property`, not a constructor field) and was missing three required fields: `query`, `active_nodes`, `message_trace`. The error branch also iterated `results` without zipping `queries`, so the failing query string was lost. Fix: extracted the fallback into a new module-level helper `_make_error_result(query, exc) -> ReasoningResult` that constructs the dataclass with all required fields plus `backend_status="failed"`, `backend_error=str(exc)`, `reasoning_mode="error"` so downstream consumers can branch on the failure without parsing the answer string. The loop now uses `for q, r in zip(queries, results)` with a defensive length-check guard. Logging is `str(q)[:80]` to handle non-string queries safely. This unblocks the native batch reasoning path; the ChatAgentLoop v4 adversarial debate subsystem can now use `graq_reason_batch` directly instead of falling back to serial `asyncio.gather` of 3 `graq_reason` calls.

### Added
- **`graqle.core.graph._make_error_result`** — module-level helper that builds a valid error-fallback `ReasoningResult`. Reusable by any caller that needs to construct an error result consistently.
- **9 regression tests** in `tests/test_core/test_areason_batch.py`:
  - 4 helper tests: TypeError-free construction, all required fields populated, `node_count` property accessibility, `confidence=0.0` warning emission as failure telemetry
  - 1 mixed-batch test: success and failure interleaved, result count == query count, query strings preserved
  - 1 all-fail batch test: every query fails, every result is an error fallback
  - 1 downstream consumer compatibility test: error result is consumable through the exact field-access pattern used by `mcp_dev_server._handle_reason_batch` (`.answer`, `.confidence`, `.node_count`, `.cost_usd`, `.reasoning_mode`)
  - 1 empty batch test
  - 1 single-query failure test

### Notes
- Pre-implementation `graq_reason` (96% confidence) chose Option B (helper function) over Option A (inline minimal patch) and Option C (changing the dataclass contract).
- Pre-implementation `graq_review` (86% confidence) returned CHANGES_REQUESTED with 1 BLOCKER + 4 MAJORs + 2 MINORs — all folded into the implementation including dataclass-signature verification, `zip` length-check guard, downstream-consumer test, and test consolidation from 6 cases to 4.
- Post-implementation `graq_review` on the diff (89% confidence) flagged 2 MAJORs + 1 MINOR. The unsafe `q[:80]` was fixed via `str(q)[:80]`. The `_make_error_result` constructor concern was already validated by 9 passing tests and the smoke test. The "redundant length check" stays as defensive code with `# pragma: no cover`.
- Post-implementation broader `graq_review` on `graqle/core/graph.py` flagged 1 BLOCKER + 5 MAJORs on **pre-existing code** (`_release_lock`, `_validate_graph_data`, `reclassify_batch`, etc.) — out of scope for CG-REASON-01 and logged for follow-up.
- Test suite: 67 passed in 7.75s (9 new areason_batch + 19 continuation + 7 aggregation + 5 node + 18 graph + 9 base serialization). This is the cumulative test set across TB-H1, TB-H2, TB-H3 — zero regressions.
- All 3 blocking hotfixes (CG-REASON-02, SDK-HF-02, CG-REASON-01) are now shipped. The ChatAgentLoop v4 build track (TB-F1 → TB-F9) is unblocked.

---

## v0.47.2 — 2026-04-11

### Fixed
- **SDK-HF-02 (HIGH): synthesis truncation regression** in `graqle/orchestration/aggregation.py:_weighted_synthesis`. Synthesis was making a single `backend.generate(prompt, max_tokens=4096)` call and silently returning the (possibly truncated/empty) result whenever `stop_reason=max_tokens`. Multi-agent reasoning rounds were getting partial answers with `confidence_unreliable=True` set silently. The fix introduces a new shared `generate_with_continuation` helper in `graqle/core/node.py` (alongside the existing OT-028 helpers `_extract_overlap_anchor` / `_build_continuation_prompt` / `_deduplicate_seam`) and uses it from `_weighted_synthesis`. The helper preserves all OT-028 invariants: empty-anchor abort, zero-progress guard via content-identity check, seam deduplication, fail-open on mid-loop exception. The first `backend.generate()` call propagates exceptions unchanged; only continuation-round exceptions surface via `metadata["continuation_error"]`. `max_tokens` stays at 4096 — raising to 8192 (per `lesson_20260407T065640`) is a separate tuning decision deferred until measurement shows persistent truncation.
- **`_normalize_response` defensive guards** for `.text=None`, `.truncated=None`, `.stop_reason=None` shapes from non-conforming backends.

### Added
- **`graqle.core.node.generate_with_continuation`** — reusable async helper that any caller can use against any `BaseBackend`. Returns `(text, metadata)` where metadata has `continuation_count`, `was_continued`, `still_truncated`, `stop_reason`, `continuation_error` keys with a fully documented contract for every exit path.
- **`graqle.core.node._normalize_response`** — adapter that handles `GenerateResult` / raw `str` / malformed shapes with defensive logging.
- **19 regression tests** in `tests/test_core/test_continuation.py` covering every helper exit path: clean, recovery, empty-anchor abort, zero-progress, exhaustion, mid-loop fail-open, raw str input, malformed input, max_continuations=0, partial-overlap seam, initial-call exception propagation, mixed return types, arg passthrough, plus 5 normalizer cases including the post-impl review's None-text guard.
- **7 regression tests** in `tests/test_orchestration/test_aggregation.py` covering `_weighted_synthesis`: clean synthesis, truncation recovery (the headline SDK-HF-02 fix), exhaustion, max_tokens=4096 regression assertion, trunc_info shape preservation, initial-call exception propagation, and continuation_error fail-open with log assertion.

### Notes
- Pre-implementation `graq_reason` (94% confidence) chose Option B (shared helper extraction) over copy-paste duplication and per-backend method approaches.
- Pre-implementation `graq_review` round 1 (92% confidence) returned CHANGES_REQUESTED with 4 MAJORs — all folded into a revised plan that eliminated the highest-risk concerns (OT-028 metadata regression, re-export safety) by NOT moving the existing helpers and NOT refactoring `reason()`.
- Pre-implementation `graq_review` round 2 (86% confidence) returned CHANGES_REQUESTED with 4 more MAJORs on the revised plan (exception contract, metadata contract, normalize observability, aggregation error handling) — all folded into the final spec before any code was written.
- Post-implementation `graq_review` (86% confidence) flagged 1 BLOCKER + 4 MAJORs on **pre-existing `reason()` code** (not the new helper) plus 1 MAJOR on the new `_normalize_response` (None handling). The `_normalize_response` MAJOR was fixed immediately. The 5 pre-existing `reason()` issues are logged as **CG-OT028-01** in `.gcc/OPEN-TRACKER-CAPABILITY-GAPS.md` for follow-up — they are real but out of scope for SDK-HF-02 which targets synthesis, not per-node reasoning.
- `core/node.py:reason()` is **NOT** modified in this hotfix. Zero regression risk on the per-node reasoning path. Verified: 5/5 pre-existing tests in `test_node.py` pass.
- Test suite: 58 passed in 5.31s (19 continuation + 7 aggregation + 5 node + 18 graph + 9 base serialization).
- Knowledge nodes added to KG: `knowledge_technical_20260411T070209` (Option B validation), `knowledge_technical_20260411T070448` (design refinement v2), `knowledge_technical_20260411T070606` (design refinement v3 with exception contract).

---

## v0.47.1 — 2026-04-11

### Fixed
- **CG-REASON-02 (CRITICAL): backend pickling crash** in `graqle/backends/base.py` — `BaseBackend` now provides `__getstate__`, `__setstate__`, and `__deepcopy__` that drop transient runtime handles (`_client`, `_async_client`, `_session`, `_executor`, `_loop`, `_lock`) on serialization. Previously, `copy.deepcopy(node)` at the three ADR-151 redaction-snapshot sites in `graqle/core/graph.py` (lines 1520, 1681, 344) would crash with `TypeError: cannot pickle '_thread.RLock' object` after a node had been activated with a backend whose lazy `_client` (e.g. `AsyncOpenAI` holding an `httpx.AsyncClient`) had been instantiated. The fix is backend-agnostic — all 14 providers inherit it through `BaseBackend` — and side-effect free with respect to the source instance, so concurrent reasoning rounds sharing one backend reference each get an isolated copy. Documented serialization contract added to `_TRANSIENT_BACKEND_ATTRS`.

### Added
- **8 regression tests** in `tests/test_backends/test_base_serialization.py` covering all four review-mandated scenarios:
  1. `copy.deepcopy(backend)` after lazy `_client` populated
  2. `pickle.dumps`/`loads` round-trip preserves durable config
  3. ADR-151 simulation: deepcopying a node that holds an activated backend
  4. Concurrent shared-backend isolation (two snapshots from one source backend stay independent)

  Plus a real `OpenAIBackend` smoke test that confirms the abstract-base fix flows through to the concrete provider class, a contract test on `_TRANSIENT_BACKEND_ATTRS`, and a subclass-extension test showing how a future provider with a new transient handle can override `__getstate__`.

### Notes
- Discovered live during the 2026-04-11 ChatAgentLoop v4 design session (12 reasoning rounds). Crash hard-downed `graq_reason`, `graq_reason_batch`, `graq_predict`, and `graq_review` after the first successful round on `openai:gpt-5.4-mini`. Required mid-session VS Code reload to clear.
- Pre-implementation `graq_review(spec=...)` returned CHANGES_REQUESTED (86% confidence) with 4 MAJOR concerns: serialization contract, concurrency safety, end-to-end coverage, test breadth. All four were folded into the implementation before any code was written. The post-implementation review on the diff is pending.
- This unblocks the entire ChatAgentLoop v4 implementation track (TB-H1 → TB-H2 → TB-H3 → v0.50.0).
- Test suite: 8 passed in 0.11s.

---

## v0.47.0 — 2026-04-10

### Added
- **`graq_apply` MCP tool (CG-DIF-02)** — first-class deterministic insertion engine. A governed alternative to `graq_edit` for files where LLM-generated diffs are unreliable: CRITICAL hub modules (impact_radius > 20), large files (> 1500 lines), files with multiple lookalike methods. The tool eliminates the LLM from the diff loop — callers provide exact byte-string anchors and replacements, the engine performs Python's deterministic `bytes.replace()` and atomic write. Anchor uniqueness is enforced (each anchor must occur exactly `expected_count` times, default 1). Atomic write via tempfile + fsync + os.replace. Backup to `.graqle/edit-backup/` before write. ~50x faster than `graq_edit` on hub files (no LLM round-trip). Implements all 9 rails of the Deterministic Insertion Pattern (baseline, validation, uniqueness, replace, post-replacement invariants, atomic write, post-write verify, backup, rollback).
- **8 stable error codes** for `graq_apply`: `GRAQ_APPLY_FILE_NOT_FOUND`, `GRAQ_APPLY_SHA_MISMATCH`, `GRAQ_APPLY_ANCHOR_NOT_FOUND`, `GRAQ_APPLY_ANCHOR_NOT_UNIQUE`, `GRAQ_APPLY_BYTE_DELTA_OUT_OF_BAND`, `GRAQ_APPLY_MARKER_COUNT_MISMATCH`, `GRAQ_APPLY_POST_WRITE_VERIFY`, `GRAQ_APPLY_INVALID_INSERTION`. Callers know exactly what failed and can recover.
- **27 pytest tests** for `graq_apply` covering all 9 rails, every error code, multi-insertion sequencing, and byte-for-byte unchanged-region preservation.
- **`kogni_apply` alias** for `graq_apply` (backward-compat with the kogni_* naming).

### Notes
- This release fixes the underlying root cause of the multiple `graq_edit` failures observed during the v0.46.9 hotfix on `graqle/core/graph.py`. Other projects (Studio, CrawlQ) hitting the same pattern can now use `graq_apply` directly.
- `graq_apply` was used to register itself in `graqle/plugins/mcp_dev_server.py` and to update the `test_expected_tool_names` test — full dogfooding before ship.
- Test suite: 73 passed in 0.47s combined (`test_graq_apply.py` 27 + `test_mcp_dev_server.py` 46).

## v0.46.9 — 2026-04-10

### Fixed
- **OT-060: NEO4J_DISABLED env var gate** in `graqle/core/graph.py` — `Graqle.from_neo4j()` and `Graqle.to_neo4j()` now respect the `NEO4J_DISABLED` env var (truthy: `1`, `true`, `yes`, `on`). When set, both methods raise `RuntimeError` BEFORE importing `Neo4jConnector` or dialing `bolt://`. Zero dials, zero retries. Existing caller `try/except → JSON fallback` contract preserved. Unblocks VS Code MCP server, CI jobs, and Lambda hosts that cannot tolerate slow bolt handshakes. **Neo4j remains a first-class power-user feature** — this is a per-process override, not a feature removal. Once-per-process WARNING via module-level sentinel. 6 new tests in `TestNeo4jDisabledEnvVar`.
- **OT-062: Session-scoped MCP gate bypasses for graqle-vscode** in `graqle/plugins/mcp_dev_server.py` — the `initialize` JSON-RPC handler now reads `clientInfo.name` and, when it equals `"graqle-vscode"`, sets per-instance `_cg01_bypass`, `_cg02_bypass`, `_cg03_bypass` flags. The CG-01 (session_started), CG-02 (plan_active), and CG-03 (edit_enforcement) gates honor these flags. State is naturally session-scoped because each `KogniDevServer` instance is one MCP stdio process; concurrent non-graqle-vscode clients run in their own instances and are unaffected. **Fail-closed default**: missing or unrecognized `clientInfo` → gates remain ON. 5 new tests in `TestInitializeClientInfoBypass`.
- **OT-061: S3 AccessDenied dedupe** in `graqle/core/kg_sync.py` — added `_is_access_denied()`, `_log_s3_error()`, `_reset_access_denied_dedupe()` helpers and a module-level `_access_denied_logged` sentinel. AccessDenied errors are now logged ONCE per process at WARNING; non-AccessDenied S3 errors continue to log at ERROR per occurrence. Replaces 3 noisy `logger.warning` sites in `pull_if_newer` and `_push_worker`. 5 new tests in `TestAccessDeniedDedupe`, including the headline test "10 AccessDenied errors → 1 log line".

### Notes
- 16 new tests added across `test_graph.py`, `test_mcp_dev_server.py`, and `test_kg_sync.py`. All 91 pre-existing tests continue to pass (107 total green, zero regressions).

## v0.40.7 — 2026-04-02

### Fixed
- **4 BLOCKERs + 3 MAJORs in debate_evidence.py** — found by `graq_review` dogfooding. Includes type safety, edge case handling, and error propagation fixes.

---

## v0.40.6 — 2026-04-02

### Fixed
- **4 wrong class names in debate_evidence.py** — import references corrected. All 10 research module imports now pass.
- KG stats updated after incremental rescan.

---

## v0.40.5 — 2026-04-01

### Fixed
- **OT-018: File reader truncation** — `graq_read` default limit raised from 200 to 500 lines. `max_chunks` raised from 5 to 15.
- **Windows env var fallback** — `_get_env_with_win_fallback()` reads Windows Credential Manager when environment variables are absent.

---

## v0.40.4 — 2026-04-01

### Added
- **R15 Multi-Backend Debate** — optional multi-LLM debate mode (`mode=off|debate|ensemble`). Governance-first design with cost ceiling, audit events, and TS-2 clearance. 4 patent claims (R11-R14).
  - `DebateConfig` in settings.py with panelist validation
  - `DebateTrace` / `DebateTurn` dataclasses in types.py
  - GPT-5.4 cost entries in OpenAI backend
  - 3 live OpenAI debate evidence runs completed

### Fixed
- **6 trade secret violations** remediated from research team review (3-round PR process).
- Test constant `decay_factor=0.75` replaced with `_TEST_DECAY` to avoid coinciding with internal values.

---

## v0.40.3 — 2026-04-01

### Added
- **R11 Confidence Calibration** — 200-question benchmark (7 confidence bands), ECE/MCE/Brier metrics, temperature/Platt/isotonic calibration, CalibrationWrapper. ADR-138.

---

## v0.40.1 — 2026-03-31

### Added
- **Research Sprint Complete** — R2 Bridge Edges, R3 MCP Domain, R5 Cross-Language Linker, R6 Learned Intent, R9 Federated Activation, R10 Embedding Alignment. 7 specs, 8 patent claims.

### Fixed
- IP Protection Gate live (ADR-140). HMAC rotated, TS-1..TS-6 externalized, branch protection enforced.

---

## v0.39.0 — 2026-03-28

### Added
- **ADR-123 KG Sync** — 6-phase S3 pull-before-read + push-after-write. Makes S3 single source of truth. 35 tests.

---

## v0.38.0 — 2026-03-27

### Added
- **Phase 10 SOC2/ISO27001 Compliance** — 5-layer governance gate, 201-pattern secret scanner, RBAC actor identity, policy DSL, adversarial test suite. 303 tests.

---

## v0.35.4 — 2026-03-26

### Fixed
- **Auto-grow hook now installed on `graq scan repo`** — previously the post-commit git hook
  that keeps the KG in sync with every commit was only installed by `graq init`. Public users
  who ran `graq scan repo .` directly never got the hook, causing their graph to go stale after
  commits. The hook is now silently installed at the end of every `graq scan repo` run.
  (`graqle/cli/commands/scan.py`)

---

## v0.35.1 — graq_predict v1.4 Hotfix + PSE Sprint (2026-03-26)

**Unblocks `fold_back=True`.** Two blocking bugs in `graq_predict` meant the core write-back mechanism never worked in v0.34.0. Both are now fixed. Four additional improvements ship in the same release.

### Fixed (v1.4 Hotfix — BLOCKING)

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| `fold_back=True` always returned `SKIPPED_GENERATION_ERROR` | `areason()` calls `node.deactivate()` which sets `node.backend = None` before returning. The backend lookup loop always found `None`. | Replaced loop with `_get_backend_for_node(active_nodes[0], task_type="predict")` — uses 3-tier task routing, never returns `None` silently. |
| JSON extraction raised `re.error: unterminated character set` on LLM outputs containing `[`, `(`, or `*` in string values | `re.search(r"\{.*\}", raw, re.DOTALL)` crashes on regex metacharacters inside JSON string values | Added `_extract_json_from_llm()` module-level helper using brace-counting + trailing-comma strip. Handles all valid JSON regardless of string content. |

### Improved (v0.35.0 Sprint)

**`graq rebuild --re-embed` safety gate** (`graqle/core/graph.py`)
- Added `skip_validation=False` parameter to `Graqle.from_json()`. Default `False` — all existing callers unchanged.
- When `re_embed=True`, rebuild loads graph with `skip_validation=True` to bypass the embedding dimension check that would otherwise block recovery.

**Stricter agreement threshold** (`graqle/plugins/mcp_server.py`)
- Internal agreement threshold raised to reduce false write-backs caused by boilerplate token overlap between node responses.

**Embedding model transparency** (`graqle/plugins/mcp_server.py`)
- `graq_predict` output now includes `"embedding_model": "<model-name>"` field. Lets callers detect mid-session model changes that would cause a dimension mismatch on subsequent graph loads.

**`graq predict` CI gate** (`graqle/cli/main.py`)
- `--fail-below-threshold` exits with code 1 when `answer_confidence < confidence_threshold`. Use in GitHub Actions to gate deployments on reasoning confidence.
- Example:
```yaml
- name: graq_predict deployment gate
  run: |
    graq predict "$(git diff HEAD~1 --stat | head -20)" \
      --no-fold-back \
      --confidence-threshold 0.80 \
      --fail-below-threshold
```

### Patent Notice

European Patent **EP26167849.4** was filed 2026-03-25. The following features are patent-protected:
- `fold_back=True` confidence-gated graph write-back
- `_compute_answer_confidence()` cross-node agreement scoring
- Two-stage deduplication (content hashing + semantic similarity)
- `graq predict --fail-below-threshold` CI gate
- STG 4-class hierarchy + fold-back disable mode

### Files Changed

- `graqle/plugins/mcp_server.py` — FB-004 fix, FB-005 fix, stricter agreement threshold, `_get_active_embedding_model()`, `embedding_model` output field
- `graqle/core/graph.py` — `skip_validation` parameter on `from_json()`
- `tests/test_plugins/test_mcp_server.py` — 11 new tests (3 v1.4 hotfix + 8 v0.35.0)
- `tests/test_plugins/test_mcp_predict.py` — wired `_get_backend_for_node` in mock graph fixture

---

## v0.33.1 — Fix: Hardcoded US Bedrock Model IDs Break Non-US Users (2026-03-22)

**P1 Security/Config Fix.** Phantom Vision and SCORCH Visual audit were completely broken for any user in a non-US AWS region (eu-central-1, eu-west-1, ap-northeast-1, etc.) due to hardcoded `us.anthropic.*` model IDs.

### Fixed

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| `ValidationException: The provided model identifier is invalid` on all Vision calls | `us.anthropic.claude-sonnet-4-6-20250514-v1:0` hardcoded in 4 files | Dynamic region resolution from `graqle.yaml` → `model.region` |
| `us.anthropic.claude-opus-4-6-20250514-v1:0` invalid even in US | Versioned Opus 4.6 ID doesn't exist | Changed to `{prefix}.anthropic.claude-opus-4-6-v1` |
| SCORCH default_config.json hardcoded to US | Template shipped with `us-east-1` | Empty defaults → auto-resolved at runtime |

### How It Works Now

Phantom and SCORCH configs auto-resolve Bedrock model IDs at runtime:
1. Read `model.region` from `graqle.yaml` (same as reasoning engine)
2. Fall back to `AWS_DEFAULT_REGION` or `AWS_REGION` env var
3. Derive region prefix: `eu-*` → `eu.`, `us-*` → `us.`
4. Build model ID: `{prefix}.anthropic.claude-sonnet-4-6`

No hardcoded model IDs remain in the plugin configs.

### Files Changed

- `graqle/plugins/phantom/config.py` — Added `_detect_region()`, `_resolve_vision_model()`, auto-resolution in `BedrockConfig.model_post_init()`
- `graqle/plugins/phantom/core/analyzer.py` — Removed hardcoded fallbacks, uses resolver
- `graqle/plugins/scorch/config.py` — `BedrockConfig.model_post_init()` delegates to phantom resolver
- `graqle/plugins/scorch/templates/default_config.json` — Empty defaults (resolved at runtime)

### Lesson Learned

> **NEVER hardcode region-prefixed Bedrock model IDs.** Always derive the prefix from the user's configured region. Hardcoded `us.` model IDs silently break ALL non-US users with a confusing `ValidationException` that appears to be an AWS issue, not a GraQle bug. This was recorded as a KG lesson (`lesson_20260322T210920`).

---

## v0.33.0 — Zero-Friction Install: Auto-Cache, Smart Venv Detection, Security Hardening (2026-03-22)

**Addresses community feedback on first-run experience.** Eliminates the #1 pain point (slow queries without embedding cache) and prevents virtualenv pollution, API key leaks, and silent init failures.

### Fixed

| Issue | What Changed |
|-------|-------------|
| **Embedding cache not auto-built** (CRITICAL) | `graq scan repo .` now auto-builds `.graqle/chunk_embeddings.npz` after scanning. No more manual `graq rebuild --embeddings` step. Queries go from ~30s to <1s automatically. |
| **Virtual environments scanned** | Scanner now auto-detects venvs by `pyvenv.cfg` marker file + name suffixes (`*_env`, `*-env`, `*_venv`, `*-venv`). Catches arbitrarily-named venvs like `yugyog_env/`. |
| **API keys at risk of git commit** | `graq init` now auto-adds `graqle.yaml` and `.graqle/` to `.gitignore`. Prevents accidental plaintext API key leaks. |
| **Silent init failure** | `graq init` now shows a yellow warning panel (not green success) when the graph has 0 nodes, with guidance on how to fix it. |
| **Doc scanner venv pollution** | Document scanner (`graq scan docs`) now excludes `env/`, `.conda/`, `site-packages/`, and venvs detected by suffix/marker. |

### Technical Details

- **scan.py**: Added `_is_virtualenv()` function with `pyvenv.cfg` detection + `_VENV_SUFFIXES` matching. Added auto-build cache block with `try/except` fallback.
- **docs.py**: Extended skip-names set and added suffix-based venv detection in `os.walk` loop.
- **init.py**: Added `.gitignore` auto-update after `graqle.yaml` creation. Added conditional success/warning panel based on `node_total`.
- **No API changes.** All fixes are in CLI commands — SDK API is untouched.

### Impact

- 168 tests pass (4 pre-existing patent-stub failures unchanged)
- E2E validated: fresh repo with fake venvs, binary files, edge-case code → clean 18-node graph
- Backward compatible — no breaking changes

---

## v0.31.3 — SCORCH Extended Skills: 10 New Audit Modules (2026-03-20)

**SCORCH v3 grows from 3 to 13 specialized audit skills.** Each skill is available as an MCP tool, CLI command, and Python SDK method.

### New Skills

| Skill | What It Audits |
|-------|----------------|
| `graq_scorch_a11y` | WCAG 2.1 AA/AAA: contrast, aria-labels, focus order, headings, landmarks |
| `graq_scorch_perf` | Core Web Vitals: LCP, CLS, FID, render-blocking, DOM size, images |
| `graq_scorch_seo` | Meta tags, Open Graph, Twitter Cards, JSON-LD, canonical, heading hierarchy |
| `graq_scorch_mobile` | Touch targets (44px), viewport, text readability, horizontal scroll, pinch-zoom |
| `graq_scorch_i18n` | html lang, RTL support, hardcoded strings, date/currency formatting |
| `graq_scorch_security` | CSP headers, exposed API keys (13 patterns), XSS, mixed content, HSTS |
| `graq_scorch_conversion` | CTA inventory/placement, form quality, trust signals, pricing clarity |
| `graq_scorch_brand` | Color palette compliance, typography, spacing, button/heading uniformity |
| `graq_scorch_auth_flow` | Login/signup/dashboard flows, auth vs unauth comparison |
| `graq_scorch_diff` | Before/after report comparison: resolved/new/persistent issues, improvement % |

### CLI

All skills available via `graq scorch <skill>`:
```bash
graq scorch a11y --url http://localhost:3000 --page / --page /pricing
graq scorch security --url https://myapp.com
graq scorch diff --previous ./old-report.json
```

### MCP

56 total tools (29 `graq_*` + 27 `kogni_*` aliases). All new skills auto-generate `kogni_scorch_*` backward-compatible aliases.

### Tests

**1,657 tests passing.** No regressions.

### Files Changed

| File | Change |
|------|--------|
| `graqle/plugins/scorch/phases/a11y.py` | NEW — Accessibility audit |
| `graqle/plugins/scorch/phases/perf.py` | NEW — Performance audit |
| `graqle/plugins/scorch/phases/seo.py` | NEW — SEO audit |
| `graqle/plugins/scorch/phases/mobile.py` | NEW — Mobile audit |
| `graqle/plugins/scorch/phases/i18n.py` | NEW — i18n audit |
| `graqle/plugins/scorch/phases/security.py` | NEW — Security audit |
| `graqle/plugins/scorch/phases/conversion.py` | NEW — Conversion funnel analysis |
| `graqle/plugins/scorch/phases/brand.py` | NEW — Brand consistency audit |
| `graqle/plugins/scorch/phases/auth_flow.py` | NEW — Auth flow audit |
| `graqle/plugins/scorch/phases/diff.py` | NEW — Before/after comparison |
| `graqle/plugins/scorch/engine.py` | Added 10 `run_*()` methods |
| `graqle/plugins/mcp_dev_server.py` | Added 10 tool definitions + 10 handlers |
| `graqle/cli/commands/scorch.py` | Added 10 CLI subcommands |
| `README.md` | Updated SCORCH CLI reference + MCP tools table |

### Breaking Changes

None. All changes are additive.

---

## v0.31.2 — Codex Audit Fixes: Observability, Smoke Tests, Windows Robustness (2026-03-20)

**Community-reported issues validated and fixed.** The Codex team tested graqle==0.31.1 on Windows Python 3.10 and reported 10 issues. We validated each against the actual codebase — 7 confirmed real, 2 were design decisions (patent stubs), 1 was false (no encoding artifacts). This release fixes the 5 zero-regression-risk items.

### New: `graq config` command

See your fully resolved configuration at a glance — backend, model, routing rules, graph connector, embeddings, cost budget. No more guessing what GraQle will use at runtime.

```bash
graq config              # Rich formatted output
graq config --json       # Machine-readable for CI/scripting
```

**File:** `graqle/cli/commands/config_show.py` (NEW)

### Enhanced: `graq doctor` reasoning smoke test

Doctor now verifies that your graph file actually loads and is ready for reasoning — not just that config files exist. Catches the case where `graq doctor` passes but `graq run` fails because the graph is empty or corrupt.

```
OK   Smoke: graph loads    396 nodes from graqle.json — ready for reasoning
```

**File:** `graqle/cli/commands/doctor.py` — added `_check_reasoning_smoke()`

### Fixed: Windows file lock fd leak

The Windows `msvcrt.locking()` retry path in `_acquire_lock()` could leak a file descriptor if all 10 lock attempts failed. Now wrapped in `try/except BaseException` to guarantee `fd.close()` on any failure path.

**File:** `graqle/core/graph.py` lines 43-57

### New: Fresh-install smoke test in CI

Added a `smoke` job to GitHub Actions that builds the wheel from source and installs it in a clean environment (no editable install, no dev deps). Runs on both Ubuntu and Windows. Validates `graq --version`, `graq --help`, `graq doctor`, and `graq config`.

**File:** `.github/workflows/ci.yml` — added `smoke` job

### Docs: Config field names + Bedrock auth clarification

- **Config fields:** Routing uses `default_provider` / `default_model` (not `fallback_*`). Added note in README.
- **Bedrock auth:** Documented that AWS Bedrock uses the standard boto3 credential chain (env vars, `~/.aws/credentials`, SSO, instance profiles). No GraQle-specific profile config needed.
- **CLI reference:** Added `graq config` and `graq config --json` to the command table.

### Codex Audit — Full Validation Matrix

| # | Reported Issue | Verdict | Action |
|---|----------------|---------|--------|
| 1 | Empty modules in wheel | Design — patent stubs | No change needed |
| 2 | Missing ConstraintGraph, PCSTActivation | Design — unreleased IP | No change needed |
| 3 | fallback_* config keys missing | Misidentified — fields are `default_*` | Docs clarified |
| 4 | Bedrock auth/profile implicit | True — implicit via boto3 | Docs clarified |
| 5 | Doctor passes but run fails | **Fixed** | Smoke test added |
| 6 | No fresh-venv smoke suite | **Fixed** | CI smoke job added |
| 7 | Windows fd leak in file lock | **Fixed** | `fd.close()` guaranteed |
| 8 | Encoding artifacts | False — no mojibake found | No change needed |
| 9 | No circuit-breaker on Bedrock | True — deferred to v0.32 | Tracked |
| 10 | Config-to-runtime observability | **Fixed** | `graq config` command |

### Tests

**1,700+ tests passing.** No regressions from v0.31.1.

### Files Changed

| File | Change |
|------|--------|
| `graqle/cli/commands/config_show.py` | NEW — `graq config` / `graq config --json` |
| `graqle/cli/commands/doctor.py` | Added `_check_reasoning_smoke()` |
| `graqle/cli/main.py` | Registered `config` command |
| `graqle/core/graph.py` | Fixed Windows fd leak in `_acquire_lock()` |
| `.github/workflows/ci.yml` | Added `smoke` job (Ubuntu + Windows) |
| `README.md` | Config field docs, Bedrock auth, CLI reference |

### Breaking Changes

None. All changes are additive or fix-only.

---

## v0.31.1 — GraQle Branding (2026-03-20)

- Capital Q branding applied across 134 files (Graqle → GraQle in prose/docstrings/console output)
- No code logic changes — branding only

---

## v0.31.0 — Adoption Friction Fixes (2026-03-20)

**5 real-world adoption issues fixed in one release:**

1. **`[all]` extras fixed for Windows** — removed `gpu`/`vllm` from `[all]`, added `[all-gpu]` for GPU users
2. **Upper-bound pins** — `sentence-transformers<3.0`, `torch<2.5`, `transformers<4.50`, `peft<0.14`
3. **`graq migrate` command** — renames `cognigraph.yaml/json` → `graqle.yaml/json`, updates CLAUDE.md and `.mcp.json`
4. **kogni_ → graq_ in AI instructions** — 45 tool name references updated in init.py
5. **PATH fallback in README** — `python -m graqle.cli.main mcp serve` for when `graq` isn't on PATH
6. **`graq doctor` PATH check** — warns if `graq` binary isn't on PATH with MCP fallback suggestion

### Tests

**1,700+ tests passing.**

---

## v0.29.0 — Cloud Sync + Multi-Project Dashboard (2026-03-17)

**Push your knowledge graph to GraQle Cloud. View it anywhere. Share with your team.**

The cloud release: `graq cloud push` sends your knowledge graph to [graqle.com/dashboard](https://graqle.com/dashboard). Pull it on any machine. See all your projects in one control plane.

### Cloud CLI (`graq cloud`)

New command group for managing your knowledge graph in the cloud:

```bash
graq login --api-key grq_your_key    # Connect (get key at graqle.com/account)
graq cloud push                       # Upload graph + scorecard + intelligence
graq cloud pull                       # Download graph to any machine
graq cloud status                     # List cloud projects + connection info
```

- **Auto-detects project name** from `graqle.yaml`, `package.json`, `pyproject.toml`, or directory name
- **Uploads to S3** at `graphs/{email_hash}/{project}/` — graqle.json, scorecard, insights, metadata
- **Neptune sync** for Team tier — graphs synced to production Neptune for cross-project queries
- **Pull** downloads the latest graph from cloud to your local project

### Enhanced Login

`graq login --api-key grq_xxx` now validates the key against the GraQle Cloud API:
- Returns email, plan tier, and validation status
- Falls back gracefully when offline — key saved locally
- Key format validation (`grq_` prefix required)

### API Key Management (Studio)

New Account page at [graqle.com/dashboard/account](https://graqle.com/dashboard/account):
- **Generate API keys** (up to 5 per user) — `grq_` + 64-char hex
- **Key shown once** — copy button, then masked forever
- **Revoke keys** (soft-delete) — immediate invalidation
- **Connected Projects** — see all pushed projects with node count, health, last push time
- **Validation endpoint** — `POST /api/keys/validate` (used by `graq login`)

### Project Selector (Studio)

TopBar project dropdown — switch between projects pushed to cloud:
- Auto-fetches from S3 on auth
- Loads project-specific graph in explorer
- Per-user, per-project graph loading with fallback

### Control Plane — Cloud Integration

`/dashboard/control` now merges local backend instances with cloud projects:
- Local instances from `graq serve` + cloud instances from S3
- Deduplicated by project name
- Health status, node/edge counts, last scan time

### Lambda — Neptune-Aware Loading

Lambda handler (`cognigraph-api`) now checks `NEPTUNE_ENDPOINT`:
- If set: passes `neptune_enabled=True` to create_app — serves from Neptune
- If not: falls back to S3 JSON (existing behavior)
- Warm container caching preserved

### Cloud Gateway

`CloudGateway.upload_graph()` upgraded from stub to real S3 upload:
- Uploads `graqle.json` and optional `scorecard.json`
- Returns S3 prefix for verification
- Error handling with logging

### Tests

**2,009 tests passing.** No regressions from v0.28.0.

### Files Changed

| File | Change |
|------|--------|
| `graqle/cli/commands/cloud.py` | NEW — `graq cloud push/pull/status` |
| `graqle/cli/commands/login.py` | Enhanced — API key validation against cloud |
| `graqle/cli/main.py` | Added — `cloud` command group registration |
| `graqle/cloud/gateway.py` | Upgraded — real `upload_graph()` method |
| `graqle/server/lambda_handler.py` | Enhanced — Neptune-aware graph loading |

### Breaking Changes

None. All new features are additive. Existing configs work unchanged.

---

## v0.22.0 — Multi-Provider LLM + Task-Based Routing (2026-03-14)

**Use any LLM provider. Route tasks to the right model.** The biggest backend expansion since launch — 10+ providers, task-based routing, and Google Gemini native support.

### Multi-Provider LLM Support

7 new OpenAI-compatible providers added via **provider presets** — named configurations that auto-resolve to `CustomBackend` with the correct endpoint, env var, and per-model pricing. No new dependencies required (all use `httpx`).

| Provider | Env Var | Default Model | Cost/1K tokens |
|----------|---------|---------------|----------------|
| **Groq** | `GROQ_API_KEY` | llama-3.3-70b-versatile | $0.00059 |
| **DeepSeek** | `DEEPSEEK_API_KEY` | deepseek-chat | $0.00014 |
| **Together** | `TOGETHER_API_KEY` | Llama-3.3-70B-Instruct-Turbo | $0.00088 |
| **Mistral** | `MISTRAL_API_KEY` | mistral-small-latest | $0.00020 |
| **OpenRouter** | `OPENROUTER_API_KEY` | llama-3.3-70b-instruct | $0.00050 |
| **Fireworks** | `FIREWORKS_API_KEY` | llama-v3p3-70b-instruct | $0.00090 |
| **Cohere** | `COHERE_API_KEY` | command-r-plus | $0.00300 |

**Usage — one line in `graqle.yaml`:**
```yaml
model:
  backend: groq
  model: llama-3.3-70b-versatile
```

**Or via SDK:**
```python
from graqle.backends.providers import create_provider_backend
backend = create_provider_backend("groq", model="llama-3.3-70b-versatile")
graph.set_default_backend(backend)
```

**Files:**
- `graqle/backends/providers.py` — Provider preset registry with `PROVIDER_PRESETS`, `create_provider_backend()`, `get_provider_names()`, `get_provider_env_var()`
- `graqle/backends/registry.py` — 15 new entries in `BUILTIN_BACKENDS`
- `graqle/backends/__init__.py` — Lazy imports for new exports
- `graqle/core/graph.py` — `_auto_create_backend()` handles provider presets
- `graqle/cli/commands/doctor.py` — Detects all provider API keys

### Google Gemini Backend

Gemini uses Google's own `generateContent` API format (not OpenAI-compatible), so it gets its own backend class with proper request/response translation.

- Supports `GEMINI_API_KEY` and `GOOGLE_API_KEY` env vars
- Per-model pricing: Gemini 2.5 Pro, 2.5 Flash, 2.0 Flash, 2.0 Flash-Lite, 1.5 Pro, 1.5 Flash
- Retry with backoff (shared with other API backends)

**Files:**
- `graqle/backends/gemini.py` — `GeminiBackend` class with `GEMINI_PRICING`

### Task-Based Model Routing

Users define rules that map task types to providers — never auto-assigned, always explicit opt-in.

**8 task types:** `context`, `reason`, `preflight`, `impact`, `lessons`, `learn`, `code`, `docs`

**Built-in recommendations** suggest which providers suit which tasks, with reasoning:
- Context lookups → fast/cheap (Groq, Gemini, DeepSeek)
- Reasoning → smart/thorough (Anthropic, OpenAI, DeepSeek)
- Preflight checks → reliable (Anthropic, Mistral)
- Impact analysis → fast/structured (Groq, Together, Fireworks)
- Document tasks → long-context (Gemini, Anthropic, Together)

**Configuration:**
```yaml
routing:
  default_provider: groq
  rules:
    - task: reason
      provider: anthropic
      model: claude-sonnet-4-6
      reason: "Reasoning needs strong multi-step logic"
    - task: context
      provider: groq
      model: llama-3.1-8b-instant
      reason: "Context lookups are simple — use fast model"
```

**Files:**
- `graqle/routing.py` — `TaskRouter`, `RoutingRule`, `TASK_RECOMMENDATIONS`, `MCP_TOOL_TO_TASK`
- `graqle/config/settings.py` — `RoutingConfig`, `RoutingRuleConfig` added to `GraqleConfig`
- `graqle/core/graph.py` — `areason()` and `reason()` accept `task_type` parameter
- `graqle/plugins/mcp_dev_server.py` — `_handle_reason()` passes `task_type="reason"`
- `graqle/plugins/mcp_server.py` — Same

### Config Changes

New `routing` section in `graqle.yaml`:
```yaml
routing:
  default_provider: null         # fallback provider if no task rule matches
  default_model: null             # fallback model
  rules: []                       # list of {task, provider, model, reason}
```

New `endpoint` field on `ModelConfig`:
```yaml
model:
  endpoint: https://my-proxy.example.com/v1/chat/completions  # for custom/self-hosted
```

### Tests

**1,655 tests passing.** Up from 1,627 in v0.21.2.

| Area | New Tests | What |
|------|-----------|------|
| Routing | 27 | TaskRouter, RoutingRule, recommendations, RoutingConfig, YAML validation |
| Providers | 19 | Preset structure, endpoint validation, create_provider_backend |
| Gemini | 11 | Init, pricing, API key resolution, request body, response parsing |

### Breaking Changes

None. All new features are additive. Existing configs work unchanged.

---

## v0.21.2 — Bugfix Release (2026-03-14)

- DF-005: Fixed `graq scan docs` crash when no doc manifest exists
- DF-006: Fixed background scan state file not being cleaned up

---

## v0.20.0 — Document Intelligence + Auto-Scaling (2026-03-14)

**The biggest release since v0.9.0.** GraQle now understands documents, JSON configs, and code in a single unified graph — and auto-scales to Neo4j when your graph grows past 5,000 nodes.

### Document-Aware Scanning (Phases 1-4)

GraQle is now the first tool that connects code intelligence to document intelligence in one graph. 8 out of 10 real developer questions hit documents, not code — now those answers are in the graph.

- **6-format parser pipeline:** Markdown, plain text, PDF, DOCX, PPTX, XLSX. Zero-dependency for MD/TXT; optional `pip install graqle[docs]` for rich formats.
- **Heading-aware document chunker:** Preserves document structure (heading hierarchy, page numbers, code blocks, tables). Configurable chunk sizes with overlap.
- **Auto-linking engine:** 4 levels — exact match (free), fuzzy match (free, Levenshtein + token overlap), semantic match (opt-in, embeddings), LLM-assisted (opt-in, budget-controlled).
- **Privacy redaction:** PII/secrets stripped before graph ingestion (API keys, passwords, tokens, emails, phone numbers). Configurable patterns.
- **Incremental manifest:** SHA-256 + mtime tracking in `.graqle-doc-manifest.json`. Unchanged files skip on rescan.
- **Background scanning:** `graq scan all .` runs code scan (foreground) then doc scan (background daemon thread). State file for cross-invocation progress tracking.

**CLI commands:**
```bash
graq scan all .              # Code + JSON + docs (background)
graq scan docs .             # Documents only
graq scan file report.pdf    # Single document
graq learn doc spec.pdf      # On-demand ingestion with linking
graq learn doc ./heavy-docs/ # Bulk directory ingestion
graq scan status             # Background progress
graq scan wait               # Block until done
graq scan cancel             # Stop background scan
```

**New node types:** Document, Section, Decision, Requirement, Procedure, Definition, Stakeholder, Timeline.
**New edge types:** DESCRIBES, DECIDED_BY, CONSTRAINED_BY, IMPLEMENTS, REFERENCED_IN, SECTION_OF, OWNED_BY, SUPERSEDES.

### JSON-Aware Graph Ingestion (Phase 5)

JSON files are the configuration layer that bridges documents to code. They scan after code but before documents — small, fast, highly structured, knowledge-dense.

- **Auto-classification:** Detects category by filename + content structure:
  - `DEPENDENCY_MANIFEST` — package.json, Pipfile, composer.json
  - `API_SPEC` — openapi.json, swagger.json (OpenAPI 3.x + Swagger 2.0)
  - `INFRA_CONFIG` — cdk.json, SAM templates, serverless.json, CloudFormation
  - `TOOL_CONFIG` — tsconfig.json, .eslintrc.json, .prettierrc.json
  - `APP_CONFIG` — config/*.json, settings.json
  - `SCHEMA_FILE` — *.schema.json
  - `DATA_FILE` — large files (>50KB) — skipped by default

- **Category-specific extractors:** Each produces typed nodes:
  - `DependencyExtractor` — npm deps/devDeps/scripts, Pipfile, Composer
  - `APISpecExtractor` — endpoints (method/route/params/tags), schemas, RETURNS/ACCEPTS edges
  - `InfraExtractor` — CloudFormation resources, `Ref`/`Fn::GetAtt` cross-resource edges
  - `ToolConfigExtractor` — compiler options, linting rules
  - `AppConfigExtractor` — flat/nested config values (secrets auto-filtered)

**CLI command:**
```bash
graq scan json .             # Scan only JSON files
```

**New node types:** Dependency, Script, Endpoint, Schema, Resource, ToolRule, Config.
**New edge types:** DEPENDS_ON, RETURNS, ACCEPTS, IMPLEMENTED_BY, CONSUMED_BY, TRIGGERS, READS_FROM, APPLIES_TO, INVOKES.

### Cross-Source Deduplication Engine (Phase 6)

Without deduplication, multi-source scanning produces a noisy graph where the same entity appears as 3-7 disconnected nodes. Now GraQle unifies them automatically.

- **3-layer deduplication pipeline:**
  1. **Canonical IDs** — Deterministic SHA-256 hashing by type+source. Re-scanning produces same IDs, so nodes update instead of duplicating. Supports: FUNCTION, CLASS, MODULE, ENDPOINT, CONFIG, DEPENDENCY, SECTION, DECISION, DOCUMENT, RESOURCE, SCHEMA, TOOL_RULE, SCRIPT.
  2. **Entity Unification** — Name variant registry matches across different source types. Generates variants: `verify_token` ↔ `verifyToken` ↔ `VerifyToken` ↔ `verify-token` ↔ `verify token`. Only matches cross-source (code ↔ doc, not code ↔ code).
  3. **Contradiction Detection** — Finds conflicting information across sources: numeric mismatches (config says 3600, doc says 1800), boolean mismatches, value mismatches. Case-insensitive comparison for strings.

- **Merge engine:** Source priority: Code > API spec > JSON config > User-taught > Documents. Longer description kept, properties fill gaps (no overwrite), provenance tracked.
- **Decision persistence:** User merge accept/reject decisions stored in `.graqle/merge_decisions.json`. Never asked the same question twice.

### Frictionless UX Layer (Phase 7)

Value before configuration. Always.

- **Document quality gate:** Auto-rejects low-value documents before scanning — too short (<50 chars), binary/garbled (>50% non-ASCII), no structure (0 sections), test fixtures, duplicate by hash. Quality score (0.0-1.0) for accepted docs.
- **Environment auto-detection:** DETECT don't ASK.
  - Backend: AWS credentials → Bedrock; `ANTHROPIC_API_KEY` → Anthropic; `OPENAI_API_KEY` → OpenAI; nothing → local
  - Languages: Python, TypeScript, JavaScript, Go, Rust, Java, C#, Ruby (from file extensions + config files)
  - Frameworks: Next.js, React, Django, CDK, Serverless, Terraform, Express, Vue, Angular (from config + package.json)
  - IDE: VS Code, Cursor, JetBrains (from project dirs)
  - Machine capacity: minimal (<4GB), standard (<8GB), capable (<16GB), powerful (16GB+)
- **Smart excludes:** Auto-generated based on detected languages (node_modules, __pycache__, dist, target, .gradle, etc.)
- **MCP config suggestion:** Auto-generates `.mcp.json` for detected IDE.
- **Natural language query routing:** Zero-LLM-cost keyword classifier routes free-text queries to the right tool:
  - `"what depends on auth?"` → impact
  - `"is it safe to change payment.py?"` → impact
  - `"before I deploy, what should I check?"` → preflight
  - `"what went wrong last time?"` → lessons
  - `"explain the auth system"` → context
  - `"how many nodes are there?"` → inspect
  - Complex multi-hop questions → reason (full graph reasoning)

### Pluggable Graph Backend with Auto-Upgrade (Phase 8)

- **Auto-shift to Neo4j at 5,000 nodes.** Don't ask, just do it and notify. The system detects when your graph outgrows JSON/NetworkX and recommends migration. Also triggers on >5s load latency.
- **Migration Cypher generation:** UNWIND batch pattern (same as TAMR+ pipeline). Creates constraints, indexes, and batch-inserts nodes and edges.
- **`migrate_json_to_neo4j()`** — Full migration function: loads JSON, creates Neo4j schema, batch inserts, backs up original file.
- **`check_neo4j_available()`** — Verifies driver installed before attempting migration.
- **Neptune support** — Configuration ready for AWS Neptune (teams). Backend detection skips upgrade for already-scalable backends.

### Configuration

New settings in `graqle.yaml`:

```yaml
scan:
  docs:
    enabled: true
    background: true
    extensions: [".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt"]
    max_file_size_mb: 50.0
    chunk_max_chars: 1500
    linking:
      exact: true
      fuzzy: true
      semantic: false        # opt-in (needs embeddings)
      llm_assisted: false    # opt-in (costs tokens)
    redaction:
      enabled: true
      redact_api_keys: true
      redact_passwords: true
  json:
    enabled: true
    auto_detect: true
    max_file_size_mb: 10.0
    categories:
      DEPENDENCY_MANIFEST: true
      API_SPEC: true
      TOOL_CONFIG: true
      APP_CONFIG: true
      INFRA_CONFIG: true
      SCHEMA_FILE: true
      DATA_FILE: false
```

### Tests

**1,484 tests passing.** Up from 976 in v0.19.0.

| Phase | Tests | What |
|-------|-------|------|
| 1-4 | 287 | Parsers, chunker, privacy, manifest, linker, doc scanner, background, CLI |
| 5 | 72 | JSON classifier, 5 extractors, scanner integration |
| 6 | 77 | Canonical IDs, unifier, merge engine, contradictions, decisions, orchestrator |
| 7 | 57 | Quality gate, auto-detection, NL router |
| 8 | 15 | Upgrade advisor, Cypher generation, threshold logic |

### Dependencies

New optional dependency group:

```bash
pip install graqle[docs]     # PDF, DOCX, PPTX, XLSX support
```

Adds: `pdfplumber>=0.9`, `python-docx>=0.8`, `python-pptx>=0.6`, `openpyxl>=3.1`.

---

## v0.19.0 — Multi-Agent Intelligence + Universal Fixes (2026-03-14)

**Multi-Agent Graph Access (P1-7 — the big unlock):**
- `graq context --json` — Structured JSON output, no ANSI codes, no embeddings. Subagents parse via Bash.
- `graq mcp serve --read-only` — Blocks mutation tools (`graq_learn`, `graq_reload`). Safe for subagents.
- `graq serve --read-only` — HTTP server with read-only mode (403 on write endpoints).
- **File locking** — Cross-platform (`msvcrt`/`fcntl`) file locking on `graqle.json` writes.
- `--caller <agent-id>` — Query logging with per-caller attribution in metrics.

**Windows Unicode (P0 — ADR-107):**
- Universal three-layer fix: UTF-8 stream reconfiguration, `force_terminal=True`, ASCII fallbacks.

**Region-Agnostic Backends (P1-4):**
- Removed hardcoded regions. Resolution: config → `AWS_DEFAULT_REGION` → `AWS_REGION` → `us-east-1`.

**Bedrock Model Validation (P1-5):**
- `graq doctor` validates model ID against Bedrock's available models with suggestions.

---

## v0.18.0 — Cloud Connect + Ontology Intelligence (2026-03-13)

- GraQle Cloud (`graq login` / `graq logout`) — optional, zero signup for local features
- OntologyRefiner — analyzes activation memory to suggest ontology improvements
- GitHub Action workflow (`graqle-scan.yml`)
- Studio Cloud Connect panel

## v0.17.0 — Field-Tested Release (2026-03-13)

- `edges`/`links` JSON key mismatch fix (P0)
- `entity_type` not loading from JSON fix (P0)
- Windows Unicode crash fix (P0)
- Impact analysis precision fix (skip structural edges)
- `graq learned`, `graq self-update`, `graq --version`
- `.graqle-ignore` support
- 901 tests passing

## v0.16.0 — GraQle Rebrand (2026-03-13)

- CogniGraph → GraQle. `pip install graqle`, CLI: `graq`, MCP: `graq_*`
- Backward compat: `pip install cognigraph` auto-installs graqle

## v0.15.0

- MCP hot-reload, confidence recalibration, business entity support
- Multi-project CLI (`graq link merge/edge/stats`)
- 797 tests passing

## v0.12.0

- Observer overhaul, adaptive activation, cross-query learning
- Call-graph edges, embedding cache (11K nodes: 30s → <1s)

## v0.10.0

- ChunkScorer replaces PCST as default activation
- Bedrock auth detection fix

## v0.9.0

- Neo4j backend (`from_neo4j()` / `to_neo4j()`)
- CypherActivation, chunk-aware scoring
- 736 tests passing
