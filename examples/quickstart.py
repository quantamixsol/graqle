"""Graqle Quickstart — 5-minute demo with mock backend.

This example creates a small regulatory knowledge graph,
assigns mock agents to each node, and runs a reasoning query.
No GPU, no API keys, no database — just Python.
"""

# ── graqle:intelligence ──
# module: examples.quickstart
# risk: LOW (impact radius: 0 modules)
# dependencies: asyncio, networkx, graqle, mock
# constraints: none
# ── /graqle:intelligence ──

import asyncio

import networkx as nx

from graqle import Graqle
from graqle.backends.mock import MockBackend


def create_regulatory_graph() -> nx.Graph:
    """Create a small EU regulatory knowledge graph."""
    G = nx.Graph()

    # Regulation nodes
    G.add_node("gdpr", label="GDPR", type="Regulation",
               description="General Data Protection Regulation (EU 2016/679). "
                           "Governs personal data processing, consent, and data subject rights.")

    G.add_node("ai_act", label="AI Act", type="Regulation",
               description="EU AI Act (2024/1689). "
                           "Risk-based framework for AI systems. High-risk AI requires conformity assessment.")

    G.add_node("art22", label="GDPR Art. 22", type="Article",
               description="Right not to be subject to automated decision-making. "
                           "Individuals can object to decisions made solely by automated processing.")

    G.add_node("art6", label="AI Act Art. 6", type="Article",
               description="Classification of high-risk AI systems. "
                           "Systems in Annex III are high-risk and require conformity assessment.")

    G.add_node("art13", label="AI Act Art. 13", type="Article",
               description="Transparency obligations for high-risk AI. "
                           "Must provide clear information about AI system capabilities and limitations.")

    G.add_node("consent", label="Consent Mechanism", type="Concept",
               description="Legal basis for processing under GDPR Art. 6(1)(a). "
                           "Must be freely given, specific, informed, and unambiguous.")

    # Edges (relationships)
    G.add_edge("gdpr", "art22", relationship="CONTAINS")
    G.add_edge("ai_act", "art6", relationship="CONTAINS")
    G.add_edge("ai_act", "art13", relationship="CONTAINS")
    G.add_edge("art22", "art6", relationship="CONFLICTS_WITH", weight=0.8)
    G.add_edge("art22", "art13", relationship="REFERENCES", weight=0.6)
    G.add_edge("gdpr", "consent", relationship="DEFINES")
    G.add_edge("consent", "art22", relationship="RELATED_TO", weight=0.7)
    G.add_edge("gdpr", "ai_act", relationship="INTERACTS_WITH", weight=0.9)

    return G


async def main():
    # 1. Create graph
    G = create_regulatory_graph()

    # 2. Build Graqle from NetworkX
    graph = Graqle.from_networkx(G)
    print(f"Created: {graph}")
    print(f"Stats: {graph.stats}")
    print()

    # 3. Assign mock backend (replace with real model for production)
    mock = MockBackend(responses=[
        "GDPR Art. 22 prohibits automated decision-making without human oversight. "
        "AI Act Art. 6 classifies AI systems that make automated decisions as HIGH-RISK. "
        "There is a CONFLICT: GDPR requires opt-out from automated decisions, but AI Act "
        "allows high-risk AI systems to operate with conformity assessment. "
        "Confidence: 82%",

        "The AI Act's transparency requirements (Art. 13) align with GDPR's consent mechanism. "
        "Both require informing individuals about automated processing. "
        "However, the AI Act's risk classification (Art. 6) creates a PARALLEL regime "
        "that doesn't fully defer to GDPR's individual rights framework. "
        "Confidence: 75%",

        "Synthesizing: GDPR and AI Act create a DUAL REGIME for automated decisions. "
        "Organizations must comply with BOTH: GDPR consent + AI Act conformity assessment. "
        "Key conflict: GDPR Art. 22 gives individuals opt-out rights, but AI Act allows "
        "high-risk AI operation after conformity assessment — even without individual consent. "
        "Recommendation: Implement GDPR consent as a PREREQUISITE for AI Act conformity. "
        "Confidence: 88%",
    ])
    graph.set_default_backend(mock)

    # 4. Run reasoning query
    query = "How does GDPR Article 22 conflict with AI Act Chapter 3?"
    print(f"Query: {query}")
    print("Running reasoning...")
    print()

    result = await graph.areason(
        query,
        max_rounds=3,
        strategy="full",  # activate all nodes (small graph)
    )

    # 5. Display results
    print(f"Answer:\n{result.answer}")
    print()
    print(f"Confidence: {result.confidence:.0%}")
    print(f"Rounds: {result.rounds_completed}")
    print(f"Active nodes: {result.node_count}")
    print(f"Cost: ${result.cost_usd:.4f}")
    print(f"Latency: {result.latency_ms:.0f}ms")
    print(f"Messages traced: {len(result.message_trace)}")


if __name__ == "__main__":
    asyncio.run(main())
