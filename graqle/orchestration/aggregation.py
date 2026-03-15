"""Aggregation strategies — synthesize multi-node reasoning into a final answer.

v2: Constraint-aware synthesis with filtering, validation, and concise output.
"""

# ── graqle:intelligence ──
# module: graqle.orchestration.aggregation
# risk: LOW (impact radius: 4 modules)
# consumers: run_multigov_v2, run_multigov_v3, orchestrator, __init__
# dependencies: __future__, logging, typing, message, types
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from graqle.core.message import Message
from graqle.core.types import ReasoningType

if TYPE_CHECKING:
    from graqle.core.types import ModelBackend

logger = logging.getLogger("graqle.aggregation")


# Legacy prompt (backward compatible)
AGGREGATION_PROMPT = """You are a reasoning aggregator. Multiple specialized agents have analyzed a query from different perspectives. Synthesize their outputs into a single, coherent answer.

Query: {query}

Agent Outputs:
{agent_outputs}

Instructions:
1. Identify areas of agreement across agents
2. Flag any contradictions between agents
3. Synthesize a unified answer weighted by confidence
4. State overall confidence (0-100%)
5. List key evidence sources

Provide a clear, structured response."""

# v2: Governance-constrained synthesis prompt
CONSTRAINED_AGGREGATION_PROMPT = """You are synthesizing analyses from domain experts who operated under formal governance constraints.

Query: {query}

{governance_context}

Expert analyses (only confident, validated outputs):
{filtered_outputs}

Synthesize a direct answer in 2-5 sentences. Requirements:
- Cite specific article numbers (e.g., "Article 5", "Art. 22")
- Include penalties, timelines, thresholds when relevant
- If multiple frameworks apply SIMULTANEOUSLY, state which ones and how they interact
- Respect the governance constraints — do not claim compliance without evidence
- No headers, bullet points, confidence scores, or agent names"""


class Aggregator:
    """Aggregates multi-node reasoning outputs into a final answer.

    v2 adds:
    - Confidence filtering (exclude < 0.20)
    - Pruned agent filtering
    - Constrained synthesis prompt
    - Separate synthesis backend selection
    """

    def __init__(
        self,
        strategy: str = "weighted_synthesis",
        backend: ModelBackend | None = None,
        synthesis_backend: ModelBackend | None = None,
        min_confidence: float = 0.20,
        use_constrained_prompt: bool = False,
    ) -> None:
        self.strategy = strategy
        self.backend = backend
        self.synthesis_backend = synthesis_backend
        self.min_confidence = min_confidence
        self.use_constrained_prompt = use_constrained_prompt

    async def aggregate(
        self,
        query: str,
        messages: dict[str, Message],
        backend: ModelBackend | None = None,
        governance_context: str = "",
    ) -> str:
        """Aggregate node outputs into a final answer."""
        effective_backend = (
            self.synthesis_backend or backend or self.backend
        )

        # Filter messages
        filtered = self._filter_messages(messages)

        if not filtered:
            # Fall back to best single message if all filtered
            if messages:
                best = max(messages.values(), key=lambda m: m.confidence)
                return best.content
            return "No reasoning produced."

        if self.strategy == "weighted_synthesis" and effective_backend:
            return await self._weighted_synthesis(
                query, filtered, effective_backend, governance_context
            )
        elif self.strategy == "majority_vote":
            return self._majority_vote(filtered)
        else:
            return self._confidence_weighted(filtered)

    def _filter_messages(
        self, messages: dict[str, Message]
    ) -> dict[str, Message]:
        """Filter out low-confidence and pruned agent messages."""
        filtered: dict[str, Message] = {}
        for node_id, msg in messages.items():
            # Skip low confidence
            if msg.confidence < self.min_confidence:
                logger.debug(
                    f"Filtered {node_id}: confidence {msg.confidence:.0%} < {self.min_confidence:.0%}"
                )
                continue
            # Skip observer messages
            if msg.source_node_id == "__observer__":
                continue
            filtered[node_id] = msg
        return filtered

    async def _weighted_synthesis(
        self,
        query: str,
        messages: dict[str, Message],
        backend: ModelBackend,
        governance_context: str = "",
    ) -> str:
        """Use an LLM to synthesize agent outputs."""
        # Sort by confidence (highest first)
        sorted_msgs = sorted(
            messages.values(), key=lambda m: m.confidence, reverse=True
        )

        # Build context
        parts = []
        for msg in sorted_msgs:
            parts.append(
                f"[{msg.source_node_id} | "
                f"Confidence: {msg.confidence:.0%}]\n{msg.content}"
            )

        agent_outputs = "\n\n---\n\n".join(parts)

        # Choose prompt
        if self.use_constrained_prompt:
            gov_text = ""
            if governance_context:
                gov_text = f"Governance context: {governance_context}\n"
            prompt = CONSTRAINED_AGGREGATION_PROMPT.format(
                query=query,
                governance_context=gov_text,
                filtered_outputs=agent_outputs,
            )
        else:
            prompt = AGGREGATION_PROMPT.format(
                query=query, agent_outputs=agent_outputs
            )

        return await backend.generate(prompt, max_tokens=4096, temperature=0.2)

    def _confidence_weighted(self, messages: dict[str, Message]) -> str:
        """Simple concatenation weighted by confidence."""
        sorted_msgs = sorted(
            messages.values(), key=lambda m: m.confidence, reverse=True
        )

        parts = []
        for msg in sorted_msgs:
            prefix = ""
            if msg.reasoning_type == ReasoningType.CONTRADICTION:
                prefix = "[CONFLICT] "
            parts.append(f"{prefix}{msg.content}")

        return "\n\n".join(parts) if parts else "No confident reasoning produced."

    def _majority_vote(self, messages: dict[str, Message]) -> str:
        """Return the output with highest aggregate confidence."""
        if not messages:
            return "No reasoning produced."
        best = max(messages.values(), key=lambda m: m.confidence)
        return best.content
