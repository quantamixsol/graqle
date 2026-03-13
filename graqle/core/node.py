"""CogniNode — a knowledge graph node with an embedded reasoning agent."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from graqle.core.message import Message
from graqle.core.state import NodeState
from graqle.core.types import ModelBackend, NodeStatus, ReasoningType

logger = logging.getLogger("graqle.node")


# Legacy prompt (backward compatible — used when no ontology is loaded)
NODE_REASONING_PROMPT = """You are a knowledgeable agent for: {label} ({entity_type}).

Your knowledge:
{description}

{evidence_text}

{properties_text}

Query: {query}

{context_text}

Answer the query using ALL available knowledge and evidence above. Be specific and helpful.
Cite evidence chunks by number [1], [2], etc. State your confidence (0-100%).
If you detect contradictions with neighbor messages, flag them.
IMPORTANT: If the evidence contains relevant information, USE it to answer — do not refuse."""

# Governance-constrained prompt (v2 — format-based, legacy)
CONSTRAINED_REASONING_PROMPT_V2 = """You are {label}, a {entity_type} agent in the {domain} domain.

GOVERNANCE CONSTRAINTS (you MUST respect these):
{constraint_text}

YOUR KNOWLEDGE:
{description}

RELEVANT EVIDENCE (filtered for this query):
{evidence_text}

{skills_text}

QUERY: {query}

{context_text}

INSTRUCTIONS:
- Reason within your governance constraints when applicable.
- Use your skills and evidence to provide specific, verifiable answers.
- Cite evidence by number [1], [2]. Cite article numbers where applicable.
- If you have relevant evidence, always use it to answer — do not refuse.
- Only defer if you truly have NO relevant information.
- Keep response under 100 words.

CONFIDENCE: [0-100]%"""

# Semantic governance prompt (v3 — OWL-aware, replaces format constraints)
SEMANTIC_REASONING_PROMPT = """You are {label}, a {entity_type} agent in the {domain} domain.

{semantic_governance}

YOUR KNOWLEDGE:
{description}

RELEVANT EVIDENCE (filtered for this query):
{evidence_text}

{skills_text}

QUERY: {query}

{context_text}

