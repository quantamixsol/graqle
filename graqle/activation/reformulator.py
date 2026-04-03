"""Query Reformulator — context-aware query enhancement before PCST activation.

ADR-104: When GraQle runs inside an AI tool (Claude Code, Cursor, Codex),
the tool already has rich conversation history and project context. The
reformulator leverages this context to produce a clearer, more precise query
that yields better PCST node activation and higher-quality reasoning.

Architecture:
    1. Auto-detect: Is GraQle running inside an AI tool? (env vars)
    2. If yes: reformulate using the chat context (zero extra model calls —
       the AI tool does the reformulation before calling GraQle)
    3. If no: optionally use a lightweight LLM call to clarify the query
    4. Pass-through: if disabled or detection fails, raw query flows through

The reformulator is NOT a mandatory layer — it's an enhancer. If it fails
for any reason, the original query is used unchanged (fail-open).
"""

# ── graqle:intelligence ──
# module: graqle.activation.reformulator
# risk: MEDIUM (impact radius: 2 modules)
# consumers: __init__, test_reformulator
# dependencies: __future__, logging, os, re, dataclasses +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from graqle.backends.base import BaseBackend

logger = logging.getLogger("graqle.activation.reformulator")

# Environment variables set by AI tools when they invoke subprocesses
_AI_TOOL_ENV_SIGNATURES = {
    "claude_code": [
        "CLAUDE_CODE",           # Claude Code sets this
        "CLAUDE_CODE_VERSION",   # Claude Code version marker
        "CLAUDE_PROJECT_DIR",    # Claude Code project context
    ],
    "cursor": [
        "CURSOR_SESSION_ID",     # Cursor IDE session
        "CURSOR_TRACE_ID",       # Cursor trace context
    ],
    "codex": [
        "OPENAI_CODEX",          # Codex CLI marker
        "CODEX_SESSION",         # Codex session
    ],
    "windsurf": [
        "WINDSURF_SESSION",      # Windsurf/Codeium
    ],
    "continue": [
        "CONTINUE_SESSION_ID",   # Continue.dev
    ],
}

# Minimum query length below which reformulation is skipped (too short = likely clear)
_MIN_REFORMULATE_LENGTH = 10

# Maximum context entries to include in reformulation prompt
_MAX_CONTEXT_ENTRIES = 10

# Maximum reformulated query length (chars) — prevent runaway expansion
_MAX_REFORMULATED_LENGTH = 500


@dataclass
class Attachment:
    """A file or screenshot attached to the query.

    When users paste screenshots, upload files, or reference images in their
    AI tool, those attachments carry crucial context that a text-only query
    misses. The reformulator extracts textual descriptions from attachments
    and weaves them into the reformulated query.

    Attributes:
        type: "screenshot", "image", "file", "code_snippet", "error_log",
              "diagram", "pdf", "unknown"
        description: AI-generated textual description of the attachment
                     (e.g., "Screenshot showing a 500 error in the auth Lambda logs")
        filename: Original filename if available
        content_summary: Extracted text/code from the attachment (truncated)
        mime_type: MIME type if known (e.g., "image/png", "text/plain")
    """

    type: str = "unknown"
    description: str = ""
    filename: str = ""
    content_summary: str = ""
    mime_type: str = ""


@dataclass
class ReformulationContext:
    """Chat history and project context passed from the AI tool.

    When GraQle is invoked from Claude Code / Cursor / Codex, the AI tool
    can attach conversation context that helps reformulate vague queries.

    Attributes:
        chat_history: Recent conversation turns [(role, message), ...]
        project_summary: Brief description of the project/codebase
        current_file: File the user is currently editing (if known)
        active_symbols: Recently referenced functions/classes/variables
        tool_name: Which AI tool is providing the context
        attachments: Screenshots, files, or other media the user attached.
                     The AI tool should pre-describe these (vision/OCR) before
                     passing to GraQle — we only use the text descriptions.
    """

    chat_history: list[tuple[str, str]] = field(default_factory=list)
    project_summary: str = ""
    current_file: str = ""
    active_symbols: list[str] = field(default_factory=list)
    tool_name: str = ""
    attachments: list[Attachment] = field(default_factory=list)


