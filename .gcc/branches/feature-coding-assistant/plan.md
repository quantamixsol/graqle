# Execution Plan: Graqle → Governed AI Coding Assistant
**Branch:** feature-coding-assistant | **Target:** v0.38.0
**Dogfooding:** Built with v0.37.0 graq tools
**Date:** 2026-03-26

---

## Validation Loop (runs at end of EVERY phase)

```bash
# 1. Patent scan (TS-1..TS-4)
grep -rn "w_J\|w_A\|0\.16\|theta_fold\|jaccard.*formula\|70.*30.*blend" graqle/ --include="*.py"
# must return 0 matches

# 2. Targeted test suite
python -m pytest tests/test_generation/ tests/test_plugins/ tests/test_cloud/ tests/test_studio/ -q
# must be 0 failures

# 3. Full suite (before publish only)
python -m pytest tests/ -q
# must be ≥ 927 pass, 0 new failures
```

---

## PHASE 1 — `graq_generate` Tool + Type Foundation
**Target:** 2 weeks | **Risk:** MEDIUM | **Blast radius:** 2 new files

### Tasks

- [ ] **T1.1** — Create `graqle/core/generation.py`
  - New types: `GenerationRequest`, `CodeGenerationResult`, `DiffPatch`
  - `DiffPatch`: `file_path: str`, `unified_diff: str`, `lines_added: int`, `lines_removed: int`, `preview: str`
  - `CodeGenerationResult`: extends fields from `ReasoningResult` pattern + `patches: list[DiffPatch]`, `files_affected: list[str]`
  - **No changes to `types.py`** — new file only
  - Tests: `tests/test_generation/test_types.py` (8 tests)

- [ ] **T1.2** — Register `coding` domain ontology
  - File: `graqle/ontology/domains/coding.py`
  - Entity shapes: `Function`, `Class`, `Module`, `API`, `Test`
  - Skill map: `CODE_GENERATION`, `REFACTOR`, `COMPLETION`, `TEST_GENERATION`
  - Output gates: validates diff format, file path exists, no secret exposure
  - Tests: `tests/test_ontology/test_coding_domain.py` (5 tests)

- [ ] **T1.3** — Implement `_handle_generate()` in `mcp_dev_server.py`
  - Additive only — new method, no changes to existing handlers
  - Flow: `_require_graph()` → activate context → preflight check → call backend → format as unified diff → safety_check output
  - Args: `description: str`, `file_path: str` (optional), `max_rounds: int = 2`, `dry_run: bool = False`
  - Returns: `CodeGenerationResult.to_dict()`
  - Team/enterprise plan gate (same `_is_team_plan()` pattern)
  - Tests: `tests/test_generation/test_graq_generate.py` (10 tests)

- [ ] **T1.4** — Register `graq_generate` + `kogni_generate` in `TOOL_DEFINITIONS`
  - Additive to list — no changes to existing tool definitions
  - Route via `handle_tool()` dispatch dict

- [ ] **T1.5** — Validation loop for Phase 1
  - Patent scan: clean
  - `pytest tests/test_generation/ tests/test_plugins/test_mcp_dev_server.py -q` → 0 failures
  - `graq_generate` returns a valid unified diff for: `"add a docstring to the SyncEngine class"`

**Phase 1 binary exit: `graq_generate` produces a syntactically valid unified diff. Preflight ran. Tests pass.**

---

## PHASE 2 — `graq_edit` Tool + Atomic File Writes
**Target:** 2 weeks | **Risk:** MEDIUM-HIGH | **Blast radius:** 1 new file

### Tasks

- [ ] **T2.1** — Create `graqle/core/file_writer.py`
  - `apply_diff(file_path: Path, unified_diff: str) -> ApplyResult`
  - Atomic write: read → apply patch → write to `.tmp` → verify → rename
  - Rollback: backup to `.graqle/edit-backup/{timestamp}.bak` before any write
  - `ApplyResult`: `success: bool`, `lines_changed: int`, `backup_path: str`, `error: str`
  - Tests: `tests/test_generation/test_file_writer.py` (10 tests including rollback)

- [ ] **T2.2** — Implement `_handle_edit()` in `mcp_dev_server.py`
  - Args: `file_path: str`, `description: str` (OR `diff: str` for direct apply), `dry_run: bool = True`
  - Flow: preflight → generate diff (if description given) → safety_check diff → backup → apply → verify
  - Default `dry_run=True` — never writes without explicit `dry_run=False`
  - Returns: `ApplyResult + CodeGenerationResult` merged dict
  - Tests: `tests/test_generation/test_graq_edit.py` (10 tests)

- [ ] **T2.3** — Register `graq_edit` + `kogni_edit` in `TOOL_DEFINITIONS`

- [ ] **T2.4** — Validation loop for Phase 2
  - `graq_edit dry_run=True` on a real file → returns diff preview, no write
  - `graq_edit dry_run=False` → writes atomically, backup exists, file content updated
  - Full rollback test: corrupt write → backup restored

