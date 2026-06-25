"""
Tests for scripts/ci/trade_secret_wheel_gate.py (WS-F gate).

Coverage:
  - _scan_wheel: FAIL when calibration.py in RECORD (exact .py match)
  - _scan_wheel: FAIL when calibration_store.py in RECORD (exact .py match)
  - _scan_wheel: FAIL when compiled variant (.pyc, .so) in RECORD (stem match)
  - _scan_wheel: PASS when only legitimate interface modules present
  - _scan_wheel: PASS for governance/shacl/shapes.ttl (non-calibration governance file)
  - _scan_wheel: handles backslash path separators (Windows zip artefacts)
  - _scan_wheel: ignores blank lines in RECORD
  - _scan_wheel: exits 2 when RECORD missing from wheel
  - _report: exits 0 on empty violations
  - _report: exits 1 on non-empty violations (stderr output with path)
  - _report: dry_run=True exits 0 even on violations
  - CLI --wheel PATH clean: exit 0 + PASS in stdout
  - CLI --wheel PATH violation: exit 1 + FAIL in stdout
  - CLI --dry-run violation: exit 0 (inspection mode)
  - CLI --dry-run without --wheel: error
  - CLI --wheel not found: exit 2
"""

import io
import zipfile
from pathlib import Path
import subprocess
import sys

import pytest

# ---------------------------------------------------------------------------
# Import the gate module under test
# ---------------------------------------------------------------------------

# The gate lives at scripts/ci/trade_secret_wheel_gate.py.
# Import it directly so we can test individual functions in isolation.

import importlib.util
import os

_GATE_PATH = Path(__file__).parents[2] / "scripts" / "ci" / "trade_secret_wheel_gate.py"

spec = importlib.util.spec_from_file_location("trade_secret_wheel_gate", _GATE_PATH)
assert spec is not None, f"Cannot find gate at {_GATE_PATH}"
_gate = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(_gate)  # type: ignore[union-attr]

_scan_wheel = _gate._scan_wheel
_report = _gate._report
_DENY_LIST = _gate._DENY_LIST


# ---------------------------------------------------------------------------
# Helpers — build fake wheel zip in memory
# ---------------------------------------------------------------------------


def _make_wheel(record_lines: list[str], tmp_path: Path) -> Path:
    """Create a minimal .whl (zip) with the given RECORD content."""
    whl = tmp_path / "graqle-0.99.0-py3-none-any.whl"
    record_content = "\n".join(record_lines) + "\n"
    with zipfile.ZipFile(whl, "w") as zf:
        zf.writestr("graqle-0.99.0.dist-info/RECORD", record_content)
        # Add a dummy module so the zip is non-trivial
        zf.writestr("graqle/__init__.py", "")
        zf.writestr("graqle/core/__init__.py", "")
    return whl


def _record_lines(paths: list[str]) -> list[str]:
    """Build RECORD-format lines from a list of paths."""
    return [f"{p},sha256=abc123,999" for p in paths]


# ---------------------------------------------------------------------------
# _DENY_LIST sanity
# ---------------------------------------------------------------------------


def test_deny_list_contains_expected_entries():
    assert "graqle/governance/calibration.py" in _DENY_LIST
    assert "graqle/governance/calibration_store.py" in _DENY_LIST


# ---------------------------------------------------------------------------
# _scan_wheel: planted violation — calibration.py
# ---------------------------------------------------------------------------


def test_scan_detects_calibration_violation(tmp_path):
    lines = _record_lines([
        "graqle/__init__.py",
        "graqle/core/engine.py",
        "graqle/governance/calibration.py",   # <-- violation
        "graqle/governance/__init__.py",
    ])
    whl = _make_wheel(lines, tmp_path)
    violations = _scan_wheel(whl)
    assert "graqle/governance/calibration.py" in violations


# ---------------------------------------------------------------------------
# _scan_wheel: planted violation — calibration_store.py
# ---------------------------------------------------------------------------


def test_scan_detects_calibration_store_violation(tmp_path):
    lines = _record_lines([
        "graqle/__init__.py",
        "graqle/governance/calibration_store.py",  # <-- violation
    ])
    whl = _make_wheel(lines, tmp_path)
    violations = _scan_wheel(whl)
    assert "graqle/governance/calibration_store.py" in violations


# ---------------------------------------------------------------------------
# _scan_wheel: both violations simultaneously
# ---------------------------------------------------------------------------