@dataclass
class ReformulationResult:
    """Result of query reformulation.

    Attributes:
        original_query: The raw query as received
        reformulated_query: The enhanced query (may be same as original)
        was_reformulated: Whether reformulation actually changed the query
        context_source: Where the context came from ("ai_tool", "llm", "none")
        confidence: How confident we are in the reformulation (0.0-1.0)
    """

    original_query: str
    reformulated_query: str
    was_reformulated: bool
    context_source: str = "none"
    confidence: float = 1.0


class QueryReformulator:
    """Context-aware query reformulator for GraQle.

    The reformulator enhances raw user queries with contextual clarity before
    they reach the PCST activation layer. It operates in three modes:

    1. **AI Tool Mode (auto):** When running inside Claude Code / Cursor / Codex,
       the AI tool provides chat context via `ReformulationContext`. The
       reformulator uses this to disambiguate pronouns, expand abbreviations,
       and ground domain terms — with ZERO extra model calls.

    2. **LLM Mode (configured):** When running standalone with a backend
       configured, the reformulator makes a single cheap LLM call to
       interpret and clarify the query.

    3. **Pass-through Mode:** When disabled or no context is available,
       the original query flows through unchanged.

    Usage (AI tool integration):
        reformulator = QueryReformulator(mode="auto")
        ctx = ReformulationContext(
            chat_history=[("user", "I'm looking at the auth service"),
                          ("assistant", "The auth service uses JWT...")],
            current_file="src/services/auth.ts",
        )
        result = reformulator.reformulate("what does this do?", context=ctx)
        # result.reformulated_query = "What does the auth service (src/services/auth.ts) do, specifically the JWT authentication logic?"

    Usage (standalone SDK):
        reformulator = QueryReformulator(mode="llm", backend=my_backend)
        result = await reformulator.areformulate("fix the upload bug")
        # result.reformulated_query = "fix the upload bug"  (no context -> pass-through)
    """

    def __init__(
        self,
        *,
        mode: str = "auto",
        backend: BaseBackend | None = None,
        enabled: bool = True,
        graph_summary: str = "",
    ) -> None:
        """Initialize the query reformulator.

        Args:
            mode: "auto" (detect AI tool), "ai_tool" (force AI tool mode),
                  "llm" (use backend for reformulation), "off" (disabled)
            backend: Model backend for LLM mode reformulation
            enabled: Master switch — False disables all reformulation
            graph_summary: Brief description of the knowledge graph contents
                          (helps LLM mode produce better reformulations)
        """
        self._mode = mode
        self._backend = backend
        self._enabled = enabled
        self._graph_summary = graph_summary
        self._detected_tool: str | None = None

        if mode == "auto":
            self._detected_tool = self._detect_ai_tool()

    # ── Public API ──────────────────────────────────────────────

    def reformulate(
        self,
        query: str,
        *,
        context: ReformulationContext | None = None,
    ) -> ReformulationResult:
        """Synchronous reformulation (for AI tool mode — no model call needed).

        For LLM mode, use areformulate() instead.
        """
        if not self._should_reformulate(query):
            return ReformulationResult(
                original_query=query,
                reformulated_query=query,
                was_reformulated=False,
                context_source="none",
            )

        effective_mode = self._resolve_mode()

        if effective_mode == "ai_tool" and context is not None:
            return self._reformulate_with_context(query, context)

        # LLM mode requires async — fall through to pass-through
        if effective_mode == "llm":
            logger.debug("LLM reformulation requires async — use areformulate()")

        return ReformulationResult(
            original_query=query,
            reformulated_query=query,
            was_reformulated=False,
            context_source="none",
        )

    async def areformulate(
        self,
        query: str,
        *,
        context: ReformulationContext | None = None,
    ) -> ReformulationResult:
        """Async reformulation — supports both AI tool and LLM modes."""
        if not self._should_reformulate(query):
            return ReformulationResult(
                original_query=query,
                reformulated_query=query,
                was_reformulated=False,
                context_source="none",
            )

        effective_mode = self._resolve_mode()

        # AI tool context takes priority
        if effective_mode in ("ai_tool", "auto") and context is not None:
            return self._reformulate_with_context(query, context)

        # LLM mode
        if effective_mode == "llm" and self._backend is not None:
            return await self._reformulate_with_llm(query)

        return ReformulationResult(
            original_query=query,
            reformulated_query=query,
            was_reformulated=False,
            context_source="none",
        )

    # ── AI Tool Detection ───────────────────────────────────────

    @staticmethod
    def _detect_ai_tool() -> str | None:
        """Detect if running inside an AI coding tool via environment variables."""
        for tool_name, env_vars in _AI_TOOL_ENV_SIGNATURES.items():
            for var in env_vars:
                if os.environ.get(var):
                    logger.info("Detected AI tool environment: %s (via %s)", tool_name, var)
                    return tool_name
        return None

    @staticmethod
    def detect_ai_tool() -> str | None:
        """Public API: detect which AI tool (if any) is running."""
        for tool_name, env_vars in _AI_TOOL_ENV_SIGNATURES.items():
            for var in env_vars:
                if os.environ.get(var):
                    return tool_name
        return None

    @property
    def detected_tool(self) -> str | None:
        """Return the detected AI tool name, or None."""
        return self._detected_tool

    @property
    def is_ai_tool_environment(self) -> bool:
        """Return True if running inside a detected AI tool."""
        return self._detected_tool is not None

    # ── Core Reformulation Logic ────────────────────────────────

    def _should_reformulate(self, query: str) -> bool:
        """Decide if this query needs reformulation at all."""
        if not self._enabled or self._mode == "off":
            return False

        # Very short queries might be commands, not questions
        if len(query.strip()) < _MIN_REFORMULATE_LENGTH:
            return False

        return True

    def _resolve_mode(self) -> str:
        """Resolve the effective mode based on detection results."""
        if self._mode == "auto":
            if self._detected_tool is not None:
                return "ai_tool"
            elif self._backend is not None:
                return "llm"
            return "off"
        return self._mode

    def _reformulate_with_context(
        self, query: str, context: ReformulationContext
    ) -> ReformulationResult:
        """Reformulate using AI tool context — zero model calls.

        This is the primary reformulation path when running inside Claude Code,
        Cursor, or Codex. The AI tool has already interpreted the user's intent
        and can provide rich context.

        Strategy:
        1. Resolve pronouns ("this", "it", "that") using chat history
        2. Expand vague references using current_file and active_symbols
        3. Ground domain terms using project_summary
        4. Preserve the original intent — enhance, don't replace
        """
        parts: list[str] = []
        enrichments: list[str] = []
        confidence = 0.7  # Base confidence for context-based reformulation

        query_lower = query.lower().strip()

        # ── Step 1: Pronoun resolution ──────────────────────────
        has_pronouns = bool(re.search(
            r'\b(this|that|it|these|those|the (?:same|above|previous))\b',
            query_lower,
        ))

        resolved_subject = ""
        if has_pronouns and context.chat_history:
            resolved_subject = self._resolve_pronouns(query, context.chat_history)
            if resolved_subject:
                enrichments.append(resolved_subject)
                confidence += 0.1

        # ── Step 2: File context injection ──────────────────────
        if context.current_file and not self._query_mentions_file(query):
            enrichments.append(f"in {context.current_file}")
            confidence += 0.05

        # ── Step 3: Symbol grounding ────────────────────────────
        if context.active_symbols:
            # Only include symbols not already mentioned in the query
            unmentioned = [
                s for s in context.active_symbols
                if s.lower() not in query_lower
            ]
            if unmentioned:
                symbols_str = ", ".join(unmentioned[:5])
                enrichments.append(f"related to {symbols_str}")
                confidence += 0.05

        # ── Step 4: Attachment context injection ──────────────────
        # When users paste screenshots, upload files, or share error logs,
        # the AI tool should pre-describe them (vision/OCR) and pass the
        # textual description here. We inject that into the query so
        # GraQle can activate the right nodes.
        if context.attachments:
            attachment_parts: list[str] = []
            for att in context.attachments[:3]:  # Max 3 attachments
                if att.description:
                    attachment_parts.append(att.description)
                elif att.content_summary:
                    # Truncate long content summaries
                    summary = att.content_summary[:150]
                    if len(att.content_summary) > 150:
                        summary += "..."
                    attachment_parts.append(summary)
                elif att.filename:
                    attachment_parts.append(f"attached file: {att.filename}")

            if attachment_parts:
                enrichments.append(
                    "context from attachments: " + "; ".join(attachment_parts)
                )
                confidence += 0.15  # Attachments are high-value context

        # ── Step 5: Build reformulated query ────────────────────
        if not enrichments:
            return ReformulationResult(
                original_query=query,
                reformulated_query=query,
                was_reformulated=False,
                context_source="ai_tool",
                confidence=1.0,
            )

        # Construct the enhanced query
        # Strategy: append context as a parenthetical clarification
        base_query = query.rstrip("?.! ")
        context_clause = " (" + ", ".join(enrichments) + ")"

        # Restore original punctuation
        trailing_punct = ""
        if query.rstrip()[-1:] in "?.!":
            trailing_punct = query.rstrip()[-1]

        reformulated = base_query + context_clause + trailing_punct

        # Enforce max length
        if len(reformulated) > _MAX_REFORMULATED_LENGTH:
            reformulated = reformulated[:_MAX_REFORMULATED_LENGTH - 3] + "..."

        confidence = min(confidence, 1.0)

        logger.info(
            "Query reformulated [%s]: '%s' -> '%s' (confidence=%.2f)",
            context.tool_name or self._detected_tool or "ai_tool",
            query[:80],
            reformulated[:80],
            confidence,
        )

        return ReformulationResult(
            original_query=query,
            reformulated_query=reformulated,
            was_reformulated=True,
            context_source="ai_tool",
            confidence=confidence,
        )

    async def _reformulate_with_llm(self, query: str) -> ReformulationResult:
        """Reformulate using a lightweight LLM call (standalone SDK mode).

        This is the fallback for users not running inside an AI tool.
        Uses the cheapest available backend to interpret and clarify.
        """
        if self._backend is None:
            return ReformulationResult(
                original_query=query,
                reformulated_query=query,
                was_reformulated=False,
                context_source="none",
            )

        prompt = self._build_llm_reformulation_prompt(query)

        try:
            response = await self._backend.generate(
                prompt,
                max_tokens=200,
                temperature=0.1,  # Low temperature for precise reformulation
            )

            reformulated = self._parse_llm_response(response, query)

            if reformulated and reformulated != query:
                # Enforce max length
                if len(reformulated) > _MAX_REFORMULATED_LENGTH:
                    reformulated = reformulated[:_MAX_REFORMULATED_LENGTH - 3] + "..."

                logger.info(
                    "Query reformulated [llm]: '%s' -> '%s'",
                    query[:80],
                    reformulated[:80],
                )

                return ReformulationResult(
                    original_query=query,
                    reformulated_query=reformulated,
                    was_reformulated=True,
                    context_source="llm",
                    confidence=0.6,  # Lower confidence for blind LLM reformulation
                )
        except Exception as e:
            logger.warning("LLM reformulation failed (using original query): %s", e)

        return ReformulationResult(
            original_query=query,
            reformulated_query=query,
            was_reformulated=False,
            context_source="none",
        )

    # ── Helper Methods ──────────────────────────────────────────

    @staticmethod
    def _resolve_pronouns(
        query: str, chat_history: list[tuple[str, str]]
    ) -> str:
        """Extract the most likely referent for pronouns from chat history.

        Scans recent chat turns (newest first) for concrete nouns/subjects
        that pronouns like "this", "it", "that" likely refer to.
        """
        # Look at recent messages (newest first, up to _MAX_CONTEXT_ENTRIES)
        recent = chat_history[-_MAX_CONTEXT_ENTRIES:][::-1]

        for role, message in recent:
            # Extract potential subjects: file paths, function names, service names
            # File paths (foo/bar.ts, auth.py, etc.)
            files = re.findall(r'[\w./\\-]+\.\w{1,5}\b', message)
            if files:
                return f"regarding {files[0]}"

            # Function/class names (camelCase or snake_case identifiers)
            identifiers = re.findall(
                r'\b(?:[a-z]+[A-Z]\w+|[a-z]+_[a-z_]+\w*)\b', message
            )
            if identifiers:
                return f"regarding {identifiers[0]}"

            # Quoted terms
            quoted = re.findall(r'["\']([^"\']{3,50})["\']', message)
            if quoted:
                return f'regarding "{quoted[0]}"'

            # Service/component names (Title Case phrases)
            services = re.findall(r'\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', message)
            # Filter out common words
            services = [
                s for s in services
                if s.lower() not in {
                    "the", "this", "that", "what", "how", "when", "where",
                    "which", "who", "can", "does", "true", "false", "none",
                }
            ]
            if services:
                return f"regarding {services[0]}"

        return ""

    @staticmethod
    def _query_mentions_file(query: str) -> bool:
        """Check if the query already mentions a filename."""
        return bool(re.search(r'[\w-]+\.\w{1,5}\b', query))

    def _build_llm_reformulation_prompt(self, query: str) -> str:
        """Build a prompt for LLM-based query reformulation."""
        graph_hint = ""
        if self._graph_summary:
            # ADR-151 G7: Redact graph_summary before sending to LLM
            # B1 fix: fail-CLOSED
            from graqle.security.content_gate import ContentSecurityGate
            _summary = ContentSecurityGate().redact_text(self._graph_summary)
            graph_hint = f"\nKnowledge graph contents: {_summary}\n"

        return (
            "You are a query reformulator for a knowledge graph reasoning engine. "
            "Your job is to take a user query and make it clearer and more specific "
            "so the graph can find the right nodes to activate.\n"
            f"{graph_hint}\n"
            "Rules:\n"
            "- If the query is already clear and specific, return it UNCHANGED\n"
            "- If the query is vague, add specificity based on likely intent\n"
            "- If the query has multiple intents, focus on the primary one\n"
            "- Keep the reformulated query concise (under 100 words)\n"
            "- Do NOT add information that isn't implied by the original query\n"
            "- Return ONLY the reformulated query, nothing else\n"
            "\n"
            f"Original query: {query}\n"
            "Reformulated query:"
        )

    @staticmethod
    def _parse_llm_response(response: str, original: str) -> str:
        """Parse the LLM response to extract the reformulated query."""
        if not response:
            return original

        # Clean up the response
        reformulated = response.strip()

        # Remove common prefixes the LLM might add
        for prefix in ("Reformulated query:", "Query:", "Reformulated:"):
            if reformulated.lower().startswith(prefix.lower()):
                reformulated = reformulated[len(prefix):].strip()

        # Remove quotes if the LLM wrapped the response
        if (
            len(reformulated) >= 2
            and reformulated[0] in ('"', "'")
            and reformulated[-1] == reformulated[0]
        ):
            reformulated = reformulated[1:-1]

        # If LLM returned empty or just whitespace, use original
        if not reformulated.strip():
            return original

        # If LLM returned something wildly different (>5x length), use original
        if len(reformulated) > max(len(original) * 5, 200):
            return original

        return reformulated
