# Instagram Reels / YouTube Shorts — Production Guide

> 7 short-form videos (30-60s each) explaining the Graph-of-Agents reasoning model.
> Designed for: camera-front recording with animated background overlays.

---

## Setup

**Camera:** Phone or webcam, portrait mode (9:16)
**You:** Center-frame, chest-up, looking at camera
**Background:** Screen-record the SVG animations from a monitor behind you, OR use the static PNGs as green-screen overlays in CapCut/Premiere
**Teleprompter:** Each reel has a teleprompter script at the bottom (copy-paste into any teleprompter app)
**Pace:** Fast. Every sentence is a cut point. No filler. Think Apple keynote energy — calm authority, not hype.
**Captions:** Auto-generate with CapCut. Bold the key numbers (100x, 500, $0.0003, 92%).
**Music:** Lo-fi ambient or no music. Let the words carry it.

## Recording Tips

1. Record each reel in one continuous take using the teleprompter
2. Pause 1 second between sections (edit points)
3. Look directly into the camera lens, not the screen
4. Keep energy high but controlled — confident expert, not influencer
5. Screen-record the SVG animations separately (10s loops), overlay in edit
6. Use jump cuts between sections for pace

---

## Visual Assets Reference

| Asset | When to Show | Format |
|-------|-------------|--------|
| `node-anatomy.svg` | Reels 1, 7 (three rings concept) | Screen-record SVG for animated background |
| `traversal-1-query.svg` | Reel 2 (query enters graph) | Screen-record: ripple effect |
| `traversal-2-messages.svg` | Reel 4 (agents talk) | Screen-record: particles traveling |
| `traversal-3-consensus.svg` | Reel 5, 6 (consensus, scoring) | Screen-record: green convergence |
| `node-square.png` | Reel 3 (embedding) | Static overlay |
| `hero-dark.svg` | Reel 7 (full picture) | Screen-record: animated hero |

**How to get animated backgrounds:**
1. Open any `.svg` file in Chrome (full screen, dark mode)
2. Screen-record for 15 seconds (the rings rotate, particles orbit)
3. Import into CapCut/Premiere as background layer
4. Place your camera recording on top (use green screen or picture-in-picture)

---

## Reel Index

| # | Title | Duration | Script | Visual |
|---|-------|----------|--------|--------|
| 1 | [Your AI Is Guessing](reel-1-the-problem.md) | 35s | The hook — introduces the 3-layer model | `node-anatomy.svg` |
| 2 | [The Graph Already Knows](reel-2-memory-layer.md) | 40s | Memory layer — edges, consumers, lessons, $0 | `traversal-1-query.svg` |
| 3 | [One Vector Call](reel-3-embedding-layer.md) | 35s | Embedding layer — cached .npz, cosine sim | `node-square.png` |
| 4 | [Nodes Don't Answer. They Negotiate.](reel-4-agents-talk.md) | 45s | LLM layer — agent dialogue, message passing | `traversal-2-messages.svg` |
| 5 | [This Isn't RAG](reel-5-vs-rag.md) | 40s | Structural comparison — why graphs beat vectors | `traversal-3-consensus.svg` |
| 6 | [92% Is Not Marketing](reel-6-confidence.md) | 40s | Confidence scoring — 5 axes, evidence chains | `traversal-3-consensus.svg` |
| 7 | [The Whole Model in 45 Seconds](reel-7-full-picture.md) | 50s | Finale — complete architecture recap + CTA | All visuals |

**Total series:** ~285 seconds (~4:45) of content
**Recording time:** ~5 minutes (record all 7 back-to-back using [TELEPROMPTER-ALL.md](TELEPROMPTER-ALL.md))

---

## Post-Production Checklist

- [ ] Record all 7 takes using TELEPROMPTER-ALL.md
- [ ] Screen-record each SVG animation (15s loops)
- [ ] Import into CapCut/Premiere
- [ ] Layer: camera footage (front) + SVG animation (background)
- [ ] Add text overlays per storyboard timing
- [ ] Auto-generate captions (bold key numbers)
- [ ] Add ambient music (subtle, not distracting)
- [ ] Export 7 separate files (1080x1920, 30fps)
- [ ] Upload to Instagram Reels, YouTube Shorts, TikTok, LinkedIn Video
- [ ] Add captions/descriptions from corresponding knowledge-series post
- [ ] Pin comment: "pip install graqle — https://graqle.com"

---

## Posting Schedule

| Day | Reel | Instagram Caption From |
|-----|------|----------------------|
| Mon | Reel 1: The Problem | `knowledge-series/01-why-memory-first.md` |
| Wed | Reel 2: Memory Layer | `knowledge-series/02-what-graph-memory-knows.md` |
| Fri | Reel 3: Embedding Layer | `knowledge-series/03-embedding-layer.md` |
| Mon | Reel 4: Agents Talk | `knowledge-series/04-llm-reasoning-last.md` |
| Wed | Reel 5: vs RAG | `knowledge-series/05-vs-rag.md` |
| Fri | Reel 6: Confidence | `knowledge-series/06-confidence-scoring.md` |
| Mon | Reel 7: Full Picture | `knowledge-series/07-full-picture.md` |

Cross-post each reel to YouTube Shorts and TikTok on the same day.
