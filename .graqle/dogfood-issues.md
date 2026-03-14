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

### DF-001: Background scan duration_seconds is wildly wrong
- **Severity:** P2
- **Found:** 2026-03-14
- **Version:** v0.21.0
- **Status:** OPEN
- **Repro:** `graq scan all .` then `graq scan status`
- **Expected:** Duration shows ~1s (doc scan took <1s)
- **Actual:** Duration shows 3601.7s (1 hour off — likely UTC vs local time bug)
- **Workaround:** Ignore the duration field
- **Root cause:** `background.py` uses `time.mktime(time.strptime(...))` which converts UTC string to local time, then subtracts from `time.time()` (also local). The timezone offset creates a 1-hour error per hour of UTC offset.

### DF-002: No `graq inspect --stats` command
- **Severity:** P2
- **Found:** 2026-03-14
- **Version:** v0.21.0
- **Status:** OPEN
- **Repro:** `graq inspect --stats` or `graq scan inspect --stats`
- **Expected:** Shows graph statistics (node/edge counts by type, density, etc.)
- **Actual:** "No such command 'inspect'"
- **Workaround:** Read graqle.json directly with Python

### DF-003: `graq learn doc` accepts only one path
- **Severity:** P3
- **Found:** 2026-03-14
- **Version:** v0.21.0
- **Status:** OPEN
- **Repro:** `graq learn doc file1.md file2.md file3.md`
- **Expected:** Ingests all 3 files
- **Actual:** "Got unexpected extra arguments"
- **Workaround:** Run `graq learn doc` once per file, or use `graq learn doc <directory>/`

### DF-004: `graq init` has no non-interactive mode
- **Severity:** P3
- **Found:** 2026-03-14
- **Version:** v0.21.0
- **Status:** OPEN
- **Repro:** Try to automate `graq init` in CI or scripting
- **Expected:** `graq init --defaults` creates config with sensible defaults
- **Actual:** Always prompts interactively
- **Workaround:** Manually create `graqle.yaml`

---

## Resolved Issues

_None yet._

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
