"""Cost gate for multi-backend debate with decaying budget.

Implements the governance cost-control layer described in ADR-139.
Thin wrapper around :class:`~graqle.core.types.DebateCostBudget` —
pure governance logic, no logging, no LLM calls.
"""

from __future__ import annotations

from graqle.core.types import DebateCostBudget


class BudgetExhaustedError(Exception):
    """Raised when the debate budget is exhausted."""

    def __init__(self, remaining_budget: float, round_number: int) -> None:
        self.remaining_budget = remaining_budget
        self.round_number = round_number
        super().__init__(
            f"Debate budget exhausted at round {round_number} "
            f"(remaining: {remaining_budget:.6f})"
        )


class DebateCostGate:
    """Thin governance wrapper around :class:`DebateCostBudget`.

    Provides check-before-spend and record-after-spend semantics
    for each debate round, raising :class:`BudgetExhaustedError`
    when the decaying budget cannot cover the next round.
    """

    def __init__(self, budget: DebateCostBudget) -> None:
        self._budget = budget

    # ── round lifecycle ──────────────────────────────────────────

    def check_round(self, estimated_cost: float) -> None:
        """Authorize the next round or raise :class:`BudgetExhaustedError`."""
        if not self._budget.authorize_round(estimated_cost):
            raise BudgetExhaustedError(
                remaining_budget=self._budget._remaining,
                round_number=self._budget._round,
            )

    def record_and_decay(self, actual_cost: float) -> float:
        """Record spend for the current round and return remaining budget."""
        self._budget.record_spend(actual_cost)
        return self._budget._remaining

    # ── read-only properties ─────────────────────────────────────

    @property
    def remaining(self) -> float:
        """Remaining budget after all recorded spend and decay."""
        return self._budget._remaining

    @property
    def current_round(self) -> int:
        """Current debate round number."""
        return self._budget._round

    @property
    def exhausted(self) -> bool:
        """Whether the budget is fully exhausted."""
        return self._budget.exhausted
