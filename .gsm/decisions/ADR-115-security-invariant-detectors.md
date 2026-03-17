# ADR-115: Security Invariant Detectors + Source Parity Check Roadmap

**Date:** 2026-03-17 | **Status:** ACCEPTED

**Context:**
External feedback from CBS Delivery & Trafficking project (multi-Lambda AWS project) revealed a class of bugs that Graqle's existing intelligence pipeline cannot detect: security vulnerabilities and infrastructure drift. Specifically:
1. A deployed Lambda feature was silently lost because source files were never committed to git
2. No compile-time detection for hardcoded secrets, SQL injection, missing rate limits, open CORS
3. No mechanism to compare deployed infrastructure against source code

**Decision:**
Split into three tiers:

**Tier 1 (IMPLEMENTED — this ADR):** Add 6 security invariant detectors to the compile pipeline. These run alongside the existing 6 data flow detectors in `invariants.py`:
- Hardcoded secrets (API keys, passwords, tokens, connection strings, private keys) — severity: critical
- SQL injection risk (string concatenation/interpolation in SQL queries) — severity: warn
- Missing rate limits (API route modules without throttling config) — severity: info
- Open CORS wildcard (Access-Control-Allow-Origin: *) — severity: warn
- Insecure HTTP (non-localhost HTTP URLs) — severity: warn
- Exposed environment variables (logging or returning process.env/os.environ) — severity: critical

**Tier 2 (FUTURE — separate ADR-116):** `graq drift` CLI command that calls cloud APIs to compare deployed infrastructure against source. AWS-first, plugin architecture for GCP/Azure. Requires boto3 + credentials, runs as a separate command (not part of compile).

**Tier 3 (FUTURE):** Continuous drift monitoring via CI/CD, pre-deploy hooks in Claude Code, multi-cloud provider plugins.

**Implementation:**
- All 6 detectors added to `graqle/intelligence/invariants.py`
- Called from `detect_invariants()` which is already wired into compile.py Phase 3c
- Test files are automatically excluded (paths containing `/test`, `test_`, `_test.`)
- Results deduplicated per module+type to avoid noise
- Generalized patterns work for Python, JavaScript/TypeScript, Go, and other languages

**Consequences:**
- Positive: Catches OWASP top-10 class vulnerabilities at compile time, zero runtime cost
- Positive: Works for any codebase language (regex-based, not AST-specific)
- Positive: Insights visible in Studio Intelligence dashboard alongside existing insights
- Positive: Fails gracefully — errors don't break compile pipeline
- Negative: Regex-based detection has false positives — severity is "info"/"warn", not blocking
- Negative: Cannot detect infrastructure drift (Tier 2 scope)
- Risk: Test files are skipped, but example code or documentation may trigger false positives
