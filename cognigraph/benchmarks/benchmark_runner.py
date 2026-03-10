"""CogniGraph Benchmark Runner — Full pipeline comparison.

Runs the complete CogniGraph pipeline (PCST activation → multi-agent
message passing → convergence → aggregation) against single-agent baselines
on standard reasoning benchmarks.

Baselines:
1. Single-Agent (all context concatenated, single model call)
2. CogniGraph-Full (all nodes activated, no PCST pruning)
3. CogniGraph-PCST (PCST subgraph activation, message passing)

Metrics: EM (exact match), F1, latency, cost, tokens, rounds
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import string
import time
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import networkx as nx

from cognigraph.backends.api import OllamaBackend
from cognigraph.config.settings import CogniGraphConfig
from cognigraph.core.graph import CogniGraph
from cognigraph.core.types import ReasoningResult

logger = logging.getLogger("cognigraph.benchmark")


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
    method: str  # "single-agent", "cognigraph-full", "cognigraph-pcst"

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
    """Run CogniGraph benchmarks against baselines.

    Uses the full CogniGraph pipeline:
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

    def _build_config(self, strategy: str) -> CogniGraphConfig:
        """Build CogniGraph config for a specific strategy."""
        config = CogniGraphConfig.default()
        config.orchestration.max_rounds = self.max_rounds
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
        methods = methods or ["single-agent", "cognigraph-full", "cognigraph-pcst"]
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
        methods = methods or ["single-agent", "cognigraph-full", "cognigraph-pcst"]
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

        # CogniGraph methods: build graph and run full pipeline
        strategy = "full" if method == "cognigraph-full" else "pcst"
        config = self._build_config(strategy)
        graph = CogniGraph.from_networkx(kg, config=config)
        graph.set_default_backend(self.backend)

        start = time.perf_counter()
        result: ReasoningResult = await graph.areason(question)
        latency = (time.perf_counter() - start) * 1000

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
            "cognigraph-full": "CogniGraph-Full",
            "cognigraph-pcst": "CogniGraph-PCST",
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
