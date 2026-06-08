"""Orchestrator — controls the full message-passing reasoning process."""

# ── graqle:intelligence ──
# module: graqle.orchestration.orchestrator
# risk: MEDIUM (impact radius: 4 modules)
# consumers: run_multigov_v2, run_multigov_v3, __init__, test_error_scenarios
# dependencies: __future__, logging, random, time, typing +7 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import random
import time
from typing import TYPE_CHECKING, Any

from graqle.config.settings import ObserverConfig, OrchestrationConfig
from graqle.core.message import Message
from graqle.core.types import ReasoningResult
from graqle.orchestration.aggregation import Aggregator
from graqle.orchestration.convergence import ConvergenceDetector
from graqle.orchestration.message_passing import MessagePassingProtocol
from graqle.orchestration.observer import MasterObserver

if TYPE_CHECKING:
    from graqle.core.graph import Graqle

logger = logging.getLogger("graqle.orchestrator")


class Orchestrator:
    """Controls the message-passing reasoning lifecycle.

    1. Receives a query + activated node list
    2. Builds constraint graph + propagates constraints to nodes
    3. Runs message-passing rounds until convergence
    4. MasterObserver watches ALL traffic for transparency (if enabled)
    5. Aggregates final results with constraint-aware synthesis
    6. Returns ReasoningResult with full provenance trace + observer report
    """

    def __init__(
        self,
        config: OrchestrationConfig | None = None,
        message_protocol: MessagePassingProtocol | None = None,
        convergence_detector: ConvergenceDetector | None = None,
        aggregator: Aggregator | None = None,
        observer: MasterObserver | None = None,
        observer_config: ObserverConfig | None = None,
        # v2: Governance-constrained reasoning components
        ontology_registry: Any = None,
        constraint_graph: Any = None,
        ontology_router: Any = None,
        skill_resolver: Any = None,
        skill_admin: Any = None,
        shacl_gate: Any = None,
        embedding_fn: Any = None,
    ) -> None:
        config = config or OrchestrationConfig()
        self.config = config

        # v2: Governance components
        self.ontology_registry = ontology_registry
        self.constraint_graph = constraint_graph
        self.ontology_router = ontology_router
        self.skill_resolver = skill_resolver
        self.skill_admin = skill_admin  # v3: Smart skill assignment
        self.shacl_gate = shacl_gate
        self.embedding_fn = embedding_fn

        self.message_protocol = message_protocol or MessagePassingProtocol(
            parallel=not config.async_mode,
            ontology_router=ontology_router,
            embedding_fn=embedding_fn,
        )
        self.convergence_detector = convergence_detector or ConvergenceDetector(
            max_rounds=config.max_rounds,
            min_rounds=config.min_rounds,
            similarity_threshold=config.convergence_threshold,
            confidence_threshold=config.confidence_threshold,
        )
        self.aggregator = aggregator or Aggregator(strategy=config.aggregation)

        # MasterObserver — optional transparency layer
        if observer is not None:
            self.observer = observer
        elif observer_config and observer_config.enabled:
            self.observer = MasterObserver(
                enabled=observer_config.enabled,
                report_per_round=observer_config.report_per_round,
                detect_conflicts=observer_config.detect_conflicts,
                detect_patterns=observer_config.detect_patterns,
                detect_anomalies=observer_config.detect_anomalies,
                use_llm_analysis=observer_config.use_llm_analysis,
            )
        else:
            self.observer = MasterObserver(enabled=False)

        # Governance stats tracking
        self._gov_stats: dict[str, int] = {
            "shacl_validations_pass": 0,
            "shacl_validations_fail": 0,
            "constraint_propagations": 0,
            "observer_redirects": 0,
            "ontology_route_filtered": 0,
        }

    async def run(
        self,
        graph: Graqle,
        query: str,
        active_node_ids: list[str],
        max_rounds: int | None = None,
        *,
        relevance_scores: dict[str, float] | None = None,
    ) -> ReasoningResult:
        """Execute the full reasoning pipeline."""
        start_time = time.time()
        max_rounds = max_rounds or self.config.max_rounds

        logger.info(
            f"Starting reasoning: {len(active_node_ids)} nodes, "
            f"max {max_rounds} rounds"
        )

        # Reset convergence detector and observer
        self.convergence_detector.reset()
        self.convergence_detector.max_rounds = max_rounds
        self.observer.reset()
        self._gov_stats = {k: 0 for k in self._gov_stats}

        # === v2: Pre-reasoning governance setup ===
        self._setup_governance_constraints(graph, active_node_ids, query=query)

        # Cost budget enforcement
        cost_config = getattr(getattr(graph, "config", None), "cost", None)
        budget_limit = (
            cost_config.budget_per_query
            if cost_config and hasattr(cost_config, "budget_per_query")
            else float("inf")
        )
        cumulative_cost = 0.0

        # Dynamic ceiling parameters (v0.10.3)
        dynamic_ceiling = getattr(cost_config, "dynamic_ceiling", True)
        cont_base = getattr(cost_config, "continuation_base_prob", 0.85)
        cont_decay = getattr(cost_config, "continuation_decay", 0.6)
        hard_mult = getattr(cost_config, "hard_ceiling_multiplier", 3.0)
        rounds_over_budget = 0

        # Message passing loop
        all_messages: list[dict[str, Message]] = []
        previous_messages: dict[str, Message] | None = None
        rounds_completed = 0
        per_round_observations: list[list[str]] = []
        budget_exceeded = False
        # ADR-222 P4: cost is measured, never gated. cost_advisory_emitted ensures
        # the N x-budget advisory logs once; cost_at_advisory snapshots spend at the
        # moment reasoning chose to continue, so we can MEASURE the cost of that
        # decision (the extra spend the continuation incurred) and surface it.
        cost_advisory_emitted = False
        cost_at_advisory: float | None = None

        # CR-007 Fix 5: absolute LLM-call ceiling. Checked BEFORE each
        # round so the ceiling actually constrains rounds (post-round check
        # alone is ineffective when max_rounds=2 — round 2 always runs).
        # Halts cleanly between rounds so partial state never escapes.
        # Default 60 covers max_nodes=50 + max_rounds=2 + 1 synthesis;
        # configurable via GraqleConfig.orchestration.max_llm_calls.
        # The projected check uses len(active_node_ids) as the per-round cost
        # estimate — accurate for fan-out, conservative for hierarchical mode
        # where summary calls reduce actual count.
        orch_outer = getattr(getattr(graph, "config", None), "orchestration", None)
        max_llm_calls = int(getattr(orch_outer, "max_llm_calls", 60) or 60)
        llm_calls_so_far = 0
        per_round_estimate = max(1, len(active_node_ids))

        for round_num in range(max_rounds):
            # Pre-round ceiling: would starting this round push us over?
            projected = llm_calls_so_far + per_round_estimate
            # Reserve 1 call budget for the final synthesis.
            if round_num > 0 and projected > max_llm_calls - 1:
                logger.warning(
                    "CR-007 max_llm_calls pre-round halt: projected %d > %d "
                    "(used=%d, est_round=%d). Skipping round %d. Tune via "
                    "GraqleConfig.orchestration.max_llm_calls.",
                    projected, max_llm_calls - 1,
                    llm_calls_so_far, per_round_estimate, round_num,
                )
                break
            # Run one round
            current_messages = await self.message_protocol.run_round(
                graph=graph,
                query=query,
                active_node_ids=active_node_ids,
                round_num=round_num,
                previous_messages=previous_messages,
            )

            all_messages.append(current_messages)
            rounds_completed = round_num + 1

            # CR-007 Fix 5: account for LLM calls issued in this round and
            # halt if the absolute ceiling is reached. Each node makes 1 base
            # call per round (excluding optional continuation calls, which are
            # bounded separately by max_continuations). Synthesis adds 1 more
            # final call counted after the loop. Halting happens AFTER the
            # round completes so partial state never escapes the orchestrator.
            llm_calls_so_far += len(current_messages)
            if llm_calls_so_far >= max_llm_calls:
                logger.warning(
                    "CR-007 max_llm_calls ceiling reached: %d >= %d. "
                    "Halting after round %d. Tune via "
                    "GraqleConfig.orchestration.max_llm_calls.",
                    llm_calls_so_far, max_llm_calls, rounds_completed,
                )
                break

            # Track cumulative cost per round
            round_tokens = sum(m.token_count for m in current_messages.values())
            round_cost_rate = 0.0001
            for nid in active_node_ids:
                node = graph.nodes[nid]
                if node.backend is not None:
                    round_cost_rate = node.backend.cost_per_1k_tokens / 1000
                    break
            cumulative_cost += round_tokens * round_cost_rate

            # Dynamic budget ceiling (v0.10.3)
            # After soft limit: probabilistic continuation with decay.
            # P(continue) = base * decay^k, where k = rounds over budget.
            # Hard ceiling at N * budget is absolute safety net.
            if cumulative_cost >= budget_limit:
                if not budget_exceeded:
                    logger.warning(
                        f"Cost budget soft limit reached: ${cumulative_cost:.4f} >= "
                        f"${budget_limit:.4f} (reasoning continues — quality over cost)."
                    )
                    budget_exceeded = True

                # Cost is observability, NOT a governance/quality gate (ADR-222 P4).
                # We never halt a still-converging ("brilliant") reasoning purely
                # because it got expensive — that would cut quality for cost. The
                # value-based bound is convergence + max_rounds (below): they stop
                # reasoning when it stops ADDING value, not when it gets pricey.
                # At N x budget we emit a LOUD advisory (the cost-visibility / sell
                # story) and CONTINUE. The only true runaway guard is max_rounds.
                if (
                    cumulative_cost >= budget_limit * hard_mult
                    and rounds_completed >= 2
                    and not cost_advisory_emitted
                ):
                    logger.warning(
                        f"Cost advisory ({hard_mult}x budget): "
                        f"${cumulative_cost:.4f} at round {rounds_completed}. "
                        f"Reasoning CONTINUES — quality over cost; bounded by "
                        f"convergence and max_rounds, never by cost."
                    )
                    cost_advisory_emitted = True
                    cost_at_advisory = cumulative_cost

                # Dynamic probabilistic gate (after minimum 2 rounds)
                if dynamic_ceiling and rounds_completed >= 2:
                    p_continue = cont_base * (cont_decay ** rounds_over_budget)
                    roll = random.random()
                    if roll > p_continue:
                        logger.info(
                            f"Dynamic ceiling: stopping at round {rounds_completed} "
                            f"(P={p_continue:.2%}, roll={roll:.3f}, "
                            f"cost=${cumulative_cost:.4f})."
                        )
                        break
                    else:
                        logger.info(
                            f"Dynamic ceiling: continuing round {rounds_completed + 1} "
                            f"(P={p_continue:.2%}, roll={roll:.3f}, "
                            f"cost=${cumulative_cost:.4f})."
                        )
                    rounds_over_budget += 1

            # Observer watches this round
            round_obs = await self.observer.observe_round(
                query, round_num, current_messages, graph
            )
            if round_obs:
                per_round_observations.append(round_obs)
                logger.info(
                    f"Observer round {round_num}: {len(round_obs)} findings"
                )

            # Check convergence
            prev_list = (
                list(previous_messages.values()) if previous_messages else None
            )
            if self.convergence_detector.check(
                round_num + 1,
                list(current_messages.values()),
                prev_list,
            ):
                logger.info(f"Converged at round {rounds_completed}")
                break

            previous_messages = current_messages

        # Aggregate final answer
        final_messages = all_messages[-1] if all_messages else {}

        # Use the first available backend for aggregation
        agg_backend = None
        for nid in active_node_ids:
            node = graph.nodes[nid]
            if node.backend is not None:
                agg_backend = node.backend
                break

        answer, synthesis_trunc_info = await self.aggregator.aggregate(
            query, final_messages, backend=agg_backend
        )

        # Compute cost
        total_tokens = sum(
            msg.token_count
            for round_msgs in all_messages
            for msg in round_msgs.values()
        )
        avg_cost = 0.0001  # default local cost
        if agg_backend:
            avg_cost = agg_backend.cost_per_1k_tokens / 1000
        cost_usd = total_tokens * avg_cost

        # Build message trace
        message_trace = [
            msg.to_dict()
            for round_msgs in all_messages
            for msg in round_msgs.values()
        ]

        # Compute confidence — relevance-weighted if scores available (Bug 18)
        # v0.14.0 FIX: Top-k weighted + coverage factor
        # v0.15.0 FIX: Further recalibration for large KGs (>5K nodes).
        #   Session 2 eval showed 9-15% confidence for 8/10 quality answers
        #   on a 13K-node merged KG. Root causes:
        #   1. Default node confidence (0.5) diluted the weighted average
        #   2. 60/40 raw/coverage split underweighted the raw quality signal
        #   3. Floor of 0.30 too low for well-supported multi-node answers
        #   Fix: 75/25 weighting, logarithmic coverage, tiered floors.
        import math

        final_confidences = {
            nid: m.confidence for nid, m in final_messages.items()
        }
        if relevance_scores and final_confidences:
            # Sort by relevance, take top contributors
            scored = [
                (nid, final_confidences[nid], relevance_scores.get(nid, 0.0))
                for nid in final_confidences
            ]
            scored.sort(key=lambda x: x[2], reverse=True)

            # Use top-k nodes (at least 3, at most 20) for confidence
            top_k = max(3, min(20, len(scored) // 3))
            top_scored = scored[:top_k]

            weighted_sum = 0.0
            weight_total = 0.0
            for nid, conf, rel in top_scored:
                weighted_sum += conf * rel
                weight_total += rel

            raw_confidence = (
                weighted_sum / weight_total if weight_total > 0 else 0.0
            )

            # Coverage: logarithmic scale so large activations don't saturate
            # at the same rate as small ones.  log2(1+15)/log2(1+20) ≈ 0.91
            activated = len([s for s in scored if s[2] > 0.01])
            coverage_factor = min(
                1.0,
                math.log2(1 + activated) / math.log2(1 + max(top_k, 3)),
            )

            # Calibrated: 75% from top-k quality, 25% from coverage breadth
            avg_confidence = (0.75 * raw_confidence) + (0.25 * coverage_factor)

            # Tiered floor based on activated node count:
            #   3+  nodes with raw > 0.05  → floor 0.40
            #   5+  nodes with raw > 0.10  → floor 0.55
            #   10+ nodes with raw > 0.15  → floor 0.65
            if activated >= 10 and raw_confidence > 0.15:
                avg_confidence = max(avg_confidence, 0.65)
            elif activated >= 5 and raw_confidence > 0.10:
                avg_confidence = max(avg_confidence, 0.55)
            elif activated >= 3 and raw_confidence > 0.05:
                avg_confidence = max(avg_confidence, 0.40)

        elif final_confidences:
            avg_confidence = (
                sum(final_confidences.values()) / len(final_confidences)
            )
        else:
            avg_confidence = 0.0

        elapsed_ms = (time.time() - start_time) * 1000

        # Generate observer report
        observer_report = None
        if self.observer.enabled:
            observer_report = self.observer.generate_report(query)
            logger.info(
                f"Observer: health={observer_report.health_score:.0%}, "
                f"conflicts={observer_report.conflict_count}, "
                f"anomalies={observer_report.anomaly_count}, "
                f"patterns={observer_report.pattern_count}"
            )

        # Collect governance stats from components
        self._collect_gov_stats()

        # Build metadata
        metadata: dict = {
            "convergence_round": rounds_completed,
            "total_messages": len(message_trace),
            "total_tokens": total_tokens,
            "budget_exceeded": budget_exceeded,
            "cumulative_cost_usd": round(cumulative_cost, 6),
            "governance_stats": dict(self._gov_stats),
        }
        # ADR-222 P4: when reasoning chose to continue past the cost advisory
        # (a "brilliant decision" still converging), MEASURE the cost of that
        # decision — the extra spend the continuation incurred beyond the
        # advisory point — and surface it. Cost is reported, never gated.
        if cost_at_advisory is not None:
            metadata["cost_advisory_triggered"] = True
            metadata["cost_at_advisory_usd"] = round(cost_at_advisory, 6)
            metadata["continuation_cost_usd"] = round(
                max(0.0, cumulative_cost - cost_at_advisory), 6
            )
        if observer_report:
            metadata["observer_report"] = observer_report.to_dict()
            metadata["observer_summary"] = observer_report.to_summary()
            metadata["health_score"] = observer_report.health_score
            cost_usd += observer_report.observer_cost_usd

        # B1+B2: Surface truncation from nodes and synthesis
        # Null-safe: (or {}) handles metadata=None; .get(, False) handles absent key
        truncated_nodes = [
            nid for nid, msg in final_messages.items()
            if bool((getattr(msg, "metadata", None) or {}).get("truncated", False))
        ]
        if truncated_nodes:
            metadata["truncated_nodes"] = truncated_nodes
            metadata["truncation_count"] = len(truncated_nodes)
        if synthesis_trunc_info.get("synthesis_truncated"):
            metadata["synthesis_truncated"] = True
            metadata["synthesis_stop_reason"] = synthesis_trunc_info.get(
                "synthesis_stop_reason", ""
            )

        # v0.51.3 — ambiguous_options (VS Code extension Ambiguity Pause).
        # The Aggregator attaches a 'candidates' list to synthesis_trunc_info
        # when >=2 near-tied options survive its trigger check. We surface
        # those as ambiguous_options in the ReasoningResult metadata so the
        # MCP layer can emit them to callers. Omitted entirely when absent.
        _ambiguous = synthesis_trunc_info.get("candidates")
        if _ambiguous:
            metadata["ambiguous_options"] = _ambiguous

        # CG-REASON-DIAG-01 — missing-LLM-SDK diagnostic pass-through.
        # Aggregator attaches a sorted list at the zero-success fallback
        # branch. We promote it to metadata; MCP handler renders the
        # user-facing diagnostic. Type-guarded to reject malformed values.
        _missing_sdks = synthesis_trunc_info.get("missing_llm_sdks")
        if isinstance(_missing_sdks, list) and _missing_sdks:
            metadata["missing_llm_sdks"] = list(_missing_sdks)

        result = ReasoningResult(
            query=query,
            answer=answer,
            confidence=avg_confidence,
            rounds_completed=rounds_completed,
            active_nodes=active_node_ids,
            message_trace=message_trace,
            cost_usd=cost_usd,
            latency_ms=elapsed_ms,
            metadata=metadata,
        )

        logger.info(
            f"Reasoning complete: {rounds_completed} rounds, "
            f"{len(message_trace)} messages, {elapsed_ms:.0f}ms"
        )

        return result

    def _setup_governance_constraints(
        self, graph: Graqle, active_node_ids: list[str],
        query: str = "",
    ) -> None:
        """Pre-reasoning: propagate constraints, skills, and SHACL gate to nodes."""
        # Build constraint graph if available
        if self.constraint_graph is not None:
            if self.embedding_fn:
                self.constraint_graph.set_embedding_fn(self.embedding_fn)
            self.constraint_graph.build(graph, active_node_ids)
            self._gov_stats["constraint_propagations"] = (
                self.constraint_graph.stats.get("propagations", 0)
            )

        # Set up each active node with governance context
        for nid in active_node_ids:
            node = graph.nodes[nid]

            # Constraint text from constraint graph
            if self.constraint_graph is not None:
                constraints = self.constraint_graph.get_constraints(nid)
                node.constraint_text = constraints.to_prompt_text()

            # Skills: prefer SkillAdmin (smart, query-aware) over SkillResolver (basic)
            if self.skill_admin is not None:
                node.skills_text = self.skill_admin.assign_to_node(node, query)
            elif self.skill_resolver is not None:
                node.skills_text = self.skill_resolver.skills_to_prompt(
                    node.entity_type
                )

            # Domain identification
            if self.ontology_registry is not None:
                domain = self.ontology_registry.find_domain_for_type(
                    node.entity_type
                )
                node.domain = domain.name if domain else "general"

            # SHACL gate reference for validation during reasoning
            if self.shacl_gate is not None:
                node.shacl_gate = self.shacl_gate

    def _collect_gov_stats(self) -> None:
        """Collect governance stats from all components."""
        if self.shacl_gate is not None:
            gate_stats = self.shacl_gate.stats
            self._gov_stats["shacl_validations_pass"] = gate_stats.get("passes", 0)
            self._gov_stats["shacl_validations_fail"] = gate_stats.get("failures", 0)

        if self.ontology_router is not None:
            router_stats = self.ontology_router.stats
            self._gov_stats["ontology_route_filtered"] = router_stats.get("filtered", 0)
