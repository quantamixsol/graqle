## Cost-optimisation rules

| Rule | Why |
|------|-----|
| `graq_safety_check` replaces `graq_impact` + `graq_preflight` + `graq_reason` when risk is unknown | 3 calls → 1 |
| `graq_review(focus="security")` on the FINAL pass only | full `focus="all"` is multi-agent; security-only is light |
| `graq_reason` only when `graq_safety_check` returns MEDIUM/HIGH | `graq_context` is far cheaper for the rest |
| `graq_plan(dry_run=true)` to satisfy CG-02 before `graq_bash` | unlocks shell without full DAG cost |
| `graq_predict(fold_back=false)` | don't write to the graph unless confidence is high |
| Skip `graq_scaffold` for bug fixes | only for new modules / endpoints |
| One PR per logical group of related changes | fewer sentinel chains = lower cost |
| Cheapest correct tool tier first (LOOKUP → CROSS-CUT → IMPACT → REASONING) | never `graq_reason` a grep-answerable question |

Honour `graqle.yaml` cost ceilings: `cost.budget_per_query`,
`hard_ceiling_multiplier`. The server-side gate enforces these for every client.
