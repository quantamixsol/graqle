#!/usr/bin/env python3
"""Run the Multi-Governance 3-Tier Benchmark.

Usage:
    python -m graqle.benchmarks.run_multigov [--model MODEL] [--tiers ABC]

This runs 30 questions across 3 tiers:
    Tier A: Single-regulation (10Q) — baseline capability
    Tier B: Cross-regulation (10Q) — Graqle advantage emerges
    Tier C: Complex inter-domain (10Q) — Graqle significantly outperforms

Methods compared:
    1. Single-Agent (all context concatenated, single LLM call)
    2. Graqle-PCST (PCST subgraph activation + message passing)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("multigov_benchmark.log", mode="w"),
    ],
)
logger = logging.getLogger("graqle.benchmark.multigov")

from graqle.benchmarks.benchmark_runner import BenchmarkRunner, save_multigov_results
from graqle.benchmarks.multi_governance_benchmark import (
    ALL_QUESTIONS,
    get_questions_by_tier,
    get_tier_stats,
)
from graqle.benchmarks.multi_governance_kg import build_multi_governance_kg, get_kg_stats


async def main(
    model: str = "qwen2.5:3b",
    host: str = "http://localhost:11434",
    tiers: str = "ABC",
    max_rounds: int = 3,
    max_nodes: int = 10,
    output_dir: str = "benchmarks/results/multigov",
) -> None:
    """Run multi-governance benchmark."""
    print("=" * 70)
    print("Graqle Multi-Governance 3-Tier Benchmark")
    print("=" * 70)

    # Build KG
    print("\n[1/4] Building Multi-Governance Knowledge Graph...")
    kg = build_multi_governance_kg()
    stats = get_kg_stats(kg)
    print(f"  Nodes: {stats['nodes']}, Edges: {stats['edges']}")
    print(f"  Chunks: {stats['total_chunks']} ({stats['avg_chunks_per_node']:.1f}/node)")
    print(f"  Total knowledge: {stats['total_knowledge_chars']:,} chars")
    print(f"  Frameworks: {stats['frameworks']}")

    # Select questions
    print(f"\n[2/4] Loading benchmark questions (tiers: {tiers})...")
    questions = []
    for tier in tiers.upper():
        tier_qs = get_questions_by_tier(tier)
        questions.extend(tier_qs)
        print(f"  Tier {tier}: {len(tier_qs)} questions")

    tier_stats = get_tier_stats()
    print(f"  Total: {len(questions)} questions")

    # Initialize runner
    print(f"\n[3/4] Initializing benchmark runner...")
    print(f"  Model: {model}")
    print(f"  Host: {host}")
    print(f"  Max rounds: {max_rounds}, Max nodes: {max_nodes}")

    runner = BenchmarkRunner(
        model=model,
        host=host,
        max_rounds=max_rounds,
        max_nodes=max_nodes,
    )

    # Verify Ollama is reachable
    try:
        test = await runner.backend.generate("Hello", max_tokens=5)
        print(f"  Ollama OK: {test[:30]}...")
    except Exception as e:
        print(f"  ERROR: Cannot reach Ollama at {host}: {e}")
        print("  Start Ollama with: ollama serve")
        sys.exit(1)

    # Run benchmark
    print(f"\n[4/4] Running benchmark...")
    start = time.perf_counter()

    summaries = await runner.run_multi_governance(
        questions=questions,
        kg=kg,
        methods=["single-agent", "graqle-pcst"],
    )

    elapsed = time.perf_counter() - start
    print(f"\n  Benchmark completed in {elapsed:.1f}s")

    # Save results
    save_multigov_results(summaries, output_dir)
    print(f"\n  Results saved to {output_dir}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Graqle Multi-Governance Benchmark")
    parser.add_argument("--model", default="qwen2.5:3b", help="Ollama model name")
    parser.add_argument("--host", default="http://localhost:11434", help="Ollama host URL")
    parser.add_argument("--tiers", default="ABC", help="Which tiers to run (A, B, C, or any combination)")
    parser.add_argument("--max-rounds", type=int, default=3, help="Max message passing rounds")
    parser.add_argument("--max-nodes", type=int, default=10, help="Max active nodes per query")
    parser.add_argument("--output", default="benchmarks/results/multigov", help="Output directory")

    args = parser.parse_args()
    asyncio.run(main(
        model=args.model,
        host=args.host,
        tiers=args.tiers,
        max_rounds=args.max_rounds,
        max_nodes=args.max_nodes,
        output_dir=args.output,
    ))
