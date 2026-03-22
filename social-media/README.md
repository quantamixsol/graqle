# GraQle Social Media Kit

> All visual assets for social media, link sharing, and content marketing in one place.

---

## Folder Structure

```
social-media/
├── README.md                         ← You are here
├── PUNCHLINES.md                     ← Copy-paste captions & hooks
│
├── posts/
│   ├── knowledge-series/             ← 7-part educational series (Memory → Embedding → LLM)
│   │   ├── README.md                 ← Series index, posting schedule, visual mapping
│   │   ├── 01-why-memory-first.md
│   │   ├── 02-what-graph-memory-knows.md
│   │   ├── 03-embedding-layer.md
│   │   ├── 04-llm-reasoning-last.md
│   │   ├── 05-vs-rag.md
│   │   ├── 06-confidence-scoring.md
│   │   └── 07-full-picture.md
│   ├── story-node-square.png         ← Square format (1080x1080)
│   └── story-node-square.svg
│
├── link-previews/                    ← Auto-shown when sharing links
│   ├── og-image.png                  ← 1200x630 — LinkedIn, Facebook, Twitter, Slack, WhatsApp
│   ├── github-social-preview.png     ← 1280x640 — GitHub repo card (upload via Settings)
│   └── github-social-preview.svg     ← Source SVG
│
├── stories/                          ← Vertical format (1080x1920)
│   ├── node-anatomy/                 ← "Inside the Node" — single node deep dive
│   │   ├── story-node-anatomy.png    ← Static PNG for Instagram/LinkedIn/TikTok stories
│   │   └── story-node-anatomy.svg    ← Animated SVG (rotating rings, orbiting particles)
│   │
│   └── query-journey/                ← "The Query Journey" — 3-part swipeable series
│       ├── story-traversal-1-query.png       ← Frame 1: Query enters the graph
│       ├── story-traversal-1-query.svg
│       ├── story-traversal-2-messages.png    ← Frame 2: Agents exchange messages
│       ├── story-traversal-2-messages.svg
│       ├── story-traversal-3-consensus.png   ← Frame 3: Consensus + 92% confidence
│       └── story-traversal-3-consensus.svg
│
├── posts/                            ← Square format (1080x1080)
│   ├── story-node-square.png         ← Instagram feed, LinkedIn feed, Twitter
│   └── story-node-square.svg         ← Source SVG
│
└── hero/                             ← Website & README hero images
    ├── hero-dark.svg                 ← Animated SVG (before→after, graph traversal)
    └── hero-dark-hq.png              ← High-res PNG fallback (3200x2080)
```

---

## Quick Reference

### Which image for which platform?

| Platform | Format | File | Dimensions |
|----------|--------|------|------------|
| **LinkedIn link share** | Auto (OG) | `link-previews/og-image.png` | 1200x630 |
| **Facebook link share** | Auto (OG) | `link-previews/og-image.png` | 1200x630 |
| **Twitter/X link share** | Auto (OG) | `link-previews/og-image.png` | 1200x630 |
| **Slack/Discord embed** | Auto (OG) | `link-previews/og-image.png` | 1200x630 |
| **WhatsApp link preview** | Auto (OG) | `link-previews/og-image.png` | 1200x630 |
| **GitHub repo card** | Manual upload | `link-previews/github-social-preview.png` | 1280x640 |
| **Instagram Story** | Upload | `stories/` (any `.png`) | 1080x1920 |
| **LinkedIn Story** | Upload | `stories/` (any `.png`) | 1080x1920 |
| **TikTok background** | Upload | `stories/` (any `.png`) | 1080x1920 |
| **YouTube Shorts** | Upload | `stories/` (any `.png`) | 1080x1920 |
| **Instagram feed post** | Upload | `posts/story-node-square.png` | 1080x1080 |
| **LinkedIn feed post** | Upload | `posts/story-node-square.png` | 1080x1080 |
| **Twitter/X post** | Upload | `posts/story-node-square.png` | 1080x1080 |

### Animated versions

Open any `.svg` file in a browser to see animations:
- **Node anatomy:** Three concentric rings rotate at different speeds with orbiting particles
- **Query journey:** Message particles travel along edges, nodes pulse, ripple effects radiate
- **Consensus:** Green convergence ripple pulls inward

Screen-record the SVGs for 10-15 seconds to get animated story backgrounds.

---

## Asset Descriptions

