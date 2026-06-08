"""Cost gate for multi-backend debate with decaying budget.

Implements the governance cost-control layer described in .
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

    Provides check-before-spend and record-after-spend semantics for each
    debate round.

    ADR-222 P4 — cost is observability, NEVER a quality gate. As of P4 this
    gate is ADVISORY: when the decaying budget cannot cover the next round it
    does NOT halt the debate. Instead it records that the round ran over budget
    (so the cost of continuing is MEASURED and visible via ``over_budget`` /
    ``over_budget_rounds``) and allows the debate to continue to its natural
    bound (rounds / convergence). A still-valuable debate is never cut for cost.
    """

    def __init__(self, budget: DebateCostBudget) -> None:
        self._budget = budget
        # ADR-222 P4: advisory tracking — measure, never gate.
        self._over_budget_rounds: int = 0

    # ── round lifecycle ──────────────────────────────────────────

    def check_round(self, estimated_cost: float) -> bool:
        """ADVISORY authorization (ADR-222 P4) — NEVER raises, NEVER halts.

        Returns True when the round is within budget, False when it is over
        budget. The debate proceeds regardless; the boolean + ``over_budget``
        are observability so callers can surface the cost of continuing.
        """
        if not self._budget.authorize_round(estimated_cost):
            self._over_budget_rounds += 1
            return False
        return True

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
        """Whether the budget is fully exhausted.

        ADR-222 P4: this is now an ADVISORY signal only — callers may surface it,
        but it does NOT halt the debate (cost never gates quality).
        """
        return self._budget.exhausted

    @property
    def over_budget(self) -> bool:
        """ADR-222 P4: True if any round ran over budget (advisory/observability)."""
        return self._over_budget_rounds > 0

    @property
    def over_budget_rounds(self) -> int:
        """ADR-222 P4: count of rounds that ran over budget — the measured cost
        of continuing past the advisory, never a gate."""
        return self._over_budget_rounds
