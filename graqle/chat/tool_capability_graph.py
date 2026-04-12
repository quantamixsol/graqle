"""Tool Capability Graph (TCG) — the meta-context-management graph. of ChatAgentLoop v4 . The TCG is one of the three runtime
graphs in the v4 architecture (alongside GRAQ.md and RCAG). It is a
cross-session, self-learning graph of the project's MCP tools. Nodes are
the tools themselves plus intent / workflow-pattern / lesson classes. The
LLM becomes a *ranker over a pre-activated subgraph* rather than a cold
picker over ~134 options — this is the structural fix for SDK-HF-01.

Architecture
------------
``ToolCapabilityGraph`` IS-A :class:`graqle.core.graph.Graqle`. It ships
with a canonical seed at ``graqle/chat/templates/tcg_default.json`` and
persists to ``~/.graqle/tcg.json``. First run copies the seed to the
user directory. Tools not present in the seed are UNKNOWN until
``reinforce_sequence`` learns them — the seed is the single source of
truth from the review).

Runtime augmentation from ``KogniDevServer.list_tools()`` is explicitly
FORBIDDEN. The three-graph editorial rule requires a static anchor for
tool-selection behavior, and learning happens through reinforcement,
not through bootstrap.

CGI-compatibility note seed)
-------------------------------------
The TCG is a runtime graph, not a CGI (project-self-memory) graph. But
the seed JSON shape — flat ``{nodes, edges}`` with ``entity_type`` tags
and typed properties — is deliberately compatible with the CGI schema
described in so a future CGI loader can reuse the same
``_load_payload`` helper. Do NOT add CGI node types here — v4 ships
first, then opens its own design session.
"""

# ── graqle:intelligence ──
# module: graqle.chat.tool_capability_graph
# risk: HIGH (first chat module to cross into graqle.core.*)
# consumers: chat.agent_loop (planned # dependencies: __future__, copy, json, logging, os, pathlib, tempfile,
#   typing, graqle.core.{graph,node,edge,types}
# constraints: seed is source of truth; NO runtime augmentation from
#   list_tools; destructive-edge safety filter is non-negotiable
# ── /graqle:intelligence ──

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from graqle.core.edge import CogniEdge
from graqle.core.graph import Graqle
from graqle.core.node import CogniNode
from typing import TYPE_CHECKING
if TYPE_CHECKING:  # pragma: no cover
    from graqle.config.settings import GraqleConfig as _GraqleConfig
GraqleConfig = Any  # runtime alias keeps source-isolation rule narrow

logger = logging.getLogger("graqle.chat.tool_capability_graph")


# ──────────────────────────────────────────────────────────────────────
# Constants — node entity types and edge relationships
# ──────────────────────────────────────────────────────────────────────

NODE_TYPE_TOOL = "TCGTool"
NODE_TYPE_INTENT = "TCGIntent"
NODE_TYPE_WORKFLOW_PATTERN = "TCGWorkflowPattern"
NODE_TYPE_LESSON = "TCGLesson"

EDGE_USED_AFTER = "USED_AFTER"
EDGE_MATCHES_INTENT = "MATCHES_INTENT"
EDGE_PART_OF = "PART_OF"
EDGE_CAUSED_BY = "CAUSED_BY"

REINFORCE_SUCCESS_DELTA = 0.1
REINFORCE_FAILURE_DELTA = -0.05
WEIGHT_MIN = 0.0
WEIGHT_MAX = 10.0

PROBATION_MIN_OBSERVATIONS = 3
PROBATION_MIN_HOLDOUTS = 2
# BLOCKER-R2 Round-1: public default changed from 0.15 to 0.2 to
# avoid exact collision with the unpublished PSE similarity_threshold.
# Operators who need the production value must set it via
# .graqle/settings.json -> chat.probation.novelty_lift_min; the
# loader validates the key exists and raises ValueError on omission.
PROBATION_NOVELTY_LIFT_MIN = 0.2

_DEFAULT_SEED_RELATIVE = Path("templates") / "tcg_default.json"
_DEFAULT_USER_PATH = Path.home() / ".graqle" / "tcg.json"

