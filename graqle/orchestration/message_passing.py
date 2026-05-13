"""Message passing protocol — the core reasoning loop of Graqle."""

# ── graqle:intelligence ──
# module: graqle.orchestration.message_passing
# risk: MEDIUM (impact radius: 5 modules)
# consumers: run_multigov_v2, run_multigov_v3, orchestrator, __init__, test_message_passing
# dependencies: __future__, asyncio, logging, typing, message
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from graqle.core.message import Message

if TYPE_CHECKING:
    from graqle.core.graph import Graqle

logger = logging.getLogger("graqle.message_passing")


class MessagePassingProtocol:
    """Synchronous round-based message passing between CogniNode agents.

    Protocol:
    Round 0: Query broadcast → each node produces initial reasoning
    Round 1..N: Neighbor exchange → each node re-reasons with neighbor context
    Final: Collect all outputs for aggregation

    This is the mechanism through which emergent reasoning occurs — insights
    that exist in NO single agent emerge from their interactions.
    """

    def __init__(
        self,
        parallel: bool = True,
        ontology_router: Any = None,
        embedding_fn: Any = None,
    ) -> None:
        self.parallel = parallel
        self.ontology_router = ontology_router  # OntologyRouter instance
        self.embedding_fn = embedding_fn  # For evidence filtering in nodes
        self._observer_feedback: dict[str, Message] | None = None

    def inject_observer_feedback(self, feedback: dict[str, Message]) -> None:
        """Inject observer feedback for next round (T4.2)."""
        self._observer_feedback = feedback

    async def run_round(
        self,
        graph: Graqle,
        query: str,
        active_node_ids: list[str],
        round_num: int,
        previous_messages: dict[str, Message] | None = None,
    ) -> dict[str, Message]:
        """Execute one round of message passing."""
        # Filter out pruned nodes
        active_ids = [
            nid for nid in active_node_ids
            if not getattr(graph.nodes.get(nid), "pruned", False)
        ]

        logger.debug(f"Round {round_num}: {len(active_ids)} active nodes")

        if round_num == 0:
            return await self._initial_round(graph, query, active_ids)

        # CR-007 Fix 4 (CR-007b): hierarchical_synthesis flag — between
        # rounds, replace per-neighbor messages with one community summary
        # message per community. Cuts dense-graph inter-node messaging from
        # O(N x neighbors) to O(N x communities). Default OFF; opt-in via
        # GraqleConfig.orchestration.hierarchical_synthesis = True.
        orch_cfg = getattr(graph, "config", None)
        orch = getattr(orch_cfg, "orchestration", None)
        if previous_messages and getattr(orch, "hierarchical_synthesis", False):
            summary_max = int(getattr(orch, "hierarchical_summary_max_chars", 1500) or 1500)
            previous_messages = self._build_community_summaries(
                graph, previous_messages, summary_max,
            )

        return await self._exchange_round(
            graph, query, active_ids, round_num, previous_messages or {}
        )

    def _build_community_summaries(
        self,
        graph: "Graqle",
        previous_messages: dict[str, Message],
        summary_max_chars: int,
    ) -> dict[str, Message]:
        """CR-007 Fix 4: collapse round-N messages into one summary per community.

        Returns a dict where each key is a synthetic community-id (e.g.
        "__community__<bucket>") and the value is a single Message whose
        ``content`` is the concatenation of that community's messages,
        truncated to ``summary_max_chars``. Nodes in ``_exchange_round`` see
        ALL community summaries via ``graph.get_neighbors`` matches only when
        the synthetic ids match — so this only fires when consumers wire it.

        Communities are derived from (in order of preference):
        1. ``node.community`` property (set by ``compute_pagerank`` /
           ``detect_communities`` Cypher analytics).
        2. ``node.entity_type`` (fallback — coarse bucketing).
        3. Single bucket "__all__" when neither is available.

        EU AI Act note: this is a SUMMARY of evidence the model has already
        seen — no governance text is dropped; the per-node audit trail in
        ``all_messages`` (kept by the orchestrator) still has every original
        message. The summary only affects what the NEXT round's nodes see.
        """
        from graqle.core.message import Message as _Msg

        # Bucket the messages
        buckets: dict[str, list[tuple[str, Message]]] = {}
        for nid, msg in previous_messages.items():
            node = graph.nodes.get(nid)
            bucket = (
                getattr(node, "community", None)
                or getattr(node, "entity_type", None)
                or "__all__"
            )
            buckets.setdefault(str(bucket), []).append((nid, msg))

        # Build one synthetic Message per bucket
        out: dict[str, Message] = {}
        for bucket, items in buckets.items():
            parts: list[str] = []
            for nid, msg in items:
                snippet = (msg.content or "")[:max(200, summary_max_chars // max(1, len(items)))]
                parts.append(f"[{nid}] {snippet}")
            joined = "\n".join(parts)
            if len(joined) > summary_max_chars:
                joined = joined[:summary_max_chars] + "\n…[community summary truncated]"
            synth_id = f"__community__{bucket}"
            # Create a minimal Message preserving the protocol contract.
            try:
                synth = _Msg.create_query_broadcast(joined, synth_id)
            except Exception:
                # Fallback: instantiate Message directly with permissive kwargs.
                synth = _Msg(
                    content=joined,
                    source_node_id=synth_id,
                    round=0,
                )
            out[synth_id] = synth

        return out

    async def _initial_round(
        self,
        graph: Graqle,
        query: str,
        active_node_ids: list[str],
    ) -> dict[str, Message]:
        """Round 0: Each node reasons independently about the query."""

        async def _node_reason(node_id: str) -> tuple[str, Message]:
            node = graph.nodes[node_id]
            query_msg = Message.create_query_broadcast(query, node_id)
            # L2 + CR-007: wire continuation + token-economics config from graph
            orch_cfg = getattr(graph, "config", None)
            orch = getattr(orch_cfg, "orchestration", None)
            _max_cont = getattr(orch, "max_continuations", 3)
            _overlap = getattr(orch, "continuation_overlap_lines", 15)
            _ev_cap = getattr(orch, "evidence_hard_ceiling", 4000)
            _pr_cap = getattr(orch, "prompt_hard_cap", 10000)
            result = await node.reason(
                query, [query_msg], embedding_fn=self.embedding_fn,
                max_continuations=_max_cont,
                continuation_overlap_lines=_overlap,
                evidence_hard_ceiling=_ev_cap,
                prompt_hard_cap=_pr_cap,
            )
            result.source_node_id = node_id
            result.round = 0
            return node_id, result

        if self.parallel:
            tasks = [_node_reason(nid) for nid in active_node_ids]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            results = []
            for nid in active_node_ids:
                results.append(await _node_reason(nid))

        output: dict[str, Message] = {}
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Node reasoning failed: {r}")
                continue
            node_id, message = r
            output[node_id] = message

        logger.debug(f"Round 0 complete: {len(output)} nodes responded")
        return output

    async def _exchange_round(
        self,
        graph: Graqle,
        query: str,
        active_node_ids: list[str],
        round_num: int,
        previous_messages: dict[str, Message],
    ) -> dict[str, Message]:
        """Round N: Exchange messages with neighbors and re-reason."""

        # CR-007: read token-economics knobs once per round (not per node).
        orch_cfg_outer = getattr(graph, "config", None)
        orch_outer = getattr(orch_cfg_outer, "orchestration", None)
        _max_cont_outer = getattr(orch_outer, "max_continuations", 3)
        _overlap_outer = getattr(orch_outer, "continuation_overlap_lines", 15)
        _ev_cap_outer = getattr(orch_outer, "evidence_hard_ceiling", 4000)
        _pr_cap_outer = getattr(orch_outer, "prompt_hard_cap", 10000)
        _top_k_outer = getattr(orch_outer, "top_k_neighbors", 8)

        async def _node_exchange(node_id: str) -> tuple[str, Message]:
            node = graph.nodes[node_id]

            # Use ontology router if available, otherwise fall back to graph neighbors
            if self.ontology_router is not None:
                neighbor_ids = self.ontology_router.get_valid_recipients(
                    graph, node_id, active_node_ids=active_node_ids
                )
            else:
                neighbor_ids = graph.get_neighbors(node_id)

            # CR-007 Fix 2: cap neighbor messages to top-K to bound prompt
            # blow-up in dense graphs (hub nodes can have 30-50 neighbors,
            # each contributing ~700 chars of round-0 reply). Ranking is
            # best-effort: prefer activation_score on the candidate node,
            # then insertion order. Active edges (source in active set) get
            # priority via the active_node_ids intersection done implicitly
            # by `if nid in previous_messages` below.
            candidate_ids = [
                nid for nid in neighbor_ids if nid in previous_messages
            ]
            if _top_k_outer and len(candidate_ids) > _top_k_outer:
                def _rank_key(nid: str) -> float:
                    n = graph.nodes.get(nid)
                    return -float(getattr(n, "activation_score", 0.0) or 0.0)
                candidate_ids = sorted(candidate_ids, key=_rank_key)[:_top_k_outer]
            incoming = [previous_messages[nid] for nid in candidate_ids]

            # Prepend observer feedback if available (T4.2)
            if self._observer_feedback and node_id in self._observer_feedback:
                incoming.insert(0, self._observer_feedback[node_id])

            # Re-reason with neighbor context + evidence + prompt ceilings
            result = await node.reason(
                query, incoming, embedding_fn=self.embedding_fn,
                max_continuations=_max_cont_outer,
                continuation_overlap_lines=_overlap_outer,
                evidence_hard_ceiling=_ev_cap_outer,
                prompt_hard_cap=_pr_cap_outer,
            )
            result.source_node_id = node_id
            result.round = round_num
            return node_id, result

        if self.parallel:
            tasks = [_node_exchange(nid) for nid in active_node_ids]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            results = []
            for nid in active_node_ids:
                results.append(await _node_exchange(nid))

        output: dict[str, Message] = {}
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Node exchange failed: {r}")
                continue
            node_id, message = r
            output[node_id] = message

        # Clear observer feedback after consumption
        self._observer_feedback = None

        logger.debug(
            f"Round {round_num} complete: {len(output)} nodes responded"
        )
        return output
