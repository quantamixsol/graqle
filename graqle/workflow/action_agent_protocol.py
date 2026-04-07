# graqle/workflow/action_agent_protocol.py
"""
ActionAgentProtocol + ExecutionResult.

Uses typing.Protocol (PEP 544) — zero coupling to BaseAgent (402 deps).
BaseAgent is NOT modified; agents compose via delegation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ExecutionResult:
    """
    Canonical result envelope from any action agent.

    rollback_token: opaque reference for DiffApplicator.rollback()
                    (git stash SHA or backup file path).
    """

    exit_code: int
    stdout: str
    stderr: str
    modified_files: list[str] = field(default_factory=list)
    test_passed: bool = False
    rollback_token: str | None = None

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout[:4000],
            "stderr": self.stderr[:1000],
            "modified_files": self.modified_files,
            "test_passed": self.test_passed,
            "rollback_token": self.rollback_token,
        }


@runtime_checkable
class ActionAgentProtocol(Protocol):
    """
    Structural protocol — any agent satisfying this interface can be
    composed into AutonomousExecutor without subclassing BaseAgent.

    Deliberately avoids BaseAgent inheritance to respect the 402-dep
    blast-radius constraint. Compose with SLMAgent via delegation.
    """

    async def plan(self, task: str, context: dict[str, Any]) -> str:
        """Return a structured plan string."""
        ...

    async def generate_diff(
        self,
        task: str,
        plan: str | dict[str, Any],
        error_context: str | None = None,
    ) -> str:
        """Return a unified diff string implementing the plan."""
        ...

    async def apply(self, diff: str) -> ExecutionResult:
        """Apply the diff atomically; populate rollback_token on success."""
        ...

    async def run_tests(
        self, test_paths: list[str] | None = None
    ) -> ExecutionResult:
        """Run the test suite; populate test_passed."""
        ...

    async def rollback(self, token: str) -> ExecutionResult:
        """Undo changes identified by rollback_token."""
        ...
