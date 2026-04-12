"""Runtime Chat Action Graph (RCAG) — per-session ephemeral execution memory. of ChatAgentLoop v4 . RCAG is the third runtime graph
in the v4 architecture (alongside GRAQ.md and TCG). It replaces a
linear chat history with query-time activation over typed action
nodes, so context size stays constant regardless of turn count.

Six node types
--------------

  - ``ToolCall``        — an LLM-decided tool invocation (tool name,
                          parameters, tool_call_id, parent reasoning id)
  - ``ToolResult``      — the structured result of a ``ToolCall``
                          (status, payload summary, error, latency_ms)
  - ``AssistantReasoning`` — a chunk of LLM reasoning between tool calls
                             (text, embedding, partial flag)
  - ``GovernanceCheckpoint`` — a governance gate decision
                               (tier, decision, reason, related_tool_call)
  - ``CheckRound``      — one round of concern-check
                          (proposer_text, adversary_text, arbiter_verdict)
  - ``ErrorNode``       — a tool / backend error (kind, message, recovered)

Plus ``AttachmentContext`` (single-turn scope) for screenshots / PDFs /
docs that the LLM should see as a citation, never as a raw blob.

Activation
----------
``activate_for_turn(query)`` runs the existing ChunkScorer-style
``_activate_subgraph`` from ``graqle.core.graph.Graqle`` (the PCST →
chunk-scorer pattern at ``mcp_dev_server.py:4378-4385``) and returns a
small set of relevant prior nodes. The query is augmented with:

  - the latest user message
  - any partial LLM reasoning so far
  - a rolling 3-turn summary kept in ``self._rolling_summary``

so the activation is grounded in the current intent + recent dialog
shape, not just the literal token string.

CGI-compatibility note seed)
-------------------------------------
RCAG is per-session and ephemeral. CGI is cross-session and project-
scoped. They MUST stay in different graphs. RCAG node ids carry a
``rcag_`` prefix so a future CGI exporter can deterministically tell
runtime nodes from project-self-memory nodes during migration.
"""

# ── graqle:intelligence ──
# module: graqle.chat.rcag
# risk: HIGH (subclasses Graqle, hot path on every turn)
# consumers: chat.agent_loop (planned # dependencies: __future__, copy, hashlib, json, time, dataclasses,
#   typing, graqle.core.{graph,node,edge}
# constraints: ephemeral only — never persist; never bleed into TCG/CGI
# ── /graqle:intelligence ──

from __future__ import annotations

import copy
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from graqle.core.edge import CogniEdge
from graqle.core.graph import Graqle
from graqle.core.node import CogniNode

# Type-only import keeps the chat package source-clean of graqle.config
from typing import TYPE_CHECKING
if TYPE_CHECKING:  # pragma: no cover
    from graqle.config.settings import GraqleConfig as _GraqleConfig
GraqleConfig = Any  # runtime alias

logger = logging.getLogger("graqle.chat.rcag")


# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

NODE_TYPE_TOOL_CALL = "RCAGToolCall"
NODE_TYPE_TOOL_RESULT = "RCAGToolResult"
NODE_TYPE_ASSISTANT_REASONING = "RCAGAssistantReasoning"
NODE_TYPE_GOVERNANCE_CHECKPOINT = "RCAGGovernanceCheckpoint"
NODE_TYPE_CHECK_ROUND = "RCAGCheckRound"
# Backward-compat alias for pre-Round1 callers — remove in v0.51.0.
NODE_TYPE_DEBATE_ROUND = NODE_TYPE_CHECK_ROUND
NODE_TYPE_ERROR = "RCAGErrorNode"
NODE_TYPE_ATTACHMENT = "RCAGAttachmentContext"

EDGE_RESULT_OF = "RESULT_OF"
EDGE_PRECEDED_BY = "PRECEDED_BY"
EDGE_REASONING_LED_TO = "REASONING_LED_TO"
EDGE_GOVERNANCE_FOR = "GOVERNANCE_FOR"
EDGE_RECOVERED_FROM = "RECOVERED_FROM"
EDGE_DEBATED_FOR = "DEBATED_FOR"
EDGE_ATTACHED_TO = "ATTACHED_TO"

ROLLING_SUMMARY_TURNS = 3


# ──────────────────────────────────────────────────────────────────────
# Runtime Chat Action Graph
# ──────────────────────────────────────────────────────────────────────


