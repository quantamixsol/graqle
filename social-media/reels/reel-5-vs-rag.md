# Reel 5: "This Isn't RAG"

**Duration:** 40 seconds
**Series:** 5 of 7
**Hashtags:** #RAG #AI #KnowledgeGraph #GraphOfAgents #GraQle #LLM
**Background visual:** `traversal-3-consensus.svg` (green unified graph)

---

## Storyboard

| Time | You (Camera) | Background | On-Screen Text |
|------|-------------|------------|----------------|
| 0-4s | Hands up, slight smile. "People keep asking me..." | Dark | **"But isn't this just RAG?"** |
| 4-8s | "No. And here's the difference in one frame." | Split screen appears | (split layout) |
| 8-15s | "RAG: embed query, vector search, stuff top-K chunks into one prompt, one model answers alone." | LEFT side: linear flow, red tint | **RAG: query → chunks → 1 LLM → guess** |
| 15-22s | "GraQle: graph memory, embed query, activate subgraph, eight agents negotiate, consensus with evidence." | RIGHT side: branching flow, cyan tint | **GraQle: memory → embed → agents → consensus** |
| 22-28s | "RAG finds what's similar. GraQle finds what's connected AND similar." | Highlight: routes.py example | **Structure > Similarity** |
| 28-34s | "Routes-dot-py has LOW text similarity to auth. But it IMPORTS auth. RAG misses it. The graph catches it." | routes node lights up | **RAG misses structural deps** |
| 34-40s | "Fifty thousand tokens versus five hundred. That's not optimization. That's a different paradigm." | Big comparison | **50,000 vs 500** |

## Script (Dialogue)

> People keep asking me — "isn't this just RAG?"
>
> No. And here's the difference in one frame.
>
> RAG: embed the query, vector search, stuff top-K chunks into one prompt, one model answers alone.
>
> GraQle: graph memory, embed query, activate subgraph, eight agents negotiate, consensus with evidence.
>
> RAG finds what's similar. GraQle finds what's connected AND similar.
>
> Routes-dot-py has low text similarity to auth. But it imports auth. RAG misses it. The graph catches it.
>
> Fifty thousand tokens versus five hundred. That's not optimization. That's a different paradigm.

## Teleprompter

```
People keep asking me —
"isn't this just RAG?"

No. And here's the difference
in one frame.

RAG: embed the query,
vector search,
stuff top-K chunks into one prompt,
one model answers alone.

GraQle: graph memory,
embed query,
activate subgraph,
eight agents negotiate,
consensus with evidence.

RAG finds what's similar.
GraQle finds what's
connected AND similar.

Routes dot py has low text similarity
to auth. But it imports auth.
RAG misses it. The graph catches it.

Fifty thousand tokens versus five hundred.
That's not optimization.
That's a different paradigm.
```

## Edit Notes

- **0-4s hook:** "But isn't this just RAG?" — this is the #1 objection. Opens a curiosity loop.
- **8-22s:** Use a real split-screen: RAG pipeline (left, red/dim) vs GraQle pipeline (right, cyan/bright). Can be simple text flows or arrows.
- **22-28s:** This is the insight moment. The routes.py example makes the abstract concrete. Pause slightly before "The graph catches it."
- **34-40s:** "Different paradigm" — deliver with finality. This is a mic-drop line.
