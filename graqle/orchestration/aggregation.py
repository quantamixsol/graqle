# ──────────────────────────────────────────────────────────────────
# PATENT NOTICE — Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Applications EP26162901.8 and EP26166054.2, owned by
# Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: legal@quantamix.io
# ──────────────────────────────────────────────────────────────────

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
    ) -> tuple[str, dict]:
        """Aggregate node outputs into a final answer.

        Returns:
            (answer_text, truncation_info) where truncation_info has keys:
            synthesis_truncated (bool), synthesis_stop_reason (str).
            No instance state — safe for async/concurrent use.
        """
        return await self._aggregate_inner(
            query, messages, backend, governance_context
        )

    async def _aggregate_inner(
        self,
        query: str,
        messages: dict[str, Message],
        backend: ModelBackend | None = None,
        governance_context: str = "",
    ) -> tuple[str, dict]:
        """Inner aggregation logic. Returns (answer, truncation_info).

        v0.51.3: truncation_info may also carry an optional 'candidates' key
        containing top-N near-tied agent outputs, used by downstream layers
        to emit the ambiguous_options field on graq_reason responses
        (see VS Code extension Ambiguity Pause UX).
        """
        _no_trunc = {"synthesis_truncated": False, "synthesis_stop_reason": ""}
        effective_backend = (
            self.synthesis_backend or backend or self.backend
        )

        # Filter messages
        filtered = self._filter_messages(messages)

        # v0.51.3 — compute ambiguity candidates BEFORE dispatching to a
        # strategy so they're attached regardless of which synthesis path runs.
        candidates = self._compute_ambiguous_options(filtered)

        if not filtered:
            # Fall back to best single message if all filtered
            if messages:
                best = max(messages.values(), key=lambda m: m.confidence)
                return best.content, _no_trunc
            return "No reasoning produced.", _no_trunc

        if self.strategy == "weighted_synthesis" and effective_backend:
            answer, trunc_info = await self._weighted_synthesis(
                query, filtered, effective_backend, governance_context
            )
        elif self.strategy == "majority_vote":
            answer, trunc_info = self._majority_vote(filtered), dict(_no_trunc)
        else:
            answer, trunc_info = self._confidence_weighted(filtered), dict(_no_trunc)

        # v0.51.3 — attach candidates (empty list when trigger doesn't fire).
        # Downstream orchestrator reads trunc_info["candidates"]; absent or
        # empty means no ambiguous_options will be emitted.
        if candidates:
            trunc_info["candidates"] = candidates
        return answer, trunc_info

    def _compute_ambiguous_options(
        self, filtered: dict[str, Message]
    ) -> list[dict]:
        """v0.51.3 — compute ambiguity candidates per VS Code extension contract.

        Emits a list of 2-5 near-tied candidate options only when ALL hold:
          - >= 2 filtered messages
          - top1.confidence - top2.confidence <= 0.10 (near-tie)
          - top1.confidence >= 0.50 (noise floor)
          - >= 2 messages have confidence >= 0.50

        Each option dict carries option_id, label (1-6 words, <=60 chars),
        rationale (one sentence, <=200 chars), confidence (0.0-1.0), and
        evidence_refs (list of source_node_ids + msg metadata refs).

        Returns [] when ambiguity is not detected — downstream callers should
        omit the ambiguous_options field entirely (per handoff contract).
        """
        if len(filtered) < 2:
            return []
        sorted_msgs = sorted(
            filtered.values(), key=lambda m: m.confidence, reverse=True
        )
        top_n = sorted_msgs[:5]
        if top_n[0].confidence - top_n[1].confidence > 0.10:
            return []
        if top_n[0].confidence < 0.50:
            return []
        # Need at least 2 options >= 0.50 to avoid noise triggering a pause
        if sum(1 for m in top_n if m.confidence >= 0.50) < 2:
            return []

        seen_labels: set[str] = set()
        options: list[dict] = []
        for i, msg in enumerate(top_n):
            content = (msg.content or "").strip()
            # Rationale: first sentence, trimmed to 200 chars.
            first_sentence = content.split(". ", 1)[0].split("\n", 1)[0].strip()
            if not first_sentence.endswith("."):
                first_sentence = first_sentence.rstrip(".") + "."
            rationale = first_sentence[:200]
            # Label: first 6 words of the content, capped at 60 chars.
            words = content.replace("\n", " ").split()
            label_raw = " ".join(words[:6]).strip().rstrip(",.;:") or f"Option {i + 1}"
            label = label_raw[:60]
            # Enforce label uniqueness — append node id suffix if collision.
            if label in seen_labels:
                label = (label[:54] + " [" + str(i + 1) + "]")[:60]
            seen_labels.add(label)
            evidence_refs: list[str] = []
            if getattr(msg, "source_node_id", None):
                evidence_refs.append(f"node:{msg.source_node_id}")
            # Message.metadata may carry refs from the reasoning step.
            msg_meta = getattr(msg, "metadata", None) or {}
            for ref in msg_meta.get("evidence_refs", []) or []:
                if isinstance(ref, str):
                    evidence_refs.append(ref)
            options.append({
                "option_id": f"opt_{i + 1}",
                "label": label,
                "rationale": rationale,
                "confidence": round(float(msg.confidence), 4),
                "evidence_refs": evidence_refs,
            })
        # Contract guarantees 2 <= len <= 5
        return options if 2 <= len(options) <= 5 else []

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

        # SDK-HF-02 (v0.47.2): synthesis was hitting stop_reason=max_tokens
        # and silently returning empty/partial text. Use the shared
        # generate_with_continuation helper from core/node.py to recover
        # truncated synthesis the same way per-node responses recover.
        # max_tokens stays 4096 — raising to 8192 is a separate tuning
        # decision (see lesson_20260407T065640).
        from graqle.core.node import generate_with_continuation

        final_text, helper_meta = await generate_with_continuation(
            backend, prompt, max_tokens=4096, temperature=0.2,
        )
        _truncated = helper_meta["still_truncated"]
        _stop_reason = helper_meta["stop_reason"]
        if helper_meta["was_continued"]:
            logger.info(
                " Synthesis recovered from truncation via %d continuation(s) (still_truncated=%s)",
                helper_meta["continuation_count"], _truncated,
            )
        if helper_meta["continuation_error"]:
            logger.warning(
                " Synthesis continuation hit an error mid-loop — "
                "returning fail-open accumulated text",
            )
        if _truncated:
            logger.warning(
                " Synthesis response truncated (stop_reason=%s)",
                _stop_reason,
            )
        trunc_info = {
            "synthesis_truncated": _truncated,
            "synthesis_stop_reason": _stop_reason,
        }
        return final_text, trunc_info

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