@dataclass
class TurnSummary:
    """A short summary of one prior turn for activation augmentation."""

    turn_id: str
    user_message: str
    final_text: str
    tool_count: int

    def to_text(self) -> str:
        msg = self.user_message[:120]
        return f"[{self.turn_id}] user='{msg}' tools={self.tool_count}"


class RuntimeChatActionGraph(Graqle):
    """A per-session :class:`Graqle` subclass for ephemeral chat memory.

    Construction follows the same enrichment-bypass pattern as
    :class:`graqle.chat.tool_capability_graph.ToolCapabilityGraph`:
    pass ``nodes=None``/``edges=None`` to ``super().__init__`` so the
    ``if self.nodes:`` enrichment branch never fires. RCAG nodes are
    transient runtime artifacts, not domain entities — enrichment is
    semantically wrong here.

    The graph is intentionally NOT persisted. ``TurnLedger`` handles the immutable historical transcript at the file level;
    RCAG itself dies with the session.
    """

    def __init__(
        self,
        session_id: str,
        *,
        config: GraqleConfig | None = None,
    ) -> None:
        super().__init__(nodes=None, edges=None, config=config)
        self.session_id = session_id
        self._turn_counter = 0
        self._call_counter = 0
        self._rolling_summary: list[TurnSummary] = []
        self._current_turn_id: str | None = None

    # ------------------------------------------------------------------
    # ID helpers
    # ------------------------------------------------------------------

    def _next_id(self, kind: str) -> str:
        """Generate a deterministic-ish per-session id with kind prefix."""
        self._call_counter += 1
        salt = f"{self.session_id}:{kind}:{self._call_counter}:{time.time_ns()}"
        digest = hashlib.sha1(salt.encode("utf-8")).hexdigest()[:10]
        return f"rcag_{kind}_{digest}"

    def begin_turn(self, user_message: str) -> str:
        """Mark the start of a new turn. Returns the turn id."""
        self._turn_counter += 1
        self._current_turn_id = f"rcag_turn_{self._turn_counter}_{self.session_id[:8]}"
        # Record the user message as an assistant-reasoning seed node so
        # the activation query is grounded in the most recent intent.
        self.add_assistant_reasoning(
            text=f"USER: {user_message}",
            partial=False,
            tag="user_message",
        )
        return self._current_turn_id

    def end_turn(self, final_text: str, tool_count: int) -> None:
        """Close the current turn and update the rolling summary."""
        if self._current_turn_id is None:
            return
        # Find the most recent user_message tag for this turn (best effort).
        user_msg = ""
        for nid in reversed(list(self.nodes)):
            node = self.nodes[nid]
            if node.entity_type == NODE_TYPE_ASSISTANT_REASONING and \
                    node.properties.get("tag") == "user_message":
                user_msg = node.description.replace("USER: ", "", 1)
                break
        summary = TurnSummary(
            turn_id=self._current_turn_id,
            user_message=user_msg,
            final_text=final_text[:200],
            tool_count=tool_count,
        )
        self._rolling_summary.append(summary)
        if len(self._rolling_summary) > ROLLING_SUMMARY_TURNS:
            self._rolling_summary.pop(0)
        self._current_turn_id = None

    # ------------------------------------------------------------------
    # Node creators
    # ------------------------------------------------------------------

    def _add_node(
        self,
        kind: str,
        entity_type: str,
        label: str,
        description: str,
        properties: dict[str, Any] | None = None,
    ) -> CogniNode:
        node_id = self._next_id(kind)
        node = CogniNode(
            id=node_id,
            label=label,
            entity_type=entity_type,
            description=description,
            properties=dict(properties or {}),
        )
        node.properties["session_id"] = self.session_id
        node.properties["turn_id"] = self._current_turn_id or ""
        node.properties["created_at"] = time.time()
        self.nodes[node_id] = node
        return node

    def _add_edge(
        self,
        source_id: str,
        target_id: str,
        relationship: str,
        weight: float = 1.0,
    ) -> CogniEdge:
        edge_id = f"e_{relationship.lower()}_{source_id}_{target_id}_{int(time.time_ns()) & 0xffffffff:x}"
        edge = CogniEdge(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            relationship=relationship,
            weight=weight,
        )
        self.edges[edge_id] = edge
        if source_id in self.nodes:
            self.nodes[source_id].outgoing_edges.append(edge_id)
        if target_id in self.nodes:
            self.nodes[target_id].incoming_edges.append(edge_id)
        return edge

    def add_tool_call(
        self,
        tool_name: str,
        params: dict[str, Any],
        *,
        tool_call_id: str | None = None,
        parent_reasoning_id: str | None = None,
    ) -> str:
        """Add a ToolCall node and link it to its parent reasoning."""
        node = self._add_node(
            kind="call",
            entity_type=NODE_TYPE_TOOL_CALL,
            label=tool_name,
            description=f"call to {tool_name}",
            properties={
                "tool_name": tool_name,
                "params": copy.deepcopy(params),
                "tool_call_id": tool_call_id or "",
            },
        )
        if parent_reasoning_id and parent_reasoning_id in self.nodes:
            self._add_edge(node.id, parent_reasoning_id, EDGE_REASONING_LED_TO)
        return node.id

    def add_tool_result(
        self,
        tool_call_id: str,
        *,
        status: str,
        payload_summary: str,
        latency_ms: float = 0.0,
        error: str | None = None,
    ) -> str:
        """Add a ToolResult node and link RESULT_OF its tool call."""
        node = self._add_node(
            kind="result",
            entity_type=NODE_TYPE_TOOL_RESULT,
            label=f"result:{status}",
            description=payload_summary[:500],
            properties={
                "status": status,
                "latency_ms": latency_ms,
                "error": error or "",
            },
        )
        if tool_call_id in self.nodes:
            self._add_edge(node.id, tool_call_id, EDGE_RESULT_OF)
        return node.id

    def add_assistant_reasoning(
        self,
        text: str,
        *,
        partial: bool = False,
        tag: str = "",
    ) -> str:
        node = self._add_node(
            kind="reason",
            entity_type=NODE_TYPE_ASSISTANT_REASONING,
            label=tag or "reasoning",
            description=text[:1000],
            properties={"partial": partial, "tag": tag, "full_text": text},
        )
        return node.id

    def add_governance_checkpoint(
        self,
        tool_call_id: str,
        *,
        tier: str,
        decision: str,
        reason: str,
    ) -> str:
        node = self._add_node(
            kind="gov",
            entity_type=NODE_TYPE_GOVERNANCE_CHECKPOINT,
            label=f"{tier}:{decision}",
            description=reason[:500],
            properties={
                "tier": tier,
                "decision": decision,
                "reason": reason,
            },
        )
        if tool_call_id in self.nodes:
            self._add_edge(node.id, tool_call_id, EDGE_GOVERNANCE_FOR)
        return node.id

    def add_debate_round(
        self,
        *,
        proposer_text: str,
        adversary_text: str,
        arbiter_verdict: str,
        related_tool_call_id: str | None = None,
    ) -> str:
        node = self._add_node(
            kind="debate",
            entity_type=NODE_TYPE_DEBATE_ROUND,
            label=f"arbiter:{arbiter_verdict}",
            description=f"PROP: {proposer_text[:200]} | ADV: {adversary_text[:200]}",
            properties={
                "proposer_text": proposer_text,
                "adversary_text": adversary_text,
                "arbiter_verdict": arbiter_verdict,
            },
        )
        if related_tool_call_id and related_tool_call_id in self.nodes:
            self._add_edge(node.id, related_tool_call_id, EDGE_DEBATED_FOR)
        return node.id

    def add_error(
        self,
        *,
        kind: str,
        message: str,
        related_tool_call_id: str | None = None,
        recovered: bool = False,
    ) -> str:
        node = self._add_node(
            kind="error",
            entity_type=NODE_TYPE_ERROR,
            label=f"error:{kind}",
            description=message[:500],
            properties={
                "kind": kind,
                "message": message,
                "recovered": recovered,
            },
        )
        if related_tool_call_id and related_tool_call_id in self.nodes:
            self._add_edge(node.id, related_tool_call_id, EDGE_RECOVERED_FROM)
        return node.id

    def add_attachment(
        self,
        *,
        kind: str,
        citation: str,
        bytes_size: int = 0,
    ) -> str:
        """Add an AttachmentContext node — single-turn scope.

        Raw blobs stay external to the graph. The LLM sees only the
        citation summary the upload pipeline produces.
        """
        node = self._add_node(
            kind="att",
            entity_type=NODE_TYPE_ATTACHMENT,
            label=f"attachment:{kind}",
            description=citation[:500],
            properties={
                "kind": kind,
                "bytes": bytes_size,
                "single_turn": True,
            },
        )
        return node.id

    # ------------------------------------------------------------------
    # Activation — query-time relevance retrieval
    # ------------------------------------------------------------------

    def augment_query(self, query: str, partial_reasoning: str = "") -> str:
        """Build the activation query: user message + partial reasoning
        + rolling summary. Format is intentionally compact so embeddings
        stay near the user's literal intent.
        """
        parts: list[str] = [query]
        if partial_reasoning:
            parts.append(f"reasoning_so_far: {partial_reasoning[:300]}")
        if self._rolling_summary:
            summary_text = " | ".join(s.to_text() for s in self._rolling_summary)
            parts.append(f"recent: {summary_text[:400]}")
        return "\n".join(parts)

    def activate_for_turn(
        self,
        query: str,
        *,
        partial_reasoning: str = "",
        max_nodes: int = 8,
    ) -> list[CogniNode]:
        """Return up to ``max_nodes`` relevant prior nodes for the query.

        v4 will eventually call into ``Graqle._activate_subgraph(query,
        strategy='chunk')`` (the ChunkScorer pattern at
        ``mcp_dev_server.py:4378-4385``). For we ship a
        deterministic local fallback that scores nodes by token-overlap
        with the augmented query so the unit tests are independent of
        the embedding pipeline. The hot path is wired through
        ``augment_query`` so when the ChunkScorer integration lands, the
        only change is the scoring function.
        """
        if not self.nodes:
            return []
        augmented = self.augment_query(query, partial_reasoning).lower()
        query_tokens = set(_tokenize(augmented))
        if not query_tokens:
            return list(self.nodes.values())[:max_nodes]

        scored: list[tuple[float, CogniNode]] = []
        for node in self.nodes.values():
            haystack = (
                f"{node.label} {node.description} "
                f"{node.properties.get('full_text', '')}"
            ).lower()
            node_tokens = set(_tokenize(haystack))
            if not node_tokens:
                continue
            # Jaccard similarity for deterministic ordering.
            inter = len(query_tokens & node_tokens)
            if inter == 0:
                continue
            union = len(query_tokens | node_tokens)
            score = inter / union if union else 0.0
            # Recency bonus for nodes from the current turn.
            if node.properties.get("turn_id") == self._current_turn_id:
                score += 0.05
            scored.append((score, node))

        scored.sort(key=lambda kv: (-kv[0], kv[1].id))
        return [node for _, node in scored[:max_nodes]]

    # ------------------------------------------------------------------
    # Filtered views
    # ------------------------------------------------------------------

    def tool_calls(self) -> list[CogniNode]:
        return [n for n in self.nodes.values() if n.entity_type == NODE_TYPE_TOOL_CALL]

    def errors(self) -> list[CogniNode]:
        return [n for n in self.nodes.values() if n.entity_type == NODE_TYPE_ERROR]

    def reasoning_chunks(self) -> list[CogniNode]:
        return [
            n for n in self.nodes.values()
            if n.entity_type == NODE_TYPE_ASSISTANT_REASONING
        ]


