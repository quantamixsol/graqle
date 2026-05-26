"""Tests for `graqle govern serve` CLI (ADR-221 §4.4 / R2-PR2).

These tests dispatch the typer command directly with the worker assembly patched out,
so they exercise the CLI lifecycle (config loading, PID files, --once, signal handlers,
graceful exits) without spinning up a real Rekor anchor.
"""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from graqle.cli.commands.govern_serve import (
    _cleanup_pid_file,
    _install_signal_handlers,
    _write_pid_files,
    govern_app,
)
from graqle.governance.tamper_evidence.worker import WorkerError

runner = CliRunner()


def _invoke(args: list[str]):
    """Invoke govern_app directly.

    govern_app is a typer sub-app; with a single registered command (`serve`),
    typer collapses the subcommand name — args are passed WITHOUT a leading "serve".
    """
    return runner.invoke(govern_app, args)


# -- helpers ----------------------------------------------------------------


def _fake_worker(committed: int = 0):
    """A worker stub with the surface govern_serve calls (tick / run / stop / health)."""
    w = MagicMock(name="AnchoringWorker")
    w._tick_seconds = 5.0
    w.tick.return_value = committed
    health = MagicMock()
    health.backfill_count = 0
    health.replay_queue_depth = 0
    health.ticks = 1
    health.records_committed = committed
    w.health.return_value = health
    return w


def _disabled_config_yaml(tmp_path: Path) -> Path:
    """A minimal graqle.yaml with the attestation block explicitly disabled."""
    p = tmp_path / "graqle.yaml"
    p.write_text(
        "graph:\n  connector: networkx\n"
        "attestation:\n  enabled: false\n",
        encoding="utf-8",
    )
    return p


# -- happy path: --once ------------------------------------------------------


