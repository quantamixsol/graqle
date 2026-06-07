## GraQle tool inventory (all MCP tools, by role)

Every tool is also available with the `kogni_` prefix (backward-compat alias).

| Category | Tools | Purpose |
|----------|-------|---------|
| Investigation | `graq_context`, `graq_reason`, `graq_inspect`, `graq_lessons`, `graq_route`, `graq_reason_batch` | Understand before touching |
| Planning | `graq_plan`, `graq_preflight`, `graq_impact`, `graq_safety_check`, `graq_gate` | Govern before coding |
| Code generation | `graq_generate`, `graq_scaffold`, `graq_edit`, `graq_write`, `graq_read` | Write + apply changes |
| Validation | `graq_review`, `graq_test`, `graq_drace`, `graq_predict`, `graq_gate` | Verify correctness + safety |
| Learning | `graq_learn`, `graq_lessons`, `graq_lifecycle` | Record outcomes, prevent recurrence |
| Git / PR | `graq_git_branch`, `graq_git_commit`, `graq_git_diff`, `graq_git_status`, `graq_git_log`, `graq_github_pr`, `graq_github_diff` | Governed version control |
| Shell / files | `graq_bash`, `graq_glob`, `graq_grep` | File ops + builds |
| Observability | `graq_runtime`, `graq_scorch_*`, `graq_phantom_*` | Live logs + UX audits |
| Workflow | `graq_workflow`, `graq_reason_batch`, `graq_auto` | Multi-step orchestration |
| Compliance | `graq_gov_gate`, `graq_calibrate_governance`, `graq_release_gate`, `graq_config_audit` | Governance + EU AI Act gates |
| Session | `graq_lifecycle`, `graq_reload`, `graq_session_list`, `graq_session_resume`, `graq_session_compact`, `graq_memory` | Continuity + memory |

## Tool-selection rules (cheapest correct path first)

- **LOOKUP** (single named fact) → `graq_grep` / `graq_read`. ~100-500 tokens.
- **CROSS-CUT** (2-3 known entities) → `graq_context`. ~300-800 tokens.
- **IMPACT** ("what breaks if…") → `graq_impact`. ~800-1500 tokens.
- **REASONING** (why / how, multi-hop) → `graq_reason`. ~1500-3000 tokens.
- **PREFLIGHT** (about to change) → `graq_preflight`. ~500-1000 tokens.
- **LESSONS** (past mistakes) → `graq_lessons`. ~400-800 tokens.
- **UNKNOWN RISK** → `graq_safety_check` (chains impact+preflight+reason in 1).

Escalate, don't guess: if grep finds nothing, move up a tier — never fabricate.
