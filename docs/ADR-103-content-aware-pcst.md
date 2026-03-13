# ADR-103: Content-Aware PCST Activation

**Date:** 2026-03-12 | **Status:** ACCEPTED
**Author:** Harish Kumar, Quantamix Solutions B.V.

## Context

PCST (Prize-Collecting Steiner Tree) activation selects the optimal subgraph of nodes to activate for each query. The algorithm assigns prizes (relevance scores) to nodes and costs to edges, then finds the subtree that maximizes total prize minus total cost.

**Problem:** In codebases with directory structures, Directory nodes act as high-degree hub connectors in the PCST tree. Because they connect many children, PCST frequently selects them as Steiner nodes (relay points) even when they carry zero evidence chunks. The agents assigned to these empty Directory nodes produce generic, low-confidence answers — degrading overall reasoning quality.

**Root cause:** The v2 relevance scorer computed prizes purely from cosine similarity + property boosts, with no weighting for whether a node actually has evidence to reason from. A Directory node with a description like "Source directory containing all services" could score similarly to a JSModule node with actual code chunks.

## Decision

Implement a 3-layer content-awareness system that ensures PCST always prefers content-bearing nodes over empty structural connectors.

### Layer 1: Content Richness Multiplier (relevance.py)

**Formula:**
```
adjusted_prize = base_relevance × log₂(2 + chunk_count)
```

| chunk_count | multiplier | effect |
|-------------|-----------|--------|
| 0 | 1.0 | neutral (no penalty, no boost) |
| 1 | ~1.58 | +58% prize boost |
| 3 | ~2.32 | +132% prize boost |
| 5 | ~2.81 | +181% prize boost |
| 10 | ~3.58 | +258% prize boost |

**Why logarithmic?** Linear would over-penalize nodes with few chunks. Logarithmic provides diminishing returns — the first few chunks matter most, avoiding bias toward large files with many functions.

**Why not penalty instead of boost?** A penalty on zero-chunk nodes would break regulatory/ontology KGs where nodes legitimately have no source files. The multiplicative boost preserves the neutral baseline for empty nodes while rewarding evidence-bearing ones.

### Layer 2: Post-PCST Content Filter (pcst.py)

After PCST selects its optimal subtree, any remaining zero-chunk nodes are replaced:

1. For each selected node with 0 chunks:
   - Find its graph neighbours
   - Select the neighbour with the highest relevance score that has ≥1 chunk
   - Swap it in
2. If no neighbour has chunks, keep the original (agent uses description)
3. If the replacement is already selected, drop the duplicate slot

**Edge cases:**
- Isolated nodes (no edges) → kept as-is
- All neighbours also have zero chunks → original kept
- Replacement already in selection → no duplicates

### Layer 3: Direct File Lookup Bypass (graph.py)

When the query explicitly mentions a filename (e.g., "What does auth.ts do?"), bypass PCST entirely:

1. Build a filename→node_id index from all node labels
2. Check if the query contains any known filename (full name or bare name)
3. If match found: activate that node + its immediate neighbours
4. If no match: fall through to PCST

**Edge cases:**
- Short labels (<3 chars) → ignored to prevent false positives
- Bare name matching uses word boundary regex ("auth" in "the auth service" matches, but "auth" in "authentication" does not)
- Path labels ("src/services/auth.ts") → basename extracted
- Multiple files in query → all activated
- Case-insensitive matching

## Consequences

### Positive
- Directory/Namespace nodes no longer crowd out content-bearing JSModule/Module/Config nodes
- Explicit file references are guaranteed to activate the right node (100% precision)
- Zero-chunk Steiner relay nodes are replaced with evidence-bearing alternatives
- Backward compatible — regulatory KGs with no source files get neutral multiplier (1.0)
- Scores can now exceed 1.0, providing better PCST prize differentiation

### Negative
- Slightly higher computational cost in relevance scoring (log2 per node — negligible)
- Post-PCST filter adds O(N×D) work where N = selected nodes, D = avg degree
- Direct file lookup adds an O(N) index build per query (amortizable)

### Trade-offs
- The `_apply_property_boosts` return value is no longer clamped to [0, 1] — this is intentional, as prizes > 1.0 improve PCST differentiation
- The content multiplier uses base 2 (log₂). Alternatives considered: ln (too aggressive), log₁₀ (too conservative), sqrt (wrong curve shape)

## Test Coverage

33 dedicated tests in `tests/test_activation/test_content_aware_pcst.py`:
- 6 tests for Layer 1 (content richness multiplier)
- 6 tests for Layer 2 (post-PCST content filter)
- 9 tests for Layer 3 (direct file lookup)
- 5 integration tests (full pipeline)
- 7 edge case tests (empty chunks, string chunks, missing nodes, short labels, etc.)

## References

- Patent EP26162901.8 — Innovation #1 (PCST Activation), Innovation #9 (Adaptive Activation)
- `graqle/activation/relevance.py` — Layer 1 + Layer 3 partial
- `graqle/activation/pcst.py` — Layer 2
- `graqle/core/graph.py` — Layer 3 full (direct file lookup bypass)
