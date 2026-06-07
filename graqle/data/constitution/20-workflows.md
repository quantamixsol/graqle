## Governed workflows

The 9-phase chain is the backbone. Apply the phase subset that matches the task.

### Phase backbone

| Phase | Tool(s) | When |
|-------|---------|------|
| 1 — SESSION BOOT | `graq_lifecycle(session_start)` → `graq_reload()` → `graq_lessons(operation=<domain>)` | Once per session |
| 2 — INVESTIGATE | `graq_reason(question=symptom)` → `graq_inspect(node=file)` | Per task |
| 3 — BLAST RADIUS | `graq_safety_check(component=file)` — STOP if CRITICAL | Per change |
| 4 — PLAN | `graq_plan(goal, scope)` — also unlocks `graq_bash` (CG-02) | Per change |
| 5 — GENERATE | `graq_generate(..., dry_run=true)` → user approves diff | Per change |
| 6 — APPLY | `graq_edit(strategy="literal", dry_run=false)` | Per change |
| 7 — SENTINEL REVIEW | `graq_preflight` → `graq_review(all)` ×2 → `graq_predict` → `graq_review(security)` | Per PR |
| 8 — PR | `graq_write(/tmp/pr_body.md)` → `gh pr create --body-file` | Per PR |
| 9 — LEARN | `graq_learn(knowledge=what/why/fix)` | Per task — NEVER skip |

### Workflow selection by task type

| Task | Required phases | May skip |
|------|-----------------|----------|
| Read-only investigation | 1 → 2 | 3–9 |
| Bug fix (single file, S) | 1→2→3→4→5→6→7→9 | 8 (batch the PR) |
| Bug fix (multi-file, M/L) | all 9 | — |
| New feature | all 9 + `graq_scaffold` at 5 | — |
| Refactor | all 9 | — |
| Hotfix P0 | 1→2→4→6→7→9 | 3 if time-critical (LOG the skip) |
| Graph health / tooling | 1→2→6→9 | 3,5,7,8 |
| UX / frontend audit | 1 → `graq_scorch_*` / `graq_phantom_*` → 9 | 3–5 if read-only |
| Release / publish | 7 → 8 → `graq_release_gate` → tag → publish → verify → 9 | — |

### Private → public ship sequence (ABSOLUTE — IP isolation)

1. `git fetch private`
2. branch from **`private/master`** (NEVER `origin/master`, NEVER public master)
3. develop + commit on the branch
4. push to **private**; open private PR → **owner merges** (sole approver)
5. only AFTER private merge: cherry-pick to public master → public PR → owner merges
6. tag + publish only after public PR merged

Never `git add`/`commit`/`push` on public master directly. Never open a public PR
before the private PR is merged. Never push a release tag before private merge.
