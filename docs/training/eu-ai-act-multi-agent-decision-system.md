# GraQle Training Course
## Building EU AI Act-Aligned Multi-Agent Decision Systems

> **A complete, hands-on course for new students.** Ten detailed chapters take
> you from "what is GraQle?" to a fully governed, auditable, multi-agent
> decision system whose development *and* operation support the EU AI Act
> (Regulation (EU) 2024/1689).
>
> Every chapter follows the same rhythm:
> **① Concept** (what & why) → **② Walkthrough** (runnable code/CLI) →
> **③ Use case** (a realistic scenario) → **④ Check yourself** (exercises) →
> **⑤ How it maps to the Act** (the article-level "so what").

---

### ⚖️ Read this before anything else — the honesty contract

GraQle is an **engineering aid**. It helps you *produce the records, oversight
signals, and traceability* the EU AI Act expects, and it gives you guardrails so
your team works consistently. It does **NOT**:

- certify that your system is EU-AI-Act-compliant,
- replace a Notified Body, a conformity assessment, or your legal/compliance team,
- guarantee any regulatory outcome.

Throughout this course you will say to stakeholders: *"GraQle supports the Act's
record-keeping and oversight expectations; the compliance judgement stays human."*
Anyone who tells a customer "GraQle makes you compliant" has misunderstood the
tool. Teach the honest version.

### Who this is for

- **Students / new engineers** learning GraQle from zero.
- **ML/platform engineers** who must ship a decision system that touches people
  (credit, hiring, benefits, triage, content moderation) and need an audit trail.
- **Compliance-adjacent engineers** who must hand an auditor real evidence.

### Prerequisites & setup

```bash
python --version            # need >= 3.10
pip install "graqle>=0.75.0"
graq doctor                 # environment health check
```

You need an LLM backend. Cheapest to start: a local Ollama model (free) or an API
key (Anthropic / OpenAI / Bedrock / …). The course notes where the backend matters.

### The running use case (we build ONE system across all 10 chapters)

We build **"LoanFlow"** — a loan pre-screening decision support system. It is a
realistic **Annex III high-risk** example (creditworthiness assessment of natural
persons). Across the chapters we will:

1. model LoanFlow's architecture as a knowledge graph,
2. run multi-agent reasoning over it with confidence scores,
3. route low-confidence decisions to a human (Article 14),
4. turn on GraQle's EU AI Act layer (advisory, then blocking),
5. produce a tamper-evident audit trail of every compliance-relevant event,
6. keep the regulation reference current, and
7. operate it as a lifecycle, not a one-off.

> ⚠️ LoanFlow is a teaching example. Do not ship it as-is. Real
> creditworthiness systems need data-governance, bias testing, DPIAs, and human
> review designed with your compliance team.

---

## Chapter 1 — What GraQle is, and why governance is the product

### ① Concept

Most "AI systems" are a prompt wrapped around a model. That is easy to build and
**very hard to defend**. When a system decides something about a person, the
regulator (and your own risk team) will ask:

- *How* was this decision reached? (explainability)
- Could a **human** have understood and overridden it? (oversight — Article 14)
- Where is the **record**? (logging — Article 12)
- Is the system **monitored** after launch? (post-market monitoring — Article 72)
- Did you **manage risk** continuously? (Article 9)

GraQle's core idea: turn your **architecture into a knowledge graph** — every
module, agent, data source, and rule is a *node*; every call/dependency is an
*edge*. Then reasoning, impact analysis, oversight, and audit all hang off **one
source of truth** instead of being bolted on later. Governance stops being a
document you write at the end and becomes the *substrate* you build on.

GraQle has two surfaces:

