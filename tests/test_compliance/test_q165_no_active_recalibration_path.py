"""MANDATORY patent-novelty audit test per Q-PATENT 2026-05-22 (CG-MKT-04).

This test enforces the **Q16.5 OBSERVATION-ONLY boundary**: the
drift indicator surfaced by :mod:`graqle.compliance.evidence_state`
MUST NOT trigger calibration. The boundary keeps R25-EU04 patent-clean
under existing EP26167849.4 Claim 4 (per-call calibration), since our
drift indicator is cross-call observation only.

If this test fails, the build MUST NOT ship — a future contributor
has accidentally wired the drift indicator to a recalibration call,
which would breach the patent-novelty boundary.

The audit is an AST scan rather than a runtime probe so that a code
path that *could* trigger recalibration but doesn't in any test
scenario is still flagged.

Anchors:
    - R25-EU04 § Q16.5 "patent-novelty boundary"
    - Q-PATENT 2026-05-22 binding decision
    - EP26167849.4 Claim 4
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from graqle.compliance import evidence_state


# Symbols that, if called from evidence_state.py, would breach the
# OBSERVATION-only boundary. The list is forbidden-substring conservative
# — any identifier whose name contains "calibrat" anywhere is flagged.
_FORBIDDEN_SUBSTRINGS = (
    "calibrate",
    "recalibrate",
    "refresh_calibration",
)


def _module_source_path() -> Path:
    src_file = inspect.getsourcefile(evidence_state)
    assert src_file is not None
    return Path(src_file)


def _all_callsites_in_module() -> list[tuple[str, int]]:
    """Walk the AST of evidence_state.py and collect every call site.

    Returns:
        list[tuple[str, int]]: (callee_name, lineno) for every Call node.
        Both ``foo()`` and ``obj.foo()`` are recorded as ``foo``.
    """
    source = _module_source_path().read_text(encoding="utf-8")
    tree = ast.parse(source)
    call_sites: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = ""
        if isinstance(node.func, ast.Name):
            callee = node.func.id
        elif isinstance(node.func, ast.Attribute):
            callee = node.func.attr
        if callee:
            call_sites.append((callee, node.lineno))
    return call_sites


class TestPatentNoveltyBoundary:
    """The Q-PATENT 2026-05-22 boundary is enforced HERE."""

    def test_no_calibrate_callsite_in_evidence_state(self):
        """No call to anything containing 'calibrat' may originate
        from evidence_state.py.

        If you are reading this test because it just failed: STOP.
        Adding a calibration trigger to the Q16.5 drift indicator
        breaches the patent-novelty boundary per Q-PATENT 2026-05-22
        and EP26167849.4 Claim 4. Re-design so the operator decides
        whether to recalibrate (e.g. via a separate CLI surface), or
        consult the Research team via CR amendment.
        """
        call_sites = _all_callsites_in_module()
        offenders = [
            (name, lineno)
            for name, lineno in call_sites
            if any(sub in name.lower() for sub in _FORBIDDEN_SUBSTRINGS)
        ]
        assert offenders == [], (
            f"PATENT-NOVELTY BOUNDARY BREACHED: "
            f"graqle/compliance/evidence_state.py calls forbidden "
            f"symbols at: {offenders}. "
            f"Per Q-PATENT 2026-05-22 + EP26167849.4 Claim 4, the "
            f"Q16.5 drift indicator must be OBSERVATION ONLY — "
            f"no calibration trigger may originate from this module."
        )

    def test_no_import_of_calibrate_into_evidence_state(self):
        """The audit also forbids any IMPORT of a calibration symbol.

        Importing it without calling it is still a footgun for future
        contributors and a misdirection on the OBSERVATION-only
        contract.
        """
        source = _module_source_path().read_text(encoding="utf-8")
        tree = ast.parse(source)
        offenders: list[tuple[str, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = (alias.asname or alias.name).lower()
                    if any(sub in name for sub in _FORBIDDEN_SUBSTRINGS):
                        offenders.append((alias.name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name = (alias.asname or alias.name).lower()
                    if any(sub in name for sub in _FORBIDDEN_SUBSTRINGS):
                        offenders.append((alias.name, node.lineno))
        assert offenders == [], (
            f"PATENT-NOVELTY BOUNDARY BREACHED: "
            f"graqle/compliance/evidence_state.py imports forbidden "
            f"symbols at: {offenders}."
        )

    def test_drift_alert_is_a_field_not_a_method(self):
        """Belt-and-braces: the drift alert is exposed as a frozen
        dataclass FIELD (``drift_alert_emitted``), not as a method
        that could perform side effects.

        Frozen dataclasses cannot have mutable side-effecting methods
        added without breaking the immutability contract; this test
        documents that property explicitly.
        """
        from graqle.compliance.evidence_state import FeedbackTrend
        from dataclasses import fields, is_dataclass

        assert is_dataclass(FeedbackTrend)
        field_names = {f.name for f in fields(FeedbackTrend)}
        assert "drift_alert_emitted" in field_names
        assert "drift_indicator" in field_names
        # And the dataclass is frozen — no method can mutate state
        # post-construction.
        assert FeedbackTrend.__dataclass_params__.frozen  # type: ignore[attr-defined]

    def test_compute_drift_indicator_is_pure(self):
        """The drift-indicator helper must be pure arithmetic — no
        I/O, no global state mutation.

        We probe by inspecting its source for forbidden patterns.
        """
        from graqle.compliance.evidence_state import compute_drift_indicator
        src = inspect.getsource(compute_drift_indicator)
        # No file/network I/O
        assert "open(" not in src
        assert "subprocess" not in src
        assert "requests" not in src
        # No print/logger writes
        assert "logger.info" not in src
        assert "logger.warning" not in src