**Phase 2 binary exit: `graq_edit` writes a real file atomically. Rollback works. Dry-run default confirmed by test.**

---

## PHASE 3 — Streaming Backend + Token Streaming
**Target:** 1.5 weeks | **Risk:** MEDIUM | **Blast radius:** `backends/api.py`, `backends/base.py`

### Tasks

- [ ] **T3.1** — Add `agenerate_stream()` to `ModelBackend` protocol in `backends/base.py`
  - `async def agenerate_stream(self, prompt: str) -> AsyncIterator[str]`
  - Default implementation: yields full result as single chunk (backward compat for all existing backends)
  - Tests: `tests/test_backends/test_streaming.py` (6 tests)

- [ ] **T3.2** — Implement real streaming in `AnthropicBackend`
  - Uses `client.messages.stream()` context manager
  - Yields `text_delta` chunks

- [ ] **T3.3** — Implement streaming in `MockBackend`
  - Word-by-word yield from `_mock_response` string
  - Used in all tests — never needs real API key

- [ ] **T3.4** — Wire streaming into `graq_generate`
  - `_handle_generate(stream=True)` → SSE chunks via MCP stdio
  - Tests: `tests/test_generation/test_graq_generate_streaming.py` (4 tests)

- [ ] **T3.5** — Validation loop for Phase 3
  - MockBackend streaming test: 10+ chunks yielded for a 50-word response
  - Anthropic streaming: integration test (skipped if no API key, clearly marked)
  - All existing backend tests still pass

**Phase 3 binary exit: `MockBackend.agenerate_stream()` yields multiple chunks. Existing backends unaffected.**

---

## PHASE 4 — CLI Commands + Studio Endpoint
**Target:** 1 week | **Risk:** LOW | **Blast radius:** `cli/main.py`, `studio/routes/api.py`

### Tasks

- [ ] **T4.1** — Add `graq generate` CLI command to `cli/main.py`
  - `graq generate "add error handling to SyncEngine.push()" --file graqle/cloud/sync_engine.py`
  - Options: `--dry-run` (default True), `--force` (apply immediately), `--backend anthropic`
  - Output: colored unified diff to terminal; confirmation prompt before write
  - Tests: `tests/test_cli/test_generate.py` (6 tests)

- [ ] **T4.2** — Add `graq edit` CLI command
  - `graq edit graqle/cloud/sync_engine.py "add retry logic to _do_push"`
  - Alias: `graq gen` (short form)
  - Tests: `tests/test_cli/test_edit_command.py` (4 tests)

- [ ] **T4.3** — Add `POST /api/generate` Studio endpoint to `studio/routes/api.py`
  - Body: `{"description": "...", "file_path": "...", "dry_run": true}`
  - Streams SSE: routing → diff chunks → done/error
  - Builds on existing `/chat` and `/cli/exec` SSE patterns
  - Tests: `tests/test_studio/test_api_generate_route.py` (6 tests)

- [ ] **T4.4** — Wire `/chat` slash command `/generate`
  - `/generate <description> in <file>` → routes to `graq_generate` via `_route_chat_message()`
  - Already-built routing table in `api.py` — additive entry only

- [ ] **T4.5** — Validation loop for Phase 4
  - `graq generate --dry-run "..."` prints diff without writing
  - `POST /api/generate` returns SSE stream with valid diff
  - `/generate` slash command in Studio chat routed correctly

**Phase 4 binary exit: `graq generate --dry-run` works end-to-end from CLI. Studio `/generate` streams a diff.**

---

## PHASE 5 — VS Code Extension
**Target:** 3 weeks | **Risk:** HIGH | **New repo:** `quantamixsol/graqle-vscode`

### Tasks

- [ ] **T5.1** — Scaffold extension (`yo code` → TypeScript, webpack)
  - Extension ID: `graqle.graqle-vscode`
  - Commands: `graqle.generate`, `graqle.chat`, `graqle.preflight`, `graqle.impact`
  - Settings: `graqle.serverUrl` (default `http://localhost:8077`), `graqle.apiKey`

- [ ] **T5.2** — Chat panel (WebviewPanel)
  - Renders Studio `/chat` SSE stream in sidebar
  - Supports all slash commands: `/reason`, `/generate`, `/context`, `/impact`, `/preflight`
  - Shows routing decision ("Using graq_generate…") before result
  - Syntax highlighting for diff output

- [ ] **T5.3** — "Governed Generate" command
  - Right-click menu → "Graqle: Generate here"
  - Sends current file path + selected text as description to `graq_generate`
  - Shows diff preview in diff editor (`vscode.diff`)
  - "Apply" button calls `graq_edit dry_run=False`
  - "Reject" closes without writing

- [ ] **T5.4** — Audit trail sidebar
  - TreeView showing last 10 AI edits
  - Each entry: timestamp, file, lines changed, confidence, backend used
  - "Export for compliance" → JSON/CSV download

