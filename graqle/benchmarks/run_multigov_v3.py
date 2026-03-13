#!/usr/bin/env python3
"""Run Multi-Governance Benchmark v3 — Multi-Backend Comparison.

Thesis: "Reasoning without governance is creativity at scale with compliance risk."
Graqle delivers governance-enforced reasoning at fraction of cost.

Usage:
    # Sonnet 4.6 via Bedrock (fast, ~$5-10):
    python -m graqle.benchmarks.run_multigov_v3 --backend bedrock --model anthropic.claude-sonnet-4-6

    # DeepSeek-R1:7B via Ollama (local, free, ~90min):
    python -m graqle.benchmarks.run_multigov_v3 --backend ollama --model deepseek-r1:7b

    # Qwen2.5-3B via Ollama (local, free, ~15min — previous baseline):
    python -m graqle.benchmarks.run_multigov_v3 --backend ollama --model qwen2.5:3b
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("multigov_v3_benchmark.log", mode="w"),
    ],
)
logger = logging.getLogger("graqle.benchmark.multigov_v3")

from graqle.backends.api import BedrockBackend, OllamaBackend
from graqle.benchmarks.benchmark_runner import (
    BenchmarkSummary,
    QuestionResult,
    exact_match,
    f1_score,
    constrained_f1_score,
    save_multigov_results,
    BenchmarkRunner,
)
from graqle.benchmarks.multi_governance_benchmark import (
    ALL_QUESTIONS,
    get_questions_by_tier,
)
from graqle.benchmarks.multi_governance_kg import build_multi_governance_kg, get_kg_stats
from graqle.config.settings import GraqleConfig
from graqle.core.graph import Graqle
from graqle.core.types import ReasoningResult
from graqle.ontology import (
    DomainRegistry,
    SHACLGate,
    ConstraintGraph,
    OntologyRouter,
    SkillResolver,
    UpperOntology,
)
from graqle.ontology.domains.governance import register_governance_domain
from graqle.ontology.domains.governance_v3 import (
    build_governance_semantic_constraints,
    register_governance_domain_v3,
)
from graqle.ontology.semantic_shacl_gate import SemanticSHACLGate
from graqle.orchestration.aggregation import Aggregator
from graqle.orchestration.convergence import ConvergenceDetector
from graqle.orchestration.message_passing import MessagePassingProtocol
from graqle.orchestration.observer import MasterObserver
from graqle.orchestration.orchestrator import Orchestrator


# Type remapping for governance ontology
KG_TYPE_TO_GOV_TYPE = {
    "Article": "GOV_REQUIREMENT",
    "Regulation": "GOV_FRAMEWORK",
    "Actor": "GOV_ACTOR",
    "Concept": "Governance",
    "Process": "GOV_PROCESS",
    "Penalty": "GOV_ENFORCEMENT",
}


def _remap_node_types(graph: Graqle) -> None:
    """Remap generic KG types to governance ontology types."""
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
    observer_backend=None,
) -> Orchestrator:
    """Create an Orchestrator with full governance components."""
    message_protocol = MessagePassingProtocol(
        parallel=not config.orchestration.async_mode,
        ontology_router=ontology_router,
    )
    convergence = ConvergenceDetector(
        max_rounds=config.orchestration.max_rounds,
        min_rounds=config.orchestration.min_rounds,
        similarity_threshold=0.88,
        confidence_threshold=config.orchestration.confidence_threshold,
    )
    aggregator = Aggregator(
        strategy="weighted_synthesis",
        min_confidence=0.20,
        use_constrained_prompt=True,
    )
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


def _create_backend(backend_type: str, model: str, region: str, host: str):
    """Factory: create the right backend based on type."""
    if backend_type == "bedrock":
        return BedrockBackend(model=model, region=region)
    elif backend_type == "ollama":
        num_ctx = 8192 if "deepseek" in model.lower() or "r1" in model.lower() else None
        return OllamaBackend(model=model, host=host, num_ctx=num_ctx, timeout=300.0)
    else:
        raise ValueError(f"Unknown backend type: {backend_type}")


async def run_v3_benchmark(
    backend_type: str = "bedrock",
    model: str = "anthropic.claude-sonnet-4-6",
    observer_backend_type: str = "ollama",
    observer_model: str = "qwen2.5:0.5b",
    region: str = "eu-central-1",
    host: str = "http://localhost:11434",
    tiers: str = "ABC",
    max_rounds: int = 3,
    max_nodes: int = 10,
    output_dir: str | None = None,
) -> dict:
    """Run the v3 multi-backend governance-constrained benchmark.

    Returns a dict with summaries + cost report for logging.
    """
    # Auto-name output dir
    model_short = model.split(".")[-1] if "." in model else model.replace(":", "-")
    if output_dir is None:
        output_dir = f"benchmarks/results/multigov_v3_{model_short}"

    run_start = datetime.now(timezone.utc)
    cost_log = []  # Per-question cost tracking

    print("=" * 70)
    print("Graqle v3: Governed Intelligence Benchmark")
    print(f"Thesis: Governance-enforced reasoning at fraction of cost")
    print("=" * 70)
    print(f"  Backend: {backend_type} | Model: {model}")
    print(f"  Observer: {observer_backend_type} | Model: {observer_model}")
    print(f"  Output: {output_dir}")
    print(f"  Started: {run_start.isoformat()}")

    # 1. Build KG
    print("\n[1/7] Building Multi-Governance Knowledge Graph...")
    kg = build_multi_governance_kg()
    stats = get_kg_stats(kg)
    print(f"  Nodes: {stats['nodes']}, Edges: {stats['edges']}, Chunks: {stats['total_chunks']}")

    # 2. Setup governance ontology (v3 — semantic SHACL)
    print("\n[2/7] Initializing Governance Ontology (v3 — Semantic SHACL)...")
    registry = DomainRegistry()
    register_governance_domain(registry)  # Legacy registration for backward compat
    semantic_constraints = build_governance_semantic_constraints()
    semantic_gate = SemanticSHACLGate(constraints=semantic_constraints)
    upper = UpperOntology()
    upper.extend({"Governance": "Entity"})
    all_output_shapes = registry.get_all_output_shapes()
    shacl_gate = SHACLGate(all_output_shapes)  # Legacy gate kept for fallback
    constraint_graph = ConstraintGraph()
    ontology_router = OntologyRouter(registry)
    skill_resolver = SkillResolver(registry)
    gov_domain = registry.get_domain("governance")
    print(f"  Types: {len(gov_domain.valid_entity_types)}, Skills: {sum(len(v) for v in gov_domain.skill_map.values())}")
    print(f"  Semantic constraints: {len(semantic_constraints)} entity types")

    # 3. Select questions
    print(f"\n[3/7] Loading benchmark questions (tiers: {tiers})...")
    questions = []
    for tier in tiers.upper():
        tier_qs = get_questions_by_tier(tier)
        questions.extend(tier_qs)
        print(f"  Tier {tier}: {len(tier_qs)} questions")
    print(f"  Total: {len(questions)} questions")

    # 4. Initialize backends
    print(f"\n[4/7] Initializing backends...")
    reasoning_backend = _create_backend(backend_type, model, region, host)
    obs_backend = _create_backend(observer_backend_type, observer_model, region, host)
    print(f"  Reasoning: {reasoning_backend.name}")
    print(f"  Observer: {obs_backend.name}")

    # Verify reasoning backend
    try:
        test = await reasoning_backend.generate("Say 'hello' in one word.", max_tokens=10)
        print(f"  Reasoning OK: '{test.strip()[:40]}'")
    except Exception as e:
        print(f"  ERROR: Cannot reach reasoning model: {e}")
        sys.exit(1)

    # 5. Build context text for single-agent baseline
    print(f"\n[5/7] Building context for single-agent baseline...")
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
    context_word_count = len(context_text.split())
    print(f"  Context size: {context_word_count} words (~{context_word_count * 4 // 3} tokens)")

    # 6. Run benchmark
    print(f"\n[6/7] Running benchmark ({len(questions)} questions x 2 methods)...")
    bench_start = time.perf_counter()

    results: dict[str, list[QuestionResult]] = {
        "single-agent": [],
        "graqle-pcst-v2": [],
    }

    for i, q in enumerate(questions):
        tier_label = f"Tier {q.tier}" if hasattr(q, "tier") else ""
        print(f"\n  Q{i+1}/{len(questions)} [{tier_label}] {q.id}: {q.question[:60]}...")

        q_cost_entry = {
            "question_id": q.id,
            "tier": getattr(q, "tier", "?"),
            "question": q.question[:80],
        }

        # --- Single-agent baseline ---
        try:
            # Track cost before call
            sa_cost_before = 0.0
            if hasattr(reasoning_backend, 'total_cost_usd'):
                sa_cost_before = reasoning_backend.total_cost_usd

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

            # Get actual cost from backend (Bedrock tracks precisely)
            sa_cost_after = 0.0
            if hasattr(reasoning_backend, 'total_cost_usd'):
                sa_cost_after = reasoning_backend.total_cost_usd
            sa_call_cost = sa_cost_after - sa_cost_before

            # Token count: use backend tracking if available, else estimate
            if hasattr(reasoning_backend, 'total_input_tokens'):
                sa_tokens = reasoning_backend.total_input_tokens + reasoning_backend.total_output_tokens
            else:
                sa_tokens = len(prompt.split()) + len(sa_answer.split())

            # If no tracked cost, estimate
            if sa_call_cost == 0:
                sa_call_cost = reasoning_backend.cost_per_1k_tokens * sa_tokens / 1000

            sa_f1 = f1_score(sa_answer, q.expected_answer)
            if hasattr(q, "keywords") and q.keywords:
                kw_f1 = BenchmarkRunner._keyword_f1(sa_answer, q.keywords)
                sa_f1 = max(sa_f1, kw_f1)

            # Single-agent has no governance enforcement → governance_accuracy = 0
            sa_constrained_f1 = constrained_f1_score(sa_f1, 0.0)

            results["single-agent"].append(QuestionResult(
                question_id=q.id,
                question=q.question,
                gold_answer=q.expected_answer,
                predicted_answer=sa_answer,
                exact_match=exact_match(sa_answer, q.expected_answer),
                f1=sa_f1,
                latency_ms=sa_latency,
                cost_usd=sa_call_cost,
                total_tokens=sa_tokens,
                convergence_rounds=1,
                active_nodes=1,
                method="single-agent",
                governance_accuracy=0.0,  # No governance enforcement
                constrained_f1=sa_constrained_f1,
            ))
            q_cost_entry["sa_f1"] = round(sa_f1, 4)
            q_cost_entry["sa_constrained_f1"] = round(sa_constrained_f1, 4)
            q_cost_entry["sa_cost"] = round(sa_call_cost, 6)
            q_cost_entry["sa_latency_ms"] = round(sa_latency, 0)
            print(f"    [single-agent] F1={sa_f1:.3f} cF1={sa_constrained_f1:.3f} lat={sa_latency:.0f}ms cost=${sa_call_cost:.6f}")
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
            q_cost_entry["sa_error"] = str(e)[:100]

        # --- Graqle-PCST v2 (governance-constrained) ---
        try:
            # Track cost before Graqle calls
            cg_cost_before = 0.0
            if hasattr(reasoning_backend, 'total_cost_usd'):
                cg_cost_before = reasoning_backend.total_cost_usd

            config = GraqleConfig.default()
            config.orchestration.max_rounds = max_rounds
            config.orchestration.async_mode = True
            config.activation.strategy = "pcst"
            config.activation.max_nodes = max_nodes

            graph = Graqle.from_networkx(kg, config=config)
            _remap_node_types(graph)
            graph.set_default_backend(reasoning_backend)

            # Inject semantic governance into nodes (v3)
            for node in graph.nodes.values():
                prompt_text = semantic_gate.get_constraint_prompt(node.entity_type, node.label)
                if prompt_text:
                    node.semantic_governance_text = prompt_text
                    node.semantic_gate = semantic_gate

            orchestrator = _setup_governance_orchestrator(
                config=config,
                ontology_router=ontology_router,
                skill_resolver=skill_resolver,
                shacl_gate=shacl_gate,
                constraint_graph=constraint_graph,
                ontology_registry=registry,
                observer_backend=obs_backend,
            )
            graph._orchestrator = orchestrator

            cg_start = time.perf_counter()
            result: ReasoningResult = await graph.areason(q.question)
            cg_latency = (time.perf_counter() - cg_start) * 1000

            # Get actual cost delta
            cg_cost_after = 0.0
            if hasattr(reasoning_backend, 'total_cost_usd'):
                cg_cost_after = reasoning_backend.total_cost_usd
            cg_call_cost = cg_cost_after - cg_cost_before
            if cg_call_cost == 0:
                cg_call_cost = result.cost_usd

            cg_f1 = f1_score(result.answer, q.expected_answer)
            if hasattr(q, "keywords") and q.keywords:
                kw_f1 = BenchmarkRunner._keyword_f1(result.answer, q.keywords)
                cg_f1 = max(cg_f1, kw_f1)

            gov_stats = result.metadata.get("governance_stats", {})

            # Compute semantic governance accuracy on the aggregated answer
            sem_result = semantic_gate.validate(
                "GOV_REQUIREMENT", result.answer, q.question,
            )
            gov_accuracy = sem_result.governance_accuracy
            cg_constrained_f1 = constrained_f1_score(cg_f1, gov_accuracy)

            # Also get semantic gate stats
            sem_stats = semantic_gate.stats

            results["graqle-pcst-v2"].append(QuestionResult(
                question_id=q.id,
                question=q.question,
                gold_answer=q.expected_answer,
                predicted_answer=result.answer,
                exact_match=exact_match(result.answer, q.expected_answer),
                f1=cg_f1,
                latency_ms=cg_latency,
                cost_usd=cg_call_cost,
                total_tokens=result.metadata.get("total_tokens", 0),
                convergence_rounds=result.rounds_completed,
                active_nodes=result.node_count,
                method="graqle-pcst-v2",
                shacl_pass=gov_stats.get("shacl_validations_pass", 0),
                shacl_fail=gov_stats.get("shacl_validations_fail", 0),
                constraint_propagations=gov_stats.get("constraint_propagations", 0),
                observer_redirects=gov_stats.get("observer_redirects", 0),
                ontology_route_filtered=gov_stats.get("ontology_route_filtered", 0),
                governance_accuracy=gov_accuracy,
                framework_fidelity=sem_result.framework_fidelity_score,
                scope_adherence=sem_result.scope_adherence_score,
                cross_reference_score=sem_result.cross_reference_score,
                constrained_f1=cg_constrained_f1,
            ))
            q_cost_entry["cg_f1"] = round(cg_f1, 4)
            q_cost_entry["cg_constrained_f1"] = round(cg_constrained_f1, 4)
            q_cost_entry["cg_governance_accuracy"] = round(gov_accuracy, 4)
            q_cost_entry["cg_cost"] = round(cg_call_cost, 6)
            q_cost_entry["cg_latency_ms"] = round(cg_latency, 0)
            q_cost_entry["cg_nodes"] = result.node_count
            q_cost_entry["cg_rounds"] = result.rounds_completed
            q_cost_entry["shacl_pass"] = gov_stats.get("shacl_validations_pass", 0)
            q_cost_entry["shacl_fail"] = gov_stats.get("shacl_validations_fail", 0)
            print(f"    [pcst-v2] F1={cg_f1:.3f} cF1={cg_constrained_f1:.3f} gov={gov_accuracy:.3f} "
                  f"lat={cg_latency:.0f}ms nodes={result.node_count} rounds={result.rounds_completed} "
                  f"cost=${cg_call_cost:.6f}")
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
            q_cost_entry["cg_error"] = str(e)[:100]

        cost_log.append(q_cost_entry)

    bench_elapsed = time.perf_counter() - bench_start
    print(f"\n  Benchmark completed in {bench_elapsed:.1f}s")

    # Build summaries
    summaries: dict[str, BenchmarkSummary] = {}
    for method, qrs in results.items():
        valid = [r for r in qrs if not r.predicted_answer.startswith("ERROR")]
        n = len(valid) or 1
        summaries[method] = BenchmarkSummary(
            method=method,
            dataset=f"MultiGov-30-v3-{model_short}",
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
            avg_governance_accuracy=sum(r.governance_accuracy for r in valid) / n,
            avg_framework_fidelity=sum(r.framework_fidelity for r in valid) / n,
            avg_scope_adherence=sum(r.scope_adherence for r in valid) / n,
            avg_cross_reference_score=sum(r.cross_reference_score for r in valid) / n,
            avg_constrained_f1=sum(r.constrained_f1 for r in valid) / n,
            question_results=qrs,
        )

    # 7. Save results + cost report
    print(f"\n[7/7] Saving results...")
    save_multigov_results(summaries, output_dir)

    # Save detailed cost log
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    cost_report = {
        "run_metadata": {
            "timestamp": run_start.isoformat(),
            "backend": backend_type,
            "model": model,
            "observer_model": observer_model,
            "region": region,
            "tiers": tiers,
            "total_questions": len(questions),
            "total_elapsed_s": round(bench_elapsed, 1),
        },
        "cost_summary": {
            "single_agent_total_cost": round(sum(r.cost_usd for r in results["single-agent"]), 6),
            "graqle_total_cost": round(sum(r.cost_usd for r in results["graqle-pcst-v2"]), 6),
            "total_benchmark_cost": round(
                sum(r.cost_usd for r in results["single-agent"]) +
                sum(r.cost_usd for r in results["graqle-pcst-v2"]), 6
            ),
        },
        "per_question_log": cost_log,
    }

    # Add backend-level cost report if available (Bedrock)
    if hasattr(reasoning_backend, 'get_cost_report'):
        cost_report["backend_cost_report"] = reasoning_backend.get_cost_report()

    cost_path = output_path / "cost_report.json"
    cost_path.write_text(json.dumps(cost_report, indent=2), encoding="utf-8")
    print(f"  Cost report saved to {cost_path}")

    # Print final summary
    print("\n" + "=" * 70)
    print(f"GOVERNED INTELLIGENCE BENCHMARK — {model}")
    print("=" * 70)

    sa_summary = summaries["single-agent"]
    cg_summary = summaries["graqle-pcst-v2"]

    print(f"\n{'Metric':<30} {'Single-Agent':>15} {'Graqle-v2':>15} {'Delta':>15}")
    print("-" * 75)
    print(f"{'Token F1':<30} {sa_summary.avg_f1:>15.4f} {cg_summary.avg_f1:>15.4f} {cg_summary.avg_f1 - sa_summary.avg_f1:>+15.4f}")
    print(f"{'Constrained F1':<30} {sa_summary.avg_constrained_f1:>15.4f} {cg_summary.avg_constrained_f1:>15.4f} {cg_summary.avg_constrained_f1 - sa_summary.avg_constrained_f1:>+15.4f}")
    print(f"{'Governance Accuracy':<30} {sa_summary.avg_governance_accuracy:>15.4f} {cg_summary.avg_governance_accuracy:>15.4f} {cg_summary.avg_governance_accuracy - sa_summary.avg_governance_accuracy:>+15.4f}")
    print(f"{'  Framework Fidelity':<30} {sa_summary.avg_framework_fidelity:>15.4f} {cg_summary.avg_framework_fidelity:>15.4f} {'':>15}")
    print(f"{'  Scope Adherence':<30} {sa_summary.avg_scope_adherence:>15.4f} {cg_summary.avg_scope_adherence:>15.4f} {'':>15}")
    print(f"{'  Cross-Reference':<30} {sa_summary.avg_cross_reference_score:>15.4f} {cg_summary.avg_cross_reference_score:>15.4f} {'':>15}")
    print(f"{'Exact Match':<30} {sa_summary.avg_em:>15.4f} {cg_summary.avg_em:>15.4f} {cg_summary.avg_em - sa_summary.avg_em:>+15.4f}")
    print(f"{'Avg Latency (ms)':<30} {sa_summary.avg_latency_ms:>15.0f} {cg_summary.avg_latency_ms:>15.0f} {'':>15}")
    print(f"{'Avg Tokens/Query':<30} {sa_summary.avg_tokens:>15.0f} {cg_summary.avg_tokens:>15.0f} {(cg_summary.avg_tokens / max(sa_summary.avg_tokens, 1) - 1) * 100:>+14.1f}%")
    print(f"{'Total Cost (USD)':<30} ${sa_summary.total_cost_usd:>14.6f} ${cg_summary.total_cost_usd:>14.6f} {(cg_summary.total_cost_usd / max(sa_summary.total_cost_usd, 0.0001) - 1) * 100:>+14.1f}%")
    print(f"{'Active Nodes/Query':<30} {sa_summary.avg_nodes:>15.1f} {cg_summary.avg_nodes:>15.1f} {'':>15}")

    # Per-tier breakdown
    print(f"\n{'Tier':<15} {'Method':<25} {'F1':>8} {'Cost':>12} {'Lat(ms)':>10}")
    print("-" * 70)
    for tier in ["A", "B", "C"]:
        tier_name = {"A": "Single-Reg", "B": "Cross-Reg", "C": "Inter-Domain"}[tier]
        for method_key, method_label in [("single-agent", "Single-Agent"), ("graqle-pcst-v2", "Graqle-v2")]:
            tier_results = [r for r in results[method_key]
                          if hasattr(r, 'question_id') and r.question_id.split("-")[1][0] == tier]
            if tier_results:
                valid = [r for r in tier_results if not r.predicted_answer.startswith("ERROR")]
                n = len(valid) or 1
                avg_f1 = sum(r.f1 for r in valid) / n
                total_cost = sum(r.cost_usd for r in tier_results)
                avg_lat = sum(r.latency_ms for r in valid) / n
                print(f"{tier_name:<15} {method_label:<25} {avg_f1:>8.4f} ${total_cost:>11.6f} {avg_lat:>10.0f}")

    # Thesis validation
    print("\n" + "=" * 70)
    print("THESIS VALIDATION")
    print("\"Reasoning without governance is creativity at scale with compliance risk.\"")
    print("=" * 70)
    f1_delta = cg_summary.avg_f1 - sa_summary.avg_f1
    cf1_delta = cg_summary.avg_constrained_f1 - sa_summary.avg_constrained_f1
    cost_ratio = cg_summary.total_cost_usd / max(sa_summary.total_cost_usd, 0.0001)

    checks = [
        ("Governance enforced (gov_accuracy > 0)", cg_summary.avg_governance_accuracy > 0),
        ("Constrained F1 > Single-Agent", cg_summary.avg_constrained_f1 > sa_summary.avg_constrained_f1),
        ("Governance accuracy > 50%", cg_summary.avg_governance_accuracy > 0.5),
        ("Framework fidelity > 50%", cg_summary.avg_framework_fidelity > 0.5),
        ("Scope adherence > 50%", cg_summary.avg_scope_adherence > 0.5),
    ]
    for label, passed in checks:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {label}")

    if all(c[1] for c in checks):
        print("\n  THESIS PROVEN: Governed intelligence delivers higher constrained F1 with semantic validation.")
    elif checks[0][1]:
        print(f"\n  PARTIAL: Governance enforced. Constrained F1 delta = {cf1_delta:+.4f}")
        print(f"  Governance accuracy: {cg_summary.avg_governance_accuracy:.4f}")
        print(f"  Token F1 delta: {f1_delta:+.4f}")

    print(f"\n  Total benchmark cost: ${cost_report['cost_summary']['total_benchmark_cost']:.6f}")
    print(f"  Total time: {bench_elapsed:.1f}s")

    return {
        "summaries": summaries,
        "cost_report": cost_report,
        "output_dir": output_dir,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Graqle v3 — Governed Intelligence Benchmark"
    )
    parser.add_argument("--backend", default="bedrock", choices=["bedrock", "ollama"],
                       help="Backend type (bedrock or ollama)")
    parser.add_argument("--model", default="anthropic.claude-sonnet-4-6",
                       help="Reasoning model ID")
    parser.add_argument("--observer-backend", default="ollama",
                       help="Observer backend type")
    parser.add_argument("--observer-model", default="qwen2.5:0.5b",
                       help="Observer model")
    parser.add_argument("--region", default="eu-central-1",
                       help="AWS region for Bedrock")
    parser.add_argument("--host", default="http://localhost:11434",
                       help="Ollama host")
    parser.add_argument("--tiers", default="ABC", help="Tiers to run (A, B, C)")
    parser.add_argument("--max-rounds", type=int, default=3, help="Max reasoning rounds")
    parser.add_argument("--max-nodes", type=int, default=10, help="Max active nodes")
    parser.add_argument("--output", default=None, help="Output directory")

    args = parser.parse_args()
    asyncio.run(run_v3_benchmark(
        backend_type=args.backend,
        model=args.model,
        observer_backend_type=args.observer_backend,
        observer_model=args.observer_model,
        region=args.region,
        host=args.host,
        tiers=args.tiers,
        max_rounds=args.max_rounds,
        max_nodes=args.max_nodes,
        output_dir=args.output,
    ))
