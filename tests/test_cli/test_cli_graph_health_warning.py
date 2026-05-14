"""CR-004 PR-004d tests — CLI yellow-warning end-to-end behaviour.

Covers the full probe → degraded → sanitise → print path through the
``graq run`` / ``graq reason`` CLI command boundary, complementing:

  * PR-004a unit tests in ``tests/test_activation/test_graph_health_probe.py``
    (probe behaviour matrix on the helper itself).
  * PR-004b/c envelope-wiring tests in
    ``tests/test_reasoning/test_graph_health_envelope_wiring.py`` and
    ``tests/test_reasoning/test_reasoning_result_graph_health.py``
    (MCP envelope shape on graq_reason / graq_predict / graq_safety_check).

The CLI yellow-warning was explicitly deferred from PR-004c to "the e2e
layer" per the docstring of ``test_graph_health_envelope_wiring.py`` §
1.13–1.15. This file closes that gap.

Test strategy:

  * Patch ``graqle.cli.main.graph_health_probe`` to return a controlled
    ``GraphHealth`` snapshot — degraded with a sanitised reason for the
    yellow-banner case, healthy for the silent case.
  * Patch ``_load_graph`` + ``_create_backend_from_config`` +
    ``asyncio.run`` so the test exercises only the wiring, not the real
    reasoning pipeline. Same patch surface as
    ``tests/test_cli/test_bench_failfast.py``.
  * Capture ``console.print`` calls to assert the yellow banner is
    printed (degraded case) or absent (healthy case). Asserting on
    ``console.print`` arguments — not on terminal output — is robust to
    Rich's environment-dependent rendering.

CI safety: no real graph load, no real backend, no real ``asyncio.run``
of ``areason``. Two parametrised scenarios — the test footprint is
intentionally narrow because the deeper coverage is already in
PR-004a/b/c.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from graqle.core.graph_health import GraphHealth


# ── Test doubles ─────────────────────────────────────────────────────────


@dataclass
class _StubReasoningResult:
    """Minimal duck-typed ReasoningResult — only the fields the CLI reads.

    The CLI path under test only writes ``graph_health`` and reads
    ``answer`` / ``confidence`` further down. Anything else can be a
    no-op default.
    """
    answer: str = "stub answer"
    confidence: float = 0.9
    rounds_completed: int = 1
    node_count: int = 10
    cost_usd: float = 0.0
    latency_ms: int = 0
    active_nodes: list = None  # type: ignore[assignment]
    graph_health: GraphHealth | None = None

    def __post_init__(self) -> None:
        if self.active_nodes is None:
            self.active_nodes = []


def _degraded_health(reason: str = "0 edges — graph is empty") -> GraphHealth:
    return GraphHealth(
        node_count=42,
        edge_count=0,
        chunks_unembedded=0,
        percent_stale=0.0,
        activation_mode="keyword_fallback",
        degraded=True,
        reason=reason,
        schema_version="1",
    )


def _healthy_health() -> GraphHealth:
    return GraphHealth(
        node_count=1000,
        edge_count=5000,
        chunks_unembedded=0,
        percent_stale=0.0,
        activation_mode="semantic",
        degraded=False,
        reason=None,
        schema_version="1",
    )


# ── E2E tests ────────────────────────────────────────────────────────────


def test_run_command_prints_yellow_banner_when_degraded() -> None:
    """``graq run`` prints a yellow ``⚠ degraded reasoning`` banner when
    the probe reports ``degraded=True`` with a non-empty reason.

    The reason text is rendered through Rich markup escape so that any
    accidental ``[bold]``-shaped tokens in the reason are displayed as
    literal text rather than parsed as markup — guards against the
    PR-004c sentinel-feedback class of finding.
    """
    from graqle.cli.main import run

    mock_backend = MagicMock()
    mock_backend.is_fallback = False
    mock_graph = MagicMock()

    captured_prints: list[str] = []

    def _capture_print(*args: Any, **kwargs: Any) -> None:
        if args:
            captured_prints.append(str(args[0]))

    with patch("graqle.cli.main._load_graph", return_value=mock_graph), \
         patch(
             "graqle.cli.main._create_backend_from_config",
             return_value=mock_backend,
         ), \
         patch(
             "graqle.activation.health_probe.graph_health_probe",
             return_value=_degraded_health(),
         ), \
         patch(
             "asyncio.run",
             return_value=_StubReasoningResult(),
         ), \
         patch.object(
             __import__("graqle.cli.main", fromlist=["console"]).console,
             "print",
             side_effect=_capture_print,
         ):
        # Run the typer function directly — same calling pattern as
        # tests/test_cli/test_bench_failfast.py.
        run(
            query="anything — areason is mocked",
            config="graqle.yaml",
            strategy="hybrid",
            protocol="consensus",
            max_rounds=1,
            verbose=False,
            explain=False,
            coordinator=False,
        )

    # The yellow banner must appear in the captured print stream.
    banner_lines = [
        line for line in captured_prints
        if "degraded reasoning" in line and "yellow" in line
    ]
    assert banner_lines, (
        f"Expected '⚠ degraded reasoning' yellow banner in CLI output. "
        f"Got: {captured_prints!r}"
    )
    # Reason text is included in the banner (sanitised + Rich-escaped).
    assert any("0 edges" in line for line in banner_lines), (
        f"Expected probe reason ('0 edges') to be embedded in the banner. "
        f"Got: {banner_lines!r}"
    )


def test_run_command_no_banner_when_healthy() -> None:
    """``graq run`` MUST NOT print any degraded-reasoning banner when the
    probe reports ``degraded=False``. Healthy graphs go through the
    print path silently — the user sees only the answer.
    """
    from graqle.cli.main import run

    mock_backend = MagicMock()
    mock_backend.is_fallback = False
    mock_graph = MagicMock()

    captured_prints: list[str] = []

    def _capture_print(*args: Any, **kwargs: Any) -> None:
        if args:
            captured_prints.append(str(args[0]))

    with patch("graqle.cli.main._load_graph", return_value=mock_graph), \
         patch(
             "graqle.cli.main._create_backend_from_config",
             return_value=mock_backend,
         ), \
         patch(
             "graqle.activation.health_probe.graph_health_probe",
             return_value=_healthy_health(),
         ), \
         patch(
             "asyncio.run",
             return_value=_StubReasoningResult(),
         ), \
         patch.object(
             __import__("graqle.cli.main", fromlist=["console"]).console,
             "print",
             side_effect=_capture_print,
         ):
        run(
            query="anything — areason is mocked",
            config="graqle.yaml",
            strategy="hybrid",
            protocol="consensus",
            max_rounds=1,
            verbose=False,
            explain=False,
            coordinator=False,
        )

    # Inverse property — no degraded banner anywhere in the capture.
    banner_lines = [
        line for line in captured_prints
        if "degraded reasoning" in line
    ]
    assert not banner_lines, (
        f"Did NOT expect any 'degraded reasoning' banner on a healthy "
        f"graph. Got: {banner_lines!r}"
    )
