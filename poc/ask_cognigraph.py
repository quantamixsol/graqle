"""Ask CogniGraph a real question about the CrawlQ/TraceGov KG.

Uses the CogniGraph SDK to reason over the 291-node CrawlQ knowledge graph
to answer: "What information and tests should be done before and after
adding a new Lambda function?"
"""

import asyncio
import os
import sys
import time

# Add cognigraph to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cognigraph.core.graph import CogniGraph
from cognigraph.config.settings import CogniGraphConfig, CostConfig
from cognigraph.backends.api import AnthropicBackend, BedrockBackend


async def main():
    # Fix Windows encoding
    import io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print("=" * 70)
    print("CogniGraph -- Real Question on CrawlQ/TraceGov KG")
    print("=" * 70)

    # 1. Load the CrawlQ KG
    kg_path = os.path.join(os.path.dirname(__file__), "..", "..", "cognigraph.json")
    kg_path = os.path.abspath(kg_path)
    print(f"\nLoading KG from: {kg_path}")

    # Increase cost budget to $0.10 for a complete answer
    config = CogniGraphConfig.default()
    config.cost = CostConfig(budget_per_query=0.10)

    graph = CogniGraph.from_json(kg_path, config=config)
    print(f"Loaded: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
    print(f"Cost budget: ${config.cost.budget_per_query}")

    # 2. Set up backend — prefer Bedrock (in-region EU), fallback to Anthropic API
    use_bedrock = os.environ.get("COGNIGRAPH_BACKEND", "anthropic").lower() == "bedrock"
    if use_bedrock:
        backend = BedrockBackend(
            model="eu.anthropic.claude-haiku-4-5-20251001-v1:0",
            region="eu-central-1",
        )
    else:
        backend = AnthropicBackend(
            model="claude-haiku-4-5-20251001",
            api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        )
    graph.set_default_backend(backend)
    print(f"Backend: {backend.name}")

    # 3. The question
    query = (
        "What is the dependency of NEO4J_PASSWORD environment variable? "
        "Which Lambda functions depend on it, what services use it, "
        "and what tests should be performed to verify NEO4J_PASSWORD is "
        "correctly configured before and after deployment?"
    )

    print(f"\nQuery: {query}")
    print("-" * 70)

    # 4. Run reasoning with PCST strategy (activate query-relevant nodes)
    # PCST selects nodes most relevant to the query, not just most connected
    use_streaming = os.environ.get("COGNIGRAPH_STREAM", "").lower() == "true"

    if use_streaming:
        print("\nActivating STREAMING reasoning (PCST strategy)...")
        start = time.time()
        chunks = []
        async for chunk in graph.areason_stream(query, max_rounds=3, strategy="pcst"):
            if chunk.chunk_type == "node_result":
                print(f"  [{chunk.node_id}] {chunk.content[:80]}...")
            elif chunk.chunk_type == "round_complete":
                print(f"  -- Round {chunk.round_num} complete --")
            elif chunk.chunk_type == "final_answer":
                chunks.append(chunk)
        # Build a result-like object from streaming
        from cognigraph.core.types import ReasoningResult
        elapsed = time.time() - start
        final = chunks[-1] if chunks else None
        result = ReasoningResult(
            query=query,
            answer=final.content if final else "No answer",
            confidence=final.confidence if final else 0.0,
            rounds_completed=final.round_num if final else 0,
            active_nodes=list(final.metadata.get("active_nodes", [])) if final else [],
            message_trace=[],
            cost_usd=final.metadata.get("cost_usd", 0.0) if final else 0.0,
            latency_ms=elapsed * 1000,
        )
    else:
        print("\nActivating reasoning (PCST strategy, max rounds=3)...")
        start = time.time()
        result = await graph.areason(
            query,
            max_rounds=3,
            strategy="pcst",
        )

    elapsed = time.time() - start

    # 5. Print results
    print("\n" + "=" * 70)
    print("COGNIGRAPH ANSWER")
    print("=" * 70)
    print(f"\n{result.answer}")
    print("\n" + "-" * 70)
    print(f"Confidence: {result.confidence:.2f}")
    print(f"Rounds completed: {result.rounds_completed}")
    print(f"Active nodes: {len(result.active_nodes)}")
    print(f"Node IDs: {result.active_nodes}")
    print(f"Cost: ${result.cost_usd:.4f}")
    print(f"Latency: {elapsed:.1f}s")

    # 6. Show message trace summary
    if result.message_trace:
        print(f"\nMessage trace ({len(result.message_trace)} messages):")
        for i, msg in enumerate(result.message_trace[:10]):
            sender = getattr(msg, "sender", "?")
            content = str(getattr(msg, "content", str(msg)))
            print(f"  [{i+1}] {sender}: {content[:120]}...")

    # 7. Show metrics — what we saved and gained
    print("\n" + "=" * 70)
    print("COGNIGRAPH METRICS -- SAVINGS & GAINS")
    print("=" * 70)

    try:
        from cognigraph.metrics import get_metrics
        engine = get_metrics()

        # End session to finalize
        engine.end_session()

        summary = engine.get_summary()

        # Token savings
        tokens_saved = summary["tokens_saved"]
        context_loads = summary["context_loads"]
        queries = summary["queries"]

        # Cost calculation
        # Without CogniGraph: ~25K tokens per service lookup * $0.015/1K = $0.375 each
        # With CogniGraph: ~500 tokens per context load * $0.015/1K = $0.0075 each
        brute_force_cost = context_loads * 25_000 * 0.015 / 1000
        cognigraph_cost = result.cost_usd
        cost_saved = brute_force_cost - cognigraph_cost

        # Time savings
        # Without CogniGraph: manually reading 20+ files ~15 min per question
        # With CogniGraph: ~30 seconds
        manual_time_min = queries * 15
        cogni_time_min = elapsed / 60

        print(f"\n  --- Token Efficiency ---")
        print(f"  Context loads (node accesses):  {context_loads}")
        print(f"  Total tokens saved:             {tokens_saved:,}")
        if context_loads > 0:
            avg_saved = tokens_saved // context_loads
            avg_returned = 25_000 - avg_saved
            reduction = round(25_000 / max(avg_returned, 1), 1)
            print(f"  Avg tokens saved per load:      {avg_saved:,}")
            print(f"  Context reduction factor:       {reduction}x")

        print(f"\n  --- Cost Impact ---")
        print(f"  Brute-force cost (25K tok/svc): ${brute_force_cost:.2f}")
        print(f"  CogniGraph actual cost:         ${cognigraph_cost:.4f}")
        print(f"  Net savings:                    ${cost_saved:.2f}")
        if brute_force_cost > 0:
            print(f"  Cost reduction:                 {brute_force_cost / max(cognigraph_cost, 0.001):.0f}x cheaper")

        print(f"\n  --- Time Impact ---")
        print(f"  Manual analysis estimate:       ~{manual_time_min} min (reading 20+ files)")
        print(f"  CogniGraph reasoning:           {elapsed:.1f}s ({cogni_time_min:.1f} min)")
        if manual_time_min > 0:
            print(f"  Time savings:                   {manual_time_min - cogni_time_min:.0f} min saved")
            print(f"  Speed improvement:              {manual_time_min * 60 / max(elapsed, 1):.0f}x faster")

        print(f"\n  --- Knowledge Quality ---")
        print(f"  Reasoning queries answered:     {queries}")
        print(f"  Lessons auto-applied:           {summary['lessons_applied']}")
        print(f"  Mistakes flagged:               {summary['mistakes_prevented']}")
        print(f"  Nodes in graph:                 {summary.get('graph_stats_current', {}).get('nodes', len(graph.nodes))}")
        print(f"  Unique nodes accessed:          {summary['unique_nodes_accessed']}")
        print(f"  Active agents this query:       {len(result.active_nodes)}")
        print(f"  Message exchanges:              {len(result.message_trace)}")
        print(f"  Confidence:                     {result.confidence:.0%}")

        # Show node type breakdown
        gs = summary.get("graph_stats_current", {})
        node_types = gs.get("node_types", {})
        if node_types:
            print(f"\n  --- Node Types Accessed ---")
            for ntype, count in sorted(node_types.items(), key=lambda x: -x[1])[:10]:
                print(f"    {ntype}: {count}")

        # Show ROI report
        print(f"\n{engine.get_roi_report()}")

    except Exception as e:
        print(f"  Metrics not available: {e}")

    print("\n" + "=" * 70)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
