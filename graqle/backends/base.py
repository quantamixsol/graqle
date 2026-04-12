"""Base model backend — the protocol that all backends implement. /030 Layer 1: Adds GenerateResult structured return type with
backward-compatible str behavior for 31+ consuming modules. (v0.47.1): __getstate__/__setstate__/__deepcopy__ drop
transient client handles so backend instances are deepcopy-safe.
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


# B1/B3 fix: Read-only str method allowlist for backward-compat.
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


# ── (v0.47.1): backend serialization contract ────────────────
#
# Backend instances must be deepcopy- and pickle-safe so they can ride along
# with reasoning-node snapshots (graqle/core/graph.py:areason). The contract:
#
#   PERSISTED on copy/pickle:
#     - durable configuration (model id, retry counts, base URLs)
#     - credentials reference (env-var name only, NOT live handles)
#     - cost trackers (totals, counters)
#
#   DROPPED on copy/pickle (recreated lazily on next call):
#     - HTTP client handles (httpx, AsyncOpenAI, anthropic.AsyncClient, ...)
#     - cloud SDK sessions (boto3 client, gemini sdk client, ...)
#     - executor / event-loop refs
#     - threading primitives (Lock / RLock / Semaphore)
#
# Subclasses that introduce a new transient handle MUST add its attribute
# name to ``_TRANSIENT_BACKEND_ATTRS`` (or override ``__getstate__``).
# Future contributors: this is a serialization contract, not a style note.
# Reintroducing a non-picklable handle outside this set will reopen
# across every reasoning round.

_TRANSIENT_BACKEND_ATTRS: frozenset[str] = frozenset({
    "_client",
    "_async_client",
    "_session",
    "_executor",
    "_loop",
    "_lock",
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
    a convenient base class with shared functionality. /030: generate() returns GenerateResult (str-compatible). (v0.47.1): Backend instances are deepcopy- and pickle-safe.
    Transient runtime handles (HTTP clients, cloud SDK sessions, executor
    references, threading locks) listed in ``_TRANSIENT_BACKEND_ATTRS`` are
    dropped on serialization and lazily recreated on next access. This
    fixes the ``cannot pickle '_thread.RLock' object`` crash that hit
    ``graqle.core.graph.areason()`` when reasoning nodes were deepcopied
    for the redaction snapshot. ``__deepcopy__`` is side-effect
    free with respect to the source instance — concurrent reasoning rounds
    sharing one backend reference are isolated by their own copies.
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
        to yield token-by-token chunks for lower time-to-first-token. /030: Keeps yielding str chunks, not GenerateResult.
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

    # ── (v0.47.1): copy/pickle safety ─────────────────────────

    def __getstate__(self) -> dict[str, Any]:
        """Drop transient runtime handles before pickling/copying.

        See ``_TRANSIENT_BACKEND_ATTRS`` for the contract. Recreated lazily
        on next access by whatever ``_get_*`` accessor a concrete backend
        defines. Side-effect free: does not mutate ``self``.
        """
        state = self.__dict__.copy()
        for attr in _TRANSIENT_BACKEND_ATTRS:
            state.pop(attr, None)
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        """Restore state and reset every transient handle to None.

        Concrete backends use lazy ``_get_client()``-style accessors that
        rebuild the handle on first call. We reset EVERY entry in
        ``_TRANSIENT_BACKEND_ATTRS`` to ``None`` so subclasses with
        multiple transient handles (e.g. both ``_client`` AND
        ``_async_client``) come out consistent regardless of which
        attributes the originating instance happened to set. Side-effect
        free with respect to any other instance — this only mutates
        ``self.__dict__``.
        """
        self.__dict__.update(state)
        for attr in _TRANSIENT_BACKEND_ATTRS:
            if attr not in self.__dict__:
                self.__dict__[attr] = None

        # Defensive note: if a future subclass uses ``__slots__`` only
        # (no ``__dict__``), this and ``__deepcopy__`` need to be
        # overridden in that subclass. All current backends are
        # ``__dict__``-backed; see test_subclass_specific_transient_attr_can_be_added.

    def __deepcopy__(self, memo: dict[int, Any]) -> "BaseBackend":
        """Deepcopy via ``__getstate__`` / ``__setstate__``.

        Without this, ``copy.deepcopy(backend)`` would walk the underlying
        HTTP client tree and crash on the first ``_thread.RLock`` it
        finds. By routing through ``__getstate__``, the resulting copy
        holds only durable configuration (model name, retry counts,
        credentials env-var name, cost trackers) and lazily rebuilds
        the client on next call.

        This implementation does NOT mutate ``self`` — the source
        instance keeps its live client. Two reasoning rounds that share
        a backend reference therefore each get an isolated copy with
        its own lazy ``_client`` slot.
        """
        import copy as _copy

        new_obj = self.__class__.__new__(self.__class__)
        memo[id(self)] = new_obj
        new_state = _copy.deepcopy(self.__getstate__(), memo)
        new_obj.__setstate__(new_state)
        return new_obj
