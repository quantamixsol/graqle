"""Graqle Benchmark Runner — Full pipeline comparison.

Runs the complete Graqle pipeline (PCST activation → multi-agent
message passing → convergence → aggregation) against single-agent baselines
on standard reasoning benchmarks.

Baselines:
1. Single-Agent (all context concatenated, single model call)
2. Graqle-Full (all nodes activated, no PCST pruning)
3. Graqle-PCST (PCST subgraph activation, message passing)

Metrics: EM (exact match), F1, latency, cost, tokens, rounds
"""

# ── graqle:intelligence ──
# module: graqle.benchmarks.benchmark_runner
# risk: HIGH (impact radius: 5 modules)
# consumers: run_multigov, run_multigov_v2, run_multigov_v3, test_constrained_f1, test_metrics
# dependencies: __future__, asyncio, json, logging, re +11 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
import re
import string
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from graqle.backends.api import OllamaBackend
from graqle.config.settings import GraqleConfig
from graqle.core.graph import Graqle
from graqle.core.types import ReasoningResult

logger = logging.getLogger("graqle.benchmark")


# ── Scoring Functions (standard HotpotQA metrics) ──

def _normalize_answer(s: str) -> str:
    """Normalize answer for EM/F1: lowercase, strip articles/punctuation/whitespace."""
    s = s.lower()
    # Remove articles
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    # Remove punctuation
    s = s.translate(str.maketrans("", "", string.punctuation))
    # Collapse whitespace
    s = " ".join(s.split())
    return s.strip()


def exact_match(prediction: str, gold: str) -> float:
    """Exact match score (0 or 1)."""
    return float(_normalize_answer(prediction) == _normalize_answer(gold))


def f1_score(prediction: str, gold: str) -> float:
    """Token-level F1 score."""
    pred_tokens = _normalize_answer(prediction).split()
    gold_tokens = _normalize_answer(gold).split()

    if not gold_tokens:
        return float(not pred_tokens)
    if not pred_tokens:
        return 0.0

    common = Counter(pred_tokens) & Counter(gold_tokens)
    num_same = sum(common.values())

    if num_same == 0:
        return 0.0

    precision = num_same / len(pred_tokens)
    recall = num_same / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)


def constrained_f1_score(
    token_f1: float,
    governance_accuracy: float,
    weight_token: float = 0.5,
    weight_governance: float = 0.5,
) -> float:
    """Constrained F1 — combines token F1 with governance accuracy.

    This metric answers: "Did the system get the right answer AND respect
    governance constraints?" A high token F1 with low governance accuracy
    means the answer has correct keywords but wrong regulatory attribution.

    Args:
        token_f1: Standard token-level F1 (0.0-1.0)
        governance_accuracy: Governance accuracy from SemanticSHACLGate (0.0-1.0)
            Composed of: framework_fidelity (40%) + scope_adherence (40%) + cross_ref (20%)
        weight_token: Weight for token F1 (default 0.5)
        weight_governance: Weight for governance accuracy (default 0.5)

    Returns:
        Constrained F1 score (0.0-1.0)
    """
    return weight_token * token_f1 + weight_governance * governance_accuracy


# ── Result Containers ──

