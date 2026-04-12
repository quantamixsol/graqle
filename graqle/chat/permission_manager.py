"""Permission Manager + TurnStore — durable pause/resume for ChatAgentLoop v4. of ChatAgentLoop v4 . Holds:

  - ``TurnState`` enum: the v4 state machine
  - ``TurnCheckpoint`` dataclass: runtime + persisted split
  - ``TurnStore``: in-memory store with CAS state transitions under
    ``asyncio.Lock``, idempotent resume via ``tool_result_cache``,
    crash recovery via terminal-state tombstoning
  - ``PermissionManager``: session-scoped permission cache keyed by
    ``(tool_name, resource_scope, session_id)`` with revocation hooks

Concurrency contract
--------------------
Every ``TurnStore`` mutation is performed inside a single
``asyncio.Lock``. The CAS contract is:

  ``transition(turn_id, expected_state, new_state) -> bool``

Returns ``True`` only when the current state equals
``expected_state``. The ``async`` API never blocks for more than the
duration of the lock.

Crash recovery
--------------
On startup, any turn whose state is ``ACTIVE`` or ``PAUSED`` (i.e.
non-terminal) is moved to ``ABANDONED`` with reason
``"crash_recovery"``. The default policy never tries to resume an
async task that died with the previous process.

Permission caching
------------------
Decisions are cached by ``(tool_name, resource_scope, session_id)``.
Approve once for a scope, subsequent same-scope calls auto-proceed
with a soft chip. Revocation is mid-session and takes effect at the
next safe boundary (next call to ``check``).

CGI-compatibility note seed)
-------------------------------------
``TurnCheckpoint`` carries fields (``started_at``, ``ended_at``,
``model_id``, ``cost_usd``, ``tools_used_count``, ``exit_reason``)
that map directly onto the future ``Session`` and ``Checkpoint``
nodes in . Today they are stored in the runtime ``TurnStore``;
post-v0.50.0 the CGI design session can decide whether to copy them
into a persistent CGI on terminal transitions.
"""

# ── graqle:intelligence ──
# module: graqle.chat.permission_manager
# risk: HIGH (concurrency contract)
# consumers: chat.agent_loop (planned # dependencies: __future__, asyncio, dataclasses, enum, typing, time
# constraints: every mutation inside the asyncio.Lock
# ── /graqle:intelligence ──

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TurnState(str, Enum):
    """The v4 turn state machine.

    Transitions allowed:
        PENDING  → ACTIVE | CANCELLED
        ACTIVE   → PAUSED | COMPLETED | FAILED | CANCELLED
        PAUSED   → ACTIVE | CANCELLED | ABANDONED
        COMPLETED, FAILED, CANCELLED, ABANDONED → terminal
    """

    PENDING = "pending"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"

    @classmethod
    def terminal(cls) -> set["TurnState"]:
        return {cls.COMPLETED, cls.FAILED, cls.CANCELLED, cls.ABANDONED}

    @classmethod
    def non_terminal(cls) -> set["TurnState"]:
        return {cls.PENDING, cls.ACTIVE, cls.PAUSED}


_ALLOWED_TRANSITIONS: dict[TurnState, set[TurnState]] = {
    TurnState.PENDING: {TurnState.ACTIVE, TurnState.CANCELLED},
    TurnState.ACTIVE: {
        TurnState.PAUSED, TurnState.COMPLETED, TurnState.FAILED,
        TurnState.CANCELLED,
    },
    TurnState.PAUSED: {
        TurnState.ACTIVE, TurnState.CANCELLED, TurnState.ABANDONED,
    },
    # Terminal states have no outgoing transitions.
    TurnState.COMPLETED: set(),
    TurnState.FAILED: set(),
    TurnState.CANCELLED: set(),
    TurnState.ABANDONED: set(),
}


@dataclass
class TurnCheckpoint:
    """Runtime + persisted split for one in-flight chat turn."""

    turn_id: str
    session_id: str
    state: TurnState = TurnState.PENDING
    user_message: str = ""
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    model_id: str = ""
    cost_usd: float = 0.0
    tools_used_count: int = 0
    exit_reason: str = ""
    last_seq: int = 0
    pending_id: str | None = None  # set when waiting on a permission
    # Idempotent resume cache: tool_call_id -> serialized result
    tool_result_cache: dict[str, Any] = field(default_factory=dict)
    # Append-only audit trail of state transitions
    transitions: list[tuple[float, TurnState, TurnState]] = field(default_factory=list)

    def is_terminal(self) -> bool:
        return self.state in TurnState.terminal()

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "state": self.state.value,
            "user_message": self.user_message,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "model_id": self.model_id,
            "cost_usd": self.cost_usd,
            "tools_used_count": self.tools_used_count,
            "exit_reason": self.exit_reason,
            "last_seq": self.last_seq,
            "pending_id": self.pending_id,
        }


