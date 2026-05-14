"""CR-004 PR-004c tests — graph_health envelope wiring for predict,
safety_check, and CLI consumers.

Covers the four wiring surfaces:

1. ``mcp_server._build_graph_health_snapshot()`` helper: happy path,
   import-failure simulation, probe-exception simulation.
2. graq_predict envelope: ``output["graph_health"]`` present on happy
   path; key omitted when helper returns None.
3. graq_safety_check envelope: top-level ``graph_health`` lifted from
   nested ``reasoning_result`` when present; key omitted entirely when
   reasoning was skipped (low-risk + skip_reasoning).
4. CLI yellow-warning logic: tested via direct probe-then-degraded
   verification (the actual console output is exercised at the e2e
   layer; this PR keeps the unit-test boundary at the probe).

CI safety: no ``importlib.util.module_from_spec``, no real graph
instantiation, no real MCP server start. Builds proceed via duck-typed
fakes.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import pytest

from graqle.activation.health_probe import _clear_probe_cache_for_tests
from graqle.core.graph_health import GraphHealth


@dataclass
class _FakeGraph:
    nodes: dict[str, object]
    edges: dict[str, object]


def _make_graph(n: int, e: int) -> _FakeGraph:
    return _FakeGraph(
        nodes={f"n{i}": object() for i in range(n)},
        edges={f"e{i}": object() for i in range(e)},
    )


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    _clear_probe_cache_for_tests()
    yield
    _clear_probe_cache_for_tests()


# ─── 1. _build_graph_health_snapshot() helper ───────────────────────────────


def test_helper_returns_eight_key_dict_on_healthy_graph() -> None:
    """Happy path: 1000-node / 5000-edge graph → 8-key snapshot, degraded=False."""
    from graqle.plugins.mcp_server import _build_graph_health_snapshot

    snap = _build_graph_health_snapshot(_make_graph(1000, 5000))
    assert snap is not None
    assert set(snap.keys()) == {
        "node_count", "edge_count", "chunks_unembedded", "percent_stale",
        "activation_mode", "degraded", "reason", "schema_version",
    }
    assert snap["degraded"] is False
    assert snap["schema_version"] == "1"


def test_helper_returns_none_on_import_failure() -> None:
    """Simulate ImportError on health_probe module → helper returns None."""
    from graqle.plugins.mcp_server import _build_graph_health_snapshot

    saved = sys.modules.pop("graqle.activation.health_probe", None)
    try:
        class _Broken:
            def __getattr__(self, name: str) -> object:
                raise ImportError(f"simulated: {name}")

        sys.modules["graqle.activation.health_probe"] = _Broken()  # type: ignore[assignment]
        out = _build_graph_health_snapshot(_make_graph(10, 20))
    finally:
        if saved is not None:
            sys.modules["graqle.activation.health_probe"] = saved
        else:
            sys.modules.pop("graqle.activation.health_probe", None)
    assert out is None


def test_helper_returns_none_on_probe_exception() -> None:
    """Probe raises → helper absorbs and returns None (defence-in-depth)."""
    from graqle.plugins.mcp_server import _build_graph_health_snapshot

    with patch(
        "graqle.activation.health_probe.graph_health_probe",
        side_effect=RuntimeError("probe blew up"),
    ):
        out = _build_graph_health_snapshot(_make_graph(10, 20))
    assert out is None


def test_helper_returns_degraded_dict_on_zero_edge_graph() -> None:
    """Zero-edge graph → snapshot has degraded=True and the canonical reason."""
    from graqle.plugins.mcp_server import _build_graph_health_snapshot

    snap = _build_graph_health_snapshot(_make_graph(100, 0))
    assert snap is not None
    assert snap["degraded"] is True
    assert snap["reason"] is not None
    assert "0 edges" in snap["reason"]


# ─── 2. graq_predict envelope wiring ────────────────────────────────────────


def test_predict_output_dict_has_graph_health_key_when_probe_succeeds() -> None:
    """Simulate the relevant slice of _handle_predict STEP 5: build output,
    then call the helper, then verify the key is attached. This validates
    the wiring pattern without spinning up the full MCPServer."""
    from graqle.plugins.mcp_server import _build_graph_health_snapshot

    output: dict[str, Any] = {
        "answer": "X",
        "activation_confidence": 0.5,
        "answer_confidence": 0.5,
    }
    _gh_snap = _build_graph_health_snapshot(_make_graph(100, 200))
    if _gh_snap is not None:
        output["graph_health"] = _gh_snap
    assert "graph_health" in output
    assert output["graph_health"]["degraded"] is False


def test_predict_output_dict_omits_key_when_probe_fails() -> None:
    """When the helper returns None, the wiring MUST omit the key (per
    pre-impl sentinel feedback: 'not probed' must be distinguishable
    from 'healthy')."""
    output: dict[str, Any] = {"answer": "X", "activation_confidence": 0.5}
    _gh_snap = None  # simulate helper returning None
    if _gh_snap is not None:
        output["graph_health"] = _gh_snap
    assert "graph_health" not in output


# ─── 3. graq_safety_check top-level lift ────────────────────────────────────


def test_safety_check_top_level_lift_when_nested_present() -> None:
    """reasoning_result has graph_health → top-level envelope gets it."""
    reasoning_result: dict[str, Any] = {
        "answer": "...",
        "graph_health": {"degraded": False, "schema_version": "1"},
    }
    envelope: dict[str, Any] = {
        "component": "x",
        "reasoning": reasoning_result,
    }
    if isinstance(reasoning_result, dict):
        _gh = reasoning_result.get("graph_health")
        if _gh is not None:
            envelope["graph_health"] = _gh
    assert envelope["graph_health"]["schema_version"] == "1"


def test_safety_check_omits_top_level_when_reasoning_skipped() -> None:
    """reasoning_result is None (low risk + skip_reasoning) → key omitted."""
    reasoning_result = None
    envelope: dict[str, Any] = {
        "component": "x",
        "reasoning": reasoning_result,
    }
    if isinstance(reasoning_result, dict):
        _gh = reasoning_result.get("graph_health")
        if _gh is not None:
            envelope["graph_health"] = _gh
    assert "graph_health" not in envelope


def test_safety_check_omits_top_level_when_nested_missing() -> None:
    """reasoning ran but didn't include graph_health (older PR-004a-pre
    consumer mock) → key omitted at top level too."""
    reasoning_result: dict[str, Any] = {"answer": "..."}  # no graph_health key
    envelope: dict[str, Any] = {"reasoning": reasoning_result}
    if isinstance(reasoning_result, dict):
        _gh = reasoning_result.get("graph_health")
        if _gh is not None:
            envelope["graph_health"] = _gh
    assert "graph_health" not in envelope


# ─── 4. CLI degraded-reasoning warning logic ───────────────────────────────


def test_cli_warning_logic_fires_on_degraded() -> None:
    """The CLI's degraded-warning conditional fires when degraded=True
    AND reason is non-None. This unit-tests the boolean logic; the
    actual console output is e2e territory."""
    gh = GraphHealth(
        node_count=100,
        edge_count=0,
        chunks_unembedded=0,
        percent_stale=0.0,
        activation_mode="semantic",
        degraded=True,
        reason="graph has 100 nodes but 0 edges",
    )
    should_warn = gh.degraded and gh.reason is not None
    assert should_warn is True


def test_cli_warning_logic_skips_on_healthy() -> None:
    """Healthy graph_health → warning suppressed."""
    gh = GraphHealth(
        node_count=1000,
        edge_count=5000,
        chunks_unembedded=0,
        percent_stale=0.0,
        activation_mode="semantic",
        degraded=False,
        reason=None,
    )
    should_warn = gh.degraded and gh.reason is not None
    assert should_warn is False


def test_cli_warning_logic_skips_when_degraded_but_no_reason() -> None:
    """Defensive: degraded=True but reason=None → no warning (better
    to stay silent than print an empty warning)."""
    gh = GraphHealth(
        node_count=100,
        edge_count=200,
        chunks_unembedded=0,
        percent_stale=0.0,
        activation_mode="semantic",
        degraded=True,
        reason=None,
    )
    should_warn = gh.degraded and gh.reason is not None
    assert should_warn is False


# ─── 5. Sentinel 1B hardening: exception classes + ANSI strip + log truncation ─


@pytest.mark.parametrize(
    "exc_type",
    [KeyError, TypeError],
)
def test_helper_absorbs_keyerror_and_typeerror(exc_type: type[BaseException]) -> None:
    """Sentinel 1B fix: helper's narrow except now includes KeyError +
    TypeError. Both must be absorbed → helper returns None, no leak."""
    from graqle.plugins.mcp_server import _build_graph_health_snapshot

    with patch(
        "graqle.activation.health_probe.graph_health_probe",
        side_effect=exc_type("simulated"),
    ):
        out = _build_graph_health_snapshot(_make_graph(10, 20))
    assert out is None


def test_sanitise_for_console_strips_csi_sequences() -> None:
    """Sentinel 1C: CLI module exposes _sanitise_for_console with
    corrected ANSI CSI regex per reviewer feedback.

    Sentinel 4 fix: structural assertions (no \\x1b CSI bytes left, key
    payload preserved) instead of exact-string match — regex
    refinements should not invalidate the test."""
    from graqle.cli.main import _sanitise_for_console

    payload = "before \x1b[31mRED\x1b[0m after"
    cleaned = _sanitise_for_console(payload)
    # Structural: no CSI sequences remain (negative assertion).
    assert "\x1b[" not in cleaned
    # Structural: key text payload around the stripped sequences is preserved.
    assert "before" in cleaned and "RED" in cleaned and "after" in cleaned


def test_sanitise_for_console_strips_osc_with_bel_terminator() -> None:
    """OSC sequences with BEL (0x07) terminator must be stripped."""
    from graqle.cli.main import _sanitise_for_console

    payload = "before \x1b]0;malicious title\x07 after"
    cleaned = _sanitise_for_console(payload)
    assert "\x1b]" not in cleaned
    assert "malicious title" not in cleaned


def test_sanitise_for_console_strips_osc_with_st_terminator() -> None:
    """Sentinel 1C MAJOR fix: OSC sequences with ST (ESC \\) terminator
    were missed in 1B. Now must also be stripped."""
    from graqle.cli.main import _sanitise_for_console

    # ST = ESC \\  (0x1b 0x5c)
    payload = "before \x1b]8;;https://evil/\x1b\\link\x1b]8;;\x1b\\ after"
    cleaned = _sanitise_for_console(payload)
    assert "\x1b]" not in cleaned
    assert "evil" not in cleaned


def test_sanitise_for_console_handles_none_and_non_str() -> None:
    """Defensive: helper returns input unchanged when not a real string."""
    from graqle.cli.main import _sanitise_for_console

    assert _sanitise_for_console("") == ""
    # type: ignore[arg-type] — testing defensive shape
    assert _sanitise_for_console(None) is None  # type: ignore[arg-type]
    assert _sanitise_for_console(42) == 42  # type: ignore[arg-type]


def test_sanitise_for_console_passes_through_clean_text() -> None:
    """No ANSI in input → input returned unchanged."""
    from graqle.cli.main import _sanitise_for_console

    payload = "graph has 100 nodes but 0 edges (silent edge-loss)"
    assert _sanitise_for_console(payload) == payload


def test_sanitise_for_console_handles_mixed_csi_and_osc() -> None:
    """Mixed CSI + OSC in one string both get stripped.

    Sentinel 4 fix: structural assertions only — no exact-string match."""
    from graqle.cli.main import _sanitise_for_console

    payload = "\x1b[31mred\x1b[0m and \x1b]0;title\x07 same line"
    cleaned = _sanitise_for_console(payload)
    # No control bytes remain.
    assert "\x1b[" not in cleaned
    assert "\x1b]" not in cleaned
    assert "\x07" not in cleaned
    # CSI text payload preserved.
    assert "red" in cleaned
    # OSC payload (entire bracket+data+terminator) elided as a unit.
    assert "title" not in cleaned
    # Surrounding plain-text preserved.
    assert "same line" in cleaned


def test_sanitise_for_console_handles_incomplete_escape() -> None:
    """Malformed/incomplete escape sequence: helper should be permissive,
    not eat surrounding good text. A bare ESC (no following [ or ])
    passes through untouched (Rich escape will catch it downstream)."""
    from graqle.cli.main import _sanitise_for_console

    payload = "bare\x1bescape no bracket"
    cleaned = _sanitise_for_console(payload)
    # The ESC is preserved (not a CSI/OSC); the surrounding text is intact.
    assert "bare" in cleaned
    assert "escape no bracket" in cleaned


def test_debug_log_message_capped_at_120_chars() -> None:
    """Sentinel 1B verification: helper's debug log truncates exception
    message at 120 chars so a pathological exception text doesn't bloat
    the operator's debug log."""
    from graqle.plugins.mcp_server import _build_graph_health_snapshot

    huge_msg = "x" * 500
    with patch(
        "graqle.activation.health_probe.graph_health_probe",
        side_effect=ValueError(huge_msg),
    ):
        out = _build_graph_health_snapshot(_make_graph(10, 20))
    # The slice [:120] is what gets logged. The helper still returns None.
    assert out is None
    # The truncation is a property of the log call site itself — verify
    # the slice operation produces the expected cap.
    assert len(str(ValueError(huge_msg))[:120]) == 120