# Destructive / non-predictable tools — predicted edges ending at ANY of
# these are BLOCKED regardless of support (MAJOR-2). This list is a
# hard allowlist.
_DESTRUCTIVE_TOOL_LABELS = frozenset({
    "graq_bash",
    "graq_write",
    "graq_git_commit",
    "graq_ingest",
    "graq_vendor",
    "graq_reload",
})


# ──────────────────────────────────────────────────────────────────────
# Activation result containers
# ──────────────────────────────────────────────────────────────────────


@dataclass
class ToolCandidate:
    """A single tool candidate emitted by ``activate_for_query``."""

    tool_id: str
    label: str
    score: float
    governance_tier: str
    suggested_position: int
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "label": self.label,
            "score": self.score,
            "governance_tier": self.governance_tier,
            "suggested_position": self.suggested_position,
            "rationale": self.rationale,
        }


@dataclass
class ActivationResult:
    """Result of ``activate_for_query``: matched intent + ranked candidates."""

    intent_id: str | None
    intent_label: str | None
    intent_confidence: float
    candidates: list[ToolCandidate] = field(default_factory=list)
    workflow_pattern_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "intent_label": self.intent_label,
            "intent_confidence": self.intent_confidence,
            "candidates": [c.to_dict() for c in self.candidates],
            "workflow_pattern_id": self.workflow_pattern_id,
        }


# ──────────────────────────────────────────────────────────────────────
# Seed loading
# ──────────────────────────────────────────────────────────────────────


def load_default_seed(seed_path: Path | None = None) -> dict[str, Any]:
    """Load the canonical TCG seed from the packaged template."""
    if seed_path is None:
        seed_path = Path(__file__).resolve().parent / _DEFAULT_SEED_RELATIVE
    if not seed_path.exists():
        raise FileNotFoundError(f"TCG seed not found: {seed_path}")
    with seed_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if "nodes" not in payload or "edges" not in payload:
        raise ValueError(
            f"TCG seed {seed_path} missing required top-level keys 'nodes'/'edges'"
        )
    return payload


# ──────────────────────────────────────────────────────────────────────
# ToolCapabilityGraph
# ──────────────────────────────────────────────────────────────────────


