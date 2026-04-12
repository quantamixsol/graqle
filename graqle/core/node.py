"""CogniNode — a knowledge graph node with an embedded reasoning agent."""

# ── graqle:intelligence ──
# module: graqle.core.node
# risk: HIGH (impact radius: 11 modules)
# consumers: __init__, graph, __init__, conftest, test_content_aware_pcst +6 more
# dependencies: __future__, logging, dataclasses, typing, numpy +3 more
# constraints: none
# ── /graqle:intelligence ──

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


# ── Layer 2: Continuation loop helpers ──────────────


def _build_continuation_prompt(overlap_anchor: str) -> str:
    """Build a prompt that asks the LLM to continue from where it left off.

    B3 security: overlap_anchor is sanitized to prevent prompt injection
    from malicious/adversarial LLM output being re-injected as instructions.
    """
    # Sanitize: strip any delimiter markers that could escape the quoted block
    safe_anchor = overlap_anchor.replace("=== END PREVIOUS ===", "[END_MARKER]")
    safe_anchor = safe_anchor.replace("=== LAST LINES", "[LAST_MARKER]")
    # Truncate to prevent oversized anchors from dominating the prompt
    if len(safe_anchor) > 3000:
        safe_anchor = safe_anchor[-3000:]
    return (
        "Your previous response was truncated. "
        "Continue EXACTLY where you left off.\n\n"
        "=== LAST LINES OF YOUR PREVIOUS RESPONSE ===\n"
        f"{safe_anchor}\n"
        "=== END PREVIOUS ===\n\n"
        "Continue from this exact point. "
        "Do not repeat any content shown above. "
        "Do not add preamble or summary."
    )


def _extract_overlap_anchor(content: str, n_lines: int = 15) -> str:
    """Extract the last N lines of content as an overlap anchor."""
    if not content or not content.strip():
        return ""
    lines = [ln for ln in content.rstrip().splitlines() if ln.strip()]
    if len(lines) >= n_lines:
        return "\n".join(lines[-n_lines:])
    return "\n".join(lines) if lines else ""


def _deduplicate_seam(
    previous: str,
    continuation: str,
    overlap_lines: int = 15,
) -> str:
    """Remove duplicated content at the junction of previous and continuation.

    Uses longest-suffix-of-previous matching longest-prefix-of-continuation
    at line granularity.
    """
    prev_lines = previous.rstrip().splitlines()
    cont_lines = continuation.strip().splitlines()

    if not cont_lines:
        return previous

    # Find the longest suffix of prev_lines that matches a prefix of cont_lines
    max_check = min(overlap_lines, len(prev_lines), len(cont_lines))
    best_overlap = 0

    for overlap in range(1, max_check + 1):
        if prev_lines[-overlap:] == cont_lines[:overlap]:
            best_overlap = overlap

    # Merge: keep all of previous, append only the non-overlapping continuation
    if best_overlap > 0:
        merged_continuation = "\n".join(cont_lines[best_overlap:])
    else:
        merged_continuation = continuation.strip()

    if not merged_continuation:
        return previous

    return previous.rstrip() + "\n" + merged_continuation


# ── SDK-HF-02 (v0.47.2): reusable continuation helper ──────────────────────
#
# Extracts the truncation-recovery loop into a callable that any caller
# (synthesis aggregator, future tool layers, etc.) can use against any
# BaseBackend without re-implementing the contract. CogniNode.reason() keeps
# its own inline copy of the loop (untouched in this hotfix to eliminate
# metadata regression risk on the per-node path).
#
# Exception contract:
#   - The FIRST backend.generate() call is OUTSIDE the try/except, so its
#     exceptions propagate unchanged to the caller (matches reason()).
#   - Only continuation-round exceptions are caught and surface as
#     metadata["continuation_error"] = True with the accumulated response
#     returned (fail-open semantics).
#
# Metadata contract (every exit path):
#   clean (no truncation):
#     continuation_count=0, was_continued=False, still_truncated=False,
#     stop_reason="", continuation_error=False
#   recovery (truncated → continued → finished):
#     count=N, was_continued=True, still_truncated=False, error=False
#   empty-anchor abort (initial truncation but anchor extraction yielded ""):
#     count=0, was_continued=False, still_truncated=True, error=False
#   zero-progress abort (continuation produced no new content):
#     count=N, was_continued=True, still_truncated=<last>, error=False
#   max_continuations exhaustion:
#     count=max, was_continued=True, still_truncated=True, error=False
#   mid-loop exception (fail-open):
#     count=N, was_continued=True, still_truncated=True, error=True


