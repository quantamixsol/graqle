"""Bring-your-own-backend polyglot router for ChatAgentLoop v4. of ChatAgentLoop v4 . Reads ``graqle.yaml``'s
``models:`` section, detects backend families, and routes the 6 new
chat task types (``chat_triage``, ``chat_reasoning``,
``chat_debate_proposer``, ``chat_debate_adversary``,
``chat_debate_arbiter``, ``chat_format``) to whichever backend the
user has configured.

Family separation
-----------------
For the concern-check roles to provide a meaningful second opinion,
the CANDIDATE and CRITIC roles should run on backends from DIFFERENT families
(e.g. anthropic vs openai). The router enforces family separation
ONLY when 2+ families are configured. With a single family available,
it logs a warning chip and runs same-family debate.

Minimal-polyglot degradation
----------------------------
When only ONE backend is configured at all, the router degrades to
"minimal polyglot mode": every task type gets the same backend, the
debate runs against a single persona (no adversary), and the user
gets a soft warning chip on session start.

Capability detection
--------------------
Backends without native tool-use support (Ollama, older local models)
are detected via the ``supports_tool_use`` flag on the backend
adapter. The fallback chain is probed once at session_start and
cached for the lifetime of the session.
"""

# ── graqle:intelligence ──
# module: graqle.chat.backend_router
# risk: MEDIUM (config-driven dispatch)
# consumers: chat.agent_loop (planned chat.debate # dependencies: __future__, dataclasses, enum, typing
# constraints: never hard-code backend choices; family detection by name
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("graqle.chat.backend_router")


# 6 new task types added by ChatAgentLoop v4
CHAT_TASK_TYPES = (
    "chat_triage",
    "chat_reasoning",
    "chat_debate_proposer",
    "chat_debate_adversary",
    "chat_debate_arbiter",
    "chat_format",
)

# Family detection — keyed by backend prefix
_FAMILY_PREFIXES: dict[str, str] = {
    "anthropic": "anthropic",
    "claude": "anthropic",
    "openai": "openai",
    "gpt": "openai",
    "bedrock": "bedrock",
    "aws": "bedrock",
    "ollama": "ollama",
    "gemini": "google",
    "google": "google",
    "groq": "groq",
    "deepseek": "deepseek",
    "together": "together",
    "mistral": "mistral",
    "openrouter": "openrouter",
    "fireworks": "fireworks",
    "cohere": "cohere",
}


def detect_family(backend_name: str) -> str:
    """Return the family name for a backend id like ``openai:gpt-5.4-mini``."""
    head = backend_name.split(":")[0].lower()
    for prefix, family in _FAMILY_PREFIXES.items():
        if head.startswith(prefix):
            return family
    return "custom"


@dataclass
class BackendProfile:
    """One configured backend entry from ``graqle.yaml``."""

    name: str  # full id, e.g. "anthropic:claude-sonnet-4-6"
    family: str
    supports_tool_use: bool = True
    latency_tier: str = "medium"  # fast | medium | slow

    @classmethod
    def from_name(
        cls,
        name: str,
        *,
        supports_tool_use: bool = True,
        latency_tier: str = "medium",
    ) -> BackendProfile:
        return cls(
            name=name,
            family=detect_family(name),
            supports_tool_use=supports_tool_use,
            latency_tier=latency_tier,
        )


@dataclass
class RoutingDecision:
    """Result of ``BackendRouter.route``."""

    task_type: str
    selected: BackendProfile
    fallback_chain: list[BackendProfile] = field(default_factory=list)
    family_separation_violated: bool = False
    minimal_polyglot_mode: bool = False
    warning: str = ""


class BackendRouter:
    """Bring-your-own-backend router.

    Construction:
        ``BackendRouter(profiles=[...])`` — passes a list of already-built
        BackendProfile entries. ChatAgentLoop will read graqle.yaml and
        construct profiles before instantiating the router.
    """

    def __init__(self, profiles: list[BackendProfile]) -> None:
        if not profiles:
            raise ValueError(
                "BackendRouter requires at least one configured backend"
            )
        self.profiles = profiles
        self._families = sorted({p.family for p in profiles})
        self._tool_use_capable = [p for p in profiles if p.supports_tool_use]

    @property
    def family_count(self) -> int:
        return len(self._families)

    @property
    def is_minimal_polyglot(self) -> bool:
        return len(self.profiles) <= 1

    def route(
        self,
        task_type: str,
        *,
        prefer_family: str | None = None,
    ) -> RoutingDecision:
        """Route a task type to a backend profile.

        Family separation (for debate adversary) is enforced only when
        2+ families are configured. Otherwise the router degrades
        gracefully and surfaces a warning string the agent loop can
        emit as a chip.
        """
        if task_type not in CHAT_TASK_TYPES:
            # Unknown task types fall through to the first profile
            # rather than raising — keeps the agent loop forgiving.
            logger.debug("router: unknown task_type %s, using first profile", task_type)
            return RoutingDecision(
                task_type=task_type,
                selected=self.profiles[0],
                fallback_chain=self.profiles[1:],
                minimal_polyglot_mode=self.is_minimal_polyglot,
            )

        # For tool-use sensitive task types, only consider tool-use-capable
        # backends; for plain text task types, any backend works.
        tool_use_required = task_type in {
            "chat_reasoning", "chat_debate_proposer",
            "chat_debate_adversary", "chat_debate_arbiter",
        }
        candidates = self._tool_use_capable if tool_use_required else self.profiles
        if not candidates:
            candidates = self.profiles  # last-resort fallback

        # Apply family preference for debate personas.
        selected: BackendProfile | None = None
        warning = ""
        violated = False

        if prefer_family and self.family_count >= 2:
            for p in candidates:
                if p.family == prefer_family:
                    selected = p
                    break
        elif prefer_family and self.family_count < 2:
            warning = (
                f"only one family ({self._families[0]}) configured — "
                f"{task_type} cannot use family separation"
            )
            violated = True

        if selected is None:
            selected = candidates[0]

        fallback_chain = [p for p in candidates if p is not selected]

        return RoutingDecision(
            task_type=task_type,
            selected=selected,
            fallback_chain=fallback_chain,
            family_separation_violated=violated,
            minimal_polyglot_mode=self.is_minimal_polyglot,
            warning=warning,
        )

    def adversary_for(
        self, proposer_family: str,
    ) -> RoutingDecision:
        """Pick an adversary that is from a DIFFERENT family from the proposer.

        Falls back to same-family with a warning when 1 family configured.
        """
        if self.family_count >= 2:
            for fam in self._families:
                if fam != proposer_family:
                    return self.route(
                        "chat_debate_adversary", prefer_family=fam,
                    )
        return self.route(
            "chat_debate_adversary", prefer_family=proposer_family,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profiles": [
                {
                    "name": p.name,
                    "family": p.family,
                    "supports_tool_use": p.supports_tool_use,
                    "latency_tier": p.latency_tier,
                }
                for p in self.profiles
            ],
            "families": self._families,
            "minimal_polyglot": self.is_minimal_polyglot,
        }


__all__ = [
    "BackendProfile",
    "BackendRouter",
    "CHAT_TASK_TYPES",
    "RoutingDecision",
    "detect_family",
]