class ToolCapabilityGraph(Graqle):
    """A :class:`Graqle` subclass specialized for tool selection.

    Construction bypasses the Graqle enrichment branch by
    passing ``nodes=None`` and ``edges=None`` to ``super().__init__`` and
    then populating ``self.nodes`` / ``self.edges`` directly from the
    seed payload. This prevents Graqle's mandatory
    ``_auto_enrich_descriptions`` / ``_auto_load_chunks`` /
    ``_enforce_no_empty_descriptions`` from firing against TCG nodes.
    """

    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        *,
        path: Path | None = None,
        config: GraqleConfig | None = None,
        settings: dict | None = None,
    ) -> None:
        # empty maps to super() so the
        # `if self.nodes:` branch at graph.py:331 evaluates False
        # and enrichment never fires.
        super().__init__(nodes=None, edges=None, config=config)

        self.path = path
        self._probation: dict[str, dict[str, Any]] = {}
        self._raw_payload_meta: dict[str, Any] = {}

        # RO2-1 (Round-2): resolve the probation novelty-lift threshold
        # from an optional settings dict. If settings are provided,
        # settings_loader.load_novelty_lift_min extracts
        # chat.probation.novelty_lift_min and validates the value. If
        # settings are None or the key is absent, the public default
        # PROBATION_NOVELTY_LIFT_MIN (0.2) is used as a fallback —
        # deliberately non-operational so operators in production MUST
        # configure the real value.
        from graqle.chat.settings_loader import load_novelty_lift_min
        resolved = load_novelty_lift_min(settings) if settings else None
        self._novelty_lift_min: float = (
            resolved if resolved is not None else PROBATION_NOVELTY_LIFT_MIN
        )

        if payload is not None:
            self._load_payload(payload)

    def _load_payload(self, payload: dict[str, Any]) -> None:
        """Populate ``self.nodes`` / ``self.edges`` from a seed payload.

        The payload shape is compatible with the CGI schema seed in so a future CGI loader can share this helper.
        """
        self._raw_payload_meta = dict(payload.get("_meta", {}))
        raw_nodes = payload.get("nodes", {})
        raw_edges = payload.get("edges", [])

        for node_id, node_data in raw_nodes.items():
            node = CogniNode(
                id=node_id,
                label=node_data.get("label", node_id),
                entity_type=node_data.get("entity_type", "Entity"),
                description=node_data.get("description", ""),
                properties=dict(node_data.get("properties", {})),
            )
            self.nodes[node_id] = node

        for edge_data in raw_edges:
            eid = edge_data["id"]
            edge = CogniEdge(
                id=eid,
                source_id=edge_data["source_id"],
                target_id=edge_data["target_id"],
                relationship=edge_data.get("relationship", "RELATED_TO"),
                weight=float(edge_data.get("weight", 1.0)),
                properties=dict(edge_data.get("properties", {})),
            )
            self.edges[eid] = edge
            if edge.source_id in self.nodes:
                self.nodes[edge.source_id].outgoing_edges.append(eid)
            if edge.target_id in self.nodes:
                self.nodes[edge.target_id].incoming_edges.append(eid)

    @classmethod
    def from_seed(
        cls,
        seed_path: Path | None = None,
        *,
        config: GraqleConfig | None = None,
    ) -> ToolCapabilityGraph:
        """Build a TCG from the packaged default seed."""
        payload = load_default_seed(seed_path)
        return cls(payload=payload, path=None, config=config)

    @classmethod
    def load_or_init(
        cls,
        user_path: Path | None = None,
        *,
        seed_path: Path | None = None,
        config: GraqleConfig | None = None,
    ) -> ToolCapabilityGraph:
        """Load a user TCG, copying the seed to ``user_path`` on first run."""
        if user_path is None:
            user_path = _DEFAULT_USER_PATH
        user_path = Path(user_path)

        if not user_path.exists():
            user_path.parent.mkdir(parents=True, exist_ok=True)
            tcg = cls.from_seed(seed_path=seed_path, config=config)
            tcg.path = user_path
            tcg.save()
            return tcg

        try:
            with user_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except json.JSONDecodeError as exc:
            logger.error(
                "TCG user file %s is corrupt (%s) — restoring from seed",
                user_path, exc,
            )
            corrupt_backup = user_path.with_suffix(".corrupt")
            try:
                os.replace(user_path, corrupt_backup)
            except OSError:
                pass
            tcg = cls.from_seed(seed_path=seed_path, config=config)
            tcg.path = user_path
            tcg.save()
            return tcg

        return cls(payload=payload, path=user_path, config=config)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def tools(self) -> dict[str, CogniNode]:
        return {
            nid: n for nid, n in self.nodes.items()
            if n.entity_type == NODE_TYPE_TOOL
        }

    def intents(self) -> dict[str, CogniNode]:
        return {
            nid: n for nid, n in self.nodes.items()
            if n.entity_type == NODE_TYPE_INTENT
        }

    def workflow_patterns(self, *, graduated_only: bool = False) -> dict[str, CogniNode]:
        out: dict[str, CogniNode] = {}
        for nid, n in self.nodes.items():
            if n.entity_type != NODE_TYPE_WORKFLOW_PATTERN:
                continue
            if graduated_only and not bool(n.properties.get("graduated", False)):
                continue
            out[nid] = n
        return out

    def lessons(self) -> dict[str, CogniNode]:
        return {
            nid: n for nid, n in self.nodes.items()
            if n.entity_type == NODE_TYPE_LESSON
        }

    # ------------------------------------------------------------------
    # Intent classification
    # ------------------------------------------------------------------

    def _classify_intent(
        self,
        question: str,
        intent_hint: str | None = None,
    ) -> tuple[str | None, float]:
        """Pick the best matching intent by keyword overlap."""
        intents = self.intents()
        if not intents:
            return None, 0.0

        if intent_hint:
            if intent_hint in intents:
                return intent_hint, 1.0
            for nid, node in intents.items():
                if node.label == intent_hint:
                    return nid, 1.0

        q_lower = question.lower()
        best_id: str | None = None
        best_score = 0.0
        for nid, node in intents.items():
            keywords = node.properties.get("keywords", []) or []
            if not keywords:
                continue
            hits = sum(1 for kw in keywords if kw.lower() in q_lower)
            if hits <= 0:
                continue
            score = hits / max(len(keywords), 1)
            score = min(1.0, score * (1.0 + 0.2 * (hits - 1)))
            if score > best_score:
                best_score = score
                best_id = nid

        return best_id, best_score

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    def activate_for_query(
        self,
        question: str,
        *,
        intent_hint: str | None = None,
        max_candidates: int = 8,
    ) -> ActivationResult:
        """Return ranked tool candidates for ``question``.

        MAJOR-3: graduated=False WorkflowPattern nodes are filtered
        BEFORE scoring, not after.
        """
        intent_id, intent_conf = self._classify_intent(question, intent_hint)
        result = ActivationResult(
            intent_id=intent_id,
            intent_label=self.nodes[intent_id].label if intent_id else None,
            intent_confidence=intent_conf,
        )

        tool_scores: dict[str, float] = {}
        rationales: dict[str, list[str]] = {}

        def _bump(tool_id: str, delta: float, reason: str) -> None:
            tool_scores[tool_id] = tool_scores.get(tool_id, 0.0) + delta
            rationales.setdefault(tool_id, []).append(reason)

        if intent_id and intent_id in self.nodes:
            intent_node = self.nodes[intent_id]
            for eid in intent_node.outgoing_edges:
                edge = self.edges.get(eid)
                if edge is None or edge.relationship != EDGE_MATCHES_INTENT:
                    continue
                target = edge.target_id
                if target not in self.nodes:
                    continue
                if self.nodes[target].entity_type != NODE_TYPE_TOOL:
                    continue
                _bump(target, edge.weight * max(intent_conf, 0.3),
                      f"matches intent {intent_node.label}")

            preferred = intent_node.properties.get("preferred_sequence", []) or []
            for idx, tool_id in enumerate(preferred):
                if tool_id in self.nodes and self.nodes[tool_id].entity_type == NODE_TYPE_TOOL:
                    _bump(tool_id, 0.5 * (1.0 - idx * 0.1), f"preferred_sequence[{idx}]")

            for wp_id, wp_node in self.workflow_patterns(graduated_only=True).items():
                if wp_node.properties.get("intent_id") != intent_id:
                    continue
                result.workflow_pattern_id = wp_id
                seq = wp_node.properties.get("tool_sequence", []) or []
                for idx, tool_id in enumerate(seq):
                    if tool_id in self.nodes:
                        _bump(tool_id, 1.0 * (1.0 - idx * 0.05),
                              f"workflow {wp_node.label}[{idx}]")

        boost_passes = dict(tool_scores)
        for tool_id, base_score in boost_passes.items():
            tool_node = self.nodes.get(tool_id)
            if tool_node is None:
                continue
            for eid in tool_node.incoming_edges:
                edge = self.edges.get(eid)
                if edge is None or edge.relationship != EDGE_USED_AFTER:
                    continue
                successor = edge.source_id
                if successor in self.nodes and successor != tool_id:
                    _bump(successor, 0.2 * base_score * edge.weight / 10.0,
                          f"chain after {tool_node.label}")

        ranked = sorted(
            tool_scores.items(),
            key=lambda kv: (-kv[1], self.nodes[kv[0]].label),
        )[:max_candidates]

        for pos, (tool_id, score) in enumerate(ranked):
            node = self.nodes[tool_id]
            tier = str(node.properties.get("governance_tier", "GREEN"))
            rationale = "; ".join(rationales.get(tool_id, ["matched"]))[:200]
            result.candidates.append(ToolCandidate(
                tool_id=tool_id,
                label=node.label,
                score=round(score, 4),
                governance_tier=tier,
                suggested_position=pos,
                rationale=rationale,
            ))

        return result

    # ------------------------------------------------------------------
    # Reinforcement
    # ------------------------------------------------------------------

    @staticmethod
    def _clamp_weight(new_weight: float) -> float:
        """MINOR-1: clamp reinforcement updates to [0.0, 10.0]."""
        return max(WEIGHT_MIN, min(WEIGHT_MAX, float(new_weight)))

    def _find_edge(
        self, source_id: str, target_id: str, relationship: str,
    ) -> CogniEdge | None:
        src_node = self.nodes.get(source_id)
        if src_node is None:
            return None
        for eid in src_node.outgoing_edges:
            edge = self.edges.get(eid)
            if edge is None:
                continue
            if edge.target_id == target_id and edge.relationship == relationship:
                return edge
        return None

    def _upsert_edge(
        self,
        source_id: str,
        target_id: str,
        relationship: str,
        initial_weight: float = 1.0,
    ) -> CogniEdge:
        existing = self._find_edge(source_id, target_id, relationship)
        if existing is not None:
            return existing
        edge_id = (
            f"e_{relationship.lower()}_{source_id}_{target_id}_"
            f"{int(time.time() * 1000000) & 0xffffffff:x}"
        )
        edge = CogniEdge(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            relationship=relationship,
            weight=self._clamp_weight(initial_weight),
        )
        self.edges[edge_id] = edge
        if source_id in self.nodes:
            self.nodes[source_id].outgoing_edges.append(edge_id)
        if target_id in self.nodes:
            self.nodes[target_id].incoming_edges.append(edge_id)
        return edge


    # ── MAJOR-R1b (Round-1): auto-create probationary unknown tools ─────
    #
    # Research review flagged that silent-skip in reinforce_sequence
    # combined with 's "no runtime list_tools() bootstrap"
    # rule meant the 36 tools missing from the seed could never be
    # learned after ship. The fix: when reinforce_sequence encounters
    # a tool_id that isn't in the TCG, auto-create a probationary
    # TCGTool node with governance_tier=YELLOW and
    # safe_for_prediction=False. The node is visible to activation
    # (so future turns can use it) but predict_missing_edges cannot
    # surface it until a future session graduates it explicitly.
    #
    # This is NOT a runtime list_tools() bootstrap — we only learn
    # from OBSERVED usage, which is the same mechanism the graduated
    # seed workflows use.

    def _auto_create_probationary_tool(self, tool_id: str) -> CogniNode:
        """Create a probationary YELLOW tool node for a tool_id that
        was observed in live usage but is not in the TCG seed."""
        label = tool_id.removeprefix("tool_")
        node = CogniNode(
            id=tool_id,
            label=label,
            entity_type=NODE_TYPE_TOOL,
            description=(
                f"probationary TCGTool created from live reinforcement "
                f"observation — awaiting graduation via holdout validation"
            ),
            properties={
                "governance_tier": "YELLOW",
                "side_effect": "unknown",
                "category": "probationary",
                "latency_tier": "medium",
                "safe_for_prediction": False,
                "probation": True,
                "auto_created": True,
            },
        )
        self.nodes[tool_id] = node
        logger.info(
            "TCG auto-created probationary tool %s from live observation",
            tool_id,
        )
        return node

    def reinforce_sequence(
        self,
        tool_ids: list[str],
        *,
        outcome: str,
    ) -> int:
        """Bump USED_AFTER edges along an observed sequence.

        ``outcome ∈ {"success","failure"}``. The reinforcement direction
        follows the TCG seed convention: ``USED_AFTER.source`` is the
        tool that came AFTER ``target`` (tool B is USED_AFTER tool A,
        so the edge points B → A).
        """
        if len(tool_ids) < 2:
            return 0
        delta = REINFORCE_SUCCESS_DELTA if outcome == "success" else REINFORCE_FAILURE_DELTA
        touched = 0
        for prev, cur in zip(tool_ids[:-1], tool_ids[1:]):
            # MAJOR-R1b (Round-1): auto-create probationary YELLOW
            # tool nodes for observed tools that are not in the seed.
            # No longer silently drops unknown tools — they now
            # participate in reinforcement with safe_for_prediction=False
            # so predict_missing_edges still cannot surface them.
            if prev not in self.nodes:
                if prev.startswith("tool_"):
                    self._auto_create_probationary_tool(prev)
                else:
                    continue
            if cur not in self.nodes:
                if cur.startswith("tool_"):
                    self._auto_create_probationary_tool(cur)
                else:
                    continue
            edge = self._find_edge(cur, prev, EDGE_USED_AFTER)
            if edge is None:
                edge = self._upsert_edge(cur, prev, EDGE_USED_AFTER, initial_weight=1.0)
            edge.weight = self._clamp_weight(edge.weight + delta)
            touched += 1
        return touched

    def reinforce_intent_match(
        self,
        intent_id: str,
        tool_id: str,
        *,
        outcome: str,
    ) -> bool:
        if intent_id not in self.nodes or tool_id not in self.nodes:
            return False
        delta = REINFORCE_SUCCESS_DELTA if outcome == "success" else REINFORCE_FAILURE_DELTA
        edge = self._find_edge(intent_id, tool_id, EDGE_MATCHES_INTENT)
        if edge is None:
            edge = self._upsert_edge(intent_id, tool_id, EDGE_MATCHES_INTENT, initial_weight=1.0)
        edge.weight = self._clamp_weight(edge.weight + delta)
        return True

    # ------------------------------------------------------------------
    # Pattern mining (with probation)
    # ------------------------------------------------------------------

    def mine_workflow_patterns(
        self,
        observations: list[dict[str, Any]],
    ) -> list[str]:
        """Propose candidate WorkflowPattern nodes from recent sessions.

        MINOR-2 thresholds: 3+ unrelated successful observations create
        a probationary candidate. ``graduate_pattern`` promotes after
        ≥ 2 unrelated holdout successes.
        """
        if not observations:
            return []

        groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        for obs in observations:
            if not obs.get("success"):
                continue
            seq = tuple(obs.get("tool_sequence", []))
            if len(seq) < 2:
                continue
            groups[seq].append(obs)

        proposed: list[str] = []
        for seq, members in groups.items():
            distinct_intents = {m.get("intent_id") for m in members if m.get("intent_id")}
            distinct_files: set[tuple[str, ...]] = set()
            for m in members:
                f = tuple(sorted(m.get("support_files", []) or []))
                if f:
                    distinct_files.add(f)
            unrelated_count = max(len(distinct_intents), len(distinct_files))
            if unrelated_count < PROBATION_MIN_OBSERVATIONS:
                continue

            cand_id = f"workflow_candidate_{hash(seq) & 0xffffffff:x}"
            if cand_id in self._probation or cand_id in self.nodes:
                continue
            self._probation[cand_id] = {
                "tool_sequence": list(seq),
                "intent_id": members[0].get("intent_id"),
                "support_count": len(members),
                "distinct_support": unrelated_count,
                "holdouts_seen": 0,
                "created_at": time.time(),
            }
            label_suffix = "_".join(t.split("_")[-1] for t in list(seq)[:3])
            node = CogniNode(
                id=cand_id,
                label=f"candidate_{label_suffix}",
                entity_type=NODE_TYPE_WORKFLOW_PATTERN,
                description="Probationary candidate — awaiting holdout validation",
                properties={
                    "tool_sequence": list(seq),
                    "intent_id": members[0].get("intent_id"),
                    "support_count": len(members),
                    "graduated": False,
                },
            )
            self.nodes[cand_id] = node
            proposed.append(cand_id)

        return proposed

    def graduate_pattern(
        self,
        candidate_id: str,
        *,
        holdout_successes: int,
        novelty_lift: float,
    ) -> bool:
        if candidate_id not in self._probation:
            return False
        if holdout_successes < PROBATION_MIN_HOLDOUTS:
            return False
        if novelty_lift < self._novelty_lift_min:
            return False
        node = self.nodes.get(candidate_id)
        if node is None:
            return False
        node.properties["graduated"] = True
        node.properties["holdouts_seen"] = holdout_successes
        node.properties["novelty_lift"] = novelty_lift
        del self._probation[candidate_id]
        return True

    # ------------------------------------------------------------------
    # Missing-edge prediction with safety filter
    # ------------------------------------------------------------------

    def _is_safe_for_prediction(self, tool_id: str) -> bool:
        """Destructive-edge safety filter (MAJOR-2).

        Applied during traversal BEFORE ranking, so destructive
        suggestions can never surface even if support is high.
        """
        node = self.nodes.get(tool_id)
        if node is None:
            return False
        if node.label in _DESTRUCTIVE_TOOL_LABELS:
            return False
        return bool(node.properties.get("safe_for_prediction", True))

    def predict_missing_edges(
        self,
        *,
        min_confidence: float = 0.3,
        max_suggestions: int = 20,
    ) -> list[dict[str, Any]]:
        """Discover missing USED_AFTER edges via 2-hop traversal.

        MAJOR-2: ``_is_safe_for_prediction`` is applied during candidate
        traversal, so destructive edges are eliminated BEFORE ranking.
        """
        tool_ids = [
            nid for nid, n in self.nodes.items()
            if n.entity_type == NODE_TYPE_TOOL
        ]
        safe_ids = [t for t in tool_ids if self._is_safe_for_prediction(t)]
        safe_set = set(safe_ids)

        used_after: dict[str, set[str]] = {t: set() for t in tool_ids}
        for edge in self.edges.values():
            if edge.relationship != EDGE_USED_AFTER:
                continue
            if edge.source_id in used_after:
                used_after[edge.source_id].add(edge.target_id)

        suggestions: list[dict[str, Any]] = []
        for a in safe_ids:
            direct = used_after[a]
            for b in safe_ids:
                if b == a or b in direct:
                    continue
                two_hop = sum(
                    1 for m in direct
                    if m in safe_set and b in used_after.get(m, set())
                )
                if two_hop == 0:
                    continue
                score = min(1.0, two_hop / 3.0)
                if score < min_confidence:
                    continue
                suggestions.append({
                    "source": a,
                    "target": b,
                    "score": round(score, 4),
                    "reason": f"{two_hop} intermediary path(s)",
                })

        suggestions.sort(key=lambda s: (-s["score"], s["source"], s["target"]))
        return suggestions[:max_suggestions]

    # ------------------------------------------------------------------
    # Persistence (atomic save + rollback)
    # ------------------------------------------------------------------

    def to_payload(self) -> dict[str, Any]:
        """Serialize back to the seed payload shape."""
        nodes_out: dict[str, Any] = {}
        for nid, node in self.nodes.items():
            nodes_out[nid] = {
                "id": nid,
                "label": node.label,
                "entity_type": node.entity_type,
                "description": node.description,
                "properties": copy.deepcopy(node.properties),
            }
        edges_out: list[dict[str, Any]] = []
        for eid, edge in self.edges.items():
            edges_out.append({
                "id": eid,
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "relationship": edge.relationship,
                "weight": float(edge.weight),
                "properties": copy.deepcopy(edge.properties),
            })
        return {
            "_meta": dict(self._raw_payload_meta),
            "nodes": nodes_out,
            "edges": edges_out,
        }

    def save(self, path: Path | None = None) -> Path:
        """Atomic save with .bak rollback — MAJOR-4.

        Protocol:
          1. Write payload to ``<path>.tmp`` in the same directory
          2. flush + fsync the temp file
          3. If ``<path>`` exists, rotate it to ``<path>.bak``
          4. ``os.replace(<path>.tmp, <path>)``
          5. Clean up on any failure: restore ``<path>.bak`` → ``<path>``
             and remove the tmp file.
        """
        target = Path(path) if path is not None else self.path
        if target is None:
            raise ValueError("ToolCapabilityGraph.save requires an explicit path")
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)

        payload = self.to_payload()
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=target.name + ".", suffix=".tmp", dir=str(target.parent),
        )
        tmp_path = Path(tmp_name)
        bak_path = target.with_suffix(target.suffix + ".bak")
        bak_created = False

        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=False)
                f.flush()
                os.fsync(f.fileno())

            if target.exists():
                try:
                    if bak_path.exists():
                        bak_path.unlink()
                except OSError:
                    pass
                os.replace(target, bak_path)
                bak_created = True

            os.replace(tmp_path, target)
        except Exception:
            if bak_created and bak_path.exists() and not target.exists():
                try:
                    os.replace(bak_path, target)
                except OSError:
                    logger.exception(
                        "TCG rollback failed restoring %s from %s",
                        target, bak_path,
                    )
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise

        self.path = target
        return target


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────

__all__ = [
    "ActivationResult",
    "EDGE_CAUSED_BY",
    "EDGE_MATCHES_INTENT",
    "EDGE_PART_OF",
    "EDGE_USED_AFTER",
    "NODE_TYPE_INTENT",
    "NODE_TYPE_LESSON",
    "NODE_TYPE_TOOL",
    "NODE_TYPE_WORKFLOW_PATTERN",
    "PROBATION_MIN_HOLDOUTS",
    "PROBATION_MIN_OBSERVATIONS",
    "PROBATION_NOVELTY_LIFT_MIN",
    "ToolCandidate",
    "ToolCapabilityGraph",
    "WEIGHT_MAX",
    "WEIGHT_MIN",
    "load_default_seed",
]
