"""R22 SGCV — Fail-closed SHACL output gate.

AC-3 invariant: if validation fails, the gate BLOCKS. No warning mode,
no bypass. Raises loudly if pyshacl is not installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

try:
    import pyshacl as _pyshacl  # noqa: F401
    _SHACL_AVAILABLE = True
except ImportError:
    _SHACL_AVAILABLE = False

from graqle.governance.trace_schema import GovernedTrace


@dataclass
class ShaclGateResult:
    """Result of the fail-closed SHACL output gate."""

    passed: bool
    report: "ShaclValidationResult"  # type: ignore[name-defined]
    blocked_at: str | None  # ISO8601 timestamp if blocked, None if passed


def check_output_gate(
    trace: GovernedTrace,
    validator: "ShaclValidator",  # type: ignore[name-defined]
) -> ShaclGateResult:
    """Validate a GovernedTrace through the fail-closed SHACL gate.

    Always fail-closed (AC-3): any SHACL violation → gate BLOCKS.
    Raises ImportError if pyshacl is not installed.
    """
    if not _SHACL_AVAILABLE:
        raise ImportError(
            "R22 SHACL gate requires pyshacl: pip install 'graqle[api]'"
        )

    result = validator.validate(trace)

    if not result.conforms:
        return ShaclGateResult(
            passed=False,
            report=result,
            blocked_at=datetime.now(timezone.utc).isoformat(),
        )

    return ShaclGateResult(passed=True, report=result, blocked_at=None)


# Deferred import for type annotations — avoids circular imports at module load
from graqle.governance.shacl.validator import ShaclValidationResult, ShaclValidator  # noqa: E402, F401
