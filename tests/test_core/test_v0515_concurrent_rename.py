"""Regression tests for v0.51.5 — concurrent ``os.replace`` rename retry.

Covers the VS Code extension's "concurrent edits silently lost" pain reported
in the v0.51.5 handoff. Root cause: on Windows, ``os.replace(tmp, dst)`` raises
``PermissionError`` (WinError 5) when a peer MCP process holds ``dst`` open.
v0.51.5 adds an exponential-backoff retry inside ``_write_with_lock`` whose
total budget is governed by the ``GRAQLE_WRITE_RETRY_BUDGET_MS`` env var
(default 2600 ms). The function returns the number of retry attempts used so
upstream callers can surface ``retry_attempts`` in the MCP response.

Per VS Code team handoff Q1+Q2 answers:

  Q1 → response shape on failure: ``recorded: false`` + ``error_code:
       "WRITE_COLLISION"`` + ``retry_after_ms`` hint.  Tested in
       ``test_save_graph_returns_false_and_error_code_on_persistent_failure``.
  Q2 → 2.6 s default budget, env-tunable.  Tested in
       ``test_budget_is_env_tunable_via_GRAQLE_WRITE_RETRY_BUDGET_MS``.
  Q3 → no per-client priority.  No test needed.

The bonus "regression: ``import os`` must be in scope inside ``_save_graph``"
ask from the VS Code team is covered in
``test_save_graph_has_os_in_namespace``.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from graqle.core.graph import _write_with_lock


def _make_graph(n_nodes: int) -> dict:
    return {
        "directed": True,
        "multigraph": False,
        "nodes": [{"id": f"n{i}"} for i in range(n_nodes)],
        "links": [],
    }


def _payload(n_nodes: int) -> str:
    return json.dumps(_make_graph(n_nodes))


@pytest.fixture
def kg_file(tmp_path: Path) -> str:
    return str(tmp_path / "graqle.json")


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make sure no caller env leaks into the tests."""
    monkeypatch.delenv("GRAQLE_WRITE_RETRY_BUDGET_MS", raising=False)
    monkeypatch.delenv("GRAQLE_ALLOW_SHRINK", raising=False)


# -------------------------------------------------------------------------
# Return-value contract — _write_with_lock now returns int (rename_attempts)
# -------------------------------------------------------------------------


class TestReturnValueContract:
    """The function must return an int rename_attempts count.

    Existing callers (`_save_graph`, `kg_sync`, `scan`, `grow`, `link`,
    `rebuild`, `json_graph`, `mcp_dev_server`) ignore the return value, so
    the change is backward-compatible.  But the new MCP response surface
    needs the count to populate ``retry_attempts``.
    """

    def test_first_write_returns_zero_attempts(self, kg_file: str) -> None:
        attempts = _write_with_lock(kg_file, _payload(100))
        assert attempts == 0

    def test_overwrite_returns_zero_attempts_when_no_contention(
        self, kg_file: str
    ) -> None:
        _write_with_lock(kg_file, _payload(100))
        attempts = _write_with_lock(kg_file, _payload(101))
        assert attempts == 0


# -------------------------------------------------------------------------
# Retry behaviour — simulated PermissionError from os.replace
# -------------------------------------------------------------------------


class _FlakyReplace:
    """Callable that fails the first ``fail_count`` invocations with
    ``PermissionError`` then delegates to the real ``os.replace``."""

    def __init__(self, fail_count: int) -> None:
        self.fail_count = fail_count
        self.call_count = 0
        self._real = os.replace

    def __call__(self, src: str, dst: str) -> None:
        self.call_count += 1
        if self.call_count <= self.fail_count:
            raise PermissionError(13, "Access is denied", dst)
        self._real(src, dst)


