# Post 6: Why Confidence Scores Change Everything

**Series:** The Graph-of-Agents Reasoning Model (6 of 7)
**Visual:** `stories/query-journey/story-traversal-3-consensus.png` (scoring bars)
**Platforms:** LinkedIn, Twitter, Reddit

---

## LinkedIn / Facebook Caption

```
"92% confidence" is not a marketing number.
It's a calculated score across 5 axes.

When GraQle answers a question, it doesn't just give you text.
It gives you a GOVERNED response with a confidence score
computed from five independent measurements:

1. RELEVANCE (95%)
   How well do the activated nodes match the question?
   Measured by: embedding cosine similarity + graph distance

2. COMPLETENESS (90%)
   Did we cover all affected modules?
   Measured by: activated nodes / total nodes in impact radius

3. EVIDENCE (93%)
   Is every claim backed by a graph edge or code reference?
   Measured by: claims with evidence links / total claims

4. CONSENSUS (87%)
   Did the agents agree?
   Measured by: agreement ratio across multi-round messages

5. GOVERNANCE (97%)
   Does the answer respect safety boundaries?
   Measured by: zero violations of configured constraints

Why this matters:

When confidence is 92% — you ship with conviction.
When confidence is 45% — you know to investigate more.
When confidence drops from 90% to 60% — the graph is telling
you something changed that needs attention.

No other AI coding tool gives you this.

They give you text. We give you text + confidence +
evidence chain + governance audit trail.

That's the difference between "I think" and "I know."

#ConfidenceScoring #AI #Governance #DevTools #GraQle
```

## Twitter / X Thread (continuation)

```
15/ "92% confidence" — how is it calculated?

5 independent axes, each scored separately:

Relevance:    95% (embedding + graph distance)
Completeness: 90% (coverage of impact radius)
Evidence:     93% (claims backed by edges)
Consensus:    87% (agent agreement ratio)
Governance:   97% (safety boundary compliance)

Weighted average: 92%
```

```
16/ Why this matters in practice:

High confidence (>85%): ship it
Medium (60-85%): review the evidence chain
Low (<60%): the graph is telling you something is incomplete

This turns AI from "vibes" to "decisions."

Your AI doesn't just answer. It tells you
HOW MUCH to trust the answer.
```

```
17/ And it's all auditable.

Every answer links back to:
→ Which graph nodes were consulted
→ What evidence was found
→ How agents agreed/disagreed
→ Exact token cost

Hash-chained audit trail.
When compliance asks "how do you trust your AI?" —
you show them the dashboard.
```