# ──────────────────────────────────────────────────────────────────────
# TurnStore — async-locked CAS state machine
# ──────────────────────────────────────────────────────────────────────


class TurnBusyError(Exception):
    """Raised when a second graq_chat_turn arrives while one is active."""


class TurnStore:
    """In-memory store of TurnCheckpoint objects with CAS transitions.

    Every mutation is performed inside ``self._lock`` so the contract
    holds even when several MCP calls land concurrently. The store is
    intentionally NOT persisted — 's ``TurnLedger`` handles the
    immutable historical transcript at the file layer; this is hot
    runtime state.
    """

    def __init__(self) -> None:
        self._turns: dict[str, TurnCheckpoint] = {}
        self._active_by_session: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        turn_id: str,
        session_id: str,
        user_message: str,
        *,
        model_id: str = "",
    ) -> TurnCheckpoint:
        """Create a new turn. Raises TurnBusyError if the session
        already has a non-terminal turn.
        """
        async with self._lock:
            existing = self._active_by_session.get(session_id)
            if existing is not None:
                existing_turn = self._turns.get(existing)
                if existing_turn and not existing_turn.is_terminal():
                    raise TurnBusyError(
                        f"session {session_id} already has active turn {existing}"
                    )
            cp = TurnCheckpoint(
                turn_id=turn_id,
                session_id=session_id,
                state=TurnState.PENDING,
                user_message=user_message,
                model_id=model_id,
            )
            self._turns[turn_id] = cp
            self._active_by_session[session_id] = turn_id
            cp.transitions.append((time.time(), TurnState.PENDING, TurnState.PENDING))
            return cp

    async def get(self, turn_id: str) -> TurnCheckpoint | None:
        async with self._lock:
            return self._turns.get(turn_id)

    async def transition(
        self,
        turn_id: str,
        expected_state: TurnState,
        new_state: TurnState,
        *,
        exit_reason: str = "",
    ) -> bool:
        """CAS transition. Returns True only on success.

        - Verifies ``cp.state == expected_state``
        - Verifies ``new_state`` is in the allowed set for ``expected_state``
        - Sets ``cp.ended_at`` on transition into a terminal state
        """
        async with self._lock:
            cp = self._turns.get(turn_id)
            if cp is None:
                return False
            if cp.state != expected_state:
                return False
            if new_state not in _ALLOWED_TRANSITIONS.get(expected_state, set()):
                return False
            cp.transitions.append((time.time(), cp.state, new_state))
            cp.state = new_state
            if exit_reason:
                cp.exit_reason = exit_reason
            if new_state in TurnState.terminal():
                cp.ended_at = time.time()
                # Clear active map only when terminal.
                if self._active_by_session.get(cp.session_id) == turn_id:
                    self._active_by_session.pop(cp.session_id, None)
            return True

    async def cache_tool_result(
        self,
        turn_id: str,
        tool_call_id: str,
        result: Any,
    ) -> bool:
        """Idempotent resume helper: cache a tool result by call id."""
        async with self._lock:
            cp = self._turns.get(turn_id)
            if cp is None:
                return False
            cp.tool_result_cache[tool_call_id] = result
            return True

    async def get_cached_tool_result(
        self,
        turn_id: str,
        tool_call_id: str,
    ) -> tuple[bool, Any]:
        """Returns ``(found, value)`` from the resume cache."""
        async with self._lock:
            cp = self._turns.get(turn_id)
            if cp is None:
                return False, None
            if tool_call_id in cp.tool_result_cache:
                return True, cp.tool_result_cache[tool_call_id]
            return False, None

    async def crash_recover(self) -> list[str]:
        """Tombstone any non-terminal turns from a previous run.

        Returns the list of turn ids that were forced to ABANDONED.
        Called once at process startup before accepting new turns.
        """
        affected: list[str] = []
        async with self._lock:
            for turn_id, cp in list(self._turns.items()):
                if cp.state in TurnState.non_terminal():
                    cp.transitions.append(
                        (time.time(), cp.state, TurnState.ABANDONED),
                    )
                    cp.state = TurnState.ABANDONED
                    cp.exit_reason = "crash_recovery"
                    cp.ended_at = time.time()
                    affected.append(turn_id)
                    self._active_by_session.pop(cp.session_id, None)
        return affected