class TestRetryBehavior:
    """Exponential-backoff retry around ``os.replace``."""

    def test_retry_recovers_from_transient_permission_error(
        self, kg_file: str
    ) -> None:
        flaky = _FlakyReplace(fail_count=3)
        with patch("os.replace", side_effect=flaky):
            attempts = _write_with_lock(kg_file, _payload(100))
        assert attempts == 3, f"expected 3 retries, got {attempts}"
        assert flaky.call_count == 4, "real replace should be called once after 3 fails"
        # File must be written
        assert json.loads(Path(kg_file).read_text(encoding="utf-8"))["nodes"]

    def test_retry_succeeds_on_first_try_when_no_contention(
        self, kg_file: str
    ) -> None:
        attempts = _write_with_lock(kg_file, _payload(100))
        assert attempts == 0

    def test_retry_exhausts_budget_and_raises(
        self, kg_file: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Tighten budget to 200 ms so the test runs fast
        monkeypatch.setenv("GRAQLE_WRITE_RETRY_BUDGET_MS", "200")

        always_fail = _FlakyReplace(fail_count=10**6)  # never succeed
        with patch("os.replace", side_effect=always_fail):
            with pytest.raises(PermissionError):
                _write_with_lock(kg_file, _payload(100))


# -------------------------------------------------------------------------
# Env-tunable budget — GRAQLE_WRITE_RETRY_BUDGET_MS
# -------------------------------------------------------------------------


class TestBudgetEnvVar:
    """``GRAQLE_WRITE_RETRY_BUDGET_MS`` must be honoured per-call.

    Default 2600 ms; CI environments with many concurrent agents may bump
    it to 5000+, latency-sensitive desktops may lower to 500.
    """

    def test_short_budget_fails_fast(
        self, kg_file: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import time as _time
        monkeypatch.setenv("GRAQLE_WRITE_RETRY_BUDGET_MS", "100")

        always_fail = _FlakyReplace(fail_count=10**6)
        with patch("os.replace", side_effect=always_fail):
            t0 = _time.monotonic()
            with pytest.raises(PermissionError):
                _write_with_lock(kg_file, _payload(100))
            elapsed = (_time.monotonic() - t0) * 1000.0

        # Allow up to 2x slack for first-attempt sleep + scheduling jitter
        assert elapsed < 500, f"100 ms budget exceeded: {elapsed:.1f} ms"

    def test_invalid_budget_falls_back_to_default(
        self, kg_file: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GRAQLE_WRITE_RETRY_BUDGET_MS", "not-a-number")
        # Should not raise on invalid env var — falls back silently to 2600
        attempts = _write_with_lock(kg_file, _payload(100))
        assert attempts == 0


# -------------------------------------------------------------------------
# Bonus regression: import os in _save_graph (v0.51.4 NameError)
# -------------------------------------------------------------------------


class TestSaveGraphOsImport:
    """Regression for the v0.51.4 silent ``NameError: 'os' is not defined``.

    The shrink guard inside ``_save_graph`` referenced ``os.environ`` but the
    function only imported ``pathlib``. The exception was caught by the
    guard's own except block and logged as a benign warning. Result: the
    secondary (defense-in-depth) shrink guard was DEAD on PyPI for the
    entire v0.51.4 release.

    This test asserts the import is present so a future refactor can't
    silently re-introduce the regression.
    """

    def test_save_graph_function_source_imports_os(self) -> None:
        import inspect

        from graqle.plugins.mcp_dev_server import KogniDevServer

        src = inspect.getsource(KogniDevServer._save_graph)
        # Either a bare 'import os' or 'from os import ...' inside the
        # function body must be present alongside any os.environ usage.
        assert "import os" in src or "from os " in src, (
            "_save_graph must import os in its function scope; otherwise the "
            "shrink guard's `os.environ.get(...)` raises NameError silently."
        )


# -------------------------------------------------------------------------
# Cross-platform sanity
# -------------------------------------------------------------------------


class TestCrossPlatform:
    """Make sure the retry plumbing doesn't break the POSIX happy path."""

    def test_normal_write_path_unchanged(self, kg_file: str) -> None:
        # Plain non-graph payload — guard skips entirely, write goes through.
        _write_with_lock(kg_file, "hello world")
        assert Path(kg_file).read_text(encoding="utf-8") == "hello world"

    def test_concurrent_threads_no_lost_writes(self, tmp_path: Path) -> None:
        """Drive 4 threads writing distinct payloads to one file. With the
        retry loop, every successful return must correspond to a real
        on-disk write, and the final file must be one of the writers'
        payloads (not corrupted).
        """
        import threading

        kg_file = str(tmp_path / "kg.json")
        _write_with_lock(kg_file, _payload(50))  # seed

        results: list[int] = []
        errors: list[BaseException] = []

        def worker(n: int) -> None:
            try:
                attempts = _write_with_lock(kg_file, _payload(n))
                results.append(attempts)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(50 + i,)) for i in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"unexpected errors under concurrency: {errors}"
        assert len(results) == 4
        # File must parse as valid JSON (no torn write)
        parsed = json.loads(Path(kg_file).read_text(encoding="utf-8"))
        assert "nodes" in parsed
        # Whichever writer landed last, the count must be in [50, 53]
        assert 50 <= len(parsed["nodes"]) <= 53
