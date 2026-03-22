# Post 3: The Embedding Layer — Semantic Similarity

**Series:** The Graph-of-Agents Reasoning Model (3 of 7)
**Visual:** `posts/story-node-square.png` (middle purple ring)
**Platforms:** LinkedIn, Twitter, dev.to

---

## LinkedIn / Facebook Caption

```
Memory tells us WHO is connected.
Embeddings tell us WHO is RELEVANT.

After the graph memory layer identifies connected nodes,
the embedding layer scores them by semantic similarity.

Here's how it works:

1. Your query gets embedded ONCE
   "what breaks if I change auth?" → [0.82, -0.14, 0.67, ...]

2. That single vector is compared against
   pre-computed chunk embeddings (.npz cache)

3. Cosine similarity scores every node:
   auth.py     → 0.94 (direct match)
   routes.py   → 0.87 (imports auth decorator)
   api.py      → 0.82 (imports verify_token)
   middleware   → 0.79 (wraps auth)
   config.py   → 0.31 (barely related)
   utils.py    → 0.22 (not relevant)

4. Only nodes above threshold get activated

The key insight: we DON'T re-embed the entire codebase.

The chunk embeddings are pre-computed during `graq scan`
and cached in a .npz file. At query time, only ONE
embedding call happens — for the query itself.

That's why it costs ~$0.00001 instead of $0.05.

This is the second filter:
→ Memory narrowed from ALL nodes to CONNECTED nodes
→ Embeddings narrow from CONNECTED to RELEVANT

Only the relevant subgraph goes to the LLM.

Memory first. Embeddings second. LLM last.

#GraQle #Embeddings #SemanticSearch #AI #DevTools
```

## Twitter / X Thread (continuation)

```
6/ LAYER 2: Embeddings (cost: ~$0.00001)

Memory found the connected nodes.
Now: which ones are actually RELEVANT to this query?

Your query → 1 embedding call → compare against cached chunks

auth.py  → 0.94 ✓
routes   → 0.87 ✓
api      → 0.82 ✓
config   → 0.31 ✗

Only relevant nodes survive.
```

```
7/ The critical optimization:

We DON'T re-embed the codebase every query.

Chunk embeddings are cached in .npz format
during `graq scan`. One-time cost.

At query time: 1 vector call.
Not 10,000. Not 1,000. One.

That's the difference between $0.00001 and $0.05.
```

```
8/ Two filters applied. Zero LLM tokens spent.

Memory: ALL → CONNECTED (graph edges)
Embeddings: CONNECTED → RELEVANT (cosine sim)

The LLM only sees the relevant subgraph.
500 tokens. Not 50,000.

Now we're ready for the reasoning layer →
```

## Technical Deep Dive (dev.to / blog)

```
## The Embedding Layer: Why One Vector Call Is Enough

Traditional RAG re-embeds or re-retrieves chunks on every query.
GraQle pre-computes chunk embeddings during scan time and caches
them as a NumPy .npz file.

At query time:
1. Embed the query string (1 call to sentence-transformers or Titan V2)
2. Load the cached chunk matrix (one mmap read)
3. Compute cosine similarity: query_vector @ chunk_matrix.T
4. Rank nodes by max chunk similarity
5. Activate nodes above threshold

This is O(1) embedding calls + O(N) matrix multiply.
For a 10K-node graph, activation takes <1 second.

The pre-computation happens during `graq scan repo .` and is
stored at `.graqle/chunk_embeddings.npz`. As of v0.33.0, this
cache is auto-built after every scan (no manual step needed).

Cost comparison:
- Traditional RAG: ~$0.05/query (re-embed query + retrieve top-k)
- GraQle: ~$0.00001/query (1 embed call + cached matrix)
- Difference: 5,000x cheaper at the embedding layer alone
```
