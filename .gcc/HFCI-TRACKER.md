# HFCI — Senior Developer Autonomy Tracker

**ADR:** 200 | **Started:** 2026-04-05 | **Status:** SPRINT 1 ACTIVE
**Goal:** 100% Senior autonomy — zero Junior interventions

---

## Autonomy Scorecard

| Sprint | Date | Autonomy % | Items Done | Junior Interventions | New Gaps Found |
|--------|------|-----------|------------|---------------------|----------------|
| Baseline | 2026-04-05 | **40%** | 0/18 | ~15 per session | 18 total |
| Sprint 1 | IN PROGRESS | — | 6/11 verified | Logging below | +2 (HFCI-017, 018) |
| Sprint 2 | — | — | — | — | — |
| Sprint 3 | — | — | — | — | — |

---

## ROOT CAUSE (graq_reason 89%, 2026-04-05)

Tools EXIST (116 in TOOL_DEFINITIONS) but aren't ACTIVATED. Three gaps:
1. **No routing protocol** — nothing makes Junior prefer graq_* over native Claude Code tools
2. **`graq_context` doesn't compose** — returns graph node metadata, not actual file contents
3. **`graq_git_diff` bug** — NoneType error on merge commits, erodes trust in toolchain

---

## Sprint 1 — Fix Activation + GitHub Read (Target: 40%→70%)

**Branch:** `hotfix/hfci-sprint1` from `private/master`

### Sprint 1 Items

| ID | Capability | Type | Status | Dogfood Result |
|----|-----------|------|--------|----------------|
| **HFCI-003** | `graq_read` works for .md/.yaml/.json | Verify | DONE | Works — resolves to graph root, not CWD |
| **HFCI-005** | `graq_glob` sandboxed to project root | Verify | DONE | Works — searches parent Graqle/ dir |
| **HFCI-006** | `graq_grep` sandboxed to project root | Verify | DONE | Works — searches main graqle-sdk/ |
| **HFCI-011a** | `graq_git_status` handler | Verify | DONE | Works WITH explicit cwd param |
| **HFCI-011b** | `graq_git_log` handler | Verify | DONE | Works WITH explicit cwd param |
| **HFCI-011c** | `graq_git_diff` handler bug fix | BUG FIX | TODO | NoneType on merge commits |
| **HFCI-017** | `graq_context` compose graq_read/grep internally | Enhancement | DONE | KEY: single call → rich context with file contents. 25 tests, 2 rounds graq_review. |
| **HFCI-018** | `tool_hints` in MCP responses | Enhancement | TODO | Proactive tool suggestion |
| **HFCI-001** | `graq_github_pr` — fetch PR metadata | New tool | TODO | Unblocks autonomous PR review |
| **HFCI-002** | `graq_github_diff` — fetch PR diff | New tool | TODO | Unblocks autonomous diff review |
| **HFCI-012** | Auto-scan after graq_generate writes | Governance | TODO | Keeps KG fresh after writes |

### Sprint 1 Intervention Log

_Every Junior intervention = a capability gap to close._

| # | Timestamp | What Junior Did | Why Senior Couldn't | Maps to HFCI |
|---|-----------|----------------|--------------------|--------------| 
| 1 | 10:30 | Read file_writer.py via Read tool | graq_read resolves to main SDK, not hotfix worktree | HFCI-003 (CWD awareness) |
| 2 | 10:31 | Read mcp_dev_server.py via Read tool | Same — needed hotfix worktree version | HFCI-003 |
| 3 | 10:35 | Ran git status via Bash | graq_git_status needs explicit cwd | HFCI-011 (default cwd) |
| 4 | 10:36 | Ran git diff via Bash | graq_git_diff BROKEN — NoneType | HFCI-011c |
| 5 | 10:40 | Wrote test files via Write tool | No graq_write for new files | HFCI-009 |
| 6 | 10:45 | Ran pytest via Bash | No graq_exec allowlisted runner | HFCI-010 |
| 7 | 10:50 | Ran git add + commit via Bash | graq_git_commit exists but untested | HFCI-011 |
| 8 | 10:51 | Ran git push via Bash | No graq_git_push tool | NEW: HFCI-019 |
| 9 | 10:55 | Created PR via gh CLI | No graq_github_pr_create tool | HFCI-007 |
| 10 | 11:00 | Checked CI via gh CLI | No CI monitoring tool | HFCI-015 |
| 11 | 11:05 | pip install from PyPI | No graq_exec for pip | HFCI-010 |
| 12 | 11:10 | Ran graq doctor via Bash | Could use graq_exec allowlist | HFCI-010 |

---

## Sprint 2 — GitHub Write + Workflow (Target: 70%→80%)

| ID | Capability | Type | Status |
|----|-----------|------|--------|
| **HFCI-007** | `graq_github_comment` — post PR review | New tool | TODO |
| **HFCI-008** | `graq_github_learn_pr` — auto-teach diff to KG | New tool | TODO |
| **HFCI-013** | Review→correct→review loop chaining | Integration | TODO |
| **HFCI-014** | CLI pipeline (scan→learn→compile) | Integration | TODO |
| **HFCI-004** | `graq_graph_diff` — compare graph snapshots | New tool | TODO |
| **HFCI-019** | `graq_git_push` — governed push with IP gate | New tool | TODO |

---

## Sprint 3 — Advanced Autonomy (Target: 80%→100%)

| ID | Capability | Type | Status |
|----|-----------|------|--------|
| **HFCI-009** | `graq_edit` with diff-before-write gate | Enhancement | TODO |
| **HFCI-010** | `graq_exec` — allowlisted command runner | New tool | TODO |
| **HFCI-015** | `graq_release` — version bump + tag + CI verify | New CLI | TODO |
| **HFCI-016** | `graq_session` — GCC session management | New tool | TODO |

---

## Violation Root Cause → HFCI Mapping

| Violation | Root Cause | HFCI Fix | Sprint |
|-----------|-----------|----------|--------|
| V1-V10 | Senior can't read files/PRs | HFCI-001, 002, 003, 017 | 1 |
| V11 | Senior can't post to GitHub | HFCI-007 | 2 |
| V22 | Senior can't read/edit files | HFCI-003, 009, 017 | 1, 3 |
| V23 | Senior can't manage git | HFCI-011, 019 | 1, 2 |
| OT-023/056 | Senior only reasons, can't execute | HFCI-009, 010, 017 | 1, 3 |

---

## Dogfooding Protocol

**Every HFCI implementation MUST be dogfooded:**
1. Use `graq_generate` to write code (Senior writes)
2. Use `graq_review` to review code (Senior reviews)
3. Use `graq_preflight` before every change (Senior gates)
4. Junior only: stages files, runs git commands, runs tests
5. **Log every Junior intervention** in Sprint Intervention Log
6. At sprint end: count interventions, compute autonomy %

**Autonomy % = 1 - (Junior interventions / Total actions in sprint)**

---

## Structural Boundaries (Not Capability Gaps — Intentional)

| Capability | Why |
|-----------|-----|
| Real-time user dialogue | MCP is request/response |
| IDE integration | Requires editor hooks |
| Human-in-the-loop confirmation | Write-gate needs judgment |
| Arbitrary code execution | Security boundary |
| Cross-session memory | Junior manages ~/.claude/memory |

---

## Acceptance Criteria Per Item

Each HFCI is DONE when:
1. MCP tool implemented and registered in TOOL_DEFINITIONS
2. `graq_review` passes (security + correctness)
3. Tests written and passing
4. Dogfooded: Senior used the tool successfully in real work
5. Autonomy scorecard updated
