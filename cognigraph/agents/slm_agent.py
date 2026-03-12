"""SLMAgent — default agent that wraps any model backend."""

from __future__ import annotations

from typing import Any

from cognigraph.agents.base_agent import BaseAgent
from cognigraph.core.message import Message
from cognigraph.core.types import ModelBackend


class SLMAgent(BaseAgent):
    """Default agent — forwards query + context to backend model.

    Works with any ModelBackend (local SLM, API, Ollama, custom).
    """

    def __init__(
        self,
        backend: ModelBackend,
        system_prompt: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> None:
        super().__init__(backend)
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.temperature = temperature

    async def reason(
        self, query: str, context: list[Message], node_info: dict[str, Any]
    ) -> str:
        """Generate reasoning from query + context + source content."""
        parts = []

        if self.system_prompt:
            parts.append(f"System: {self.system_prompt}")

        parts.append(f"Entity: {node_info.get('label', 'Unknown')}")
        parts.append(f"Description: {node_info.get('description', '')}")

        # T2: Include semantic chunks for content-aware reasoning
        chunks = node_info.get("chunks", [])
        # Also check properties (chunks may be nested there after graph load)
        if not chunks and isinstance(node_info.get("properties"), dict):
            chunks = node_info["properties"].get("chunks", [])
        if chunks:
            parts.append("Source content:")
            for chunk in chunks[:5]:  # top 5 chunks to stay within token budget
                if isinstance(chunk, dict):
                    text = chunk.get("text", "")
                    ctype = chunk.get("type", "code")
                else:
                    text = str(chunk)
                    ctype = "code"
                if text:
                    parts.append(f"[{ctype}] {text[:800]}")

        # T3: Lazy file loading fallback when no chunks
        file_path = (
            node_info.get("file_path")
            or node_info.get("source_file")
            or (node_info.get("properties", {}) or {}).get("file_path")
            or (node_info.get("properties", {}) or {}).get("source_file")
        )
        if not chunks and file_path:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(4000)
                if content.strip():
                    parts.append(f"File content:\n{content}")
            except Exception:
                pass

        parts.append(f"Query: {query}")

        if context:
            parts.append("Neighbor messages:")
            for msg in context:
                parts.append(msg.to_prompt_context())

        prompt = "\n\n".join(parts)
        return await self.backend.generate(
            prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