def _tokenize(text: str) -> list[str]:
    """Cheap word-boundary tokenizer for the local activation fallback."""
    out: list[str] = []
    buf: list[str] = []
    for ch in text:
        if ch.isalnum() or ch in {"_"}:
            buf.append(ch)
        else:
            if buf:
                tok = "".join(buf)
                if len(tok) > 1:
                    out.append(tok)
                buf.clear()
    if buf:
        tok = "".join(buf)
        if len(tok) > 1:
            out.append(tok)
    return out


__all__ = [
    "EDGE_ATTACHED_TO",
    "EDGE_DEBATED_FOR",
    "EDGE_GOVERNANCE_FOR",
    "EDGE_PRECEDED_BY",
    "EDGE_REASONING_LED_TO",
    "EDGE_RECOVERED_FROM",
    "EDGE_RESULT_OF",
    "NODE_TYPE_ASSISTANT_REASONING",
    "NODE_TYPE_ATTACHMENT",
    "NODE_TYPE_DEBATE_ROUND",
    "NODE_TYPE_ERROR",
    "NODE_TYPE_GOVERNANCE_CHECKPOINT",
    "NODE_TYPE_TOOL_CALL",
    "NODE_TYPE_TOOL_RESULT",
    "ROLLING_SUMMARY_TURNS",
    "RuntimeChatActionGraph",
    "TurnSummary",
]
