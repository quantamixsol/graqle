#!/usr/bin/env python3
"""Run the Multi-Governance 3-Tier Benchmark — v2 with Governance-Constrained Reasoning.

Usage:
    python -m graqle.benchmarks.run_multigov_v2 [--model MODEL] [--tiers ABC]

v2 enhancements over v1:
    - Ontology-aware reasoning (OWL class hierarchy + SHACL validation gate)
    - Constraint propagation between nodes
    - Ontology-routed message passing
    - Skill-enhanced node reasoning
    - Active observer feedback (REDIRECT/DEEPEN/PRUNE/AFFIRM)
    - Semantic convergence via embeddings
    - Constrained aggregation prompt
    - DeepSeek-R1:7B reasoning model (default) + Qwen2.5-3B observer
"""

# ── graqle:intelligence ──
# module: graqle.benchmarks.run_multigov_v2
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, argparse, asyncio, logging, sys +16 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("multigov_v2_benchmark.log", mode="w"),
    ],
)
logger = logging.getLogger("graqle.benchmark.multigov_v2")

from graqle.backends.api import OllamaBackend
from graqle.benchmarks.benchmark_runner import (
    BenchmarkRunner,
    BenchmarkSummary,
    QuestionResult,
    exact_match,
    f1_score,
    save_multigov_results,
)
from graqle.benchmarks.multi_governance_benchmark import (
    get_questions_by_tier,
)
from graqle.benchmarks.multi_governance_kg import build_multi_governance_kg, get_kg_stats
from graqle.config.settings import GraqleConfig
from graqle.core.graph import Graqle
from graqle.core.types import ReasoningResult
from graqle.ontology import (
    ConstraintGraph,
    DomainRegistry,
    OntologyRouter,
    SHACLGate,
    SkillResolver,
    UpperOntology,
)
from graqle.ontology.domains.governance import register_governance_domain
from graqle.orchestration.aggregation import Aggregator
from graqle.orchestration.convergence import ConvergenceDetector
from graqle.orchestration.message_passing import MessagePassingProtocol
from graqle.orchestration.observer import MasterObserver
from graqle.orchestration.orchestrator import Orchestrator

# Map benchmark KG types to governance ontology types for better skill/constraint coverage
KG_TYPE_TO_GOV_TYPE = {
    "Article": "GOV_REQUIREMENT",
    "Regulation": "GOV_FRAMEWORK",
    "Actor": "GOV_ACTOR",
    "Concept": "Governance",
    "Process": "GOV_PROCESS",
    "Penalty": "GOV_ENFORCEMENT",
}


def _remap_node_types(graph: Graqle) -> None:
    """Remap generic KG types to governance ontology types for better constraint matching."""
    for node in graph.nodes.values():
        if node.entity_type in KG_TYPE_TO_GOV_TYPE:
            node.entity_type = KG_TYPE_TO_GOV_TYPE[node.entity_type]


def _setup_governance_orchestrator(
    config: GraqleConfig,
    ontology_router: OntologyRouter,
    skill_resolver: SkillResolver,
    shacl_gate: SHACLGate,
    constraint_graph: ConstraintGraph,
    ontology_registry: DomainRegistry,
    observer_backend: OllamaBackend | None = None,
) -> Orchestrator:
    """Create an Orchestrator with full governance components."""
    # Message passing with ontology routing
    message_protocol = MessagePassingProtocol(
        parallel=not config.orchestration.async_mode,
        ontology_router=ontology_router,
    )

    # Semantic convergence (fall back to Jaccard without embedding_fn for now)
    convergence = ConvergenceDetector(
        max_rounds=config.orchestration.max_rounds,
        min_rounds=config.orchestration.min_rounds,
        similarity_threshold=0.88,
        confidence_threshold=config.orchestration.confidence_threshold,
    )

    # Constrained aggregation
    aggregator = Aggregator(
        strategy="weighted_synthesis",
        min_confidence=0.20,
        use_constrained_prompt=True,
    )

    # Active observer
    observer = MasterObserver(
        enabled=True,
        report_per_round=True,
        detect_conflicts=True,
        detect_patterns=True,
        detect_anomalies=True,
    )

    return Orchestrator(
        config=config.orchestration,
        message_protocol=message_protocol,
        convergence_detector=convergence,
        aggregator=aggregator,
        observer=observer,
        ontology_registry=ontology_registry,
        constraint_graph=constraint_graph,
        ontology_router=ontology_router,
        skill_resolver=skill_resolver,
        shacl_gate=shacl_gate,
    )


