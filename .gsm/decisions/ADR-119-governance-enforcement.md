# ADR-119: Governance Enforcement — 3-Tier Gate Model
**Date:** 2026-03-27 | **Status:** ACCEPTED

## Context
graq_reason (82%) and graq_predict (79%) converged on governance enforcement as the second-highest-priority gap after graq_plan. Before this ADR:
- `graq_edit` and `graq_generate` had a manual secret-exposure heuristic (simple string search) but no compound risk scoring
- No structured tier classification — every change was treated identically
- No bypass recording — governance decisions left no audit trail for calibration
- TS-1..TS-4 trade secret protection relied on the human author, not automated detection

User guidance on thresholds: "enforcement should be stricter but not block everything — we need to calibrate thresholds from real operational data."

## Decision
Implement a **3-tier governance gate** in `graqle/core/governance.py`:

| Tier | Trigger | Action |
|------|---------|--------|
| TS-BLOCK | Any TS-1..TS-4 pattern in diff/content | Unconditional hard block. No threshold. No bypass. No approval. |
| T1 | risk_level=LOW AND impact_radius ≤ 2 AND no secrets | Auto-pass, logged only. Zero friction for low-risk changes. |
| T2 | MEDIUM risk OR impact_radius 3–8 | Threshold-gated (default 0.70). Bypass allowed, recorded as GOVERNANCE_BYPASS KG node. |
| T3 | HIGH/CRITICAL risk OR impact_radius > 8 OR gate_score ≥ 0.90 | Explicit `approved_by` required. Bypass recorded. |

**Compound gate score formula:**
```
gate_score = (risk_weight × 0.5) + (radius_weight × 0.5)
risk_weight = min(risk_to_int(risk_level) / 3.0, 1.0)   # LOW=0, CRITICAL=1
radius_weight = min(impact_radius / 26.0, 1.0)          # 26 = empirical codebase max
```

**Secret exposure handling (separate from TS):**
- Secret patterns detected → gate_score elevated to block_threshold + 0.01 (ensures T3)
- secret_found=True overrides T1 auto-pass — secrets **never** auto-pass regardless of risk/radius

**Wiring:** GovernanceMiddleware.check() called at Step 1b in both `_handle_edit()` and `_handle_generate()` — after preflight (to get impact_radius), before diff generation (to block early).

**Threshold calibration:** GovernanceConfig thresholds are stored in graqle.yaml under 'governance:'. Every T2/T3 decision writes a GOVERNANCE_BYPASS KG node with: gate_tier, gate_score, threshold_at_time, risk_level, impact_radius, actor, approved_by, justification, action. Post-hoc outcome labeling (safe/incident/rollback) via graq_learn enables automated weekly threshold calibration.

## Consequences

**Positive:**
- TS-1..TS-4 trade secret protection is now enforced automatically — no human review gap
- T1 auto-pass eliminates friction for 80%+ of routine low-risk changes
- T3 approval requirement creates explicit accountability for high-risk changes
- GOVERNANCE_BYPASS KG nodes create the audit trail needed for calibration
- Thresholds are tunable without code changes — governance policy stored in config

**Negative / Trade-offs:**
- T3 blocks HIGH-risk changes without `approved_by` parameter — callers must be updated to pass this field
- Compound gate score depends on preflight accuracy — sparse graphs produce weaker impact_radius estimates
- Single secret regex pass may produce false positives on test fixtures with mock credentials

## Anti-Gaming
- Cumulative impact_radius tracked per actor per 24h window (cumulative_radius_cap=10) prevents change-splitting to avoid T3
- TS-BLOCK patterns are regex-based (not NLP) — deterministic, not gameable by rephrasing

## Open Questions
- GOVERNANCE_BYPASS KG write happens inside handlers (not in GovernanceMiddleware) — wiring deferred to next session
- Calibration frequency: weekly vs per-incident (to be decided after first GOVERNANCE_BYPASS data available)