def test_scan_detects_both_violations(tmp_path):
    lines = _record_lines([
        "graqle/__init__.py",
        "graqle/governance/calibration.py",
        "graqle/governance/calibration_store.py",
    ])
    whl = _make_wheel(lines, tmp_path)
    violations = _scan_wheel(whl)
    assert len(violations) == 2


# ---------------------------------------------------------------------------
# _scan_wheel: PASS — only legitimate interface modules
# ---------------------------------------------------------------------------


def test_scan_clean_wheel_returns_no_violations(tmp_path):
    lines = _record_lines([
        "graqle/__init__.py",
        "graqle/core/engine.py",
        "graqle/governance/__init__.py",
        "graqle/governance/shacl/shapes.ttl",
        "graqle/metering/__init__.py",
        "graqle/edition.py",
        "graqle/verify/__init__.py",
        "graqle-0.99.0.dist-info/METADATA",
        "graqle-0.99.0.dist-info/RECORD,,",
    ])
    whl = _make_wheel(lines, tmp_path)
    violations = _scan_wheel(whl)
    assert violations == []


# ---------------------------------------------------------------------------
# _scan_wheel: shacl/shapes.ttl is NOT in deny list (legitimate exclusion path)
# ---------------------------------------------------------------------------


def test_scan_does_not_flag_shacl_shapes(tmp_path):
    lines = _record_lines(["graqle/governance/shacl/shapes.ttl"])
    whl = _make_wheel(lines, tmp_path)
    violations = _scan_wheel(whl)
    assert violations == []


# ---------------------------------------------------------------------------
# _scan_wheel: Windows backslash separator normalisation
# ---------------------------------------------------------------------------


def test_scan_normalises_backslash_separators(tmp_path):
    # Some tools produce Windows-style paths in RECORD on Windows CI
    lines = ["graqle\\governance\\calibration.py,sha256=abc,999"]
    whl = _make_wheel(lines, tmp_path)
    violations = _scan_wheel(whl)
    assert "graqle\\governance\\calibration.py" in violations


# ---------------------------------------------------------------------------
# _scan_wheel: blank lines in RECORD are ignored
# ---------------------------------------------------------------------------


def test_scan_ignores_blank_lines(tmp_path):
    record = "\n\ngraqle/__init__.py,sha256=abc,1\n\n\n"
    whl = tmp_path / "graqle-0.99.0-py3-none-any.whl"
    with zipfile.ZipFile(whl, "w") as zf:
        zf.writestr("graqle-0.99.0.dist-info/RECORD", record)
    violations = _scan_wheel(whl)
    assert violations == []


# ---------------------------------------------------------------------------
# _scan_wheel: exits 2 when RECORD is missing from wheel
# ---------------------------------------------------------------------------


def test_scan_exits_2_when_record_missing(tmp_path):
    whl = tmp_path / "graqle-0.99.0-py3-none-any.whl"
    with zipfile.ZipFile(whl, "w") as zf:
        zf.writestr("graqle/__init__.py", "")
        # Intentionally NO .dist-info/RECORD entry
    with pytest.raises(SystemExit) as exc:
        _scan_wheel(whl)
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# Zip Slip / path traversal guard
# ---------------------------------------------------------------------------


def test_scan_exits_2_on_zip_slip_absolute_path(tmp_path):
    whl = tmp_path / "graqle-0.99.0-py3-none-any.whl"
    with zipfile.ZipFile(whl, "w") as zf:
        zf.writestr("/etc/passwd", "root:x:0:0")
        zf.writestr("graqle-0.99.0.dist-info/RECORD", "graqle/__init__.py,,\n")
    with pytest.raises(SystemExit) as exc:
        _scan_wheel(whl)
    assert exc.value.code == 2


def test_scan_exits_2_on_zip_slip_traversal_path(tmp_path):
    whl = tmp_path / "graqle-0.99.0-py3-none-any.whl"
    with zipfile.ZipFile(whl, "w") as zf:
        zf.writestr("../../etc/passwd", "root:x:0:0")
        zf.writestr("graqle-0.99.0.dist-info/RECORD", "graqle/__init__.py,,\n")
    with pytest.raises(SystemExit) as exc:
        _scan_wheel(whl)
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# _report: exits 0 on empty violations list
# ---------------------------------------------------------------------------


def test_report_exits_0_on_clean(capsys):
    with pytest.raises(SystemExit) as exc:
        _report([])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "PASS" in out


# ---------------------------------------------------------------------------
# _report: exits 1 and prints violation paths
# ---------------------------------------------------------------------------