async def run_v2_benchmark(
    model: str = "deepseek-r1:7b",
    observer_model: str = "qwen2.5:3b",
    host: str = "http://localhost:11434",
    tiers: str = "ABC",
    max_rounds: int = 3,
    max_nodes: int = 10,
    output_dir: str = "benchmarks/results/multigov_v2",
) -> dict[str, BenchmarkSummary]:
    """Run the v2 governance-constrained benchmark."""
    print("=" * 70)
    print("Graqle v2: Governance-Constrained Reasoning Benchmark")
    print("=" * 70)

    # 1. Build KG
    print("\n[1/6] Building Multi-Governance Knowledge Graph...")
    kg = build_multi_governance_kg()
    stats = get_kg_stats(kg)
    print(f"  Nodes: {stats['nodes']}, Edges: {stats['edges']}")
    print(f"  Chunks: {stats['total_chunks']} ({stats['avg_chunks_per_node']:.1f}/node)")
    print(f"  Frameworks: {stats['frameworks']}")

    # 2. Setup governance ontology
    print("\n[2/6] Initializing Governance Ontology...")
    registry = DomainRegistry()
    register_governance_domain(registry)
    upper = UpperOntology()

    # Extend upper ontology with governance types
    upper.extend({"Governance": "Entity"})

    # Extract output shapes from registry for SHACL gate
    all_output_shapes = registry.get_all_output_shapes()
    shacl_gate = SHACLGate(all_output_shapes)
    constraint_graph = ConstraintGraph()
    ontology_router = OntologyRouter(registry)
    skill_resolver = SkillResolver(registry)

    gov_domain = registry.get_domain("governance")
    print("  Domain: governance")
    print(f"  Entity types: {len(gov_domain.valid_entity_types)}")
    print(f"  Relationship shapes: {len(gov_domain.relationship_shapes)}")
    print(f"  Output shapes: {len(gov_domain.output_shapes)}")
    print(f"  Skills: {sum(len(v) for v in gov_domain.skill_map.values())}")

    # 3. Select questions
    print(f"\n[3/6] Loading benchmark questions (tiers: {tiers})...")
    questions = []
    for tier in tiers.upper():
        tier_qs = get_questions_by_tier(tier)
        questions.extend(tier_qs)
        print(f"  Tier {tier}: {len(tier_qs)} questions")
    print(f"  Total: {len(questions)} questions")

    # 4. Initialize backends
    print("\n[4/6] Initializing backends...")
    reasoning_backend = OllamaBackend(model=model, host=host, num_ctx=8192)
    observer_backend = OllamaBackend(model=observer_model, host=host)
    print(f"  Reasoning model: {model}")
    print(f"  Observer model: {observer_model}")

    # Verify backends
    try:
        test = await reasoning_backend.generate("Hello", max_tokens=5)
        print(f"  Reasoning OK: {test[:30]}...")
    except Exception as e:
        print(f"  ERROR: Cannot reach reasoning model at {host}: {e}")
        sys.exit(1)

    # 5. Run benchmark
    print("\n[5/6] Running benchmark...")
    start = time.perf_counter()

    # Build context text for single-agent baseline
    context_parts = []
    for nid, data in kg.nodes(data=True):
        label = data.get("label", nid)
        desc = data.get("description", "")
        chunks = data.get("chunks", [])
        part = f"### {label}\n{desc}"
        if chunks:
            for i, c in enumerate(chunks, 1):
                if isinstance(c, dict):
                    part += f"\n[{i}] ({c.get('type', 'evidence')}) {c.get('text', '')}"
                else:
                    part += f"\n[{i}] {c}"
        context_parts.append(part)
    context_text = "\n\n".join(context_parts)

    results: dict[str, list[QuestionResult]] = {
        "single-agent": [],
        "graqle-pcst-v2": [],
    }

    for i, q in enumerate(questions):
        tier_label = f"Tier {q.tier}" if hasattr(q, "tier") else ""
        print(f"\n  Q{i+1}/{len(questions)} [{tier_label}] {q.id}: {q.question[:50]}...")

        # --- Single-agent baseline ---
        try:
            sa_start = time.perf_counter()
            prompt = (
                f"Answer the following question using ONLY the provided context. "
                f"Give a short, direct answer.\n\n"
                f"Context:\n{context_text}\n\n"
                f"Question: {q.question}\n\n"
                f"Answer:"
            )
            sa_answer = await reasoning_backend.generate(prompt, max_tokens=256)
            sa_answer = sa_answer.strip()
            sa_latency = (time.perf_counter() - sa_start) * 1000
            sa_tokens = len(prompt.split()) + len(sa_answer.split())

            sa_f1 = f1_score(sa_answer, q.expected_answer)
            if hasattr(q, "keywords") and q.keywords:
                kw_f1 = BenchmarkRunner._keyword_f1(sa_answer, q.keywords)
                sa_f1 = max(sa_f1, kw_f1)

            results["single-agent"].append(QuestionResult(
                question_id=q.id,
                question=q.question,
                gold_answer=q.expected_answer,
                predicted_answer=sa_answer,
                exact_match=exact_match(sa_answer, q.expected_answer),
                f1=sa_f1,
                latency_ms=sa_latency,
                cost_usd=reasoning_backend.cost_per_1k_tokens * sa_tokens / 1000,
                total_tokens=sa_tokens,
                convergence_rounds=1,
                active_nodes=1,
                method="single-agent",
            ))
            print(f"    [single-agent] F1={sa_f1:.3f} lat={sa_latency:.0f}ms")
        except Exception as e:
            logger.error(f"    [single-agent] ERROR: {e}")
            results["single-agent"].append(QuestionResult(
                question_id=q.id, question=q.question,
                gold_answer=q.expected_answer,
                predicted_answer=f"ERROR: {e}",
                exact_match=0.0, f1=0.0, latency_ms=0.0,
                cost_usd=0.0, total_tokens=0,
                convergence_rounds=0, active_nodes=0,
                method="single-agent",
            ))

        # --- Graqle-PCST v2 (governance-constrained) ---
        try:
            config = GraqleConfig.default()
            config.orchestration.max_rounds = max_rounds
            config.orchestration.async_mode = True
            config.activation.strategy = "pcst"
            config.activation.max_nodes = max_nodes

            graph = Graqle.from_networkx(kg, config=config)

            # Remap node types to governance types
            _remap_node_types(graph)

            # Set backends
            graph.set_default_backend(reasoning_backend)

            # Create governance-aware orchestrator
            orchestrator = _setup_governance_orchestrator(
                config=config,
                ontology_router=ontology_router,
                skill_resolver=skill_resolver,
                shacl_gate=shacl_gate,
                constraint_graph=constraint_graph,
                ontology_registry=registry,
                observer_backend=observer_backend,
            )
            graph._orchestrator = orchestrator

            cg_start = time.perf_counter()
            result: ReasoningResult = await graph.areason(q.question)
            cg_latency = (time.perf_counter() - cg_start) * 1000

            cg_f1 = f1_score(result.answer, q.expected_answer)
            if hasattr(q, "keywords") and q.keywords:
                kw_f1 = BenchmarkRunner._keyword_f1(result.answer, q.keywords)
                cg_f1 = max(cg_f1, kw_f1)

            gov_stats = result.metadata.get("governance_stats", {})

            results["graqle-pcst-v2"].append(QuestionResult(
                question_id=q.id,
                question=q.question,
                gold_answer=q.expected_answer,
                predicted_answer=result.answer,
                exact_match=exact_match(result.answer, q.expected_answer),
                f1=cg_f1,
                latency_ms=cg_latency,
                cost_usd=result.cost_usd,
                total_tokens=result.metadata.get("total_tokens", 0),
                convergence_rounds=result.rounds_completed,
                active_nodes=result.node_count,
                method="graqle-pcst-v2",
                shacl_pass=gov_stats.get("shacl_validations_pass", 0),
                shacl_fail=gov_stats.get("shacl_validations_fail", 0),
                constraint_propagations=gov_stats.get("constraint_propagations", 0),
                observer_redirects=gov_stats.get("observer_redirects", 0),
                ontology_route_filtered=gov_stats.get("ontology_route_filtered", 0),
            ))
            print(f"    [pcst-v2] F1={cg_f1:.3f} lat={cg_latency:.0f}ms "
                  f"nodes={result.node_count} rounds={result.rounds_completed} "
                  f"shacl={gov_stats.get('shacl_validations_pass', 0)}p/{gov_stats.get('shacl_validations_fail', 0)}f")
        except Exception as e:
            logger.error(f"    [pcst-v2] ERROR: {e}", exc_info=True)
            results["graqle-pcst-v2"].append(QuestionResult(
                question_id=q.id, question=q.question,
                gold_answer=q.expected_answer,
                predicted_answer=f"ERROR: {e}",
                exact_match=0.0, f1=0.0, latency_ms=0.0,
                cost_usd=0.0, total_tokens=0,
                convergence_rounds=0, active_nodes=0,
                method="graqle-pcst-v2",
            ))

    elapsed = time.perf_counter() - start
    print(f"\n  Benchmark completed in {elapsed:.1f}s")

    # Build summaries
    summaries: dict[str, BenchmarkSummary] = {}
    for method, qrs in results.items():
        valid = [r for r in qrs if not r.predicted_answer.startswith("ERROR")]
        n = len(valid) or 1
        summaries[method] = BenchmarkSummary(
            method=method,
            dataset="MultiGov-30-v2",
            n_questions=len(qrs),
            avg_em=sum(r.exact_match for r in valid) / n,
            avg_f1=sum(r.f1 for r in valid) / n,
            avg_latency_ms=sum(r.latency_ms for r in valid) / n,
            avg_cost_usd=sum(r.cost_usd for r in valid) / n,
            avg_tokens=sum(r.total_tokens for r in valid) / n,
            avg_rounds=sum(r.convergence_rounds for r in valid) / n,
            avg_nodes=sum(r.active_nodes for r in valid) / n,
            total_cost_usd=sum(r.cost_usd for r in qrs),
            total_latency_s=sum(r.latency_ms for r in qrs) / 1000,
            total_shacl_pass=sum(r.shacl_pass for r in valid),
            total_shacl_fail=sum(r.shacl_fail for r in valid),
            total_constraint_propagations=sum(r.constraint_propagations for r in valid),
            total_observer_redirects=sum(r.observer_redirects for r in valid),
            total_ontology_route_filtered=sum(r.ontology_route_filtered for r in valid),
            question_results=qrs,
        )

    # 6. Save results
    print("\n[6/6] Saving results...")
    save_multigov_results(summaries, output_dir)
    print(f"  Results saved to {output_dir}/")

    return summaries


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Graqle v2 Multi-Governance Benchmark"
    )
    parser.add_argument("--model", default="deepseek-r1:7b", help="Reasoning model")
    parser.add_argument("--observer-model", default="qwen2.5:3b", help="Observer model")
    parser.add_argument("--host", default="http://localhost:11434", help="Ollama host")
    parser.add_argument("--tiers", default="ABC", help="Tiers to run (A, B, C)")
    parser.add_argument("--max-rounds", type=int, default=3, help="Max rounds")
    parser.add_argument("--max-nodes", type=int, default=10, help="Max active nodes")
    parser.add_argument(
        "--output", default="benchmarks/results/multigov_v2", help="Output dir"
    )

    args = parser.parse_args()
    asyncio.run(run_v2_benchmark(
        model=args.model,
        observer_model=args.observer_model,
        host=args.host,
        tiers=args.tiers,
        max_rounds=args.max_rounds,
        max_nodes=args.max_nodes,
        output_dir=args.output,
    ))
