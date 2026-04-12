"""Clearance filter and taint propagation for multi-backend debate  .

Filters KG context based on backend clearance level before prompt
assembly. Includes anti-laundering taint propagation to prevent
clearance downgrade through synthesis boundaries.
"""

from __future__ import annotations

import logging

from graqle.core.exceptions import GovernanceViolation
from graqle.core.results import ToolResult
from graqle.core.types import ClearanceLevel

logger = logging.getLogger(__name__)


class ClearanceFilter:
    """Filter KG nodes by backend clearance level."""

    def filter_nodes(
        self,
        nodes: list[dict],
        clearance: ClearanceLevel,
    ) -> list[dict]:
        """Return only nodes whose clearance rank <= the backend's rank.

        Each node dict may carry a ``"clearance"`` key whose value is a
        :class:`ClearanceLevel` name (case-insensitive).  Nodes without
        the key default to ``PUBLIC``.
        """
        filtered: list[dict] = []
        for node in nodes:
            node_level = self._parse_clearance(node.get("clearance"))
            if node_level <= clearance:
                filtered.append(node)
        return filtered

    def get_effective_clearance(
        self,
        panelist: str,
        clearance_levels: dict[str, str],
    ) -> ClearanceLevel:
        """Look up a panelist's clearance, defaulting to PUBLIC."""
        raw = clearance_levels.get(panelist)
        return self._parse_clearance(raw)

    def check_output_clearance(
        self,
        max_clearance_seen: ClearanceLevel,
        output_clearance: ClearanceLevel,
    ) -> None:
        """Raise if synthesis saw higher-clearance context than output allows.

        Prevents clearance laundering: CONFIDENTIAL context processed by
        a trusted backend must not be returned through a PUBLIC channel.
        """
        if max_clearance_seen > output_clearance:
            raise ClearanceViolationError(
                f"Synthesis saw {max_clearance_seen.name} context "
                f"but output clearance is {output_clearance.name}. "
                f"Cannot downgrade clearance.",
                max_seen=max_clearance_seen,
                output_level=output_clearance,
            )

    def taint_synthesis_output(
        self, inputs: list[ToolResult], synthesis_output: str,
    ) -> ToolResult:
        """Compute output clearance as MAX of all input clearances.

        Anti-laundering taint propagation: the synthesised output inherits
        the highest clearance from any contributing input.
        """
        if not inputs:
            max_clearance = ClearanceLevel.PUBLIC
        else:
            max_clearance = max(
                self._parse_clearance(
                    getattr(inp, "clearance", ClearanceLevel.PUBLIC)
                )
                for inp in inputs
            )

        if max_clearance != ClearanceLevel.PUBLIC:
            logger.info(
                "TAINT_AUDIT: synthesis output raised to %s from %d input(s)",
                max_clearance.name,
                len(inputs),
            )

        return ToolResult.success(data=synthesis_output, clearance=max_clearance)

    def validate_no_laundering(
        self, inputs: list[ToolResult], output: ToolResult,
    ) -> bool:
        """Verify output clearance >= MAX(input clearances).

        Returns ``False`` if laundering detected (output has lower
        clearance than the highest input). ``True`` otherwise.
        """
        if not inputs:
            return True
        max_input_clearance = max(
            self._parse_clearance(
                getattr(inp, "clearance", ClearanceLevel.PUBLIC)
            )
            for inp in inputs
        )
        output_clearance = self._parse_clearance(
            getattr(output, "clearance", ClearanceLevel.PUBLIC)
        )
        return output_clearance >= max_input_clearance

    @staticmethod
    def _parse_clearance(raw: str | None) -> ClearanceLevel:
        """Parse a raw clearance string, defaulting to PUBLIC."""
        if raw is None:
            return ClearanceLevel.PUBLIC
        try:
            return ClearanceLevel[raw.upper()] if isinstance(raw, str) else raw
        except (KeyError, ValueError, AttributeError):
            return ClearanceLevel.PUBLIC


class ClearanceViolationError(GovernanceViolation):
    """Raised when synthesis output would launder clearance levels."""

    def __init__(
        self,
        message: str,
        *,
        max_seen: ClearanceLevel,
        output_level: ClearanceLevel,
    ) -> None:
        super().__init__(
            message,
            input_state={"max_seen": max_seen.name, "output_level": output_level.name},
        )
        self.max_seen = max_seen
        self.output_level = output_level
