# GSD PLAN: Graqle Monetization v1
**Branch:** feature-monetization
**Created:** 2026-03-26
**Zero-regression guarantee:** STRICT — all 2024+ existing tests must pass

---

## Context

### What we're building
Frictionless FREE→TEAM conversion path inside the Graqle SDK CLI + Studio:
- FREE: BYOK solo dev, local JSON graph, unlimited local queries
- TEAM: cloud sync to Neptune + S3, cross-project reasoning, Studio visualization, shared lessons

### What already exists (do NOT break)
- `graqle/licensing/manager.py` — HMAC license keys, tier checks, `require_license()` decorator
- `graqle/cloud/plans.py` — plan limits per tier
- `graqle/cloud/credentials.py` — `~/.graqle/credentials.json` API key storage
- `graqle/cli/commands/cloud.py` — `graq cloud push/pull/status` + Neptune sync (already gated on `creds.plan in ("team","enterprise")`)
- `graqle/connectors/neptune.py` — `upsert_nodes`, `upsert_edges`, `check_neptune_available`, IAM auth

### Key insight from research
Neptune sync already exists and is already gated — `auto_cloud_sync()` already calls Neptune for team plan.
The gap is: (1) no cloud API key → no `creds.is_authenticated` → Neptune never called.
The fix is to set up cloud credentials pointing to Neptune directly (Team plan users with license key bypass S3 presign requirement).

---

## Success Criteria (binary pass/fail)

- [ ] `graq cloud push` from graqle-sdk syncs graph to Neptune — verifiable via `graq_inspect` or Neptune health endpoint
- [ ] Studio at `localhost:3000` shows the pushed graph live
- [ ] `graq run "question"` on FREE tier shows upgrade nudge when cross-project node count > threshold
- [ ] `graq scan` auto-pushes to Neptune after completing if Team license present
- [ ] Studio chat sends `graq_reason` queries and shows result inline (MCP passthrough)
- [ ] Full test suite: 0 regressions (2024+ passing tests must remain passing)

---

## Implementation Phases

### PHASE 1: Neptune Direct Push (TODAY — dogfooding test)
**Goal:** Push graqle-sdk graph to Neptune right now, verify in Studio
**Zero new code needed** — use what already exists

- [T1.1] Set `~/.graqle/credentials.json` with `plan: "team"` and a dummy API key
- [T1.2] Configure Neptune env vars (NEPTUNE_ENDPOINT, NEPTUNE_REGION, NEPTUNE_IAM_AUTH)
- [T1.3] Run `graq cloud push` from graqle-sdk dir
- [T1.4] Verify Neptune has nodes via health endpoint
- [T1.5] Open Studio, verify graph appears
**Complexity:** S | **Verification:** `check_neptune_available()` returns True + node count > 0

---

### PHASE 2: Auto-sync on scan/grow/learn (Team license = auto-push)
**Goal:** Any `graq scan`, `graq grow`, `graq learn` automatically pushes to Neptune if Team license active
**Files:** `graqle/cli/commands/scan.py`, `graqle/cli/commands/grow.py`, `graqle/cli/commands/learn.py`

- [T2.1] Read current `auto_cloud_sync()` call pattern in scan.py
- [T2.2] Add license-aware Neptune-direct sync: if `has_feature("cloud_sync")` → bypass S3 presign, call Neptune directly
- [T2.3] Silent by default (no output unless verbose), non-blocking (try/except wraps it)
- [T2.4] Add `neptune_sync_on_write()` helper in `graqle/connectors/neptune.py`
**Complexity:** M | **Verification:** Run `graq grow` → check Neptune node count increased

---

### PHASE 3: CLI Upgrade Nudges (5 key moments)
**Goal:** FREE users see a single, non-blocking nudge at the right CLI moments
**Files:** `graqle/cli/commands/scan.py`, `graqle/cli/main.py`, `graqle/cli/commands/cloud.py`
**Rule:** Nudge shows ONCE per session, AFTER the command completes (never interrupts), suppressed in non-TTY

