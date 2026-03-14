# Graqle Dogfood Issues — "Evolving Graqle with Graqle"

> Track all issues found while dogfooding Graqle on its own codebase.
> Each issue gets a severity, repro, and is passed to the SDK team for resolution.
> DO NOT mix these with product/feature work — these are SDK bugs/improvements only.

---

## Issue Format

```
### DF-NNN: [Title]
- **Severity:** P1 (blocks work) | P2 (workaround exists) | P3 (cosmetic/nice-to-have)
- **Found:** YYYY-MM-DD
- **Version:** v0.X.Y
- **Status:** OPEN | INVESTIGATING | FIXED (vX.Y.Z) | WONTFIX
- **Repro:** [exact command or steps]
- **Expected:** [what should happen]
- **Actual:** [what happened]
- **Workaround:** [if any]
- **Fix PR/Commit:** [link when fixed]
```

---

## Setup Notes (v0.21.0 — 2026-03-14)

- Graph: 3,926 nodes, 7,293 edges (code + JSON + docs + ADRs)
- Scan time: ~3s code, <1s JSON, <1s docs
- Platform: Windows 11, Python 3.10
- Config: graqle.yaml (anthropic backend, haiku, simple embeddings)

---

## Open Issues

_None — all resolved in v0.21.1._

---

## Resolved Issues

### DF-001: Background scan duration_seconds is wildly wrong
- **Severity:** P2
- **Found:** 2026-03-14
- **Version:** v0.21.0
- **Status:** FIXED (v0.21.1)
- **Repro:** `graq scan all .` then `graq scan status`
- **Expected:** Duration shows ~1s (doc scan took <1s)
- **Actual:** Duration shows 3601.7s (1 hour off — UTC vs local time bug)
- **Root cause:** `background.py` used `time.mktime(time.strptime(...))` which interprets UTC string as local time. `calendar.timegm()` is the correct function for UTC parsing.
- **Fix:** Replaced `time.mktime()` with `calendar.timegm()` in `background.py`.

### DF-002: No `graq inspect --stats` command
- **Severity:** P2
- **Found:** 2026-03-14
- **Version:** v0.21.0
- **Status:** WONTFIX (user error)
- **Resolution:** Command exists as `graq inspect --stats` (top-level command). Was tested as `graq scan inspect --stats` which doesn't exist. Correct usage: `graq inspect` or `graq inspect --stats`.

### DF-003: `graq learn doc` accepts only one path
- **Severity:** P3
- **Found:** 2026-03-14
- **Version:** v0.21.0
- **Status:** FIXED (v0.21.1)
- **Repro:** `graq learn doc file1.md file2.md file3.md`
- **Expected:** Ingests all 3 files
- **Actual:** "Got unexpected extra arguments"
- **Fix:** Changed `path: str` argument to `paths: list[str]` — now accepts multiple file and directory paths. Results are merged across all inputs.

### DF-004: `graq init` has no non-interactive mode
- **Severity:** P3
- **Found:** 2026-03-14
- **Version:** v0.21.0
- **Status:** WONTFIX (already implemented)
- **Resolution:** `graq init --no-interactive` already exists (with `--backend`, `--model` flags). Also auto-detects non-TTY stdin and switches to non-interactive mode automatically.

---

## Feature Requests (from dogfooding)

_Captured here, triaged to plan phases._

---

## Observations

_Running notes on UX, performance, surprises._

- 2026-03-14: Initial setup required manual graqle.yaml creation — `graq init` is interactive-only, no `--non-interactive` flag. (Potential P3: add `graq init --defaults` for CI/dogfood scenarios)
- 2026-03-14: `graq learn doc` accepts only one path arg — had to loop for multiple files. (Potential P3: accept multiple paths)
- 2026-03-14: `graq scan all` duration field shows 3601.7s for a 1s scan — time calculation bug in background scan? (Potential P2: investigate `duration_seconds` computation)
- 2026-03-14: `graq scan inspect --stats` doesn't exist — no built-in way to see graph stats from CLI. (Potential P2: add `graq inspect --stats`)
