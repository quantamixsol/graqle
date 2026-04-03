"""Base model backend — the protocol that all backends implement.

OT-028/030 Layer 1: Adds GenerateResult structured return type with
backward-compatible str behavior for 31+ consuming modules.
"""

# ── graqle:intelligence ──
# module: graqle.backends.base
# risk: MEDIUM (impact radius: 31 modules)
# consumers: api, fallback, gemini, llamacpp_backend, local +26 more
# dependencies: __future__, abc, dataclasses
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


# OT-028 B1/B3 fix: Read-only str method allowlist for backward-compat.
# Covers all str methods used by 31+ consumers. Typos still raise AttributeError.
_STR_ALLOWLIST: frozenset[str] = frozenset({
    "strip", "lstrip", "rstrip",
    "split", "rsplit", "splitlines",
    "lower", "upper", "title", "capitalize", "casefold", "swapcase",
    "startswith", "endswith",
    "find", "rfind", "index", "rindex", "count",
    "replace",
    "join",
    "encode",
    "center", "ljust", "rjust", "zfill",
    "expandtabs",
    "isalpha", "isdigit", "isalnum", "isspace", "isupper", "islower",
    "removeprefix", "removesuffix",
})


@dataclass(slots=True)
class GenerateResult:
    """Structured result from any backend .generate() call.

    Backward-compatible with str: str(result), f"{result}",
    result + "suffix", len(result), result.strip() all work.

    This is critical because 31+ modules consume generate() as str.
    """

    text: str
    truncated: bool = False
    stop_reason: str = ""
    tokens_used: int | None = None
    model: str = ""

    # ── str backward-compat (protects 31+ consumers) ────────

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        trunc_flag = " [TRUNCATED]" if self.truncated else ""
        tokens_info = (
            f", tokens={self.tokens_used}"
            if self.tokens_used is not None
            else ""
        )
        return (
            f"GenerateResult(len={len(self.text)}, "
            f"stop_reason={self.stop_reason!r}{tokens_info}{trunc_flag})"
        )

    def __format__(self, format_spec: str) -> str:
        return format(self.text, format_spec)

    def __add__(self, other: Any) -> str:
        if isinstance(other, str):
            return self.text + other
        if isinstance(other, GenerateResult):
            return self.text + other.text
        return NotImplemented

    def __radd__(self, other: Any) -> str:
        if isinstance(other, str):
            return other + self.text
        return NotImplemented

    def __contains__(self, item: str) -> bool:
        return item in self.text

    def __len__(self) -> int:
        return len(self.text)

    def __bool__(self) -> bool:
        return bool(self.text)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.text == other
        if isinstance(other, GenerateResult):
            return self.text == other.text
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.text)

    def __getitem__(self, key: Any) -> str:
        return self.text[key]

    def __iter__(self):
        return iter(self.text)

    def __getattr__(self, name: str) -> Any:
        """Proxy ONLY allowlisted str methods to self.text.

        B3 fix: Open delegation masked typos like
        result.truncatd. Now restricted to _STR_ALLOWLIST.
        Use .text.<method>() for non-allowlisted str operations.
        """
        if name in _STR_ALLOWLIST:
            return getattr(self.text, name)
        raise AttributeError(
            f"'{type(self).__name__}' has no attribute {name!r}. "
            f"Delegated str methods: {sorted(_STR_ALLOWLIST)}. "
            f"Use .text.{name}() for other str operations."
        )

    @property
    def is_complete(self) -> bool:
        """True if the response completed naturally (not truncated)."""
        return not self.truncated


class TruncationError(Exception):
    """Raised when a truncated GenerateResult is unacceptable."""

    def __init__(self, message: str, result: GenerateResult):
        super().__init__(message)
        self.result = result


class BaseBackend(ABC):
    """Abstract base class for model backends.

    All backends must implement async generate(). The ModelBackend protocol
    in core/types.py defines the structural interface; this ABC provides
    a convenient base class with shared functionality.

    OT-028/030: generate() returns GenerateResult (str-compatible).
    """

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> GenerateResult:
        """Generate text from a prompt. Returns GenerateResult (str-compatible)."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable backend name."""
        ...

    @property
    @abstractmethod
    def cost_per_1k_tokens(self) -> float:
        """Cost in USD per 1,000 tokens."""
        ...

    async def agenerate_stream(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ):
        """Stream generated text as an AsyncIterator[str].

        Default implementation: yields the full result as a single chunk.
        Backward-compatible for all existing backends — they get streaming
        for free without any changes.

        Override in backends that support native streaming (Anthropic, etc.)
        to yield token-by-token chunks for lower time-to-first-token.

        OT-028/030: Keeps yielding str chunks, not GenerateResult.
        Truncation is only knowable at stream end — Layer 2 handles this.
        """
        result = await self.generate(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=stop,
        )
        yield str(result)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"