INSTRUCTIONS:
- Reason within your governance scope. Cite your own framework explicitly.
- Cross-references to other frameworks must be attributed.
- Use your skills and evidence to provide specific, verifiable answers with article/section numbers.
- Cite evidence by number [1], [2].
- If you have relevant evidence, always use it to answer — do not refuse.
- Only defer if you truly have NO relevant information for the query.
- State your confidence as CONFIDENCE: [0-100]%"""


@dataclass
class CogniNode:
    """A knowledge graph node with an embedded SLM agent.

    Each CogniNode wraps a KG entity and its associated model backend.
    The agent is lazily initialized — the model is only loaded when the
    node is activated as part of a reasoning subgraph.
    """

    # Identity
    id: str
    label: str
    entity_type: str = "Entity"

    # Knowledge
    properties: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    embedding: np.ndarray | None = field(default=None, repr=False)

    # Agent
    backend: ModelBackend | None = field(default=None, repr=False)
    adapter_id: str | None = None
    system_prompt: str | None = None
    max_tokens: int = 2048
    temperature: float = 0.3

    # State
    state: NodeState = field(default_factory=NodeState)
    status: NodeStatus = NodeStatus.IDLE

    # Edges (IDs only — graph owns the edge objects)
    incoming_edges: list[str] = field(default_factory=list)
    outgoing_edges: list[str] = field(default_factory=list)

    # Governance constraints (v2 — set at activation time by orchestrator)
    constraint_text: str = ""
    skills_text: str = ""
    domain: str = ""
    shacl_gate: Any = field(default=None, repr=False)
    pruned: bool = False

    # Semantic governance (v3 — OWL-aware constraints)
    semantic_gate: Any = field(default=None, repr=False)
    semantic_governance_text: str = ""

    def activate(self, backend: ModelBackend) -> None:
        """Assign a model backend and mark as activated."""
        self.backend = backend
        self.status = NodeStatus.ACTIVATED
        self.state.reset()

    def deactivate(self) -> None:
        """Unload agent, free resources."""
        self.backend = None
        self.status = NodeStatus.IDLE

    async def reason(
        self, query: str, incoming_messages: list[Message],
        embedding_fn: Any = None,
    ) -> Message:
        """Produce a reasoning output given query + incoming messages.

        This is the core reasoning step — the node uses its local knowledge
        plus messages from neighbors to produce a new message.

        If governance constraints are set (constraint_text, skills_text),
        uses the constrained prompt. Otherwise uses the legacy prompt.
        """
        if self.backend is None:
            raise RuntimeError(f"Node {self.id} has no backend assigned. Call activate() first.")

        self.status = NodeStatus.REASONING

        # Build context from incoming messages
        context_text = ""
        if incoming_messages:
            context_parts = ["Messages from neighbor agents:"]
            for msg in incoming_messages:
                context_parts.append(msg.to_prompt_context())
            context_text = "\n\n".join(context_parts)

        # Build evidence text — with optional query-based filtering (T2.2)
        evidence_text = self._build_evidence_text(query, embedding_fn)

        # Choose prompt: semantic v3 > constrained v2 > legacy
        if self.semantic_governance_text:
            prompt = SEMANTIC_REASONING_PROMPT.format(
                label=self.label,
                entity_type=self.entity_type,
                domain=self.domain or "general",
                semantic_governance=self.semantic_governance_text,
                description=self.description,
                evidence_text=evidence_text,
                skills_text=self.skills_text,
                query=query,
                context_text=context_text,
            )
        elif self.constraint_text or self.skills_text:
            prompt = CONSTRAINED_REASONING_PROMPT_V2.format(
                label=self.label,
                entity_type=self.entity_type,
                domain=self.domain or "general",
                constraint_text=self.constraint_text or "No specific constraints.",
                description=self.description,
                evidence_text=evidence_text,
                skills_text=self.skills_text,
                query=query,
                context_text=context_text,
            )
        else:
            # Legacy prompt (backward compatible)
            props_text = ""
            scalar_props = {k: v for k, v in self.properties.items()
                            if k not in ("chunks",) and not isinstance(v, (list, dict))}
            if scalar_props:
                props_lines = [f"- {k}: {v}" for k, v in scalar_props.items()]
                props_text = "Properties:\n" + "\n".join(props_lines)

            prompt = NODE_REASONING_PROMPT.format(
                label=self.label,
                entity_type=self.entity_type,
                description=self.description,
                evidence_text=evidence_text,
                properties_text=props_text,
                query=query,
                context_text=context_text,
            )

        if self.system_prompt:
            prompt = f"System: {self.system_prompt}\n\n{prompt}"

        # Generate response
        response = await self.backend.generate(
            prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )

        # Semantic SHACL gate validation (v3 — preferred)
        if self.semantic_gate is not None:
            validation = self.semantic_gate.validate(
                self.entity_type, response, query,
                node_context={"label": self.label, "domain": self.domain},
            )
            if not validation.valid:
                self.semantic_gate.record_retry()
                retry_prompt = (
                    f"{prompt}\n\n"
                    f"YOUR PREVIOUS RESPONSE HAD GOVERNANCE VIOLATIONS:\n"
                    f"{validation.to_feedback()}\n\n"
                    f"Please fix the violations and respond again."
                )
                response = await self.backend.generate(
                    retry_prompt,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
        # Legacy SHACL gate (v2 — format-based, fallback)
        elif self.shacl_gate is not None:
            validation = self.shacl_gate.validate(self.entity_type, response, query)
            if not validation.valid:
                self.shacl_gate.record_retry()
                retry_prompt = (
                    f"{prompt}\n\n"
                    f"YOUR PREVIOUS RESPONSE WAS REJECTED:\n"
                    f"{validation.to_feedback()}\n\n"
                    f"Please fix the violations and respond again."
                )
                response = await self.backend.generate(
                    retry_prompt,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )

        # Parse confidence from response (simple extraction)
        confidence = self._extract_confidence(response)

        # Detect reasoning type
        reasoning_type = self._detect_reasoning_type(response, incoming_messages)

        # Update state
        self.state.update(response, confidence)
        self.status = NodeStatus.CONVERGED

        # Create outgoing message
        return Message(
            source_node_id=self.id,
            target_node_id="__broadcast__",  # orchestrator routes
            round=self.state.current_round,
            content=response,
            reasoning_type=reasoning_type,
            confidence=confidence,
            evidence=[self.id],
            parent_messages=[m.id for m in incoming_messages],
            token_count=len(response.split()),  # approximate
        )

    def _build_evidence_text(
        self, query: str, embedding_fn: Any = None
    ) -> str:
        """Build evidence text from chunks, optionally filtered by query relevance.

        If embedding_fn is provided, selects top-3 chunks by cosine similarity
        to the query. Otherwise includes all chunks (legacy behavior).
        """
        chunks = self.properties.get("chunks", [])
        if not chunks:
            # T3: Lazy load from file_path or source_file if available
            file_path = (
                self.properties.get("file_path")
                or self.properties.get("source_file")
            )
            if file_path:
                try:
                    from pathlib import Path
                    fp = Path(file_path)
                    if fp.exists():
                        content = fp.read_text(encoding="utf-8", errors="ignore")[:6000]
                        if content.strip():
                            chunks = [{"text": content, "type": "full_file"}]
                except Exception:
                    pass
            if not chunks:
                return ""

        # Parse chunks into (text, type) pairs
        parsed = []
        for chunk in chunks:
            if isinstance(chunk, dict):
                ctype = chunk.get("type", "evidence")
                ctext = chunk.get("text", "")
            else:
                ctype = "evidence"
                ctext = str(chunk)
            if ctext:
                parsed.append((ctext, ctype))

        if not parsed:
            return ""

        # Filter by relevance if embedding function is available
        if embedding_fn is not None and len(parsed) > 3:
            try:
                query_emb = embedding_fn(query)
                scored = []
                for ctext, ctype in parsed:
                    chunk_emb = embedding_fn(ctext[:500])
                    sim = float(np.dot(query_emb, chunk_emb) / (
                        (np.linalg.norm(query_emb) * np.linalg.norm(chunk_emb)) or 1.0
                    ))
                    scored.append((sim, ctext, ctype))
                scored.sort(key=lambda x: x[0], reverse=True)
                parsed = [(ctext, ctype) for _, ctext, ctype in scored[:3]]
            except Exception:
                pass  # Fall back to all chunks

        evidence_parts = ["Supporting Evidence:"]
        for i, (ctext, ctype) in enumerate(parsed, 1):
            evidence_parts.append(f"[{i}] ({ctype}) {ctext}")
        return "\n\n".join(evidence_parts)

    def _extract_confidence(self, response: str) -> float:
        """Extract confidence percentage from response text."""
        import re

        patterns = [
            r"confidence[:\s]+(\d+)%",
            r"(\d+)%\s*confiden",
            r"confidence[:\s]+0\.(\d+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, response, re.IGNORECASE)
            if match:
                val = int(match.group(1))
                if val > 1:
                    return min(val / 100.0, 1.0)
                return val
        return 0.5  # default

    def _detect_reasoning_type(
        self, response: str, incoming: list[Message]
    ) -> ReasoningType:
        """Detect the reasoning type from response content."""
        lower = response.lower()
        if any(word in lower for word in ["contradict", "conflict", "disagree", "however"]):
            return ReasoningType.CONTRADICTION
        if any(word in lower for word in ["therefore", "combining", "synthesiz", "overall"]):
            return ReasoningType.SYNTHESIS
        if "?" in response and response.count("?") > response.count("."):
            return ReasoningType.QUESTION
        if incoming:
            return ReasoningType.SYNTHESIS
        return ReasoningType.ASSERTION

    @property
    def degree(self) -> int:
        """Total number of edges (incoming + outgoing)."""
        return len(self.incoming_edges) + len(self.outgoing_edges)

    @property
    def is_hub(self) -> bool:
        """Whether this node is a high-connectivity hub (degree > 5)."""
        return self.degree > 5
