# ADR-115: Phase 3.5 — File System + Git Tool Layer
**Date:** 2026-03-27 | **Status:** ACCEPTED
**Branch:** feature-coding-assistant | **Phase:** T3.5

## Context
graq_predict (82% confidence) identified that graq_generate and graq_edit were "tested-but-unreachable" — no file I/O primitives existed to form autonomous workflows. A coding assistant needs read/write/search/execute/git as a complete toolchain.

## Decision
Add 10 new MCP tools (+ 10 kogni_* aliases = 98 total):
- **graq_read** — file reader with offset/limit line range
- **graq_write** — atomic write (NamedTemporaryFile→fsync→os.replace) + patent scan
- **graq_grep** — regex search across codebase with context lines
- **graq_glob** — file pattern finder sorted by mtime
- **graq_bash** — governed shell exec with blocklist + timeout (max 120s)
- **graq_git_status/diff/log** — read-only git inspection tools
- **graq_git_commit** — write git commit with patent scan on staged diff
- **graq_git_branch** — create/switch branches (feature-*/hotfix-* conventions)

## P0 Fixes (same commit)
- Added all write-capable tools to `_WRITE_TOOLS` frozenset (blocks them in read-only mode)
- Added all 20 new tools to `MCP_TOOL_TO_TASK` routing table
- Added 8 new task types to `TASK_RECOMMENDATIONS` (generate/edit/read/write/grep/glob/bash/git)

## Rationale
- **Autonomous loop enablement**: grep→read→generate→write→bash(test)→git(commit) chain now possible
- **Additive-only**: 78 → 98 tools, zero modifications to existing handlers
- **Safety by default**: dry_run=True for write/git_commit; blocklist for bash; patent scan for write+commit
- **Backend-agnostic**: all tools are pure Python/subprocess, no LLM calls needed for I/O primitives

## Consequences
- **Positive**: Unblocks autonomous bug fix loop, scaffold+test cycle, governed refactor with rollback
- **Positive**: graq_predict identified WorkflowOrchestrator as next critical gap — this is Phase 4+
- **Negative**: graq_bash shell=True is a security surface — blocklist must stay maintained
- **Future**: WorkflowOrchestrator with DAG/saga semantics (graq_predict, 82% confidence)

## Rules
1. NEVER remove a tool from `_WRITE_TOOLS` without explicit justification — read-only mode safety
2. graq_write and graq_git_commit MUST patent-scan before any write
3. graq_bash blocklist must include: rm -rf, git push --force, DROP TABLE, DROP DATABASE
4. dry_run=True is the default for ALL destructive tools — user must explicitly opt in
