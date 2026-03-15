"""MasterObserver — transparency intelligence layer for Graqle.

The MasterObserver is an optional agent that watches ALL inter-node
message traffic during reasoning. It does NOT participate in reasoning —
it observes, analyzes, and reports.

What it catches that humans can't:
- Contradictions between nodes (conflict detection)
- Echo chambers (nodes parroting each other without adding insight)
- Flip-flopping (nodes changing position without new evidence)
- Confidence anomalies (sudden spikes/drops)
- Isolated nodes (activated but not contributing)
- Dominant nodes (one node drowning out others)
- Convergence quality (are nodes genuinely agreeing or just giving up?)

The observer can use a SMARTER model than the node agents — e.g., Claude
Haiku watches over Qwen 0.5B agents. This creates a meta-reasoning layer
that adds transparency without disrupting the emergent process.
"""

# ── graqle:intelligence ──
# module: graqle.orchestration.observer
# risk: MEDIUM (impact radius: 5 modules)
# consumers: run_multigov_v2, run_multigov_v3, orchestrator, __init__, test_observer
# dependencies: __future__, logging, collections, typing, message +2 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from graqle.core.message import Message
from graqle.core.observer_report import (
    AnomalyFlag,
    ConflictPair,
    NodeContribution,
    ObserverReport,
    PatternInsight,
)
from graqle.core.types import ModelBackend, ReasoningType

if TYPE_CHECKING:
    from graqle.core.graph import Graqle

logger = logging.getLogger("graqle.observer")


OBSERVER_ANALYSIS_PROMPT = """You are a reasoning transparency analyst. You observe a multi-agent reasoning process where specialized agents exchange messages to answer a query.

Query: {query}

Round {round_num} messages:
{round_messages}

Previous observations:
{previous_observations}

Analyze this round for:
1. CONFLICTS: Do any agents contradict each other? (quote the conflicting claims)
2. PATTERNS: Any echo chambers, flip-flops, or new emergent insights?
3. ANOMALIES: Unusual confidence changes, empty reasoning, or off-topic responses?
4. LEARNINGS: What new understanding emerged from this round of interaction?

Be concise. Focus on what a human reviewer NEEDS to know."""


