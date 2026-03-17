# ADR-114: Compile-Time Invariant Detector

**Date:** 2026-03-17 | **Status:** ACCEPTED

**Context:**
Three production failures in one session traced to the same root cause: code writes data but nothing reads it back, or code reads from a source that returns stale/wrong data. Specifically:
1. Stripe webhook writes tier to Cognito groups → login never reads it back (hardcodes `graqle-free`)
2. IAM policy has SignUp permission → but AdminListGroupsForUser was missing (silent failure)
3. Auth store uses `graqle-free` format → billing page expects `free` format (crash)

None of these were caught by two full audit rounds because audits check "does it render" not "is the data flow correct." Graqle's current intelligence pipeline detects structural issues (missing chunks, dangling edges, risk scores) but NOT data flow invariant violations.

**Decision:**
Add an invariant detector to the intelligence compile pipeline (Phase 3b, after edge resolution). It runs automatically during `graq compile` and produces `invariant_violation` insights alongside existing insight types.

**Phase 1 — Scanner Annotations:** During chunk extraction, tag chunks with data flow annotations: WRITES_TO, READS_FROM, HARDCODES, CALLS_API, CREDENTIAL_PATTERN. These are regex-based, language-aware patterns.

**Phase 2 — Invariant Detector:** Graph-level analysis that queries annotated chunks to find:
- Write-without-read: Store X is written but never read
- Read-without-write: Store X is read but never written
- Format mismatch: Same concept uses different string formats
- Credential inconsistency: Same SDK client uses different credential patterns
- One-way integration: API endpoint exists but no frontend calls it
- Hardcoded dynamic value: Value is hardcoded where a dynamic source exists

**Implementation location:** New file `graqle/intelligence/invariants.py` called from `compile.py` after Phase 3b edge resolution. Uses existing `FileIntelligenceUnit` data — no scanner changes needed in Phase 1 because chunk text already contains the raw code. The detector uses regex on chunk text to find patterns.

**Consequences:**
- Positive: Catches the exact class of bugs that caused today's failures
- Positive: Runs at compile time (not runtime) — zero performance cost to users
- Positive: Generic patterns work for any codebase (Python, JS/TS, Go)
- Positive: Produces insights visible in Studio Intelligence dashboard
- Negative: Regex-based detection has false positives — severity should be "suggestion" not "error"
- Risk: Must not break existing compile pipeline — fail gracefully on detection errors
