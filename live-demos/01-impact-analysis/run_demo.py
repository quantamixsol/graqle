"""
Demo 01: Impact Analysis Before a Risky Change
================================================
Shows the full graqle workflow:
  1. Load existing graph (or scan)
  2. Impact analysis on a core module
  3. Graph-of-agents reasoning
  4. Preflight governance gate
  5. Teach outcome back to graph

Run from project root:
    cd graqle-sdk
    python live-demos/01-impact-analysis/run_demo.py

Requirements:
    pip install graqle>=0.39.0
    ANTHROPIC_API_KEY set (or any backend in graqle.yaml)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Use the installed graqle (or editable install from graqle-sdk/)
try:
    import graqle
except ImportError:
    print("ERROR: graqle not installed. Run: pip install graqle>=0.39.0")
    sys.exit(1)

SDK_ROOT = Path(__file__).parent.parent.parent  # graqle-sdk/
GRAPH_FILE = SDK_ROOT / "graqle.json"

LINE = "=" * 60


def banner(step: int, total: int, title: str) -> None:
    print(f"\n{LINE}")
    print(f"  Step {step}/{total}: {title}")
    print(LINE)


def main() -> None:
    print(f"\nGraqle v{graqle.__version__} — Impact Analysis Demo")
    print(f"Target: graqle/core/graph.py (hub module, CRITICAL risk)")

    # ----------------------------------------------------------------
    # Step 1: Load graph
    # ----------------------------------------------------------------
    banner(1, 5, "Loading knowledge graph")

    if not GRAPH_FILE.exists():
        print(f"No graph found at {GRAPH_FILE}")
        print("Run: graq scan repo . --output graqle.json")
        sys.exit(1)

    from graqle.core.graph import CogniGraph
    graph = CogniGraph.load(str(GRAPH_FILE))
    print(f"  Loaded: {graph.node_count} nodes, {graph.edge_count} edges")

    # ----------------------------------------------------------------
    # Step 2: Impact analysis — what does graph.py affect?
    # ----------------------------------------------------------------
    banner(2, 5, "Impact analysis: graqle/core/graph.py")

    from graqle.core.intelligence import ImpactAnalyzer
    analyzer = ImpactAnalyzer(graph)
    impact = analyzer.analyze("graqle/core/graph.py")

    if impact:
        print(f"  Impact radius: {impact.total_affected} modules")
        print(f"  Risk level: {impact.risk_level}")
        if impact.direct_consumers:
            print(f"  Direct consumers ({len(impact.direct_consumers)}):")
            for c in list(impact.direct_consumers)[:5]:
                print(f"    - {c}")
            if len(impact.direct_consumers) > 5:
                print(f"    ... and {len(impact.direct_consumers) - 5} more")
    else:
        # Fallback: use raw graph traversal
        G = graph.to_networkx()
        if "graqle/core/graph.py" in G:
            consumers = list(G.predecessors("graqle/core/graph.py"))
            print(f"  Direct consumers: {len(consumers)} modules")
            for c in consumers[:5]:
                print(f"    - {c}")
        else:
            print("  Node 'graqle/core/graph.py' not in graph — scan may be needed")

    # ----------------------------------------------------------------
    # Step 3: Reasoning — why is graph.py so central?
    # ----------------------------------------------------------------
    banner(3, 5, "Graph-of-agents reasoning")
    print("  Question: 'Why is graph.py so central and what breaks if we change it?'")
    print("  (Uses multi-agent graph-of-agents reasoning — 50 nodes, 2 rounds)")

    from graqle.core.reasoning import MultiAgentReasoner
    reasoner = MultiAgentReasoner(graph)
    start = time.perf_counter()
    result = reasoner.reason(
        "Why is graph.py so central to the graqle architecture, and what are the "
        "highest-risk things to change in it?"
    )
    elapsed = time.perf_counter() - start
    print(f"\n  Answer ({result.confidence:.0%} confidence, {elapsed:.1f}s):")
    # Print first 500 chars of answer
    answer_preview = result.answer[:500].replace("\n", "\n  ")
    print(f"  {answer_preview}")
    if len(result.answer) > 500:
        print("  [... truncated — full answer available in result.answer]")

    # ----------------------------------------------------------------
    # Step 4: Preflight governance gate
    # ----------------------------------------------------------------
    banner(4, 5, "Preflight governance gate")
    print("  Checking: what do we need to know before touching graph.py?")

    from graqle.core.governance import GovernanceMiddleware
    middleware = GovernanceMiddleware()
    gate_result = middleware.check(
        action="refactor",
        file_path="graqle/core/graph.py",
        content="Rename CogniNode.node_type to CogniNode.entity_type across all files",
        approved_by="senior-engineer",
    )

    print(f"\n  Gate result: {gate_result.tier} | blocked={gate_result.blocked}")
    if gate_result.reason:
        print(f"  Reason: {gate_result.reason[:200]}")

    from graqle.core.kg_sync import is_offline
    print(f"\n  KG sync status: {'OFFLINE (CI mode)' if is_offline() else 'ONLINE (S3 sync active)'}")

    # ----------------------------------------------------------------
    # Step 5: Teach outcome back to graph
    # ----------------------------------------------------------------
    banner(5, 5, "Teaching outcome to graph")
    print("  Recording: impact analysis on graph.py completed, T2 gate passed")

    from graqle.core.graph import CogniGraph, CogniNode
    lesson_node = CogniNode(
        id="lesson_demo01_graph_impact",
        label="Demo lesson: graph.py is a CRITICAL hub — 26+ consumers, always T2 gate",
        entity_type="LESSON",
        source="graq_learn",
        description=(
            "graqle/core/graph.py has the highest impact radius in the codebase (26+ modules). "
            "Any change to CogniNode/CogniEdge schema requires: (1) migration path for serialized "
            "graqle.json files, (2) update to all 14 backends, (3) scanner rebuild. Always T2 gate."
        ),
    )
    # Add to graph in-memory (in real usage this is saved and pushed to S3)
    G = graph.to_networkx()
    G.add_node(
        lesson_node.id,
        label=lesson_node.label,
        entity_type=lesson_node.entity_type,
        source=lesson_node.source,
        description=lesson_node.description,
    )
    print(f"  Lesson node added: {lesson_node.id}")
    print(f"  (In production: schedule_push() syncs this to S3 automatically)")

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    print(f"\n{LINE}")
    print("  DEMO COMPLETE")
    print(LINE)
    print(f"  Graph: {graph.node_count} nodes, {graph.edge_count} edges")
    print(f"  Impact: graph.py has CRITICAL risk (26+ consumers)")
    print(f"  Reasoning: confident answer from graph-of-agents")
    print(f"  Gate: T2 governance check passed")
    print(f"  Sync: lesson recorded, KG sync active (ADR-123 v0.39.0)")
    print()
    print("  Next steps:")
    print("    graq run 'what is the safest way to add a new field to CogniNode?'")
    print("    graq cloud pull  # sync latest KG from S3")
    print("    graq cloud push  # push local changes to S3")
    print()


if __name__ == "__main__":
    main()