class MasterObserver:
    """Transparency intelligence layer — watches all message traffic.

    The MasterObserver is optional and configurable:
    - `enabled`: Turn on/off
    - `backend`: Model to use for analysis (can be smarter than node agents)
    - `report_per_round`: Generate analysis after each round (vs only at end)
    - `detect_conflicts`: Enable contradiction detection
    - `detect_patterns`: Enable pattern analysis
    - `detect_anomalies`: Enable anomaly flagging
    - `use_llm_analysis`: Use LLM for deep analysis (costs tokens but catches more)
    """

    def __init__(
        self,
        backend: ModelBackend | None = None,
        *,
        enabled: bool = True,
        report_per_round: bool = False,
        detect_conflicts: bool = True,
        detect_patterns: bool = True,
        detect_anomalies: bool = True,
        use_llm_analysis: bool = False,
    ) -> None:
        self.backend = backend
        self.enabled = enabled
        self.report_per_round = report_per_round
        self.detect_conflicts = detect_conflicts
        self.detect_patterns = detect_patterns
        self.detect_anomalies = detect_anomalies
        self.use_llm_analysis = use_llm_analysis

        # Internal tracking
        self._round_messages: list[dict[str, Message]] = []
        self._conflicts: list[ConflictPair] = []
        self._patterns: list[PatternInsight] = []
        self._anomalies: list[AnomalyFlag] = []
        self._learnings: list[str] = []
        self._node_history: dict[str, list[Message]] = defaultdict(list)
        self._confidence_trajectory: list[float] = []
        self._observer_cost: float = 0.0

    # Active feedback tracking (v2)
        self._active_feedback: bool = False
        self._feedback_count: int = 0

    def reset(self) -> None:
        """Reset state for a new query."""
        self._round_messages.clear()
        self._conflicts.clear()
        self._patterns.clear()
        self._anomalies.clear()
        self._learnings.clear()
        self._node_history.clear()
        self._confidence_trajectory.clear()
        self._observer_cost = 0.0
        self._feedback_count = 0

    async def observe_round(
        self,
        query: str,
        round_num: int,
        messages: dict[str, Message],
        graph: Graqle | None = None,
    ) -> list[str] | None:
        """Observe one round of message passing.

        Returns per-round observations if report_per_round is enabled.
        """
        if not self.enabled:
            return None

        self._round_messages.append(messages)

        # Track per-node history
        for node_id, msg in messages.items():
            self._node_history[node_id].append(msg)

        # Track confidence trajectory
        if messages:
            avg_conf = sum(m.confidence for m in messages.values()) / len(messages)
            self._confidence_trajectory.append(avg_conf)

        # Run detections
        if self.detect_conflicts:
            self._detect_conflicts(messages, round_num)

        if self.detect_anomalies:
            self._detect_anomalies(messages, round_num)

        if self.detect_patterns and round_num >= 1:
            self._detect_patterns(messages, round_num)

        # LLM-based deep analysis (optional, costs tokens)
        if self.use_llm_analysis and self.backend:
            await self._llm_analysis(query, round_num, messages)

        # Return per-round observations if configured
        if self.report_per_round:
            round_findings = []
            new_conflicts = [c for c in self._conflicts if c.round_detected == round_num]
            new_anomalies = [a for a in self._anomalies if a.round == round_num]
            new_patterns = [p for p in self._patterns if p.round_detected == round_num]

            for c in new_conflicts:
                round_findings.append(
                    f"[CONFLICT] {c.node_a} vs {c.node_b}: {c.severity}"
                )
            for a in new_anomalies:
                round_findings.append(
                    f"[ANOMALY] {a.anomaly_type} at {a.node_id}: {a.description}"
                )
            for p in new_patterns:
                round_findings.append(
                    f"[PATTERN] {p.pattern_type}: {p.description}"
                )
            return round_findings if round_findings else None

        return None

    def generate_feedback(
        self,
        round_num: int,
        messages: dict[str, Message],
        graph: Graqle | None = None,
    ) -> dict[str, Message]:
        """Generate active feedback for nodes (v2 — active observer).

        Produces REDIRECT, DEEPEN, PRUNE, or AFFIRM feedback messages
        that are injected into the next round of message passing.

        Returns:
            Dict of node_id -> feedback Message
        """
        if not self.enabled:
            return {}

        feedback: dict[str, Message] = {}

        for node_id, msg in messages.items():
            history = self._node_history.get(node_id, [])

            # PRUNE: Low confidence for 2+ rounds
            if len(history) >= 2 and all(h.confidence < 0.15 for h in history[-2:]):
                fb = Message(
                    source_node_id="__observer__",
                    target_node_id=node_id,
                    round=round_num,
                    content=(
                        "[OBSERVER PRUNE] Your confidence has been below 15% for "
                        "multiple rounds. You are being pruned from further reasoning. "
                        "This is normal — not all nodes are relevant to every query."
                    ),
                    reasoning_type=ReasoningType.ASSERTION,
                    confidence=1.0,
                )
                feedback[node_id] = fb
                # Mark node as pruned
                if graph and node_id in graph.nodes:
                    graph.nodes[node_id].pruned = True
                self._feedback_count += 1
                continue

            # REDIRECT: Node seems off-topic (very low confidence, first round)
            if msg.confidence < 0.2 and round_num == 1:
                fb = Message(
                    source_node_id="__observer__",
                    target_node_id=node_id,
                    round=round_num,
                    content=(
                        "[OBSERVER REDIRECT] Your response has low relevance to this query. "
                        "Focus on what IS in your domain. If the query is outside your "
                        "expertise, state that clearly in one sentence."
                    ),
                    reasoning_type=ReasoningType.ASSERTION,
                    confidence=1.0,
                )
                feedback[node_id] = fb
                self._feedback_count += 1
                continue

            # DEEPEN: Node has good confidence but short/surface response
            word_count = len(msg.content.split())
            if msg.confidence > 0.5 and word_count < 30 and round_num < 3:
                fb = Message(
                    source_node_id="__observer__",
                    target_node_id=node_id,
                    round=round_num,
                    content=(
                        "[OBSERVER DEEPEN] Your analysis is on-topic but too brief. "
                        "Go deeper: cite specific article numbers, penalties, timelines, "
                        "or evidence chunks. Substance over brevity."
                    ),
                    reasoning_type=ReasoningType.ASSERTION,
                    confidence=1.0,
                )
                feedback[node_id] = fb
                self._feedback_count += 1
                continue

            # AFFIRM: High-confidence, substantive response
            if msg.confidence > 0.7 and word_count > 40:
                # Check if there are conflicting nodes to synthesize with
                conflict_partners = [
                    c.node_b if c.node_a == node_id else c.node_a
                    for c in self._conflicts
                    if node_id in (c.node_a, c.node_b)
                ]
                if conflict_partners:
                    fb = Message(
                        source_node_id="__observer__",
                        target_node_id=node_id,
                        round=round_num,
                        content=(
                            f"[OBSERVER AFFIRM] Good analysis. However, you conflict with "
                            f"{', '.join(conflict_partners)}. Address their points and "
                            f"explain why your position is correct, or acknowledge overlap."
                        ),
                        reasoning_type=ReasoningType.ASSERTION,
                        confidence=1.0,
                    )
                    feedback[node_id] = fb
                    self._feedback_count += 1

        return feedback

    @property
    def feedback_count(self) -> int:
        return self._feedback_count

    def generate_report(self, query: str) -> ObserverReport:
        """Generate the final transparency report."""
        # Compute per-node contributions
        contributions: dict[str, NodeContribution] = {}
        total_messages = sum(len(msgs) for msgs in self._node_history.values())

        for node_id, messages in self._node_history.items():
            type_counts: dict[str, int] = defaultdict(int)
            confidences = []
            for msg in messages:
                type_counts[msg.reasoning_type.value] += 1
                confidences.append(msg.confidence)

            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

            # Influence score: weighted by confidence, message count, and type diversity
            influence = 0.0
            if total_messages > 0:
                msg_weight = len(messages) / total_messages
                conf_weight = avg_conf
                type_diversity = len(type_counts) / 6  # 6 possible types
                influence = (msg_weight * 0.4 + conf_weight * 0.4 + type_diversity * 0.2)

            # Check if this node was contradicted
            was_contradicted = any(
                c.node_a == node_id or c.node_b == node_id
                for c in self._conflicts
            )

            # Check flip-flop count
            flip_count = self._count_flips(messages)

            contributions[node_id] = NodeContribution(
                node_id=node_id,
                messages_sent=len(messages),
                avg_confidence=avg_conf,
                reasoning_types=dict(type_counts),
                influence_score=min(influence, 1.0),
                was_contradicted=was_contradicted,
                flip_count=flip_count,
            )

        # Overall confidence
        overall_conf = (
            self._confidence_trajectory[-1]
            if self._confidence_trajectory
            else 0.0
        )

        report = ObserverReport(
            query=query,
            total_rounds=len(self._round_messages),
            total_messages=total_messages,
            total_nodes=len(self._node_history),
            overall_confidence=overall_conf,
            conflicts=self._conflicts,
            patterns=self._patterns,
            anomalies=self._anomalies,
            contributions=contributions,
            confidence_trajectory=self._confidence_trajectory,
            learnings=self._learnings,
            observer_model=self.backend.name if self.backend else "rule-based",
            observer_cost_usd=self._observer_cost,
        )

        return report

    # --- Detection Methods ---

    def _detect_conflicts(
        self, messages: dict[str, Message], round_num: int
    ) -> None:
        """Detect genuine contradictions between node outputs.

        v0.12 overhaul: perspective diversity is NOT conflict.
        With 20 nodes reasoning in parallel (ChunkScorer era), most nodes
        discuss DIFFERENT aspects of the query. Only flag a conflict when
        nodes make OPPOSING claims about the SAME topic.

        Detection tiers:
        - Explicit: node uses CONTRADICTION reasoning type → always flag
        - Strong: both nodes reference each other AND use negation language
        - Weak (suppressed at >8 nodes): one-directional reference + keyword
        """
        msg_list = list(messages.items())
        num_nodes = len(messages)

        # Negation patterns that indicate genuine disagreement (not just
        # different perspectives). Require verb negation, not just the
        # presence of words like "but" which are normal in analysis.
        _strong_contra = {
            "is incorrect", "is wrong", "this contradicts",
            "disagree with", "opposes", "but actually",
            "that is not true", "inaccurate", "misrepresents",
            "fails to account", "does not align",
        }

        for i in range(len(msg_list)):
            for j in range(i + 1, len(msg_list)):
                node_a, msg_a = msg_list[i]
                node_b, msg_b = msg_list[j]

                # Tier 1: Explicit CONTRADICTION reasoning type
                # When a node explicitly declares CONTRADICTION, trust it.
                # This is a strong signal from the reasoning engine itself.
                if (msg_a.reasoning_type == ReasoningType.CONTRADICTION
                        or msg_b.reasoning_type == ReasoningType.CONTRADICTION):
                    self._conflicts.append(ConflictPair(
                        node_a=node_a,
                        node_b=node_b,
                        claim_a=msg_a.content[:200],
                        claim_b=msg_b.content[:200],
                        round_detected=round_num,
                        severity="high",
                    ))
                    continue

                a_lower = msg_a.content.lower()
                b_lower = msg_b.content.lower()

                # Tier 2: Strong — mutual reference + strong negation phrase
                references_each_other = (
                    node_b.lower() in a_lower and node_a.lower() in b_lower
                )
                strong_hits = sum(
                    1 for phrase in _strong_contra
                    if phrase in a_lower or phrase in b_lower
                )
                if references_each_other and strong_hits >= 1:
                    self._conflicts.append(ConflictPair(
                        node_a=node_a,
                        node_b=node_b,
                        claim_a=msg_a.content[:200],
                        claim_b=msg_b.content[:200],
                        round_detected=round_num,
                        severity="medium",
                    ))
                    continue

                # Tier 3: One-directional — only for small node counts (≤5)
                # where perspective diversity is limited. With strong
                # negation language, this is still a meaningful signal.
                # Suppressed for >5 nodes to avoid false positive flood.
                if num_nodes <= 5:
                    one_directional = (
                        node_b.lower() in a_lower or node_a.lower() in b_lower
                    )
                    if one_directional and strong_hits >= 1:
                        self._conflicts.append(ConflictPair(
                            node_a=node_a,
                            node_b=node_b,
                            claim_a=msg_a.content[:200],
                            claim_b=msg_b.content[:200],
                            round_detected=round_num,
                            severity="medium",
                        ))

    def _detect_anomalies(
        self, messages: dict[str, Message], round_num: int
    ) -> None:
        """Detect anomalies in reasoning behavior.

        v0.12: Adaptive thresholds based on node count. With 20 nodes,
        confidence variance is expected — raise thresholds to avoid
        flooding the report with false anomalies.
        """
        num_nodes = len(messages)
        # Adaptive confidence delta threshold: stricter for few nodes,
        # more lenient for many (perspective diversity causes natural variance)
        conf_delta_threshold = 0.3 if num_nodes <= 5 else 0.5

        for node_id, msg in messages.items():
            history = self._node_history.get(node_id, [])

            # Empty or very short response
            if len(msg.content.strip()) < 20:
                self._anomalies.append(AnomalyFlag(
                    anomaly_type="empty_response",
                    node_id=node_id,
                    description=f"Response too short ({len(msg.content)} chars)",
                    round=round_num,
                    severity="high",
                ))

            # Confidence spike/drop — adaptive threshold
            if len(history) >= 2:
                prev_conf = history[-2].confidence
                curr_conf = msg.confidence
                delta = abs(curr_conf - prev_conf)
                if delta > conf_delta_threshold:
                    direction = "spike" if curr_conf > prev_conf else "drop"
                    # Only flag as high severity for extreme swings
                    severity = "high" if delta > 0.6 else "medium"
                    self._anomalies.append(AnomalyFlag(
                        anomaly_type=f"confidence_{direction}",
                        node_id=node_id,
                        description=(
                            f"Confidence {direction}: {prev_conf:.0%} → {curr_conf:.0%} "
                            f"(Δ={delta:.0%})"
                        ),
                        round=round_num,
                        severity=severity,
                    ))

            # Self-contradiction — require stronger signals than just
            # "actually" (which is common in normal reasoning refinement)
            if len(history) >= 2:
                curr = msg.content.lower()
                strong_self_contra = [
                    "i was wrong", "my previous answer was incorrect",
                    "correction:", "i now realize my earlier",
                ]
                if any(s in curr for s in strong_self_contra):
                    self._anomalies.append(AnomalyFlag(
                        anomaly_type="contradicts_self",
                        node_id=node_id,
                        description="Node explicitly contradicts its own previous position",
                        round=round_num,
                        severity="low",
                    ))

    def _detect_patterns(
        self, messages: dict[str, Message], round_num: int
    ) -> None:
        """Detect interaction patterns across nodes."""
        if len(self._round_messages) < 2:
            return

        prev_round = self._round_messages[-2]

        # Echo Chamber: multiple nodes producing very similar content
        msg_list = list(messages.values())
        for i in range(len(msg_list)):
            for j in range(i + 1, len(msg_list)):
                sim = self._text_overlap(msg_list[i].content, msg_list[j].content)
                if sim > 0.7:
                    self._patterns.append(PatternInsight(
                        pattern_type="echo_chamber",
                        description=(
                            f"{msg_list[i].source_node_id} and {msg_list[j].source_node_id} "
                            f"producing nearly identical output ({sim:.0%} overlap)"
                        ),
                        involved_nodes=[
                            msg_list[i].source_node_id,
                            msg_list[j].source_node_id,
                        ],
                        confidence=sim,
                        round_detected=round_num,
                        recommendation="Consider diversifying prompts or reducing these nodes' connectivity",
                    ))

        # Dominance: one node's confidence >> all others
        confidences = {nid: m.confidence for nid, m in messages.items()}
        if confidences:
            max_conf = max(confidences.values())
            avg_conf = sum(confidences.values()) / len(confidences)
            if max_conf > avg_conf + 0.25 and len(confidences) > 2:
                dominant = max(confidences, key=confidences.get)
                self._patterns.append(PatternInsight(
                    pattern_type="dominance",
                    description=(
                        f"{dominant} dominates with {max_conf:.0%} confidence "
                        f"vs {avg_conf:.0%} average"
                    ),
                    involved_nodes=[dominant],
                    confidence=max_conf - avg_conf,
                    round_detected=round_num,
                    recommendation="Consider rebalancing model assignment or adjusting hub weighting",
                ))

        # Convergence quality: are nodes genuinely converging or stalling?
        if round_num >= 2 and len(self._confidence_trajectory) >= 2:
            prev_avg = self._confidence_trajectory[-2]
            curr_avg = self._confidence_trajectory[-1]
            if abs(curr_avg - prev_avg) < 0.02 and curr_avg < 0.7:
                self._patterns.append(PatternInsight(
                    pattern_type="stagnation",
                    description=(
                        f"Confidence stagnating at {curr_avg:.0%} — "
                        f"nodes may be stuck without new information"
                    ),
                    involved_nodes=list(messages.keys()),
                    confidence=0.8,
                    round_detected=round_num,
                    recommendation="Consider injecting additional context or adding more rounds",
                ))

    def _count_flips(self, messages: list[Message]) -> int:
        """Count how many times a node changed its reasoning type."""
        if len(messages) < 2:
            return 0
        flips = 0
        for i in range(1, len(messages)):
            if messages[i].reasoning_type != messages[i - 1].reasoning_type:
                flips += 1
        return flips

    @staticmethod
    def _text_overlap(text_a: str, text_b: str) -> float:
        """Simple word overlap ratio."""
        words_a = set(text_a.lower().split())
        words_b = set(text_b.lower().split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        return len(intersection) / min(len(words_a), len(words_b))

    async def _llm_analysis(
        self, query: str, round_num: int, messages: dict[str, Message]
    ) -> None:
        """Use LLM for deeper analysis of the round."""
        if not self.backend:
            return

        # Format messages for analysis
        msg_texts = []
        for node_id, msg in messages.items():
            msg_texts.append(
                f"[{node_id}] (conf={msg.confidence:.0%}, type={msg.reasoning_type.value})\n"
                f"{msg.content[:300]}"
            )

        prev_obs = "\n".join(self._learnings[-3:]) if self._learnings else "None"

        prompt = OBSERVER_ANALYSIS_PROMPT.format(
            query=query,
            round_num=round_num,
            round_messages="\n\n".join(msg_texts),
            previous_observations=prev_obs,
        )

        try:
            analysis = await self.backend.generate(
                prompt, max_tokens=300, temperature=0.2
            )
            if analysis.strip():
                self._learnings.append(f"Round {round_num}: {analysis.strip()}")
            self._observer_cost += self.backend.cost_per_1k_tokens * 0.3 / 1000
        except Exception as e:
            logger.warning(f"Observer LLM analysis failed: {e}")
