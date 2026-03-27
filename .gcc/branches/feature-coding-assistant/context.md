# Context: Graqle → Governed AI Coding Assistant
**Branch:** feature-coding-assistant
**Date:** 2026-03-26
**Dogfooding:** v0.37.0 building v0.38.0

---

## Problem Statement

Graqle has the hardest layer already built: a validated knowledge graph of any codebase, multi-agent reasoning, preflight governance, impact analysis, BYOK multi-backend LLM routing. But it is read-only against source code. It reasons about code — it never writes it.

Adding `graq_generate` and `graq_edit` on top of this stack creates something no competitor offers: **governed code generation** — every AI-written line is preflight-checked, blast-radius-scoped, safety-gated, and audit-trailed before it touches your codebase.

This is not a race with Cursor on autocomplete speed. It's a new category: **the governance layer between AI and your codebase**, targeting regulated enterprises (finance, healthcare, defense) where Cursor/Copilot cannot go.

---

## Scope

**In scope:**
- `graq_generate` MCP tool — graph-context + preflight → structured diff output
- `graq_edit` MCP tool — read file + apply diff + safety_check + write back
- `AsyncIterator` streaming for `ModelBackend.generate()`
- `CodeGenerationResult` type extending `ReasoningResult` with diff/patch fields
- `coding` domain ontology registration
- VS Code extension (chat panel + governed generate button)
- `graq generate` CLI command
- `graq edit` CLI command
- Studio `/generate` endpoint
- `/chat` slash command: `/generate <description> in <file>`
- Validation loop at each stage (tests before merge, full suite before publish)
- v0.38.0 release after all phases pass

**Out of scope (deferred):**
- LSP server / inline ghost-text completions (FIM) — Phase 2 product
- Autonomous generate→test→fix loops — Phase 2
- Real-time file watcher incremental indexing — Phase 2
- JetBrains extension — Phase 2
- Multi-classification-tier defense deployment — Phase 3

---

## Constraints

- **0% regression guarantee** — full test suite must pass before every publish
- **Patent safety** — TS-1..TS-4 scan before every commit touching reasoning
- **`core/types.py` is HIGH RISK** — 257 modules import it; add new types, never modify existing dataclass fields
- **`mcp_dev_server.py` has 39 consumers** — new tools must be additive only; no changes to existing tool signatures
- **Never expose** `graq_generate`/`graq_edit` on free tier without plan gate
- **File writes must be atomic** — write to `.tmp`, verify, rename (existing pattern in scan.py)
- **Air-gapped deployment must still work** — Ollama backend path must be exercised in tests
- **BYOK always** — never hardcode keys; all backends via `${ENV_VAR}` resolution

---

## Success Criteria (Binary)

Each phase must satisfy ALL criteria before proceeding:

| Phase | Criteria |
|-------|---------|
| **Phase 1** | `graq_generate` returns a valid unified diff for a test query; preflight runs before generation; tests pass |
| **Phase 2** | `graq_edit` reads file, applies diff, writes back atomically; safety_check runs after; rollback works |
| **Phase 3** | `ModelBackend.generate()` returns `AsyncIterator[str]`; streaming test passes for Anthropic + Mock backends |
| **Phase 4** | `graq generate` and `graq edit` CLI commands work end-to-end; `/generate` Studio endpoint streams SSE |
| **Phase 5** | VS Code extension installs, chat panel calls `/chat`, "Governed Generate" button applies a diff to a real file |
| **PUBLISH** | Full suite ≥ 927 pass, 0 new failures; patent scan clean; git tag v0.38.0; PyPI via CI |

---

## Open Questions (Resolved)

1. ~~Add to `types.py` or new file?~~ → New `graqle/core/generation.py` — avoids touching 257-module blast radius
2. ~~Free tier gate?~~ → Same pattern as `_is_team_plan()` in `sync_engine.py` — team/enterprise only
3. ~~Atomic write pattern?~~ → Copy from `scan.py` `_write_with_lock()` — already battle-tested
4. ~~VS Code extension language?~~ → TypeScript, separate repo `quantamixsol/graqle-vscode`
