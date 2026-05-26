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
    """Invoke `govern serve` via the sub-app.

    R2-PR3 added a second command (`health`), so typer no longer collapses the
    single-command case — the `serve` subcommand name is now required.
    """
    return runner.invoke(govern_app, ["serve", *args])


# Rich/typer renders --help differently on Linux CI (ANSI-coloured table with hard
# line-wraps inside flag names) vs Windows console (unwrapped plain text). Asserting
# raw substrings is fragile cross-platform — this helper strips ANSI escapes and
# collapses all whitespace so a flag like "--tick-seconds" still matches even when
# the CLI renderer broke it across lines (e.g. "--ti\nck-seconds").
def _normalise_help(output: str) -> str:
    import re

    no_ansi = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", output)
    return re.sub(r"\s+", "", no_ansi)


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
        # Cross-platform: Rich may wrap flag names mid-token on narrow terminals
        # (e.g. "--tick-seconds" → "--ti\nck-seconds" on Linux CI's coloured table).
        # Strip ANSI + whitespace before asserting.
        normalised = _normalise_help(res.output)
        assert "--once" in normalised and "--tick-seconds" in normalised

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


# -- Health snapshot writes (R2-PR3) ---------------------------------------


class TestHealthSnapshotWrite:
    def test_writes_atomic_json(self, tmp_path):
        from graqle.cli.commands.govern_serve import _write_health_snapshot

        target = tmp_path / "govern.health.json"
        snapshot = {"running": True, "ticks": 5, "records_committed": 12}
        _write_health_snapshot(target, snapshot)
        assert target.is_file()
        import json
        assert json.loads(target.read_text(encoding="utf-8")) == snapshot
        # No leftover .tmp files (NamedTemporaryFile + os.replace is atomic)
        assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())

    def test_creates_parent_dir(self, tmp_path):
        from graqle.cli.commands.govern_serve import _write_health_snapshot

        target = tmp_path / "subdir" / "govern.health.json"
        _write_health_snapshot(target, {"ok": True})
        assert target.is_file()

    def test_write_failure_is_logged_not_raised_and_tempfile_cleaned(
        self, tmp_path, monkeypatch, caplog
    ):
        """A write failure must NEVER propagate, AND must clean up any orphaned .tmp
        file (defence in depth against disk-exhaustion via repeated failures)."""
        import logging as _logging

        from graqle.cli.commands import govern_serve as gs

        target = tmp_path / "govern.health.json"

        def _boom(*a, **k):
            raise OSError("disk full")

        # Patch os.replace (the final commit step) so the write fails inside the helper.
        monkeypatch.setattr(gs.os, "replace", _boom)
        with caplog.at_level(_logging.ERROR, logger="graqle.cli.govern_serve"):
            gs._write_health_snapshot(target, {"ok": True})  # must not raise
        assert any("health_snapshot_write_failed" in r.message for r in caplog.records)
        # No orphaned .tmp files left in the destination directory
        assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir()), (
            f"orphaned tempfile not cleaned up: {list(tmp_path.iterdir())}"
        )

    def test_early_failure_before_tempfile_creation_logs_no_cleanup(
        self, tmp_path, monkeypatch, caplog
    ):
        """If the failure happens BEFORE NamedTemporaryFile returns, there is no
        tmp_path to clean up — the cleanup branch must safely skip (tmp_path is None)."""
        import logging as _logging
        import tempfile as _tempfile

        from graqle.cli.commands import govern_serve as gs

        target = tmp_path / "govern.health.json"

        def _early_boom(*a, **k):
            raise OSError("permission denied opening tempfile")

        monkeypatch.setattr(_tempfile, "NamedTemporaryFile", _early_boom)
        with caplog.at_level(_logging.ERROR, logger="graqle.cli.govern_serve"):
            gs._write_health_snapshot(target, {"ok": True})  # must not raise
        assert any("health_snapshot_write_failed" in r.message for r in caplog.records)

    def test_tempfile_cleanup_failure_is_silently_tolerated(
        self, tmp_path, monkeypatch, caplog
    ):
        """If the os.unlink cleanup itself fails, we keep the original error log
        (operator needs the write failure, not a cascading cleanup error)."""
        import logging as _logging

        from graqle.cli.commands import govern_serve as gs

        target = tmp_path / "govern.health.json"

        def _replace_boom(*a, **k):
            raise OSError("write boom")

        def _unlink_boom(*a, **k):
            raise OSError("cleanup boom")

        monkeypatch.setattr(gs.os, "replace", _replace_boom)
        monkeypatch.setattr(gs.os, "unlink", _unlink_boom)
        with caplog.at_level(_logging.ERROR, logger="graqle.cli.govern_serve"):
            gs._write_health_snapshot(target, {"ok": True})  # must not raise
        # Only the original write-fail log is emitted; no second cascading log expected
        msgs = [r.message for r in caplog.records]
        assert any("health_snapshot_write_failed" in m for m in msgs)

    def test_serve_with_non_anchoring_worker_skips_wrap_loudly(
        self, tmp_path, monkeypatch, caplog
    ):
        """Defence in depth: a non-AnchoringWorker base (test stub) bypasses the class
        swap with a structured warning rather than crashing the serve loop."""
        import logging as _logging

        monkeypatch.chdir(tmp_path)
        cfg = _disabled_config_yaml(tmp_path)
        worker = _fake_worker(committed=2)  # MagicMock — NOT an AnchoringWorker
        with caplog.at_level(_logging.WARNING, logger="graqle.cli.govern_serve"):
            with patch(
                "graqle.cli.commands.govern_serve._build_worker", return_value=worker
            ):
                res = _invoke(["--config", str(cfg), "--once"])
        assert res.exit_code == 0
        assert any(
            "health_writer_skipped_non_anchoring_worker" in r.message for r in caplog.records
        ), "expected the skip-warning to be logged when wrap is bypassed"

    def test_health_writing_worker_swallows_health_to_dict_errors(
        self, tmp_path, monkeypatch, caplog
    ):
        """If health().to_dict() raises, the tick must still return — never crash the loop."""
        import logging as _logging

        from graqle.cli.commands.govern_serve import (
            _build_health_writing_worker,
            _build_worker,
        )

        monkeypatch.chdir(tmp_path)
        cfg = tmp_path / "graqle.yaml"
        cfg.write_text(
            "graph:\n  connector: networkx\n"
            "attestation:\n  enabled: true\n  batch_max_seconds: 3\n",
            encoding="utf-8",
        )
        base = _build_worker(str(cfg))
        wrapped = _build_health_writing_worker(base, tmp_path / "h.json")

        # Patch the wrapped worker's health() to return an object whose to_dict raises.
        class _BoomHealth:
            def to_dict(self):
                raise RuntimeError("snapshot serialise boom")

        monkeypatch.setattr(wrapped, "health", lambda: _BoomHealth())
        with caplog.at_level(_logging.ERROR, logger="graqle.cli.govern_serve"):
            wrapped.tick()  # must not raise
        assert any(
            "health_snapshot_tick_failed" in r.message for r in caplog.records
        )

    def test_health_writing_worker_subclasses_anchoring(self, tmp_path, monkeypatch):
        """_build_health_writing_worker re-classes the base worker without losing state."""
        from graqle.cli.commands.govern_serve import _build_health_writing_worker
        from graqle.governance.tamper_evidence.worker import AnchoringWorker

        monkeypatch.chdir(tmp_path)
        # Build a real AnchoringWorker via the same path serve uses, then wrap it.
        cfg = tmp_path / "graqle.yaml"
        cfg.write_text(
            "graph:\n  connector: networkx\n"
            "attestation:\n  enabled: true\n  batch_max_seconds: 3\n",
            encoding="utf-8",
        )
        from graqle.cli.commands.govern_serve import _build_worker
        base = _build_worker(str(cfg))
        assert isinstance(base, AnchoringWorker)

        wrapped = _build_health_writing_worker(base, tmp_path / "h.json")
        # In-place re-class: same instance, but subclassed type.
        assert wrapped is base
        assert isinstance(wrapped, AnchoringWorker)  # Liskov: still an AnchoringWorker
        # Calling tick() now writes the snapshot file.
        wrapped.tick()
        assert (tmp_path / "h.json").is_file()