def _normalize_response(raw: Any) -> tuple[str, bool, str]:
    """Normalize a backend.generate() return value to (text, truncated, stop_reason).

    Handles three shapes:
      - GenerateResult type): pulls .text/.truncated/.stop_reason
      - raw str: text=raw, truncated=False, stop_reason="" (str backends
        cannot report truncation)
      - anything else: defensive str(raw) fallback with a warning log so
        backend contract regressions stay visible

    Defensive guards:
      - If a structured response has .text == None, coerce to ""
      - If a structured response has .truncated == None, coerce to False
      - If a structured response has .stop_reason == None, coerce to ""
    """
    if hasattr(raw, "text") and hasattr(raw, "truncated"):
        text_val = getattr(raw, "text", None)
        if text_val is None:
            text_val = ""
        return (
            str(text_val),
            bool(getattr(raw, "truncated", False)),
            str(getattr(raw, "stop_reason", "") or ""),
        )
    if isinstance(raw, str):
        return (raw, False, "")
    logger.warning(
        " backend returned unexpected response shape %s — coercing via str()",
        type(raw).__name__,
    )
    return (str(raw), False, "")


async def generate_with_continuation(
    backend: ModelBackend,
    prompt: str,
    *,
    max_tokens: int = 4096,
    temperature: float = 0.2,
    stop: list[str] | None = None,
    max_continuations: int = 3,
    overlap_lines: int = 15,
) -> tuple[str, dict]:
    """Call backend.generate, then continue if truncated, until clean.

    Used by orchestration/aggregation.py:_weighted_synthesis to fix
    SDK-HF-02 (synthesis truncation regression). Re-uses the existing helpers (_extract_overlap_anchor, _build_continuation_prompt,
    _deduplicate_seam) so the continuation contract is identical to the
    one in CogniNode.reason().

    Args:
        backend: any ModelBackend (BaseBackend subclass or duck-typed)
        prompt: initial prompt
        max_tokens: per-call generation budget (4096 default — synthesis
            keeps this; raising to 8192 is a separate tuning decision per
            lesson_20260407T065640)
        temperature: passed through to backend.generate
        stop: passed through to backend.generate
        max_continuations: hard cap on continuation rounds (default 3)
        overlap_lines: anchor size for the continuation prompt

    Returns:
        (final_text, metadata) where metadata is a dict with five keys:
        continuation_count, was_continued, still_truncated, stop_reason,
        continuation_error. See the metadata contract block above for the
        exact value of each key on every exit path.

    Raises:
        Whatever backend.generate raises on the FIRST call. In-loop
        continuation exceptions are caught and surface via
        metadata["continuation_error"] = True (fail-open).
    """
    # First call — exceptions propagate unchanged.
    raw_first = await backend.generate(
        prompt, max_tokens=max_tokens, temperature=temperature, stop=stop,
    )
    response, is_truncated, stop_reason = _normalize_response(raw_first)

    continuation_count = 0
    continuation_error = False

    while is_truncated and continuation_count < max_continuations:
        overlap_anchor = _extract_overlap_anchor(response, n_lines=overlap_lines)
        if not overlap_anchor:
            logger.warning(
                " generate_with_continuation empty overlap anchor — aborting"
            )
            break

        cont_prompt = _build_continuation_prompt(overlap_anchor)
        try:
            raw_cont = await backend.generate(
                cont_prompt, max_tokens=max_tokens,
                temperature=temperature, stop=stop,
            )
            cont_text, cont_truncated, cont_stop = _normalize_response(raw_cont)
            if not cont_text.strip():
                logger.warning(
                    " generate_with_continuation empty continuation — aborting"
                )
                break
            new_response = _deduplicate_seam(
                response, cont_text, overlap_lines=overlap_lines,
            )
            if new_response.strip() == response.strip():
                logger.warning(
                    " generate_with_continuation zero-progress — aborting"
                )
                break
            response = new_response
            is_truncated = cont_truncated
            stop_reason = cont_stop
            continuation_count += 1
        except Exception as exc:  # noqa: BLE001 — fail-open is intentional
            logger.warning(
                " generate_with_continuation continuation %d failed: %s — fail-open",
                continuation_count + 1, exc,
            )
            continuation_error = True
            continuation_count += 1
            break

    metadata = {
        "continuation_count": continuation_count,
        "was_continued": continuation_count > 0,
        "still_truncated": is_truncated,
        "stop_reason": stop_reason,
        "continuation_error": continuation_error,
    }
    return response, metadata


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
        max_continuations: int = 3,
        continuation_overlap_lines: int = 15,
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
        raw_result = await self.backend.generate(
            prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )

        # B1: Extract truncation metadata BEFORE str conversion
        _is_truncated = bool(getattr(raw_result, "truncated", False))
        _stop_reason = getattr(raw_result, "stop_reason", "") or ""

        # Convert to str — re.search(), .lower(), etc. require it
        response = str(raw_result)

        # ── Layer 2: Continuation loop for truncated responses ──
        _continuation_count = 0
        _continuation_error = False
        while _is_truncated and _continuation_count < max_continuations:
            _continuation_count += 1
            overlap_anchor = _extract_overlap_anchor(
                response, n_lines=continuation_overlap_lines,
            )
            if not overlap_anchor:
                logger.warning(
                    " Node %s empty overlap anchor — aborting continuation",
                    self.id,
                )
                break
            cont_prompt = _build_continuation_prompt(overlap_anchor)
            try:
                cont_result = await self.backend.generate(
                    cont_prompt,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
                cont_text = str(cont_result) if cont_result else ""
                if not cont_text.strip():
                    logger.warning(
                        " Node %s continuation %d returned empty — aborting",
                        self.id, _continuation_count,
                    )
                    break
                _is_truncated = bool(getattr(cont_result, "truncated", False))
                _stop_reason = getattr(cont_result, "stop_reason", "") or ""
                new_response = _deduplicate_seam(
                    response, cont_text,
                    overlap_lines=continuation_overlap_lines,
                )
                # Guard zero-progress: content identity check (not length)
                if new_response.strip() == response.strip():
                    logger.warning(
                        " Node %s continuation %d produced no new content — aborting",
                        self.id, _continuation_count,
                    )
                    break
                response = new_response
                logger.debug(
                    " Node %s continuation %d/%d (still_truncated=%s, len=%d)",
                    self.id, _continuation_count, max_continuations,
                    _is_truncated, len(response),
                )
            except Exception as e:
                logger.warning(
                    " Node %s continuation %d failed: %s — using accumulated response",
                    self.id, _continuation_count, e,
                )
                _continuation_error = True
                break  # Fail open: return what we have so far

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
                retry_result = await self.backend.generate(
                    retry_prompt,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
                _is_truncated = bool(getattr(retry_result, "truncated", False))
                _stop_reason = getattr(retry_result, "stop_reason", "") or ""
                response = str(retry_result)
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
                retry_result = await self.backend.generate(
                    retry_prompt,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
                _is_truncated = bool(getattr(retry_result, "truncated", False))
                _stop_reason = getattr(retry_result, "stop_reason", "") or ""
                response = str(retry_result)

        # Parse confidence from response (simple extraction)
        confidence = self._extract_confidence(response)

        # Detect reasoning type
        reasoning_type = self._detect_reasoning_type(response, incoming_messages)

        # Update state
        self.state.update(response, confidence)
        self.status = NodeStatus.CONVERGED

        # B1+L2: Surface truncation + continuation metadata in Message
        _meta: dict = {
            "still_truncated": _is_truncated,
            "continuation_error": _continuation_error,
        }
        if _continuation_count > 0:
            _meta["continuation_count"] = _continuation_count
            _meta["was_continued"] = True
        if _is_truncated:
            _meta["truncated"] = True
            _meta["stop_reason"] = _stop_reason
            _meta["confidence_unreliable"] = True
            logger.warning(
                " Node %s response still truncated after %d continuations (stop_reason=%s)",
                self.id, _continuation_count, _stop_reason,
            )

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
            metadata=_meta,
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
