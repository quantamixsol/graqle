# graqle/workflow/__init__.py
"""
Autonomous workflow execution — LoopController + ActionAgentProtocol.

CREATE NEW MODULE — does NOT modify existing orchestrator, agents, or MCP server.
Composes alongside WorkflowOrchestrator via AutonomousExecutor.
"""
from graqle.workflow.action_agent_protocol import (
    ActionAgentProtocol,
    ExecutionResult,
)
from graqle.workflow.loop_controller import (
    InvalidTransitionError,
    LoopContext,
    LoopController,
    LoopState,
)
from graqle.workflow.execution_memory import ExecutionMemory, FileSnapshot, MemoryEntry
from graqle.workflow.test_result_parser import ParsedTestResult, TestResultParser
from graqle.workflow.diff_applicator import DiffApplicator
from graqle.workflow.loop_observer import (
    IterationMetrics,
    LoopObserver,
    Violation,
    ViolationType,
)

__all__ = [
    "ActionAgentProtocol",
    "ExecutionResult",
    "InvalidTransitionError",
    "LoopContext",
    "LoopController",
    "LoopState",
    "ExecutionMemory",
    "FileSnapshot",
    "MemoryEntry",
    "ParsedTestResult",
    "TestResultParser",
    "DiffApplicator",
    "IterationMetrics",
    "LoopObserver",
    "Violation",
    "ViolationType",
]