def test_report_exits_1_on_violation(capsys):
    with pytest.raises(SystemExit) as exc:
        _report(["graqle/governance/calibration.py"])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "calibration.py" in out


# ---------------------------------------------------------------------------
# CLI integration: --wheel PATH accepted, --dry-run --wheel works
# ---------------------------------------------------------------------------


def test_cli_wheel_path_clean(tmp_path):
    lines = _record_lines(["graqle/__init__.py", "graqle/core/engine.py"])
    whl = _make_wheel(lines, tmp_path)
    result = subprocess.run(
        [sys.executable, str(_GATE_PATH), "--wheel", str(whl)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_cli_wheel_path_violation(tmp_path):
    lines = _record_lines([
        "graqle/__init__.py",
        "graqle/governance/calibration.py",
    ])
    whl = _make_wheel(lines, tmp_path)
    result = subprocess.run(
        [sys.executable, str(_GATE_PATH), "--wheel", str(whl)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "FAIL" in result.stdout
    assert "calibration.py" in result.stdout


def test_cli_dry_run_requires_wheel(tmp_path):
    result = subprocess.run(
        [sys.executable, str(_GATE_PATH), "--dry-run"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "error" in result.stderr.lower() or "requires" in result.stderr.lower()


def test_cli_wheel_not_found_exits_2(tmp_path):
    result = subprocess.run(
        [sys.executable, str(_GATE_PATH), "--wheel", "/nonexistent/path/graqle.whl"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2


# ---------------------------------------------------------------------------
# Compiled artifact stem matching (BLOCKER fix)
# ---------------------------------------------------------------------------


def test_scan_detects_compiled_pyc_variant(tmp_path):
    # .pyc compiled variant at the same directory level must be caught by stem match.
    # Wheels typically ship .pyc under __pycache__; the stem match covers the
    # same-directory compiled form (e.g. calibration.cpython-311.pyc placed at
    # the governance/ level, as some build tools do).
    lines = _record_lines([
        "graqle/__init__.py",
        "graqle/governance/calibration.cpython-311.pyc",
    ])
    whl = _make_wheel(lines, tmp_path)
    violations = _scan_wheel(whl)
    assert any("calibration" in v for v in violations), f"Expected stem match, got: {violations}"


def test_scan_detects_compiled_so_variant(tmp_path):
    # .so shared-object compiled variant must be caught by stem match
    lines = _record_lines([
        "graqle/__init__.py",
        "graqle/governance/calibration.cpython-311-x86_64-linux-gnu.so",
    ])
    whl = _make_wheel(lines, tmp_path)
    violations = _scan_wheel(whl)
    assert any("calibration" in v for v in violations), f"Expected stem match, got: {violations}"


def test_scan_detects_calibration_store_pyd_variant(tmp_path):
    # .pyd Windows compiled variant for calibration_store
    lines = _record_lines([
        "graqle/governance/calibration_store.cp311-win_amd64.pyd",
    ])
    whl = _make_wheel(lines, tmp_path)
    violations = _scan_wheel(whl)
    assert any("calibration_store" in v for v in violations), f"Expected stem match, got: {violations}"


# ---------------------------------------------------------------------------
# _report: violation output goes to stderr
# ---------------------------------------------------------------------------


def test_report_prints_violation_to_stderr(capsys):
    with pytest.raises(SystemExit) as exc:
        _report(["graqle/governance/calibration.py"])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    # Violation path appears in stderr (repr-quoted for log-injection safety)
    assert "calibration.py" in captured.err


# ---------------------------------------------------------------------------
# _report: dry_run=True exits 0 even when violations present
# ---------------------------------------------------------------------------


def test_report_dry_run_exits_0_on_violation(capsys):
    with pytest.raises(SystemExit) as exc:
        _report(["graqle/governance/calibration.py"], dry_run=True)
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "dry-run" in out.lower()


# ---------------------------------------------------------------------------
# CLI --dry-run with violation exits 0 (inspection mode)
# ---------------------------------------------------------------------------


def test_cli_dry_run_violation_exits_0(tmp_path):
    lines = _record_lines([
        "graqle/__init__.py",
        "graqle/governance/calibration.py",
    ])
    whl = _make_wheel(lines, tmp_path)
    result = subprocess.run(
        [sys.executable, str(_GATE_PATH), "--dry-run", "--wheel", str(whl)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "dry-run" in result.stdout.lower()