class TestOnce:
    def test_once_runs_one_tick_and_exits(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = _disabled_config_yaml(tmp_path)
        worker = _fake_worker(committed=3)

        with patch(
            "graqle.cli.commands.govern_serve._build_worker", return_value=worker
        ):
            res = _invoke(["--config", str(cfg), "--once"])

        assert res.exit_code == 0, res.output
        assert worker.tick.call_count == 1
        worker.run.assert_not_called()
        assert "once: committed=3" in res.output


# -- fail-closed / misconfig surfaces ---------------------------------------


class TestFailClosed:
    def test_missing_config_exits_1(self, tmp_path):
        res = _invoke(["--config", str(tmp_path / "nope.yaml")])
        assert res.exit_code == 1
        assert "Config not found" in res.output

    def test_disabled_attestation_exits_2(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = _disabled_config_yaml(tmp_path)
        res = _invoke(["--config", str(cfg)])
        assert res.exit_code == 2
        assert "attestation.enabled is false" in res.output

    def test_fail_open_misconfig_surfaces_clean_exit(self, tmp_path, monkeypatch):
        """The worker raises WorkerError on fail_open=True; CLI converts to exit 1."""
        monkeypatch.chdir(tmp_path)
        cfg = _disabled_config_yaml(tmp_path)

        def _raise(*a, **kw):
            raise WorkerError("fail-open misconfig")

        with patch("graqle.cli.commands.govern_serve._build_worker", side_effect=_raise):
            res = _invoke(["--config", str(cfg)])
        assert res.exit_code == 1


# -- tick override validation ----------------------------------------------


class TestTickOverride:
    def test_zero_tick_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = _disabled_config_yaml(tmp_path)
        worker = _fake_worker()
        with patch(
            "graqle.cli.commands.govern_serve._build_worker", return_value=worker
        ):
            res = _invoke(["--config", str(cfg), "--tick-seconds", "0", "--once"])
        assert res.exit_code == 1
        assert "tick-seconds must be > 0" in res.output

    def test_positive_tick_overrides(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = _disabled_config_yaml(tmp_path)
        worker = _fake_worker()
        with patch(
            "graqle.cli.commands.govern_serve._build_worker", return_value=worker
        ):
            res = _invoke(["--config", str(cfg), "--tick-seconds", "0.5", "--once"])
        assert res.exit_code == 0
        assert worker._tick_seconds == 0.5


# -- PID file lifecycle ----------------------------------------------------


class TestPidFiles:
    def test_write_pid_files_creates_dir_and_files(self, tmp_path):
        graqle_dir = tmp_path / ".graqle"
        pid_file, version_file = _write_pid_files(graqle_dir)
        assert pid_file.is_file() and version_file.is_file()
        assert int(pid_file.read_text(encoding="utf-8")) == os.getpid()
        assert version_file.read_text(encoding="utf-8")

    def test_once_writes_pid_file(self, tmp_path, monkeypatch):
        """--once writes the PID file (atexit cleanup runs at process exit only)."""
        monkeypatch.chdir(tmp_path)
        cfg = _disabled_config_yaml(tmp_path)
        worker = _fake_worker()
        with patch(
            "graqle.cli.commands.govern_serve._build_worker", return_value=worker
        ):
            res = _invoke(["--config", str(cfg), "--once"])
        assert res.exit_code == 0
        # CliRunner runs in-process; atexit hasn't fired — proves the file was written.
        assert (tmp_path / ".graqle" / "govern.pid").is_file()


# -- run loop + KeyboardInterrupt safety net ---------------------------------


class TestRunLoop:
    def test_run_loop_invokes_run_and_prints_summary(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = _disabled_config_yaml(tmp_path)
        worker = _fake_worker()
        with patch(
            "graqle.cli.commands.govern_serve._build_worker", return_value=worker
        ), patch(
            "graqle.cli.commands.govern_serve._install_signal_handlers"
        ):
            res = _invoke(["--config", str(cfg)])
        assert res.exit_code == 0
        worker.run.assert_called_once()
        assert "stopped" in res.output

    def test_run_loop_keyboard_interrupt_stops_cleanly(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = _disabled_config_yaml(tmp_path)
        worker = _fake_worker()
        worker.run.side_effect = KeyboardInterrupt
        with patch(
            "graqle.cli.commands.govern_serve._build_worker", return_value=worker
        ), patch(
            "graqle.cli.commands.govern_serve._install_signal_handlers"
        ):
            res = _invoke(["--config", str(cfg)])
        assert res.exit_code == 0
        worker.stop.assert_called_once()

    def test_run_loop_unexpected_exception_exits_1(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = _disabled_config_yaml(tmp_path)
        worker = _fake_worker()
        worker.run.side_effect = RuntimeError("boom")
        with patch(
            "graqle.cli.commands.govern_serve._build_worker", return_value=worker
        ), patch(
            "graqle.cli.commands.govern_serve._install_signal_handlers"
        ):
            res = _invoke(["--config", str(cfg)])
        assert res.exit_code == 1
        assert "govern serve crashed" in res.output


# -- signal handler installation -------------------------------------------


class TestSignalHandlers:
    def test_sigint_handler_calls_stop(self):
        worker = _fake_worker()
        prev = signal.getsignal(signal.SIGINT)
        try:
            _install_signal_handlers(worker)
            handler = signal.getsignal(signal.SIGINT)
            assert callable(handler)
            handler(signal.SIGINT, None)  # type: ignore[misc]
            worker.stop.assert_called_once()
        finally:
            signal.signal(signal.SIGINT, prev)

    @pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM not delivered on Windows")
    def test_sigterm_handler_installed_on_posix(self):
        worker = _fake_worker()
        prev_int = signal.getsignal(signal.SIGINT)
        prev_term = signal.getsignal(signal.SIGTERM)
        try:
            _install_signal_handlers(worker)
            term_handler = signal.getsignal(signal.SIGTERM)
            assert callable(term_handler)
            term_handler(signal.SIGTERM, None)  # type: ignore[misc]
            worker.stop.assert_called_once()
        finally:
            signal.signal(signal.SIGINT, prev_int)
            signal.signal(signal.SIGTERM, prev_term)


# -- CLI surface --------------------------------------------------------------


class TestCliSurface:
    def test_serve_help(self):
        res = _invoke(["--help"])
        assert res.exit_code == 0
        assert "--once" in res.output and "--tick-seconds" in res.output

    def test_govern_serve_registered_on_main_app(self):
        """govern_app is mounted on the top-level graqle CLI as `graqle govern`."""
        from graqle.cli.main import app as main_app

        res = runner.invoke(main_app, ["govern", "--help"])
        assert res.exit_code == 0
        assert "serve" in res.output or "Runtime governance" in res.output


# -- _build_worker config-loading paths -------------------------------------


class TestBuildWorkerConfigPaths:
    def test_build_worker_yaml_parse_error_exits_1(self, tmp_path):
        import click

        from graqle.cli.commands.govern_serve import _build_worker

        bad = tmp_path / "graqle.yaml"
        bad.write_text("graph: [unclosed\n", encoding="utf-8")
        with pytest.raises(click.exceptions.Exit) as exc:
            _build_worker(str(bad))
        assert exc.value.exit_code == 1

    def test_build_worker_fail_open_misconfig_exits_1(self, tmp_path, monkeypatch):
        """attestation.security.fail_open_on_anchor_error=true triggers the worker's
        fail-closed precondition (via the _WorkerConfigView); CLI converts the
        WorkerError to a clean exit 1."""
        import click

        from graqle.cli.commands.govern_serve import _build_worker

        monkeypatch.chdir(tmp_path)
        cfg = tmp_path / "graqle.yaml"
        cfg.write_text(
            "graph:\n  connector: networkx\n"
            "attestation:\n  enabled: true\n"
            "  security:\n    fail_open_on_anchor_error: true\n",
            encoding="utf-8",
        )
        with pytest.raises(click.exceptions.Exit) as exc:
            _build_worker(str(cfg))
        assert exc.value.exit_code == 1

    def test_worker_config_view_security_missing(self):
        """Defence in depth: if .security is absent, the view returns False (fail-closed)."""
        from types import SimpleNamespace

        from graqle.cli.commands.govern_serve import _WorkerConfigView

        att = SimpleNamespace(batch_max_seconds=7, security=None)
        v = _WorkerConfigView(att)
        assert v.batch_max_seconds == 7
        assert v.fail_open_on_anchor_error is False

    def test_build_worker_enabled_assembles_real_worker(self, tmp_path, monkeypatch):
        """Happy path: attestation.enabled=true → returns a real AnchoringWorker."""
        from graqle.cli.commands.govern_serve import _build_worker
        from graqle.governance.tamper_evidence.worker import AnchoringWorker

        monkeypatch.chdir(tmp_path)  # WAL is created under .graqle/attestation/<cwd>
        cfg = tmp_path / "graqle.yaml"
        cfg.write_text(
            "graph:\n  connector: networkx\n"
            "attestation:\n  enabled: true\n  batch_max_seconds: 3\n",
            encoding="utf-8",
        )
        worker = _build_worker(str(cfg))
        assert isinstance(worker, AnchoringWorker)
        assert worker._tick_seconds == 3.0
        # WAL directory was created under the isolated tmp
        assert (tmp_path / ".graqle" / "attestation").is_dir()


# -- atexit cleanup helper ---------------------------------------------------


class TestAtexitCleanup:
    def test_cleanup_removes_pid_file(self, tmp_path):
        """The atexit-registered helper unlinks the PID file safely (missing_ok)."""
        pid = tmp_path / "govern.pid"
        pid.write_text(str(os.getpid()), encoding="utf-8")
        _cleanup_pid_file(pid)
        assert not pid.exists()
        # idempotent: a second call on the now-missing file must not raise
        _cleanup_pid_file(pid)

    def test_cleanup_swallows_unlink_errors(self, tmp_path, monkeypatch):
        """A PermissionError (or any exception) from unlink must NOT propagate."""
        pid = tmp_path / "govern.pid"
        pid.write_text("123", encoding="utf-8")

        def _boom(self, *a, **k):  # type: ignore[no-untyped-def]
            raise PermissionError("locked")

        monkeypatch.setattr(Path, "unlink", _boom)
        _cleanup_pid_file(pid)  # must not raise


# -- Windows-only SIGTERM branch --------------------------------------------


class TestWindowsSigtermBranch:
    @pytest.mark.skipif(sys.platform != "win32", reason="Branch is Windows-only")
    def test_sigterm_skipped_on_windows(self):
        """On Windows the SIGTERM-install branch is skipped (signal exists but unused)."""
        worker = _fake_worker()
        prev_int = signal.getsignal(signal.SIGINT)
        prev_term = signal.getsignal(signal.SIGTERM) if hasattr(signal, "SIGTERM") else None
        try:
            _install_signal_handlers(worker)
            # SIGINT handler is always installed
            assert callable(signal.getsignal(signal.SIGINT))
            # SIGTERM handler was NOT replaced on Windows
            if hasattr(signal, "SIGTERM"):
                assert signal.getsignal(signal.SIGTERM) == prev_term
        finally:
            signal.signal(signal.SIGINT, prev_int)
            if hasattr(signal, "SIGTERM") and prev_term is not None:
                signal.signal(signal.SIGTERM, prev_term)
