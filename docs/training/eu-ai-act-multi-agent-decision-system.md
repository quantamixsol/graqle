# Training Module — Building an EU AI Act-Compliant Multi-Agent Decision System with GraQle

> A 10-chapter, hands-on course. By the end you can stand up a governed,
> auditable, multi-agent decision system whose development and operation *support*
> the EU AI Act (Reg. (EU) 2024/1689).
>
> **Honesty up front (you will repeat this to your stakeholders):** GraQle is an
> engineering aid that helps you produce the **records, oversight signals, and
> traceability** the Act expects. It does **not** certify compliance and is not
> legal advice. Conformity is a human + legal responsibility; GraQle makes the
> evidence trail and the guardrails practical.

**Prerequisites:** Python ≥ 3.10, `pip install graqle` (≥ 0.75.0), an LLM backend
key (or local Ollama), basic familiarity with a terminal. No prior GraQle
experience assumed.

**How to use this module:** each chapter has *Concept → Do it → Check → Why it
maps to the Act*. Work in a scratch repo you don't mind throwing away.

---

## Chapter 1 — Why governance is the product, not a feature

**Concept.** A "decision system" that affects people (credit, hiring, triage,
moderation) is, under the Act, often **high-risk**. The expensive part is never
the model call — it's proving *how* a decision was reached, that a human could
oversee it, and that you kept records. GraQle's thesis: make the **graph of your
architecture** the substrate so reasoning, impact, oversight, and audit all hang
off one source of truth.

**Do it.**
```bash
mkdir decision-system && cd decision-system
git init
graq init .            # writes graqle.yaml + the governance constitution
graq doctor            # health check
```

**Check.** Open `CLAUDE.md` (or `AGENTS.md` for Codex). You should see the
governance constitution — the rulebook your AI assistant now follows.

**Act mapping.** Art. 9 (risk management as a *continuous* process) starts the
moment you treat governance as the frame, not an afterthought.

---

## Chapter 2 — Model your decision system as a knowledge graph

**Concept.** Agents, data sources, decision rules, and outputs are *nodes*; their
calls and dependencies are *edges*. Reasoning over the graph beats reading files.

**Do it.** Sketch the system as small modules, then build the graph:
```bash
# e.g. ingestion.py, risk_score.py, human_review.py, decision.py, audit_log.py
graq scan repo .
graq inspect --stats          # node/edge counts
graq context risk_score       # 500-token focused view of one component
```

**Check.** `graq inspect --stats` shows your modules as typed nodes.

**Act mapping.** Art. 11 / Annex IV (technical documentation): a queryable
architecture map is the backbone of the technical file.

---

## Chapter 3 — The multi-agent decision loop

**Concept.** A decision system is rarely one prompt. GraQle runs **graph-of-agents
reasoning**: multiple agents activate over the relevant nodes, debate, and
converge — with a **confidence score** and an **evidence trail**.

**Do it.**
```bash
graq run "Given applicant features X, should we approve? Explain the factors."
```
Observe the answer's `answer_confidence`, the **activated nodes**, and the
evidence pointers.

**Check.** You get a confidence score and *which* nodes drove the answer — not a
black-box yes/no.

**Act mapping.** Art. 13 (transparency to deployers): the output is interpretable;
you can show *why*.

---

## Chapter 4 — Confidence, thresholds, and human-in-the-loop

**Concept.** Article 14 is about **effective human oversight**. The practical
hook: low-confidence decisions should route to a human. GraQle exposes
`answer_confidence` and a review threshold so you can wire that rule.

**Do it.** In `graqle.yaml`:
```yaml
governance:
  human_review_required_threshold: 0.75   # below this -> human oversight expected
```
In your decision code, branch on confidence: ≥ threshold → auto-path with
logging; < threshold → human-review queue.

**Check.** Feed a deliberately ambiguous case; confirm it routes to review.

**Act mapping.** Art. 14(4): the overseer can *correctly interpret output* and
*decide not to use / override* it — your threshold makes that routing real.

---

## Chapter 5 — Turn on the EU AI Act layer (advisory first)

**Concept.** GraQle's EU AI Act layer is **off by default**. Start in **advisory**
mode to see signal without blocking anything.

**Do it.**
```yaml
governance:
  eu_ai_act:
    enabled: true
    mode: advisory        # observe, don't block, first
    risk_class: high
```
Run a development session through GraQle's governed tools (`graq_edit`, etc.).

**Check.** AIA-relevant writes now carry an advisory note + are recorded; nothing
is blocked.

**Act mapping.** Art. 9 (risk management) + Art. 12 (record-keeping): you begin
generating the event log before you enforce.

> **The latch is one-way.** Enabling records a signed event in
> `.graqle/eu_ai_act_latch.jsonl`. You can later *upgrade* to `blocking`, but you
> can never silently turn it off — by design. Read the
> [EU AI Act Guide](../compliance/eu-ai-act/GUIDE.md) before you flip `enabled: true`.

---

## Chapter 6 — Enforce: blocking mode + the audited override

**Concept.** Once you trust the signal, move to **blocking**. Now a low-confidence
AIA-relevant write is *refused* — unless a human records an audited override.

