# ADR-118: graq_plan — Plan-as-Graph Primitive
**Date:** 2026-03-27 | **Status:** ACCEPTED

## Context
graq_reason (82%) and graq_predict (79%) converged on the same diagnosis: the missing capability that gates governance enforcement, orchestration, and autonomy is **plan-as-graph** — storing execution plans as KG subgraphs that the reasoning engine can reason *about*.

Current state before this ADR:
- `graq_workflow` executes a predefined step list you provide — it cannot decompose goals
- Planning and execution were conflated — no reviewable plan before execution
- No pre-cost estimation, no dependency-ordered steps, no governance checkpoints

## Decision
Add `graq_plan` as a **read-only** MCP tool that:
1. Accepts a `goal` string
2. Runs `graq_impact` to discover affected modules and files
3. Uses graph topology (impact_radius, CALLS/IMPORTS edges) to order steps
4. Assigns `risk_level` (LOW/MEDIUM/HIGH/CRITICAL) per step based on impact_radius and _WRITE_TOOLS membership
5. Inserts `GovernanceCheckpoint` before any step requiring approval
6. Estimates cost from `TASK_RECOMMENDATIONS` routing metadata
7. Emits a reviewable `ExecutionPlan` — does NOT execute anything
8. Writes `ExecutionPlan` as a KG node so future reasoning can reason *about the plan itself*

**Separation of concerns:** `graq_plan` produces the plan. `graq_workflow` executes it. The caller reviews the plan between the two calls.

## Consequences

**Positive:**
- Planning is now governed: every high-risk change has a reviewable DAG before execution
- Plans stored in KG enable reasoning about planned changes (meta-reasoning)
- `GovernanceCheckpoint` objects are the first step toward blocking governance enforcement
- dry_run=True mode enables fast plan preview without graph analysis
- `GOAL_DECOMPOSITION` skill registered in coding ontology — enables skill-based routing of planning tasks

**Negative / Trade-offs:**
- Two-step flow (plan → review → execute) adds friction for simple changes
- Plan quality depends on impact analysis accuracy — sparse graphs produce weaker plans
- Full plan requires a loaded KG (`dry_run=False`); read-only deployments get skeleton plans only

## New Types (graqle/core/plan.py — zero blast radius)
- `PlanStep`: step_id, tool, description, args, depends_on, risk_level, requires_approval, gate_name, estimated_cost_usd
- `GovernanceCheckpoint`: checkpoint_id, before_step_id, check_type, description, blocking
- `ExecutionPlan`: goal, plan_id, steps, checkpoints, risk_level, estimated_cost_usd, affected_files, affected_modules, requires_approval, decomposition_confidence

## Ontology Updates
- Skill: `GOAL_DECOMPOSITION` (13th skill)
- Entity: `ExecutionPlan` with required: [goal, plan_id]
- Relationship: `PLANNED_BY` (CodeModule/Function/Class/Change → ExecutionPlan)
- Output gate: `validate_plan_format` (checks: plan_id non-empty, DAG acyclic, HIGH steps have checkpoints)

## What This Unlocks
Per graq_predict (79% confidence), graq_plan is the load-bearing primitive for:
1. **Governance enforcement** (Phase B) — gates can now block based on plan risk_level
2. **WorkflowOrchestrator** (Phase D) — graq_workflow can consume ExecutionPlan DAGs
3. **Self-governing autonomy** (Phase 5) — agents can reason about plans before executing