### Link Previews

**`og-image.png`** (1200x630)
Shows: GraQle brand, knowledge graph visualization (8 nodes), terminal output (`graq run`), stats (100x cheaper, 24x faster), `pip install graqle`, "Works with Claude Code".
Deployed at: `https://graqle.com/og-image.png`
Used by: All platforms when sharing graqle.com links.

**`github-social-preview.png`** (1280x640)
Same content optimized for GitHub's 2:1 ratio with 40pt safe zone.
Setup: Go to github.com/quantamixsol/graqle/settings > Social Preview > Upload.

### Stories: Node Anatomy ("Inside the Node")

**Concept:** Anatomical view of what happens inside a single GraQle node during reasoning.

Three concentric rings around `auth.py`:
- **Outer ring (amber):** Memory Context — graph traversal, edges, history. Cost: $0.
- **Middle ring (purple):** Embedding Context — cosine similarity, 1 vector call. Cost: ~$0.00001.
- **Inner ring (cyan):** LLM Reasoning — graph-of-agents, 500 tokens. Cost: $0.0003.

Floating data fragments show real values (embedding vectors, consumer count, confidence).
Punchline: "Memory first. Embeddings second. LLM last. That's why it's 100x cheaper."

### Stories: Query Journey (3-Part Series)

**Concept:** A query enters the graph and travels through nodes — showing the full graph-of-agents reasoning pipeline.

**Frame 1 — THE QUERY ENTERS**
- Terminal shows: `graq run "what breaks if I change auth?"`
- Query arrow enters the graph, hits `auth.py`
- Ripple effect radiates from the activated node
- 7 neighbor nodes are dimmed (not yet activated)
- Bottom shows memory/embedding/LLM starting to process
- CTA: "Auth activates. Now it talks to its neighbors."

**Frame 2 — AGENTS TALK**
- Message particles travel along edges between nodes
- 4 nodes now activated (auth, routes, api, middleware)
- 4 more partially activating (2nd hop: db, utils, config, tests)
- Chat-log style message exchange between agents:
  - auth → routes: "I handle JWT validation. Do you consume my tokens?"
  - routes → auth: "Yes — 3 endpoints require your @auth_required decorator"
  - auth → api: "Do you call verify_token() directly?"
  - api → auth: "Yes — and I also import AuthError for 401 handling"
  - middleware → all: "I wrap auth for every request. Breaking auth breaks me."
- Progress: "6 of 8 agents active · Round 1 of 2 · 180 tokens"
- CTA: "Nodes don't just answer. They negotiate."

**Frame 3 — CONSENSUS**
- All nodes turn green (AGREE), one node amber (PARTIAL)
- Green convergence ripple pulls inward
- Giant "92%" confidence number
- 5-axis scoring bars: Relevance 95%, Completeness 90%, Evidence 93%, Consensus 87%, Governance 97%
- Terminal shows final answer with impact analysis
- CTA: "8 agents. 500 tokens. 92% confidence. Your AI was guessing. Now it knows."
- `pip install graqle` button

### Posts: Square Format

**`story-node-square.png`** (1080x1080)
Same node anatomy concept condensed for feed posts. Three rings, labels, step flow (1→2→3 with costs), punchline.

### Hero Images

**`hero-dark.svg`** — The original animated hero used on the GraQle README and website. Shows before (scattered files) vs after (knowledge graph) with terminal output.

**`hero-dark-hq.png`** — High-resolution PNG fallback (3200x2080) for platforms that don't render SVG.

---

## Color System

| Element | Color | Hex | Usage |
|---------|-------|-----|-------|
| Primary / Cyan | Cyan | `#06b6d4` | Brand, LLM layer, primary accents |
| Purple | Violet | `#a855f7` | Embedding layer, secondary accents |
| Amber | Orange | `#f59e0b` | Memory layer, stats, cost highlights |
| Green | Emerald | `#10b981` | Success, consensus, confidence |
| Red/Rose | Rose | `#f43f5e` | Warnings, "before" state |
| Pink | Pink | `#ec4899` | Database nodes |
| Sky | Light blue | `#38bdf8` | Utility nodes |
| Background | Slate | `#020617` | All backgrounds |
| Card | Dark slate | `#0f172a` | Card/panel backgrounds |
| Border | Slate | `#1e293b` | Borders, separators |
| Muted text | Slate | `#64748b` | Secondary text |