# ──────────────────────────────────────────────────────────────────────
# PermissionManager — session-scoped permission cache
# ──────────────────────────────────────────────────────────────────────


class PermissionDecision(str, Enum):
    APPROVE = "approve"
    DENY = "deny"
    PROMPT = "prompt"


@dataclass
class PermissionRequest:
    """An open permission request awaiting user decision."""

    pending_id: str
    session_id: str
    tool_name: str
    resource_scope: str
    tier: str
    rationale: str
    created_at: float = field(default_factory=time.time)


class PermissionManager:
    """Session-scoped permission cache.

    Cache key: ``(tool_name, resource_scope, session_id)``. Decisions
    survive across turns within a session and are cleared on session
    end. Revocation is supported and takes effect at the next call to
    ``check``.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str, str], PermissionDecision] = {}
        self._pending: dict[str, PermissionRequest] = {}
        self._revoked: set[tuple[str, str, str]] = set()
        self._lock = asyncio.Lock()
        self._counter = 0

    async def check(
        self,
        *,
        session_id: str,
        tool_name: str,
        resource_scope: str,
        tier: str,
        rationale: str = "",
    ) -> tuple[PermissionDecision, str | None]:
        """Return ``(decision, pending_id_or_none)``.

        - GREEN tier auto-approves
        - YELLOW/RED tier consults the cache; on a miss creates a
          PermissionRequest and returns ``PROMPT`` with the new
          ``pending_id``
        - Revoked entries are removed from the cache and re-prompt
        """
        if tier == "GREEN":
            return PermissionDecision.APPROVE, None

        key = (tool_name, resource_scope, session_id)
        async with self._lock:
            if key in self._revoked:
                self._cache.pop(key, None)
                self._revoked.discard(key)
            cached = self._cache.get(key)
            if cached == PermissionDecision.APPROVE:
                return PermissionDecision.APPROVE, None
            if cached == PermissionDecision.DENY:
                return PermissionDecision.DENY, None
            # Miss → create a pending request
            self._counter += 1
            pending_id = f"perm_{session_id[:8]}_{self._counter}"
            req = PermissionRequest(
                pending_id=pending_id,
                session_id=session_id,
                tool_name=tool_name,
                resource_scope=resource_scope,
                tier=tier,
                rationale=rationale,
            )
            self._pending[pending_id] = req
            return PermissionDecision.PROMPT, pending_id

    async def resolve(
        self,
        pending_id: str,
        decision: PermissionDecision,
    ) -> bool:
        """Apply a user decision to a pending request.

        Returns True if the request was found.
        """
        async with self._lock:
            req = self._pending.pop(pending_id, None)
            if req is None:
                return False
            key = (req.tool_name, req.resource_scope, req.session_id)
            self._cache[key] = decision
            return True

    async def revoke(
        self,
        *,
        session_id: str,
        tool_name: str,
        resource_scope: str,
    ) -> bool:
        """Revoke a previously cached decision.

        Takes effect at the next ``check`` for the same key.
        """
        key = (tool_name, resource_scope, session_id)
        async with self._lock:
            if key in self._cache:
                self._revoked.add(key)
                return True
            return False

    async def clear_session(self, session_id: str) -> int:
        """Drop every cache entry for a session. Returns count cleared."""
        async with self._lock:
            keys_to_drop = [k for k in self._cache if k[2] == session_id]
            for k in keys_to_drop:
                self._cache.pop(k, None)
            pending_to_drop = [
                pid for pid, r in self._pending.items()
                if r.session_id == session_id
            ]
            for pid in pending_to_drop:
                self._pending.pop(pid, None)
            return len(keys_to_drop)


__all__ = [
    "PermissionDecision",
    "PermissionManager",
    "PermissionRequest",
    "TurnBusyError",
    "TurnCheckpoint",
    "TurnState",
    "TurnStore",
]
