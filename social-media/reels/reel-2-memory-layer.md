# Reel 2: "The Graph Already Knows"

**Duration:** 40 seconds
**Series:** 2 of 7
**Hashtags:** #AI #KnowledgeGraph #DevTools #GraQle #GraphDatabase
**Background visual:** `traversal-1-query.svg` (query enters, ripple effect)

---

## Storyboard

| Time | You (Camera) | Background | On-Screen Text |
|------|-------------|------------|----------------|
| 0-3s | Snap into frame. Direct eye contact. | Dark with faint grid | **"Layer 1: Memory"** (amber) |
| 3-9s | "When you ask 'what breaks if I change auth' — the first thing GraQle does is NOT call an LLM." | Ripple animation starts around auth node | (none) |
| 9-15s | "It checks the graph. Pure traversal. Zero cost." | Graph edges light up amber, one by one | **Cost: $0** |
| 15-22s | "The graph already knows three modules import auth..." | Text overlay: `routes → auth`, `api → auth`, `middleware → auth` | **3 direct consumers** |
| 22-28s | "...eleven modules break if auth changes..." | Wider graph illuminates | **11 transitive deps** |
| 28-34s | "...and your team learned three months ago to never skip refresh token rotation." | Lesson card appears | **Institutional memory** |
| 34-40s | "All of that. Zero tokens. Zero dollars. Under one millisecond." | Big text: `$0 · <1ms` | **Memory first.** |

## Script (Dialogue)

> When you ask "what breaks if I change auth" — the first thing GraQle does is NOT call an LLM.
>
> It checks the graph. Pure traversal. Zero cost.
>
> The graph already knows three modules import auth. Eleven modules break if auth changes. And your team learned three months ago — never skip refresh token rotation.
>
> All of that. Zero tokens. Zero dollars. Under one millisecond.
>
> That's the memory layer. And we haven't touched the model yet.

## Teleprompter

```
When you ask
"what breaks if I change auth"

the first thing GraQle does
is NOT call an LLM.

It checks the graph.
Pure traversal. Zero cost.

The graph already knows:
three modules import auth.
Eleven modules break if auth changes.

And your team learned three months ago —
never skip refresh token rotation.

All of that.
Zero tokens.
Zero dollars.
Under one millisecond.

That's the memory layer.
And we haven't touched the model yet.
```

## Edit Notes

- **0-3s hook:** Cut directly in. No intro animation. Start with "Layer 1: Memory" text already visible.
- **15-22s:** Animate the edge labels appearing one at a time, timed to your speech.
- **28-34s:** The lesson card should look like a sticky note or toast notification. Makes institutional memory feel tangible.
- **Final beat:** Pause on "haven't touched the model yet" — implies there's more coming. Drives follows.