**Do it.**
```yaml
governance:
  eu_ai_act:
    enabled: true
    mode: blocking
    risk_class: high
```
Trigger a low-confidence write; you'll get a `CG-EU-AIA_OVERSIGHT` refusal. Then
proceed *with* oversight:
```
graq_edit(..., eu_aia_override_justification="Reviewed by A. Khan (compliance):
          rule change validated against test set; proceeding under Art.14 oversight.")
```

**Check.** The override appears as a signed `override` event in the latch chain;
the latch stays `blocking`.

**Act mapping.** Art. 14 (human oversight) made operational: the system blocks,
the human decides, and the decision is recorded — exactly the oversight loop the
Act describes.

---

## Chapter 7 — The tamper-evident audit trail

**Concept.** Records only matter if they can't be quietly altered. The latch is an
**ed25519-signed, hash-chained, append-only** log; editing it breaks the chain
and the layer fails closed.

**Do it.**
```bash
cat .graqle/eu_ai_act_latch.jsonl     # inspect the chain (URLs/hashes only)
# try editing one line, then run any governed write — GraQle flags tamper, fails closed
git add .graqle/eu_ai_act_latch.jsonl  # COMMIT the trail (not the .key)
```

**Check.** A hand-edit is detected; the layer treats the system as still enabled.

**Act mapping.** Art. 12 (automatic, lifetime logging) + Art. 72 (post-market
monitoring): a tamper-evident trail is what an auditor expects to see.

---

## Chapter 8 — Keep the regulation current (EUR-Lex drift)

**Concept.** The Act and its references evolve. GraQle's **EUR-Lex drift guard**
hashes the authoritative URLs your docs cite and flags when the regulator-side
content changes.

**Do it.** Reference the law in `docs/compliance/`, then baseline it:
```bash
graq compliance eur-lex-refresh        # fetch + hash + write the baseline
# CI then re-checks weekly and files an issue if the source drifts
```

**Check.** A drift report shows `has_drift: False` against your baseline.

**Act mapping.** Art. 9 (continuous review/update): you get a signal when the
*regulation itself* moves, not just your code.

---

## Chapter 9 — Multi-client, multi-agent governance everywhere

**Concept.** Your team uses different AI tools. GraQle renders the **same
constitution** into each (`CLAUDE.md`, `AGENTS.md` for Codex, `.cursorrules`,
`.windsurfrules`) and enforces the **same server-side gate** for every MCP client
— so a Codex user and a Claude user are governed identically.

**Do it.**
```bash
graq init . --ide codex     # writes AGENTS.md + registers the MCP server
graq gate-install           # Claude Code hard wall (defense-in-depth)
```

**Check.** Every client's instruction file carries the full rulebook; the
server-side CG gates apply regardless of client.

**Act mapping.** Consistent oversight across the whole human+AI team is what makes
the Art. 14 story credible at organisational scale.

---

## Chapter 10 — Ship, prove, and operate

**Concept.** Compliance is a lifecycle, not a release. Tie it together: the
graph (architecture), the confidence routing (oversight), the latch (enforced +
auditable), the drift guard (currency), and the constitution (consistent
practice).

**Do it — an operating checklist.**
1. **Build-time:** all changes through governed tools; risk-relevant writes pass
   the Article-14 check; overrides recorded.
2. **Decision-time:** route low-confidence decisions to humans; log every
   decision with its confidence + activated nodes.
3. **Record-keeping:** commit the latch chain; export the audit trail for your
   technical file.
4. **Monitoring:** watch EUR-Lex drift; re-baseline on regulator changes;
   periodically review override frequency (a spike = a process smell).
5. **Honesty:** present GraQle as *supporting* the Act's traceability — never as
   certification.

**Check.** You can answer, with evidence: *How was this decision made? Could a
human oversee it? Where is the record? Has the regulation changed?*

**Act mapping.** The full loop — Art. 9, 12, 13, 14, 72 — backed by artifacts you
can show, not claims you assert.

---

## Appendix — Command & config quick reference

| Goal | How |
|------|-----|
| Initialise a governed project | `graq init .` |
| Build/refresh the graph | `graq scan repo .` |
| Reason over the system | `graq run "<question>"` |
| Focused component context | `graq context <module>` |
| Enable EU AI Act (advisory) | `graqle.yaml` → `governance.eu_ai_act.{enabled: true, mode: advisory}` |
| Enforce (blocking) | `mode: blocking` (one-way; cannot downgrade) |
| Override one blocked action | re-call the tool with `eu_aia_override_justification="..."` |
| Inspect the audit trail | `cat .graqle/eu_ai_act_latch.jsonl` |
| Baseline the regulation | `graq compliance eur-lex-refresh` |
| Install the Claude Code wall | `graq gate-install` |

**Further reading:** [EU AI Act Guide](../compliance/eu-ai-act/GUIDE.md) ·
[Governance Gate spec](../governance-gate.md) · the per-Article notes under
`docs/compliance/eu-ai-act/`.

> Remember the through-line: GraQle gives you the **guardrails and the evidence**.
> The **compliance judgement stays human.**