# -- govern health sub-command (R2-PR3) ------------------------------------


class TestGovernHealth:
    def _seed_snapshot(self, tmp_path, content: dict):
        snap = tmp_path / "govern.health.json"
        import json
        snap.write_text(json.dumps(content), encoding="utf-8")
        return snap

    def test_health_emits_json(self, tmp_path):
        snap = self._seed_snapshot(
            tmp_path,
            {"running": True, "ticks": 7, "records_committed": 21, "replay_queue_depth": 3},
        )
        res = runner.invoke(govern_app, ["health", "--health-file", str(snap)])
        assert res.exit_code == 0
        # Pretty-printed JSON contains the values
        assert '"running"' in res.output and "true" in res.output
        assert '"ticks"' in res.output and "7" in res.output

    def test_health_compact_mode(self, tmp_path):
        snap = self._seed_snapshot(tmp_path, {"ticks": 1})
        res = runner.invoke(
            govern_app, ["health", "--health-file", str(snap), "--compact"]
        )
        assert res.exit_code == 0
        # Compact mode emits single-line JSON
        assert '{"ticks": 1}' in res.output.replace("\n", "")

    def test_health_missing_file_exits_1(self, tmp_path):
        res = runner.invoke(
            govern_app, ["health", "--health-file", str(tmp_path / "nope.json")]
        )
        assert res.exit_code == 1
        assert "Health snapshot not found" in res.output
        assert "graqle govern serve" in res.output  # operator hint

    def test_health_corrupt_json_exits_1(self, tmp_path):
        snap = tmp_path / "govern.health.json"
        snap.write_text("{not valid json", encoding="utf-8")
        res = runner.invoke(govern_app, ["health", "--health-file", str(snap)])
        assert res.exit_code == 1
        assert "Corrupt health snapshot" in res.output

    def test_health_read_oserror_exits_1(self, tmp_path, monkeypatch):
        """An OSError reading the file is surfaced cleanly (not a stack trace)."""
        snap = self._seed_snapshot(tmp_path, {"ok": True})

        def _boom(self, *a, **k):
            raise OSError("eaccess")

        monkeypatch.setattr(Path, "read_text", _boom)
        res = runner.invoke(govern_app, ["health", "--health-file", str(snap)])
        assert res.exit_code == 1
        assert "Cannot read health snapshot" in res.output

    def test_health_negative_watch_rejected(self, tmp_path):
        snap = self._seed_snapshot(tmp_path, {"ok": True})
        res = runner.invoke(
            govern_app, ["health", "--health-file", str(snap), "--watch", "-1"]
        )
        assert res.exit_code == 1
        assert "--watch must be >= 0" in res.output

    def test_health_watch_loops_then_stops_on_keyboard_interrupt(self, tmp_path, monkeypatch):
        """--watch polls then exits cleanly on Ctrl-C."""
        snap = self._seed_snapshot(tmp_path, {"running": True})
        calls = {"n": 0}
        import time as _time

        def _sleep(_n):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise KeyboardInterrupt
        monkeypatch.setattr(_time, "sleep", _sleep)
        res = runner.invoke(
            govern_app, ["health", "--health-file", str(snap), "--watch", "0.05"]
        )
        assert res.exit_code == 0
        assert calls["n"] >= 2

    def test_health_help_shows_options(self):
        res = runner.invoke(govern_app, ["health", "--help"])
        assert res.exit_code == 0
        normalised = _normalise_help(res.output)
        assert "--watch" in normalised and "--health-file" in normalised


# -- _read_health_snapshot direct tests (defence in depth) ----------------


class TestReadHealthSnapshot:
    def test_returns_parsed_dict(self, tmp_path):
        from graqle.cli.commands.govern_serve import _read_health_snapshot

        target = tmp_path / "x.json"
        target.write_text('{"a": 1, "b": "two"}', encoding="utf-8")
        assert _read_health_snapshot(target) == {"a": 1, "b": "two"}