- **Build-time** — query and govern your codebase as a graph (this course's focus).
- **Run-time** — attach governance to a deployed AI (`graqle govern serve`,
  covered briefly in Chapter 10).

### ② Walkthrough — initialise a governed project

```bash
mkdir loanflow && cd loanflow
git init
graq init .          # creates graqle.yaml + the governance "constitution"
graq doctor          # confirms backend + config
```

`graq init` writes a **constitution** into your AI tool's instruction file
(`CLAUDE.md`, or `AGENTS.md` for Codex, `.cursorrules` for Cursor). Open it:

```bash
cat CLAUDE.md        # the rulebook your AI assistant now follows
```

You'll see the 9-phase workflow, tool inventory, and the rule that the AI writes
code only through governed tools. **This is governance-as-code:** one rulebook,
rendered identically for every AI client your team uses.

### ③ Use case — "the auditor asks: how do you control your AI dev process?"

Before GraQle, your honest answer is "we code review." After `graq init`, your
answer is: "every change goes through a governed tool chain with a constitution
checked into the repo; here it is." That is a concrete, showable control — and it
is the seed of your Article 9 risk-management story.

### ④ Check yourself

1. Open `CLAUDE.md` and find the section that says the AI must use governed tools.
2. Run `graq doctor` and confirm your backend is detected.
3. In one sentence, explain to a non-engineer why "the graph is the source of
   truth" helps with an audit.

### ⑤ How it maps to the Act

- **Art. 9 (risk management):** treating governance as the frame starts the
  continuous risk process on day one.
- **Annex IV / Art. 11 (technical documentation):** a queryable architecture is
  the backbone of the technical file.

---

## Chapter 2 — Model your decision system as a knowledge graph

### ① Concept

A decision system is many parts: data ingestion, feature/score computation, a
decision rule, a human-review path, and an audit log. GraQle represents these as
**typed nodes** and the calls between them as **edges**. Reasoning over the graph
("what feeds the decision? what breaks if I change the score?") is faster and
safer than reading files, and it produces the dependency map an auditor expects.

### ② Walkthrough — build LoanFlow's modules, then the graph

Create the skeleton (small, readable modules):

```python
# loanflow/ingestion.py
def load_applicant(applicant_id: str) -> dict:
    """Fetch applicant features (income, debts, history)."""
    ...

# loanflow/risk_score.py
def compute_risk_score(features: dict) -> float:
    """Return a 0..1 creditworthiness score. Pure, testable, documented."""
    ...

# loanflow/human_review.py
def route_to_review(case: dict, reason: str) -> None:
    """Queue a case for a human reviewer with the reason it was escalated."""
    ...

# loanflow/decision.py
def decide(applicant_id: str) -> dict:
    """Orchestrate: load -> score -> (auto | human review) -> record."""
    ...

# loanflow/audit_log.py
def record_decision(applicant_id: str, outcome: dict) -> None:
    """Append an immutable decision record."""
    ...
```

Build the graph and inspect it:

```bash
graq scan repo .            # builds graqle.json from your code
graq inspect --stats        # node/edge counts, hub nodes
graq context risk_score     # a focused ~500-token view of one component
```

Or do it from Python (the SDK you'll use throughout):

```python
from graqle import Graqle

graph = Graqle.from_json("graqle.json")
print(graph.stats())                      # nodes, edges, density
print(graph.get_neighbors("loanflow/decision.py"))   # what decision.py touches
```

### ③ Use case — impact analysis before a risky change

Your team wants to change `compute_risk_score`. Before touching it:

```bash
graq impact risk_score      # what depends on the score? what could break?
```

The graph shows `decision.py` and `audit_log.py` consume the score — so a change
ripples into the recorded decision. That is an Article 9 risk signal you caught
*before* shipping.

### ④ Check yourself

1. Add a `bias_check.py` module and re-run `graq scan repo .`. Confirm it appears
   in `graq inspect --stats`.
2. Use `graph.get_neighbors(...)` to list everything `decision.py` calls.
3. Why is "score feeds the recorded decision" a risk worth documenting?

### ⑤ How it maps to the Act

- **Art. 11 + Annex IV:** the graph *is* living technical documentation.
- **Art. 9:** impact analysis = "identify and analyse known risks" of a change.

---

## Chapter 3 — Multi-agent reasoning with confidence and evidence

### ① Concept

A real decision is rarely one model call. GraQle runs **graph-of-agents
reasoning**: multiple agents activate over the *relevant* nodes, exchange
messages across rounds, and **converge** on an answer that carries:

- an **`answer` / `confidence`** (a calibrated score, not a vibe),
- the **`active_nodes`** that drove it (evidence — *why* this answer),
- a **`message_trace`** and **`cost_usd`** (auditability + economics).

This is the difference between "the model said approve" and "here is the reasoning,
the factors, and how sure we are."

### ② Walkthrough — reason over LoanFlow

CLI:

```bash
graq run "For applicant A-1042 with income 52k, 3 open debts, 6y history — is
          this a sound approval? Explain the deciding factors."
```

Python (the part you'll embed in `decision.py`):

```python
from graqle import Graqle
from graqle.backends.api import AnthropicBackend   # or your chosen backend

graph = Graqle.from_json("graqle.json")
graph.set_default_backend(AnthropicBackend(model="claude-sonnet-4-6"))

result = graph.reason(
    "Assess approval soundness for applicant A-1042 "
    "(income 52k, 3 open debts, 6y history). List the deciding factors."
)

print("answer:     ", result.answer)
print("confidence: ", result.confidence)        # e.g. 0.83
print("evidence:   ", result.active_nodes)      # which nodes drove it
print("cost (USD): ", result.cost_usd)
print("rounds:     ", result.rounds_completed)
```

`result` is a `ReasoningResult` with fields:
`answer, confidence, active_nodes, message_trace, cost_usd, latency_ms,
rounds_completed, metadata, …`.

### ③ Use case — explainability you can hand to a reviewer

A declined applicant complains. You re-run the reasoning, and `active_nodes` +
`message_trace` show *exactly* which factors (e.g. debt-to-income node) drove the
score. You can explain the decision in human terms — the heart of Article 13.

### ④ Check yourself

1. Run a reasoning query and print `result.confidence` and `result.active_nodes`.
2. Run a deliberately ambiguous case (income missing). Does confidence drop?
3. Why is `active_nodes` more defensible than a raw model log?

### ⑤ How it maps to the Act

- **Art. 13 (transparency to deployers):** the output is interpretable; you can
  show the factors and the confidence.
- **Art. 12 (logging):** `message_trace` + `cost_usd` + `timestamp` are recordable
  per decision.

---

## Chapter 4 — Human-in-the-loop: confidence thresholds & Article 14 oversight

### ① Concept

Article 14 demands **effective human oversight** of high-risk systems: a person
must be able to understand the output, resist automation bias, and **decide not
to use / override** a decision. The practical engineering hook is simple and
powerful: **route low-confidence decisions to a human.** GraQle hands you a
calibrated `confidence`; you choose a threshold; below it, a human decides.

This is the single most important pattern in the course. Memorise it:

> *High confidence -> automated path (with logging). Low confidence -> human
> review (with the reason). Never silently auto-decide a borderline case.*

### ② Walkthrough — wire the oversight router

Set the threshold in `graqle.yaml`:

```yaml
governance:
  human_review_required_threshold: 0.75   # below this -> human oversight expected
```

Implement the router in `decision.py`:

```python
from graqle import Graqle
from graqle.backends.api import AnthropicBackend
from loanflow.human_review import route_to_review
from loanflow.audit_log import record_decision

REVIEW_THRESHOLD = 0.75

graph = Graqle.from_json("graqle.json")
graph.set_default_backend(AnthropicBackend(model="claude-sonnet-4-6"))

def decide(applicant_id: str, features: dict) -> dict:
    result = graph.reason(
        f"Assess approval soundness for {applicant_id}: {features}. "
        "List deciding factors."
    )

    record = {
        "applicant_id": applicant_id,
        "answer": result.answer,
        "confidence": result.confidence,
        "factors": result.active_nodes,        # the evidence trail
        "cost_usd": result.cost_usd,
        "timestamp": result.timestamp,
    }

    if result.confidence is None or result.confidence < REVIEW_THRESHOLD:
        # Article 14: a human MUST decide this borderline / low-confidence case.
        route_to_review(record, reason=f"confidence {result.confidence} < {REVIEW_THRESHOLD}")
        record["outcome"] = "ESCALATED_TO_HUMAN"
    else:
        record["outcome"] = "AUTO_ASSESSED"

    record_decision(applicant_id, record)       # Article 12: log EVERY decision
    return record
```

### ③ Use case — automation-bias defence in a review queue

Your reviewers were rubber-stamping the model. You add to the review UI: the
`confidence`, the `factors` (active_nodes), and a mandatory "agree / override +
reason" choice. Now the human is genuinely in the loop, not a rubber stamp —
exactly what Article 14(4)(b) (awareness of automation bias) is about.

### ④ Check yourself

1. Feed three cases: clearly good, clearly bad, genuinely ambiguous. Confirm the
   ambiguous one routes to review.
2. Lower the threshold to 0.5 and observe more auto-decisions. Discuss the
   risk/throughput trade-off you just made (and why it should be a *documented*
   decision, not a quiet one).
3. Why must the *reason* for escalation be recorded, not just the fact of it?

### ⑤ How it maps to the Act

- **Art. 14(4)(d):** overseer can "decide not to use ... or otherwise override."
- **Art. 14(4)(b):** the review UI surfaces confidence + factors to counter
  automation bias.
- **Art. 12:** every decision (auto or escalated) is logged with its reason.

---

## Chapter 5 — Turn on the EU AI Act layer (advisory first)

### ① Concept

GraQle ships an optional **EU AI Act layer** — **off by default**. When on, it
adds an enforced compliance phase to the governance gate and keeps a
**tamper-evident audit trail** of compliance-state changes. You always start in
**advisory** mode: observe and record the signal *before* you block anything.
This avoids the classic failure where a too-strict gate gets ripped out.

The layer's enforced state lives in a **one-way latch** — a switch that, once on,
cannot be silently turned off (more in Chapter 6/7). Enabling it is a deliberate,
recorded decision.

### ② Walkthrough — enable advisory mode

```yaml
governance:
  eu_ai_act:
    enabled: true          # default is false
    mode: advisory         # observe + record; never block (start here)
    risk_class: high       # LoanFlow is Annex III high-risk (creditworthiness)
```

Now drive a development session through GraQle's governed tools. AIA-relevant
writes (editing `risk_score.py`, `decision.py`, etc.) get an advisory note and
are recorded — nothing is blocked.

You can read the latch state programmatically:

```python
from graqle.compliance.eu_ai_act_latch import EuAiActLatch

latch = EuAiActLatch(".")             # project root
state = latch.read_state()
print(state.enabled, state.mode, state.risk_class)   # True advisory high
print("override events so far:", state.override_count)
```

### ③ Use case — a two-week "compliance dry run"

Before enforcing, you run advisory for two weeks. The team sees which changes are
AIA-relevant and how often. You discover most blocks *would* have been on the
risk-score and decision modules — confirming your scope and building the evidence
that you ran a continuous risk process before tightening controls.

### ④ Check yourself

1. Enable advisory mode, make an edit to `risk_score.py` via a governed tool, and
   find the advisory note + the recorded event.
2. Read the latch with `EuAiActLatch(".").read_state()` and confirm `enabled`.
3. Why is "advisory before blocking" both safer *and* better evidence?

### ⑤ How it maps to the Act

- **Art. 9 (continuous risk management):** the dry run *is* risk management.
- **Art. 12 (record-keeping):** you generate the event log before enforcing.

> **One-way warning:** enabling records a signed event. You can later *upgrade*
> to `blocking`, but you can never silently turn it off. Read the
> [EU AI Act Guide](../compliance/eu-ai-act/GUIDE.md) before flipping `enabled: true`.

---

## Chapter 6 — Enforce: blocking mode + the audited override

### ① Concept

Once you trust the advisory signal, **upgrade to blocking**. Now an AIA-relevant
write whose supplied confidence is *below the review threshold* is **refused** —
unless a human records an **audited override** with a justification. The override
is the escape valve that keeps the gate from trapping people (the abandonment
trap) while keeping a record of every exception. Crucially: **the override does
NOT disable or weaken the latch** — it records that *one* action proceeded under
human oversight.

### ② Walkthrough — upgrade and use the override

Upgrade the latch (one-way; allowed because it is *stricter*):

```yaml
governance:
  eu_ai_act:
    enabled: true
    mode: blocking          # upgrade from advisory (allowed)
    risk_class: high
```

A low-confidence AIA-relevant write now returns a refusal envelope:

```json
{
  "error": "CG-EU-AIA_OVERSIGHT",
  "message": "EU AI Act blocking mode (high-risk): 'graq_edit' needs human oversight (Article 14) - confidence 0.40 is below the 0.75 review threshold.",
  "remediation": "Re-run the same tool with an 'eu_aia_override_justification' argument to proceed with a signed, audited override."
}
```

Proceed *with* recorded oversight by re-calling the same tool:

```
graq_edit(
    file_path="loanflow/risk_score.py",
    ...,
    eu_aia_override_justification=
        "Reviewed by A. Khan (compliance): threshold tweak validated against the "
        "Q2 test set; no protected-attribute logic touched. Proceeding under Art.14."
)
```

Verify the override landed in the chain:

```python
from graqle.compliance.eu_ai_act_latch import EuAiActLatch
print(EuAiActLatch(".").read_state().override_count)   # incremented; latch still blocking
```

You can also reason about the gate decision directly with the pure helper (great
for tests):

```python
from graqle.compliance.eu_ai_act_latch import evaluate_gate, EuAiActLatch

state = EuAiActLatch(".").read_state()
decision = evaluate_gate(
    state=state, tool_name="graq_edit",
    confidence=0.40, threshold=0.75,
)
print(decision.action)               # "block"
print(decision.envelope["error"])    # "CG-EU-AIA_OVERSIGHT"
```

### ③ Use case — the emergency hotfix at 2 a.m.

A production scoring bug needs an urgent fix, but its confidence is low and the
gate blocks. The on-call engineer does not get stuck: they override with
*"Sev-1 hotfix, reviewed by on-call lead M. Osei; rollback plan attached"*. The
fix ships, and the override (who/why/when) is permanently in the audit chain for
the post-incident review. **Usability and accountability, together.**

### ④ Check yourself

1. Upgrade to blocking, trigger a refusal, then proceed via override. Confirm
   `override_count` increments and `mode` is still `blocking`.
2. Try to downgrade `blocking -> advisory` in yaml. Predict what the gate does
   (hint: Chapter 7).
3. Why is "block, then human overrides with a reason" stronger evidence than
   "never block"?

### ⑤ How it maps to the Act

- **Art. 14 (human oversight):** block -> human decides -> recorded — the
  oversight loop, made operational.
- **Art. 12:** the override is part of the automatic, tamper-evident log.

---

## Chapter 7 — The tamper-evident audit trail

### ① Concept

Records only matter if they cannot be quietly altered after the fact. GraQle's
latch is an **append-only, ed25519-signed, hash-chained** log
(`.graqle/eu_ai_act_latch.jsonl`). Each event links to the previous one by hash,
is signed with a per-project key, and embeds its own public key. If anyone edits
a past event, deletes a line, or swaps the signing key, the **chain breaks** and
GraQle **fails closed** — it treats the layer as still enabled and flags tamper.
A tamper attempt can never be used to silently turn compliance off.

### ② Walkthrough — inspect, tamper, and watch it fail closed

```bash
# Inspect the chain (each line is one signed event)
cat .graqle/eu_ai_act_latch.jsonl
```

Each entry contains: `kind` (`enable` / `upgrade` / `override`), `ts` (UTC),
`body` (mode/risk_class or justification), `prev_hash` (the chain link), `sig`
(ed25519 signature), `hash`, and `pub` (the embedded public key).

Now prove the tamper detection in Python:

```python
import json
from pathlib import Path
from graqle.compliance.eu_ai_act_latch import EuAiActLatch

p = Path(".graqle/eu_ai_act_latch.jsonl")
lines = p.read_text(encoding="utf-8").splitlines()
ev = json.loads(lines[0])
ev["body"]["mode"] = "advisory"          # attempt to WEAKEN via a raw edit
p.write_text(json.dumps(ev) + "\n", encoding="utf-8")

state = EuAiActLatch(".").read_state()
print("tampered:", state.tampered)        # True
print("enabled :", state.enabled)         # True  -> the tamper did NOT disable it
print("mode    :", state.mode)            # blocking -> stays strict (fail closed)
```

**Commit the trail** so it travels with the code (but never the signing key):

```bash
git add -f .graqle/eu_ai_act_latch.jsonl   # the audit trail (force-add past .gitignore)
# DO NOT commit .graqle/eu_ai_act_latch.key  -- it is the local signing seal
git commit -m "compliance: record EU AI Act latch audit trail"
```

### ③ Use case — handing an auditor the evidence

An auditor asks: "Show me when EU AI Act controls were enabled, prove they were
never silently weakened, and list every exception with its justification." You
hand them the chain: the `enable`/`upgrade` events with timestamps, the unbroken
hash links (proving no silent downgrade), and every `override` with its
justification text. That is concrete Article 12 / 72 evidence.

### ④ Check yourself

1. Print the latch file and identify the `prev_hash` link between two events.
2. Tamper with a line and confirm `read_state().tampered` becomes `True` while
   `enabled` stays `True`.
3. Why does committing the trail (but not the key) give the auditor what they
   need without exposing a forgery risk?

### ⑤ How it maps to the Act

- **Art. 12 (automatic, lifetime logging):** an append-only signed log is exactly
  the kind of record-keeping the Article envisions.
- **Art. 72 (post-market monitoring):** the trail feeds your ongoing monitoring.

---

## Chapter 8 — Keep the regulation current (EUR-Lex drift)

### ① Concept

The Act and its references evolve; consolidated texts get corrected, related
directives change. A compliance story that silently goes stale is a liability.
GraQle's **EUR-Lex drift guard** records a baseline hash of the authoritative
EUR-Lex URLs your docs cite, and re-checks them on a schedule — flagging when the
regulator-side content changes so a human can review *what* changed.

### ② Walkthrough — baseline and check

Reference the law in your compliance docs (e.g. under `docs/compliance/`), then:

```bash
# Establish (or refresh) the baseline: fetch + hash the referenced EUR-Lex URLs
graq compliance eur-lex-refresh
```

From Python you can drive and inspect it directly:

```python
from pathlib import Path
from graqle.compliance.eur_lex_guard import refresh_baseline, check_drift

# one-time: write the baseline for every EUR-Lex URL found under docs/compliance
entries, errors = refresh_baseline(
    search_roots=[Path("docs/compliance")],
    baseline_path=Path(".graqle/eur-lex-baseline.json"),
)
print("baselined:", len(entries), "errors:", len(errors))

# later (e.g. weekly CI): compare current vs baseline
report = check_drift(
    search_roots=[Path("docs/compliance")],
    baseline_path=Path(".graqle/eur-lex-baseline.json"),
    offline=True,                 # offline = structural check only
)
print("has_drift:", report.has_drift, "missing:", report.n_missing_from_baseline)
```

A weekly CI job runs the same check and files an issue when the source drifts, so
a human updates the relevant doc and re-baselines.

### ③ Use case — the Commission publishes a corrigendum

Six months after launch, EUR-Lex publishes a corrigendum to the Act's text. Your
weekly drift job fires: the AI Act URL hash no longer matches the baseline. A
human reads the diff, updates `docs/compliance/eu-ai-act/article-14-...md` if the
change is substantive, runs `graq compliance eur-lex-refresh`, and commits the new
baseline. Your "we track the regulation" claim is now demonstrably true.

### ④ Check yourself

1. Baseline the URLs and confirm `check_drift(...).has_drift` is `False`.
2. Add a new EUR-Lex URL to a doc, re-run the check, and watch it report a
   `missing_from_baseline`. Re-baseline to clear it.
3. Why is "a human reviews what changed" the right response to drift, rather than
   auto-accepting the new content?

### ⑤ How it maps to the Act

- **Art. 9 (continuous review and update):** you get a signal when the
  *regulation itself* moves, not only when your code changes.

---

## Chapter 9 — Multi-client, multi-agent governance everywhere

### ① Concept

Real teams use different AI tools — one engineer on Claude Code, another on
Codex, another on Cursor. If governance only works for one tool, your oversight
story has a hole. GraQle solves this two ways:

1. **One constitution, rendered per client.** `graq init` writes the *same*
   rulebook into `CLAUDE.md`, `AGENTS.md` (Codex), `.cursorrules` (Cursor), and
   `.windsurfrules` (Windsurf).
2. **One server-side gate for all clients.** Every MCP client routes through the
   same governed `graq_*` tools, so the CG gates — including the EU AI Act phase —
   apply identically no matter which tool is driving.

### ② Walkthrough — bring every client under governance

```bash
# Render the constitution + register the MCP server for a Codex user:
graq init . --ide codex          # writes AGENTS.md + .mcp.json

# Render for Cursor / Windsurf:
graq init . --ide cursor         # writes .cursorrules
graq init . --ide windsurf       # writes .windsurfrules

# Claude Code: add the hard client-side wall (defense-in-depth) on top:
graq gate-install                # settings.json deny native tools + PreToolUse hook
```

Confirm every instruction file carries the rulebook:

```bash
grep -l "GraQle" CLAUDE.md AGENTS.md .cursorrules .windsurfrules 2>/dev/null
```

The EU AI Act phase you enabled in Chapters 5–6 now governs **all** of them,
because it lives in the shared server-side gate — not in any one client.

### ③ Use case — a mixed team, one audit story

Your audit covers the whole team. Because the constitution and the server gate
are shared, you can truthfully say "every engineer, on every AI tool, works under
the same governed process and the same EU AI Act controls." There is no "but the
Codex user was ungoverned" gap.

> **Honest limitation:** a developer who abandons the GraQle tools entirely and
> uses raw native editors is outside the *server* gate. The Claude Code client
> wall narrows that on Claude; organisationally, the constitution + code review
> cover the rest. Teach this limitation — do not pretend it away.

### ④ Check yourself

1. Run `graq init . --ide codex` and confirm `AGENTS.md` contains the constitution.
2. Explain why putting enforcement in the *server gate* (not the client) is what
   makes multi-client governance real.
3. Name the one bypass the server gate cannot close, and how you mitigate it.

### ⑤ How it maps to the Act

- **Art. 14 at organisational scale:** consistent human-oversight controls across
  the whole human+AI team, not just one tool.

---

## Chapter 10 — Ship, prove, and operate (the lifecycle)

### ① Concept

Compliance is a lifecycle, not a release. This final chapter ties LoanFlow
together: the **graph** (architecture), **confidence routing** (oversight), the
**latch** (enforced + auditable), the **drift guard** (currency), and the
**constitution** (consistent practice) — operated continuously.

GraQle also has a **run-time** surface for deployed systems: `graqle govern serve`
runs a continuous anchoring/monitoring worker, and `graqle govern health` emits an
Article-72-style monitoring snapshot. (Run-time is its own topic; here we just
note it exists so your operate-phase story is complete.)

### ② Walkthrough — an operating checklist you can adopt

**Build-time (every change):**
```bash
# all changes go through governed tools; AIA-relevant writes pass the Art-14 check;
# overrides are recorded. The constitution + gate enforce this automatically.
```

**Decision-time (every decision):** use the Chapter-4 router — log `answer`,
`confidence`, `active_nodes`, `cost_usd`, `timestamp`, and the outcome
(auto vs escalated) for *every* decision.

**Record-keeping:**
```bash
git add -f .graqle/eu_ai_act_latch.jsonl    # commit the audit trail
```

**Monitoring (deployed):**
```bash
graqle govern serve --once        # one monitoring tick (cron-friendly)
graqle govern health              # Article-72-style JSON snapshot
```

**Currency (weekly):**
```bash
graq compliance eur-lex-refresh   # re-baseline if the regulator changed the text
```

**Review (periodic):** check override frequency. A spike in overrides is a process
smell — maybe the threshold is too tight, or a module genuinely needs redesign.

### ③ Use case — the four questions you can now answer with evidence

When anyone — auditor, regulator, your own risk committee — asks about a LoanFlow
decision, you can answer *with artifacts, not assertions*:

1. **How was it made?** -> the reasoning `answer` + `active_nodes` (factors).
2. **Could a human oversee it?** -> the confidence-routed review + override records.
3. **Where is the record?** -> the decision log + the tamper-evident latch chain.
4. **Is the regulation current?** -> the EUR-Lex baseline + drift history.

### ④ Check yourself (capstone)

Stand up LoanFlow end to end:

1. `graq init`, model the modules, `graq scan repo .`.
2. Wire the Chapter-4 confidence router with a 0.75 threshold.
3. Enable the EU AI Act layer in **advisory**, run a few decisions, inspect the
   recorded events.
4. Upgrade to **blocking**; trigger a refusal; proceed via an audited override.
5. Inspect + commit the latch chain; prove a tamper fails closed.
6. Baseline the EUR-Lex URLs; show `has_drift: False`.
7. Write a one-page "evidence pack" answering the four questions above.

If you can do all seven, you can teach this course.

### ⑤ How it maps to the Act

- The full loop — **Art. 9, 10, 12, 13, 14, 72** — backed by artifacts you can
  show. That is the difference between *claiming* alignment and *demonstrating* it.

---

## Appendix A — Command & config quick reference

| Goal | How |
|------|-----|
| Initialise a governed project | `graq init .` |
| Initialise for a specific client | `graq init . --ide codex` (or `cursor`/`windsurf`) |
| Claude Code hard wall | `graq gate-install` |
| Build / refresh the graph | `graq scan repo .` |
| Reason over the system | `graq run "<question>"` |
| Focused component context | `graq context <module>` |
| Impact of a change | `graq impact <module>` |
| Health check | `graq doctor` |
| Enable EU AI Act (advisory) | `graqle.yaml` -> `governance.eu_ai_act.{enabled: true, mode: advisory}` |
| Enforce (blocking; one-way) | `mode: blocking` (cannot later downgrade) |
| Override one blocked action | re-call the tool with `eu_aia_override_justification="..."` |
| Inspect the audit trail | `cat .graqle/eu_ai_act_latch.jsonl` |
| Baseline the regulation | `graq compliance eur-lex-refresh` |
| Run-time monitoring snapshot | `graqle govern health` |

## Appendix B — Python API cheat sheet

```python
from graqle import Graqle, ReasoningResult
from graqle.backends.api import AnthropicBackend
from graqle.compliance.eu_ai_act_latch import EuAiActLatch, evaluate_gate

graph = Graqle.from_json("graqle.json")
graph.set_default_backend(AnthropicBackend(model="claude-sonnet-4-6"))

r = graph.reason("...")                 # -> ReasoningResult
r.answer; r.confidence; r.active_nodes; r.cost_usd; r.timestamp; r.metadata

latch = EuAiActLatch(".")
st = latch.read_state()                 # .enabled .mode .risk_class .override_count .tampered
# st transitions are recorded as signed events; downgrades raise LatchDowngradeRefused

decision = evaluate_gate(state=st, tool_name="graq_edit",
                         confidence=0.4, threshold=0.75)   # .action: allow|block|advise
```

## Appendix C — Article-to-feature map

| EU AI Act article | GraQle feature used in this course |
|-------------------|-------------------------------------|
| Art. 9 — risk management (continuous) | governed dev loop; impact analysis; advisory dry run; drift guard |
| Art. 10 — data governance | (model your data nodes + a `bias_check` module; document datasets) |
| Art. 11 / Annex IV — technical documentation | the knowledge graph as living architecture docs |
| Art. 12 — record-keeping / logging | decision logs; the tamper-evident latch chain |
| Art. 13 — transparency to deployers | reasoning `answer` + `active_nodes` (explainable factors) |
| Art. 14 — human oversight | confidence-threshold routing; blocking mode; audited override |
| Art. 50 — transparency (limited-risk) | (disclose AI interaction where applicable) |
| Art. 72 — post-market monitoring | `graqle govern serve/health`; ongoing drift + override review |

> **Final reminder for every student:** GraQle gives you the **guardrails and the
> evidence**. The **compliance judgement stays human.** Teach that first, last,
> and always.