@dataclass
class QuestionResult:
    """Result for a single question under one method."""

    question_id: str
    question: str
    gold_answer: str
    predicted_answer: str
    exact_match: float
    f1: float
    latency_ms: float
    cost_usd: float
    total_tokens: int
    convergence_rounds: int
    active_nodes: int
    method: str  # "single-agent", "graqle-full", "graqle-pcst"

    # Governance metrics (v2)
    shacl_pass: int = 0
    shacl_fail: int = 0
    constraint_propagations: int = 0
    observer_redirects: int = 0
    ontology_route_filtered: int = 0

    # Semantic governance metrics (v3)
    governance_accuracy: float = 0.0
    framework_fidelity: float = 0.0
    scope_adherence: float = 0.0
    cross_reference_score: float = 0.0
    constrained_f1: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkSummary:
    """Aggregated benchmark results for one method on one dataset."""

    method: str
    dataset: str
    n_questions: int
    avg_em: float
    avg_f1: float
    avg_latency_ms: float
    avg_cost_usd: float
    avg_tokens: float
    avg_rounds: float
    avg_nodes: float
    total_cost_usd: float
    total_latency_s: float
    # Governance metrics (v2 aggregated)
    total_shacl_pass: int = 0
    total_shacl_fail: int = 0
    total_constraint_propagations: int = 0
    total_observer_redirects: int = 0
    total_ontology_route_filtered: int = 0
    # Semantic governance metrics (v3 aggregated)
    avg_governance_accuracy: float = 0.0
    avg_framework_fidelity: float = 0.0
    avg_scope_adherence: float = 0.0
    avg_cross_reference_score: float = 0.0
    avg_constrained_f1: float = 0.0
    question_results: list[QuestionResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("question_results")  # too large for summary
        return d


# ── Single-Agent Baseline ──

async def _run_single_agent(
    backend: Any,
    question: str,
    context: str,
    max_tokens: int = 256,
) -> tuple[str, float, int]:
    """Run single-agent baseline: all context concatenated."""
    prompt = (
        f"Answer the following question using ONLY the provided context. "
        f"Give a short, direct answer.\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {question}\n\n"
        f"Answer:"
    )
    start = time.perf_counter()
    answer = await backend.generate(prompt, max_tokens=max_tokens)
    latency = (time.perf_counter() - start) * 1000
    # Rough token estimate
    tokens = len(prompt.split()) + len(answer.split())
    return answer.strip(), latency, tokens


# ── Benchmark Runner ──

class BenchmarkRunner:
    """Run Graqle benchmarks against baselines.

    Uses the full Graqle pipeline:
    1. Build KG from question context
    2. PCST subgraph activation (or full activation)
    3. Multi-agent message passing with convergence
    4. Hierarchical aggregation → answer
    """

    def __init__(
        self,
        model: str = "qwen2.5:0.5b",
        host: str = "http://localhost:11434",
        max_rounds: int = 3,
        max_nodes: int = 8,
    ) -> None:
        self.model = model
        self.host = host
        self.max_rounds = max_rounds
        self.max_nodes = max_nodes
        self.backend = OllamaBackend(model=model, host=host)

    def _build_config(self, strategy: str) -> GraqleConfig:
        """Build Graqle config for a specific strategy."""
        config = GraqleConfig.default()
        config.orchestration.max_rounds = self.max_rounds
        config.orchestration.async_mode = True  # sequential node calls (parallel=False) for local Ollama
        config.activation.strategy = strategy
        config.activation.max_nodes = self.max_nodes
        return config

    async def run_hotpotqa(
        self,
        questions: list,
        *,
        methods: list[str] | None = None,
    ) -> dict[str, BenchmarkSummary]:
        """Run HotpotQA benchmark across all methods.

        Args:
            questions: List of HotpotQAQuestion objects
            methods: Which methods to run (default: all 3)

        Returns:
            Dict of method_name -> BenchmarkSummary
        """
        methods = methods or ["single-agent", "graqle-full", "graqle-pcst"]
        results: dict[str, list[QuestionResult]] = {m: [] for m in methods}

        for i, q in enumerate(questions):
            logger.info(f"Question {i + 1}/{len(questions)}: {q.question[:60]}...")

            # Build KG for this question
            kg = q.to_kg()

            # Build concatenated context for single-agent
            context_text = "\n\n".join(
                f"### {title}\n{' '.join(sents)}"
                for title, sents in q.context
            )

            for method in methods:
                try:
                    qr = await self._run_one(
                        method=method,
                        question_id=q.id,
                        question=q.question,
                        gold_answer=q.answer,
                        kg=kg,
                        context_text=context_text,
                    )
                    results[method].append(qr)
                    logger.info(
                        f"  [{method}] EM={qr.exact_match:.0f} F1={qr.f1:.2f} "
                        f"latency={qr.latency_ms:.0f}ms tokens={qr.total_tokens}"
                    )
                except Exception as e:
                    logger.error(f"  [{method}] ERROR: {e}")
                    results[method].append(QuestionResult(
                        question_id=q.id,
                        question=q.question,
                        gold_answer=q.answer,
                        predicted_answer=f"ERROR: {e}",
                        exact_match=0.0,
                        f1=0.0,
                        latency_ms=0.0,
                        cost_usd=0.0,
                        total_tokens=0,
                        convergence_rounds=0,
                        active_nodes=0,
                        method=method,
                    ))

        # Build summaries
        summaries: dict[str, BenchmarkSummary] = {}
        for method, qrs in results.items():
            valid = [r for r in qrs if not r.predicted_answer.startswith("ERROR")]
            n = len(valid) or 1
            summaries[method] = BenchmarkSummary(
                method=method,
                dataset="HotpotQA",
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
                question_results=qrs,
            )

        return summaries

    async def run_eu_regqa(
        self,
        questions: list,
        kg: nx.Graph,
        *,
        methods: list[str] | None = None,
    ) -> dict[str, BenchmarkSummary]:
        """Run EU-RegQA benchmark on the EU AI Act knowledge graph.

        Uses the same KG for all questions (shared regulatory graph).
        """
        methods = methods or ["single-agent", "graqle-full", "graqle-pcst"]
        results: dict[str, list[QuestionResult]] = {m: [] for m in methods}

        # Build context text from KG nodes for single-agent
        context_text = "\n\n".join(
            f"### {data.get('label', nid)}\n{data.get('description', '')}"
            for nid, data in kg.nodes(data=True)
        )

        for i, q in enumerate(questions):
            logger.info(f"RegQA {i + 1}/{len(questions)}: {q.question[:60]}...")

            for method in methods:
                try:
                    qr = await self._run_one(
                        method=method,
                        question_id=q.id,
                        question=q.question,
                        gold_answer=q.expected_answer,
                        kg=kg,
                        context_text=context_text,
                    )
                    results[method].append(qr)
                    logger.info(
                        f"  [{method}] F1={qr.f1:.2f} "
                        f"latency={qr.latency_ms:.0f}ms"
                    )
                except Exception as e:
                    logger.error(f"  [{method}] ERROR: {e}")
                    results[method].append(QuestionResult(
                        question_id=q.id,
                        question=q.question,
                        gold_answer=q.expected_answer,
                        predicted_answer=f"ERROR: {e}",
                        exact_match=0.0,
                        f1=0.0,
                        latency_ms=0.0,
                        cost_usd=0.0,
                        total_tokens=0,
                        convergence_rounds=0,
                        active_nodes=0,
                        method=method,
                    ))

        summaries: dict[str, BenchmarkSummary] = {}
        for method, qrs in results.items():
            valid = [r for r in qrs if not r.predicted_answer.startswith("ERROR")]
            n = len(valid) or 1
            summaries[method] = BenchmarkSummary(
                method=method,
                dataset="EU-RegQA-20",
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
                question_results=qrs,
            )

        return summaries

    async def run_multi_governance(
        self,
        questions: list,
        kg: nx.Graph,
        *,
        methods: list[str] | None = None,
    ) -> dict[str, BenchmarkSummary]:
        """Run Multi-Governance 3-Tier benchmark.

        Uses a shared multi-governance KG (EU AI Act + GDPR + DORA + NIS2)
        with thick nodes and evidence chunks. Reports per-tier results
        to demonstrate Graqle's increasing advantage on cross-regulation
        and complex inter-domain queries.
        """
        methods = methods or ["single-agent", "graqle-pcst"]
        results: dict[str, list[QuestionResult]] = {m: [] for m in methods}

        # Build context text from KG nodes for single-agent baseline
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

        for i, q in enumerate(questions):
            tier_label = f"Tier {q.tier}" if hasattr(q, "tier") else ""
            logger.info(
                f"MultiGov {i + 1}/{len(questions)} [{tier_label}] {q.id}: "
                f"{q.question[:60]}..."
            )

            for method in methods:
                try:
                    qr = await self._run_one(
                        method=method,
                        question_id=q.id,
                        question=q.question,
                        gold_answer=q.expected_answer,
                        kg=kg,
                        context_text=context_text,
                    )
                    # Use keyword-based F1 for governance questions
                    if hasattr(q, "keywords") and q.keywords:
                        kw_f1 = self._keyword_f1(qr.predicted_answer, q.keywords)
                        qr.f1 = max(qr.f1, kw_f1)  # best of token F1 and keyword F1
                    results[method].append(qr)
                    logger.info(
                        f"  [{method}] F1={qr.f1:.2f} "
                        f"latency={qr.latency_ms:.0f}ms nodes={qr.active_nodes}"
                    )
                except Exception as e:
                    logger.error(f"  [{method}] ERROR: {e}")
                    results[method].append(QuestionResult(
                        question_id=q.id,
                        question=q.question,
                        gold_answer=q.expected_answer,
                        predicted_answer=f"ERROR: {e}",
                        exact_match=0.0,
                        f1=0.0,
                        latency_ms=0.0,
                        cost_usd=0.0,
                        total_tokens=0,
                        convergence_rounds=0,
                        active_nodes=0,
                        method=method,
                    ))

        # Build per-tier summaries
        summaries: dict[str, BenchmarkSummary] = {}
        for method, qrs in results.items():
            valid = [r for r in qrs if not r.predicted_answer.startswith("ERROR")]
            n = len(valid) or 1
            summaries[method] = BenchmarkSummary(
                method=method,
                dataset="MultiGov-30",
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

        return summaries

    @staticmethod
    def _keyword_f1(prediction: str, keywords: list[str]) -> float:
        """Compute keyword recall — fraction of expected keywords found in prediction."""
        if not keywords:
            return 0.0
        pred_lower = prediction.lower()
        found = sum(1 for kw in keywords if kw.lower() in pred_lower)
        return found / len(keywords)

    @staticmethod
    def _keyword_recall(prediction: str, keywords: list[str]) -> float:
        """Compute keyword recall (explicit named method for clarity)."""
        if not keywords:
            return 0.0
        pred_lower = prediction.lower()
        found = sum(1 for kw in keywords if kw.lower() in pred_lower)
        return found / len(keywords)

    async def _run_one(
        self,
        *,
        method: str,
        question_id: str,
        question: str,
        gold_answer: str,
        kg: nx.Graph,
        context_text: str,
    ) -> QuestionResult:
        """Run a single question under one method."""
        if method == "single-agent":
            answer, latency, tokens = await _run_single_agent(
                self.backend, question, context_text
            )
            return QuestionResult(
                question_id=question_id,
                question=question,
                gold_answer=gold_answer,
                predicted_answer=answer,
                exact_match=exact_match(answer, gold_answer),
                f1=f1_score(answer, gold_answer),
                latency_ms=latency,
                cost_usd=self.backend.cost_per_1k_tokens * tokens / 1000,
                total_tokens=tokens,
                convergence_rounds=1,
                active_nodes=1,
                method=method,
            )

        # Graqle methods: build graph and run full pipeline
        strategy = "full" if method == "graqle-full" else "pcst"
        config = self._build_config(strategy)
        graph = Graqle.from_networkx(kg, config=config)
        graph.set_default_backend(self.backend)

        start = time.perf_counter()
        result: ReasoningResult = await graph.areason(question)
        latency = (time.perf_counter() - start) * 1000

        # Extract governance stats from metadata
        gov_stats = result.metadata.get("governance_stats", {})

        return QuestionResult(
            question_id=question_id,
            question=question,
            gold_answer=gold_answer,
            predicted_answer=result.answer,
            exact_match=exact_match(result.answer, gold_answer),
            f1=f1_score(result.answer, gold_answer),
            latency_ms=latency,
            cost_usd=result.cost_usd,
            total_tokens=result.metadata.get("total_tokens", 0),
            convergence_rounds=result.rounds_completed,
            active_nodes=result.node_count,
            method=method,
            shacl_pass=gov_stats.get("shacl_validations_pass", 0),
            shacl_fail=gov_stats.get("shacl_validations_fail", 0),
            constraint_propagations=gov_stats.get("constraint_propagations", 0),
            observer_redirects=gov_stats.get("observer_redirects", 0),
            ontology_route_filtered=gov_stats.get("ontology_route_filtered", 0),
        )


def save_results(
    summaries: dict[str, BenchmarkSummary],
    output_dir: str | Path,
    dataset_name: str,
) -> None:
    """Save benchmark results to JSON and LaTeX-ready format."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save full JSON
    json_data = {
        method: {
            "summary": s.to_dict(),
            "questions": [qr.to_dict() for qr in s.question_results],
        }
        for method, s in summaries.items()
    }
    json_path = output_dir / f"{dataset_name}_results.json"
    json_path.write_text(json.dumps(json_data, indent=2), encoding="utf-8")
    logger.info(f"Saved JSON results to {json_path}")

    # Save LaTeX table
    latex = _generate_latex_table(summaries, dataset_name)
    latex_path = output_dir / f"{dataset_name}_table.tex"
    latex_path.write_text(latex, encoding="utf-8")
    logger.info(f"Saved LaTeX table to {latex_path}")


def save_multigov_results(
    summaries: dict[str, BenchmarkSummary],
    output_dir: str | Path,
) -> None:
    """Save multi-governance results with per-tier breakdown."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save full JSON
    json_data = {
        method: {
            "summary": s.to_dict(),
            "questions": [qr.to_dict() for qr in s.question_results],
        }
        for method, s in summaries.items()
    }
    json_path = output_dir / "multigov_results.json"
    json_path.write_text(json.dumps(json_data, indent=2), encoding="utf-8")
    logger.info(f"Saved JSON results to {json_path}")

    # Per-tier breakdown
    tier_data: dict[str, dict[str, list]] = {}
    for method, s in summaries.items():
        for qr in s.question_results:
            # Extract tier from question_id (e.g., "MG-A01" → "A")
            tier = qr.question_id.split("-")[1][0] if "-" in qr.question_id else "?"
            tier_data.setdefault(tier, {}).setdefault(method, []).append(qr)

    # Save per-tier LaTeX table
    latex = _generate_multigov_latex(tier_data)
    latex_path = output_dir / "multigov_table.tex"
    latex_path.write_text(latex, encoding="utf-8")
    logger.info(f"Saved LaTeX table to {latex_path}")

    # Print summary
    print("\n" + "=" * 80)
    print("MULTI-GOVERNANCE BENCHMARK RESULTS")
    print("=" * 80)
    for tier in ["A", "B", "C"]:
        if tier not in tier_data:
            continue
        print(f"\n--- Tier {tier} ---")
        for method, qrs in tier_data[tier].items():
            valid = [r for r in qrs if not r.predicted_answer.startswith("ERROR")]
            n = len(valid) or 1
            avg_f1 = sum(r.f1 for r in valid) / n
            avg_lat = sum(r.latency_ms for r in valid) / n
            avg_nodes = sum(r.active_nodes for r in valid) / n
            print(f"  {method:25s}  F1={avg_f1:.3f}  Lat={avg_lat:.0f}ms  Nodes={avg_nodes:.1f}")

    # Print governance stats
    print("\n--- Governance Metrics ---")
    for method, s in summaries.items():
        print(f"  {method:25s}  SHACL pass={s.total_shacl_pass} fail={s.total_shacl_fail}  "
              f"Constraints={s.total_constraint_propagations}  "
              f"Observer={s.total_observer_redirects}  "
              f"Filtered={s.total_ontology_route_filtered}")


def _generate_multigov_latex(
    tier_data: dict[str, dict[str, list]],
) -> str:
    """Generate per-tier LaTeX table for multi-governance benchmark."""
    rows = []
    for tier in ["A", "B", "C"]:
        if tier not in tier_data:
            continue
        tier_name = {"A": "Single-Regulation", "B": "Cross-Regulation", "C": "Complex Inter-Domain"}[tier]
        for method, qrs in tier_data[tier].items():
            valid = [r for r in qrs if not r.predicted_answer.startswith("ERROR")]
            n = len(valid) or 1
            display = {
                "single-agent": "Single-Agent",
                "graqle-full": "Graqle-Full",
                "graqle-pcst": "Graqle-PCST",
            }.get(method, method)
            avg_f1 = sum(r.f1 for r in valid) / n
            avg_lat = sum(r.latency_ms for r in valid) / n
            avg_nodes = sum(r.active_nodes for r in valid) / n
            avg_rounds = sum(r.convergence_rounds for r in valid) / n
            rows.append(
                f"  {tier_name} & {display} & {len(valid)} & {avg_f1:.3f} & "
                f"{avg_lat:.0f} & {avg_rounds:.1f} & {avg_nodes:.1f} \\\\"
            )
        rows.append("  \\midrule")

    table = f"""% Auto-generated Multi-Governance Benchmark Results
\\begin{{table}}[ht]
\\centering
\\caption{{Multi-Governance 3-Tier Benchmark Results (Qwen2.5, Local GPU)}}
\\label{{tab:multigov_results}}
\\begin{{tabular}}{{llccccc}}
\\toprule
\\textbf{{Tier}} & \\textbf{{Method}} & \\textbf{{N}} & \\textbf{{F1}} & \\textbf{{Lat. (ms)}} & \\textbf{{Rounds}} & \\textbf{{Nodes}} \\\\
\\midrule
{chr(10).join(rows)}
\\bottomrule
\\end{{tabular}}
\\end{{table}}"""

    return table


def _generate_latex_table(
    summaries: dict[str, BenchmarkSummary],
    dataset_name: str,
) -> str:
    """Generate a LaTeX-ready results table."""
    header = dataset_name.replace("_", " ").title()

    rows = []
    for method, s in summaries.items():
        display_name = {
            "single-agent": "Single-Agent (concat.)",
            "graqle-full": "Graqle-Full",
            "graqle-pcst": "Graqle-PCST",
        }.get(method, method)

        rows.append(
            f"  {display_name} & {s.avg_em:.3f} & {s.avg_f1:.3f} & "
            f"{s.avg_latency_ms:.0f} & {s.avg_tokens:.0f} & "
            f"{s.avg_rounds:.1f} & {s.avg_nodes:.1f} & "
            f"\\${s.total_cost_usd:.4f} \\\\"
        )

    table = f"""% Auto-generated benchmark results — {header}
\\begin{{table}}[ht]
\\centering
\\caption{{{header} Benchmark Results (Qwen2.5-0.5B, RTX 5060)}}
\\label{{tab:{dataset_name.lower()}_results}}
\\begin{{tabular}}{{lccccccc}}
\\toprule
\\textbf{{Method}} & \\textbf{{EM}} & \\textbf{{F1}} & \\textbf{{Lat. (ms)}} & \\textbf{{Tokens}} & \\textbf{{Rounds}} & \\textbf{{Nodes}} & \\textbf{{Cost}} \\\\
\\midrule
{chr(10).join(rows)}
\\bottomrule
\\end{{tabular}}
\\end{{table}}"""

    return table
