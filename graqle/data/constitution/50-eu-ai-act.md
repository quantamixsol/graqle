## EU AI Act compliance (configurable — off by default)

> Status: design ratified (ADR-222), enforcement phases pending. This section is
> the contract; the gate is wired in a later release. When OFF (the default),
> none of this applies.

GraQle can enforce EU AI Act (Reg. (EU) 2024/1689) obligations for a project via
`graqle.yaml`:

```yaml
governance:
  eu_ai_act:
    enabled: false              # off by default
    mode: blocking | advisory   # default: blocking when risk_class == high
    risk_class: high | limited | minimal
```

- **risk_class default mapping:** `high` → blocking; `limited` → advisory
  (transparency checks only); `minimal` → off. Profiling of natural persons
  forces `high`.
- **What blocking gates (NARROW scope):** only AI-Act-relevant artifacts —
  risk-management record (Art. 9), automatic logging (Art. 12), instructions-for-
  use / transparency (Art. 13, 50), human-oversight hook + stop control (Art. 14),
  declared accuracy metrics (Art. 15), post-market-monitoring plan (Art. 72).
  Routine dev ops (tests, formatting, reads) are NEVER AI-Act-blocked.
- **Date-aware:** obligations are not hard-blocked before their legal effective
  date (most high-risk + transparency: 2 Aug 2026; Annex-I product route under
  Art. 6(1): 2 Aug 2027) — advisory until then, then auto-escalate.
- **Irreversibility (latch):** once `enabled: true`, the switch cannot be turned
  off and `blocking` cannot be downgraded to `advisory`. The latch is a
  tamper-evident, cryptographically-signed record — not a plain yaml flag.
- **Override:** a wrongly-blocked action may proceed ONCE via an audited, signed,
  logged per-action justification — this is NOT a downgrade; the latch stays on.

> **Framing rule (honest):** the irreversible latch is a GraQle design that
> SUPPORTS the Act's record-keeping / traceability expectations. The Act does NOT
> itself require an un-disableable switch. Never document it as "required by the
> Act".
