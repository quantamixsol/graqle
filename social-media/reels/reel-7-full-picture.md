# Reel 7: "The Whole Model in 45 Seconds"

**Duration:** 50 seconds
**Series:** 7 of 7 (Finale)
**Hashtags:** #AI #KnowledgeGraph #GraphOfAgents #DevTools #GraQle #OpenSource
**Background visual:** Start with `node-anatomy.svg`, transition through all visuals, end with `hero-dark.svg`

---

## Storyboard

| Time | You (Camera) | Background | On-Screen Text |
|------|-------------|------------|----------------|
| 0-3s | Calm. "Here's the whole model." | Dark | **"The Full Architecture"** |
| 3-8s | "You ask: what breaks if I change auth?" | Terminal typing animation | `$ graq run "what breaks if I change auth?"` |
| 8-13s | "Layer one — Memory. The graph checks edges, consumers, lessons. Ten thousand nodes down to eleven. Cost: zero." | Amber ring appears | **Memory: 10,127 → 11 · $0** |
| 13-18s | "Layer two — Embeddings. One vector call scores relevance. Eleven nodes down to eight. Cost: one hundred-thousandth of a cent." | Purple ring appears | **Embedding: 11 → 8 · $0.00001** |
| 18-24s | "Layer three — LLM. Eight agents activate. They exchange messages. Two rounds. They reach consensus." | Cyan ring appears. All three visible. | **LLM: 8 agents · 500 tokens · $0.0003** |
| 24-30s | "The answer: auth breaks routes, api, and middleware. Eleven modules impacted. Ninety-two percent confidence." | Terminal result appears | **92% confidence · 5.2 seconds** |
| 30-35s | "Total cost: three ten-thousandths of a dollar. Total tokens: five hundred. Total time: five seconds." | Three numbers stack | **$0.0003 · 500 tokens · 5.2s** |
| 35-40s | "The same question with traditional tools? Fifty thousand tokens. Fifteen cents. Two minutes. No confidence score." | Numbers cross out (red) | ~~$0.15~~ ~~50,000~~ ~~2 min~~ |
| 40-45s | "Memory first. Embeddings second. LLM last." | Three rings, unified | **Memory first. Embeddings second. LLM last.** |
| 45-50s | "That's GraQle. Ten seconds to install. And your AI stops guessing." | `pip install graqle` + graqle.com | **pip install graqle** |

## Script (Dialogue)

> Here's the whole model.
>
> You ask: what breaks if I change auth?
>
> Layer one — Memory. The graph checks edges, consumers, lessons. Ten thousand nodes down to eleven. Cost: zero.
>
> Layer two — Embeddings. One vector call scores relevance. Eleven down to eight. Cost: one hundred-thousandth of a cent.
>
> Layer three — LLM. Eight agents activate. They exchange messages. Two rounds. They reach consensus.
>
> The answer: auth breaks routes, API, and middleware. Eleven modules impacted. Ninety-two percent confidence.
>
> Total cost: three ten-thousandths of a dollar. Total tokens: five hundred. Total time: five seconds.
>
> The same question with traditional tools? Fifty thousand tokens. Fifteen cents. Two minutes. No confidence score.
>
> Memory first. Embeddings second. LLM last.
>
> That's GraQle. Ten seconds to install. And your AI stops guessing.

## Teleprompter

```
Here's the whole model.

You ask:
what breaks if I change auth?

Layer one — Memory.
The graph checks edges, consumers, lessons.
Ten thousand nodes down to eleven.
Cost: zero.

Layer two — Embeddings.
One vector call scores relevance.
Eleven down to eight.
Cost: one hundred-thousandth of a cent.

Layer three — LLM.
Eight agents activate.
They exchange messages. Two rounds.
They reach consensus.

The answer:
auth breaks routes, API, and middleware.
Eleven modules impacted.
Ninety-two percent confidence.

Total cost:
three ten-thousandths of a dollar.
Total tokens: five hundred.
Total time: five seconds.

The same question with traditional tools?
Fifty thousand tokens.
Fifteen cents.
Two minutes.
No confidence score.

Memory first.
Embeddings second.
LLM last.

That's GraQle.
Ten seconds to install.
And your AI stops guessing.
```

## Edit Notes

- **This is the finale — it should feel like a culmination.** The pace should be slightly slower, more authoritative than previous reels.
- **8-24s:** The three rings appearing one by one is the visual climax. Each ring appears exactly when you name the layer. Amber → Purple → Cyan. By 24s all three are visible — the complete node anatomy.
- **35-40s:** The red strikethrough on old numbers is satisfying. Makes the comparison visceral.
- **45-50s:** Hold the final frame for 5 full seconds. `pip install graqle` centered. Clean.
- **End screen:** Add "Follow for more" and pin comment with GitHub link.