- [ ] **T5.5** — Extension tests (Jest)
  - Mock `graq serve` server
  - Test: generate command calls correct endpoint
  - Test: diff preview renders
  - Test: apply writes file
  - Test: reject does not write

- [ ] **T5.6** — Publish to VS Code Marketplace
  - `vsce package` → `.vsix`
  - `vsce publish` with marketplace token
  - README with demo GIF

- [ ] **T5.7** — Validation loop for Phase 5
  - Extension installs in VS Code without errors
  - "Governed Generate" produces a diff preview for a real Python file
  - "Apply" writes the file and backup exists in `.graqle/edit-backup/`
  - Audit trail shows the edit

**Phase 5 binary exit: Extension installed. Generate → diff preview → Apply → file written. All in VS Code UI.**

---

## PUBLISH: v0.38.0

- [ ] **PUB.1** — Full test suite: `pytest tests/ -q` → ≥ 927 pass, 0 new failures
- [ ] **PUB.2** — Patent scan: TS-1..TS-4 clean across all new files
- [ ] **PUB.3** — Bump `__version__.py` + `pyproject.toml` → `0.38.0`
- [ ] **PUB.4** — `graq scan repo .` — rebuild KG with new modules
- [ ] **PUB.5** — `graq cloud push` — sync updated graph to cloud
- [ ] **PUB.6** — `git tag v0.38.0 && git push origin master && git push origin v0.38.0`
- [ ] **PUB.7** — CI publishes to PyPI via Trusted Publishing
- [ ] **PUB.8** — VS Code extension published to Marketplace

---

## File Map (New Files Only — Zero Modifications to Existing)

| New File | Purpose | Phase |
|----------|---------|-------|
| `graqle/core/generation.py` | `GenerationRequest`, `CodeGenerationResult`, `DiffPatch` types | 1 |
| `graqle/ontology/domains/coding.py` | Coding domain ontology + skill map | 1 |
| `graqle/core/file_writer.py` | Atomic diff application + rollback | 2 |
| `tests/test_generation/` | All generation tests | 1–4 |
| `tests/test_generation/__init__.py` | Package init | 1 |
| `tests/test_generation/test_types.py` | GenerationResult types | 1 |
| `tests/test_generation/test_graq_generate.py` | graq_generate tool | 1 |
| `tests/test_generation/test_graq_edit.py` | graq_edit tool | 2 |
| `tests/test_generation/test_file_writer.py` | Atomic write + rollback | 2 |
| `tests/test_generation/test_graq_generate_streaming.py` | Streaming generation | 3 |
| `tests/test_backends/test_streaming.py` | Backend streaming protocol | 3 |
| `tests/test_cli/test_generate.py` | graq generate CLI | 4 |
| `tests/test_cli/test_edit_command.py` | graq edit CLI | 4 |
| `tests/test_studio/test_api_generate_route.py` | /generate Studio route | 4 |
| `graqle-vscode/` (new repo) | VS Code extension | 5 |

**Modifications to existing files:**
- `graqle/plugins/mcp_dev_server.py` — additive only: `_handle_generate`, `_handle_edit`, 2 new tool defs
- `graqle/backends/base.py` — additive only: `agenerate_stream()` default method
- `graqle/backends/api.py` — additive only: `AnthropicBackend.agenerate_stream()`
- `graqle/backends/mock.py` — additive only: `MockBackend.agenerate_stream()`
- `graqle/cli/main.py` — additive only: `generate_command`, `edit_command`
- `graqle/studio/routes/api.py` — additive only: `POST /generate`, `/generate` slash cmd
- `graqle/ontology/domains/__init__.py` — additive only: register coding domain

---

## Effort + Sequencing

| Phase | Effort | Risk | Dependency |
|-------|--------|------|-----------|
| Phase 1: graq_generate | 2 weeks | MEDIUM | None — starts now |
| Phase 2: graq_edit | 2 weeks | MEDIUM-HIGH | Phase 1 |
| Phase 3: Streaming | 1.5 weeks | MEDIUM | Phase 1 |
| Phase 4: CLI + Studio | 1 week | LOW | Phase 1+2 |
| Phase 5: VS Code | 3 weeks | HIGH | Phase 1+2+3+4 |
| **Total** | **~10 weeks** | | |

Phases 2 and 3 can run in parallel after Phase 1.

---

## COMMIT 0 — Branch Created
**Date:** 2026-03-26
**State:** WORKING
**Milestone:** GSD DISCUSS + PLAN complete. Full execution plan written. Dogfooding confirmed (v0.37.0 MCP tools used to generate this plan).
**Next:**
- [ ] T1.1 — Create `graqle/core/generation.py` with new types
- [ ] T1.2 — Register coding domain ontology
- [ ] T1.3 — Implement `_handle_generate()` in mcp_dev_server.py
