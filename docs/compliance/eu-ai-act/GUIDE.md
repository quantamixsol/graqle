# GraQle EU AI Act Layer — User Guide

> **Status:** available since graqle **0.75.0**. **Off by default.**
> **Honest framing:** this layer is a record-keeping / traceability **aid** that
> *supports* the EU AI Act (Reg. (EU) 2024/1689), especially its logging
> (Art. 12) and post-market-monitoring (Art. 72) expectations. It is **not a
> hard compliance wall**, and it is **not a substitute for human compliance
> judgement or legal advice**. GraQle does not certify your system as EU-AI-Act-aligned.

---

## What it is

When you turn it on, GraQle adds an **enforced compliance phase** to the
governance gate. For AIA-relevant **write** operations (code edits/generation),
it runs an **Article-14 human-oversight check** and keeps a **tamper-evident,
append-only audit trail** of compliance state changes and overrides.

Its enforcement state is held in an **irreversible latch** — a one-way switch:
once you enable it, it cannot be silently turned off, and you cannot quietly
weaken `blocking` to `advisory`. This is deliberate: a regulated operator should
not be able to disable their own controls without leaving a record.

## What it does NOT do

- It does **not** gate reads, planning, reasoning, or lifecycle tools — only
  AIA-relevant writes (`graq_edit`, `graq_write`, `graq_generate`, `graq_apply`).
- It does **not** block your work to save cost (cost is observability only).
- It does **not** make your system EU-AI-Act-compliant on its own. It provides
  signals, a switch, and an audit trail you can cite — the compliance
  responsibility remains yours.
- It cannot govern **native, non-GraQle** tools — those bypass the server phase
  (the Claude Code client wall covers that surface separately).

---

## Enabling it

### 1. Configure (`graqle.yaml`)

```yaml
governance:
  eu_ai_act:
    enabled: true            # default: false
    mode: blocking           # blocking | advisory   (default: blocking)
    risk_class: high         # high | limited | minimal   (default: high)
```

- **`mode: blocking`** — AIA-relevant writes with a supplied confidence below the
  human-review threshold are **refused** (with an override path).
- **`mode: advisory`** — the same situations are **recorded + advised**, never
  blocked. A good first step to see signal before enforcing.
- **`risk_class`** — `high` projects default to `blocking`; `limited` /
  `minimal` lean advisory. (Maps to the Act's risk tiers — see
  `docs/compliance/eu-ai-act/`.)

### 2. The latch

The first time the layer is enabled, GraQle records a **signed enable event** in
`.graqle/eu_ai_act_latch.jsonl` and generates a per-project signing key
(`.graqle/eu_ai_act_latch.key`, kept local, `0600`). From then on:

- **Upgrades are allowed:** `advisory → blocking`, raising `risk_class`.
- **Downgrades are refused:** `blocking → advisory`, or disabling — there is no
  "off" once it is on.
- **Tampering fails closed:** if the latch file is edited, the chain breaks, or
  the signing key is swapped, GraQle detects it and treats the layer as
  **enabled + blocking** (a tamper attempt can never disable it).

> The raw `enabled: false` in `graqle.yaml` cannot override a recorded latch —
> the gate reads the **latch**, not the yaml. The yaml is the *request*; the
> latch is the *enforced truth*.

---

## When a write is blocked

In `blocking` mode, if an AIA-relevant write supplies a confidence below the
review threshold, you get a refusal envelope like:

```json
{
  "error": "CG-EU-AIA_OVERSIGHT",
  "message": "EU AI Act blocking mode (high-risk): 'graq_edit' needs human
              oversight (Article 14) — confidence 0.40 is below the 0.75
              review threshold.",
  "remediation": "Re-run the same tool with an 'eu_aia_override_justification'
                  argument to proceed with a signed, audited override. ..."
}
```

### The audited override

A wrongly-blocked or human-reviewed action can proceed **once** by re-calling the
**same tool** with an `eu_aia_override_justification` argument:

```
graq_edit(..., eu_aia_override_justification="Reviewed by J. Smith (compliance);
          change is a formatting-only edit, no model-decision logic touched.")
```

This:
- **records a signed `override` event** in the latch chain (who/what/when/why),
- lets that **one** action through,
- **does NOT disable or downgrade the latch** — it stays exactly as strict.

The justification should name the human reviewer. (Note: at the MCP layer the
recorded actor is the client role, `mcp-client`; bind the human identity in your
justification text. Verified-identity binding is a planned enhancement.)

---

## The audit trail

`.graqle/eu_ai_act_latch.jsonl` is an **append-only, ed25519-signed, hash-chained**
log. Each entry records: the event kind (`enable` / `upgrade` / `override`), a
UTC timestamp, the mode/risk_class or justification, the previous hash (chain),
the signature, and the signing public key. This is what an auditor can inspect to
see *when* compliance was enabled, *whether* it was ever weakened (it can't be,
silently), and *every* override with its justification — supporting the Act's
record-keeping (Art. 12) and traceability expectations (Art. 72).

**Commit the latch file** to your repo so the audit trail travels with the code.
(Do not commit `eu_ai_act_latch.key` — it is the local signing seal.)

---

## FAQ

**Can I turn it off if I change my mind?**
No — by design. The latch is one-way. If you need an exception for a specific
action, use the audited override; it records the exception rather than removing
the control.

**Does enabling it slow down my normal work?**
No. It only evaluates AIA-relevant write tools, and only when enabled. Reads,
planning, and reasoning are untouched. If the phase ever cannot evaluate, it
**allows** (fails safe for usability) — it never blocks routine work by accident.

**Is this legal compliance?**
No. It is an engineering aid that helps you *produce the records and oversight
signals* the Act expects. Consult your compliance/legal team for actual
conformity.
