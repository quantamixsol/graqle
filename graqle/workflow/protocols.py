# graqle/workflow/protocols.py
"""
Structural protocols that let AutonomousExecutor be composed with pluggable
collaborators — no subclassing, zero coupling (PEP 544).

ADR-239 (Universal SDK Build Engine): the same autonomous-loop engine must
serve both the SDK's default git/pytest workflow AND cloud consumers that
checkpoint to a non-git store (e.g. an object-store file sink) with no test
stage. CheckpointProtocol is the seam for the checkpoint/rollback concern.

The default implementation is graqle.workflow.diff_applicator.DiffApplicator
(git stash + atomic apply), which satisfies this protocol structurally with
zero changes. A cloud consumer injects its own object satisfying the same two
methods (e.g. create_stash returns a snapshot id / None; rollback deletes the
files it wrote).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from graqle.workflow.action_agent_protocol import ExecutionResult


@runtime_checkable
class CheckpointProtocol(Protocol):
    """Checkpoint/rollback seam for AutonomousExecutor.

    Only two methods are required — they match DiffApplicator's real
    signatures exactly, so DiffApplicator is a valid CheckpointProtocol with
    no modification.

    create_stash: take a checkpoint before a write attempt. Returns an opaque
      token used to roll back, or None when no checkpoint is possible (e.g.
      git unavailable) — the executor already tolerates a None token.
    rollback: undo changes identified by a token. Returns an ExecutionResult
      whose .success reports whether the rollback applied.
    """

    def create_stash(self, message: str = ...) -> str | None: ...

    def rollback(self, token: str) -> ExecutionResult: ...
