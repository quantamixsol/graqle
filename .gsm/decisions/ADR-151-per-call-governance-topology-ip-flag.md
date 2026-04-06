# ADR-151: Per-Call Governance Topology Injection — IP Flag

**Date:** 2026-04-04 | **Status:** FLAGGED FOR IP REVIEW
**Origin:** PR #12 research team review (Round 2, Senior Researcher, 88% confidence)
**Patent Reference:** EP26167849.4, Claims K-O (pending counsel mapping)

## Context

During S5 Phase 1 review of the `ReasoningCoordinator` skeleton (PR #12), the
research team independently identified a potentially novel architectural pattern:
**per-call governance topology injection**.

The pattern was flagged by the Senior Researcher at 88% confidence, with
unanimous agreement from 15/15 agents that it strengthens the GL-MAGR patent
narrative and is absent from LangGraph, CrewAI, and AutoGen architectures.

## The Pattern

`governance_topology` is passed as a **per-call parameter** to `decompose()`,
`dispatch()`, `synthesize()`, and `execute()` — it is never stored on the
coordinator instance.

This means governance constraints can change between calls without reconstructing
the coordinator. The coordinator is ephemeral (B2 constraint) and stateless with
respect to governance.

## Why This May Be Novel

Existing multi-agent frameworks (LangGraph, CrewAI, AutoGen) bind governance
constraints at construction time. Changing constraints requires rebuilding the
orchestrator. The per-call injection pattern enables:

- Hot-swapping governance rules mid-session
- Composable, context-dependent governance per query
- Stateless coordinators that are safe to pool and reuse

## What This ADR Does NOT Contain

Per GraQle Senior Developer guidance (48% → escalated to human):

- No internal topology representation details
- No weight parameters or dispatch algorithms
- No production rules or threshold values
- No claim-by-claim mapping (requires patent counsel)

The patent-vs-trade-secret boundary (TS-1..TS-4) must be resolved by legal
counsel before any detailed IP documentation is produced.

## Required Actions

- [ ] Route to research team for IP review
- [ ] Patent counsel maps pattern to Claims K-O specifically
- [ ] Determine minimum disclosure boundary (patent strengthening vs TS protection)
- [ ] Run `_check_ts_leakage()` on any detailed IP note before filing
- [ ] Decision: file CIP amendment, defensive publication, or internal-only note

## Consequences

**Positive:** Early flagging preserves priority date alignment with EP26167849.4.
**Negative:** None — this is a placeholder awaiting human IP review.
**Risk:** Delaying IP review past Phase 2 implementation could expose the pattern
in testable surface area before protection is in place.
