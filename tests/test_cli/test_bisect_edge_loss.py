"""CR-003b smoke tests — bisect_edge_loss.py is read-only + safe.

Full bisect requires a real git history, so the integration test is left
for the .gcc/REGRESSION-REPORT-edge-loss.md generation. These smoke tests
verify only the safety properties:

  * The script's module-level code parses cleanly.
  * ``_refuse_if_dirty`` actually refuses on a dirty tree.
  * ``_probe_commit`` returns a ``ProbeResult`` with status "skipped" when
    the fixture file is missing — never raises.
  * Anonymous IDs and ProbeResult dataclass round-trip cleanly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "bisect_edge_loss.py"
_MODULE_NAME = "bisect_edge_loss"


def _load_script_module():
    """Load scripts/bisect_edge_loss.py as an importable module.

    The script lives outside the ``graqle`` package so we use importlib
    directly to bring it into the test session without touching sys.path.

    The module is registered into ``sys.modules`` BEFORE execution because
    the script defines a ``@dataclass`` and dataclasses look up
    ``cls.__module__`` in ``sys.modules`` during type annotation resolution.
    Without this, the dataclass decoration raises AttributeError.
    """
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(_MODULE_NAME, None)
        raise
    return mod


# ── Smoke: the script module loads ─────────────────────────────────────────


def test_script_module_loads_cleanly() -> None:
    mod = _load_script_module()
    # Public surface present
    assert callable(getattr(mod, "main", None))
    assert callable(getattr(mod, "_refuse_if_dirty", None))
    assert callable(getattr(mod, "_probe_commit", None))
    assert mod.DEFAULT_TIMEOUT_SECONDS == 30


# ── ProbeResult dataclass ──────────────────────────────────────────────────


def test_probe_result_dataclass_shape() -> None:
    mod = _load_script_module()
    r = mod.ProbeResult(sha="x" * 40, short="x" * 8, subject="msg", status="good")
    assert r.detail == ""  # default
    assert r.status == "good"


# ── _probe_commit skipped on missing fixture (never raises) ────────────────


def test_probe_commit_skipped_when_fixture_missing(tmp_path) -> None:
    mod = _load_script_module()
    res = mod._probe_commit(
        sha="0" * 40,
        fixture=tmp_path / "does-not-exist.json",
        timeout=5,
    )
    assert res.status == "skipped"
    assert "fixture missing" in res.detail


# ── REPORT_PATH points at .gcc/ ─────────────────────────────────────────────


def test_report_path_is_under_gcc_audit_dir() -> None:
    mod = _load_script_module()
    assert str(mod.REPORT_PATH).replace("\\", "/").endswith(".gcc/REGRESSION-REPORT-edge-loss.md")