| Moment | Trigger | Nudge |
|--------|---------|-------|
| `graq scan` completion | node_count > 400 (80% of 500 free limit) | "Your graph has {N} nodes. Team plan stores unlimited nodes + syncs to cloud." |
| `graq run` / `graq reason` | answer_confidence < 0.5 | "Reasoning over 1 project. Team plan enables cross-project reasoning for higher confidence." |
| `graq cloud push` | plan=free (blocked) | "Cloud sync requires Team plan. graqle.com/pricing" |
| `graq learn` | 10th lesson learned | "You've taught Graqle {N} lessons. Team plan syncs lessons across your whole team." |
| `graq doctor` | no license key found | "You're on Free tier. graq activate --key YOUR_KEY to unlock Team features." |

- [T3.1] Add `_show_upgrade_nudge(moment, context)` helper in `graqle/cli/console.py`
- [T3.2] TTY detection: `sys.stdout.isatty()` — skip nudges in CI/pipes
- [T3.3] Session deduplication: `os.environ["_GRAQ_NUDGE_SHOWN"]` flag — show max once per session
- [T3.4] Wire nudges into 5 CLI commands (additive only, no logic change)
- [T3.5] Add tests: nudge appears when triggered, suppressed in non-TTY, suppressed after first show
**Complexity:** M | **Verification:** `graq scan` on 450-node graph shows nudge; pipe to file → no nudge

---

### PHASE 4: Studio Chat → graq command execution (MCP passthrough)
**Goal:** Studio chat input executes `graq_reason`, `graq_context`, `graq_predict` etc. and shows result inline
**Files:** `graqle-studio/` (Next.js) + `graqle/server/app.py`

- [T4.1] Audit current Studio chat implementation — what does it call today?
- [T4.2] Add `/api/graq` passthrough endpoint in `app.py` → routes to MCP tool handler
- [T4.3] Studio chat: detect `graq:reason`, `graq:predict`, `graq:context` prefixes in input
- [T4.4] Studio chat: render structured tool response (nodes, confidence, reasoning trace)
- [T4.5] Neptune-backed queries: Studio queries go to Neptune (if available) not local JSON
**Complexity:** L | **Verification:** Type "graq:reason what modules are high risk?" in Studio chat → see answer

---

### PHASE 5: Cross-project reasoning in Studio
**Goal:** When multiple projects are synced to Neptune, Studio can query across all of them
**Files:** `graqle/connectors/neptune.py`, `graqle/server/app.py`, Studio

- [T5.1] Sync all 3 projects (graqle-sdk, graqle-studio, cognigraph-deprecation) to Neptune
- [T5.2] `cross_project_search()` already exists in neptune.py — wire it to `/api/reason` endpoint
- [T5.3] Studio project selector: "All projects" option that triggers cross-project query
- [T5.4] Response shows source project for each node
**Complexity:** L | **Verification:** Studio cross-project query returns nodes from 2+ projects

---

## Zero-Regression Strategy

1. **All new code is additive** — no existing function signatures change
2. **License checks use `has_feature()` not hard blocks** — graceful fallback to local
3. **Neptune sync is always try/except wrapped** — failure = silent skip, never crash
4. **Nudges are post-completion, TTY-gated** — cannot break piped or CI usage
5. **Test coverage per task** — each task has a paired test before marking done
6. **Run `python -m pytest tests/ -x -q` after each phase before starting next**

---

## Dependency Order

```
T1 (verify push works) → T2 (auto-sync) → T3 (nudges) → T4 (Studio chat) → T5 (cross-project)
```
T1 is independent infrastructure test.
T2-T3 are parallel (different files).
T4-T5 depend on T1 (need Neptune populated).

---

## Files To Touch Per Phase

| Phase | Files | New Files |
|-------|-------|-----------|
| T1 | ~/.graqle/credentials.json (config only) | none |
| T2 | scan.py, grow.py, learn.py, neptune.py | none |
| T3 | console.py, scan.py, main.py, cloud.py, learn.py | test_nudges.py |
| T4 | app.py, Studio chat component | none (extend existing) |
| T5 | neptune.py, app.py, Studio project selector | none |
