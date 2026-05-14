"""CR-005 PR-005a tests — ``graq_bash`` ``stdout_path`` parameter.

Locks down the new optional ``stdout_path`` parameter on ``_handle_bash``.
The headline bug it fixes (BHG #4): ``graq_bash("cmd > file.log")``
produces an empty file because the subprocess shell is sandboxed. The
new parameter writes the FULL untruncated stdout to disk atomically,
bypassing the 4000-char JSON-body truncation.

Test categories:

1. Happy path — stdout_path receives the full stdout, atomically.
2. TOCTOU-safe validation — symlinks resolved before relative_to check.
3. Path-traversal refusal — absolute paths outside project root.
4. Dotdot refusal — '..' in resolved parts (defence-in-depth).
5. Parent-dir creation — mkdir parents=True exist_ok=True.
6. Atomic rename — tmp file cleaned up on success, on failure.
7. Truncation independence — stdout_path captures FULL output even when
   the JSON body has its own 4000-char truncation.
8. Backwards compatibility — calls without stdout_path behave identically
   to before (no schema change visible to existing callers).
9. Input validation — non-string / empty stdout_path rejected with a
   structured error envelope, not a Python exception.

CI safety: no real long-running subprocess (we use short ``echo``/``cmd``
commands that finish in milliseconds). All file I/O is under ``tmp_path``.
``KogniDevServer.__new__`` bypasses ``__init__`` per the existing
``tests/test_cloud/test_kg_sync.py`` and CR-008 patterns.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from graqle.plugins.mcp_dev_server import KogniDevServer


# ── Test doubles ──────────────────────────────────────────────────────


def _bare_server(graph_file: object = None) -> KogniDevServer:
    """Construct a server skeleton without running __init__.

    Matches the pattern from ``tests/test_cloud/test_kg_sync.py`` and the
    CR-008 tests in ``test_save_graph_status.py``.
    """
    server = KogniDevServer.__new__(KogniDevServer)
    server._graph_file = graph_file
    server._graph = None
    return server


def _call_bash(server: KogniDevServer, **args) -> dict:
    coro = server._handle_bash(args)
    return json.loads(asyncio.run(coro))


# ── 1. Happy path ─────────────────────────────────────────────────────


class TestStdoutPathHappyPath:
    def test_writes_full_stdout_to_file_atomically(self, tmp_path) -> None:
        """stdout_path inside project_root → file contains full stdout,
        response reports stdout_path + stdout_bytes_written."""
        server = _bare_server(graph_file=str(tmp_path / "graqle.json"))
        target = tmp_path / "out" / "captured.log"

        # Use a tiny portable command that produces deterministic output
        if sys.platform == "win32":
            cmd = 'cmd /c echo CR-005a happy path'
        else:
            cmd = 'printf "CR-005a happy path\\n"'

        response = _call_bash(
            server,
            command=cmd,
            cwd=str(tmp_path),
            timeout=10,
            stdout_path=str(target),
        )

        assert response.get("success") is True, (
            f"Subprocess failed: stderr={response.get('stderr')!r} "
            f"exit_code={response.get('exit_code')!r}"
        )
        assert "stdout_path" in response
        # Canonical path comparison (resolve both sides for cross-platform sanity)
        assert Path(response["stdout_path"]).resolve() == target.resolve()
        assert response["stdout_bytes_written"] > 0
        assert target.exists(), "stdout_path file must exist after happy-path write"
        content = target.read_text(encoding="utf-8")
        assert "CR-005a happy path" in content

    def test_response_still_has_truncated_stdout_field(self, tmp_path) -> None:
        """The JSON response retains its in-body ``stdout`` (truncated to
        4000 chars) AND adds ``stdout_path``. Existing callers parsing the
        body keep working unchanged."""
        server = _bare_server(graph_file=str(tmp_path / "graqle.json"))
        target = tmp_path / "captured.log"
        cmd = 'cmd /c echo X' if sys.platform == "win32" else 'echo X'
        response = _call_bash(
            server, command=cmd, cwd=str(tmp_path),
            timeout=10, stdout_path=str(target),
        )
        assert "stdout" in response  # body field preserved
        assert "stdout_path" in response  # new field added
        assert "stdout_bytes_written" in response


# ── 2-4. Path-traversal refusal ───────────────────────────────────────


class TestStdoutPathRefusal:
    def test_absolute_path_outside_project_root_refused(self, tmp_path) -> None:
        """stdout_path resolving outside project_root → structured error,
        NOT a Python exception, NOT a subprocess run."""
        # project root = tmp_path
        server = _bare_server(graph_file=str(tmp_path / "graqle.json"))
        # Pick a path that's guaranteed outside tmp_path
        outside = tmp_path.parent / "definitely_outside.log"

        response = _call_bash(
            server,
            command="echo nope",
            cwd=str(tmp_path),
            stdout_path=str(outside),
        )
        assert response.get("error") == "stdout_path_outside_project_root"
        assert "project root" in response.get("message", "").lower()
        # Subprocess MUST NOT have run — no file created at the refused location
        assert not outside.exists()

    def test_dotdot_traversal_resolved_outside_refused(self, tmp_path) -> None:
        """A path with .. that resolves OUTSIDE project_root is refused.
        (Inside-project '..' that stays in-root is fine — Path.resolve
        collapses it before the relative_to check.)"""
        server = _bare_server(graph_file=str(tmp_path / "graqle.json"))
        # tmp_path/../<basename of parent>/escape.log resolves to outside
        escape = tmp_path / ".." / ".." / "escape.log"

        response = _call_bash(
            server,
            command="echo nope",
            cwd=str(tmp_path),
            stdout_path=str(escape),
        )
        # Either branch is acceptable as long as it's a REFUSAL
        assert response.get("error") in {
            "stdout_path_outside_project_root",
            "stdout_path_contains_dotdot_after_resolve",
        }


# ── 5. Parent-directory creation ──────────────────────────────────────


class TestStdoutPathParentDirCreation:
    def test_creates_missing_parent_dirs(self, tmp_path) -> None:
        """stdout_path with nested parent dirs that don't exist yet →
        mkdir(parents=True, exist_ok=True) creates them."""
        server = _bare_server(graph_file=str(tmp_path / "graqle.json"))
        deeply_nested = tmp_path / "a" / "b" / "c" / "out.log"
        assert not deeply_nested.parent.exists()

        cmd = 'cmd /c echo deep' if sys.platform == "win32" else 'echo deep'
        response = _call_bash(
            server, command=cmd, cwd=str(tmp_path),
            stdout_path=str(deeply_nested),
        )
        assert deeply_nested.parent.is_dir()
        assert deeply_nested.exists()
        assert "deep" in deeply_nested.read_text(encoding="utf-8")

    def test_existing_parent_dir_is_fine(self, tmp_path) -> None:
        """exist_ok=True: writing into an existing dir does not raise."""
        server = _bare_server(graph_file=str(tmp_path / "graqle.json"))
        (tmp_path / "logs").mkdir()
        target = tmp_path / "logs" / "out.log"

        cmd = 'cmd /c echo y' if sys.platform == "win32" else 'echo y'
        response = _call_bash(
            server, command=cmd, cwd=str(tmp_path),
            stdout_path=str(target),
        )
        assert response.get("success") is True
        assert target.exists()


# ── 6. Atomic rename + cleanup ────────────────────────────────────────


class TestStdoutPathAtomicRename:
    def test_no_tmp_files_left_after_success(self, tmp_path) -> None:
        """Successful write leaves only the canonical file — no .tmp stragglers."""
        server = _bare_server(graph_file=str(tmp_path / "graqle.json"))
        target = tmp_path / "captured.log"
        cmd = 'cmd /c echo done' if sys.platform == "win32" else 'echo done'
        _call_bash(
            server, command=cmd, cwd=str(tmp_path),
            stdout_path=str(target),
        )
        # No .tmp leftovers in the parent
        tmp_residue = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
        assert tmp_residue == [], f"Stray temp files: {tmp_residue!r}"

    def test_overwrite_existing_file(self, tmp_path) -> None:
        """stdout_path pointing at an existing file → atomically replaced."""
        server = _bare_server(graph_file=str(tmp_path / "graqle.json"))
        target = tmp_path / "captured.log"
        target.write_text("OLD CONTENT", encoding="utf-8")

        cmd = 'cmd /c echo NEW' if sys.platform == "win32" else 'echo NEW'
        _call_bash(
            server, command=cmd, cwd=str(tmp_path),
            stdout_path=str(target),
        )
        content = target.read_text(encoding="utf-8")
        assert "NEW" in content
        assert "OLD CONTENT" not in content


# ── 7. Truncation independence ────────────────────────────────────────


class TestStdoutPathTruncationIndependence:
    def test_full_stdout_captured_even_when_body_truncated(self, tmp_path) -> None:
        """The 4000-char JSON-body truncation is independent of stdout_path.
        stdout_path captures the FULL stdout regardless. This is the
        headline use case — long subprocess output (CI logs, test runs)
        that the response body would truncate.

        Test approach: patch subprocess.run to return a controlled long
        stdout. This avoids depending on real CI tools and stays cross-platform.
        """
        server = _bare_server(graph_file=str(tmp_path / "graqle.json"))
        target = tmp_path / "big.log"
        # 10_000 chars of 'A' — well above the 4000-char body truncation
        long_stdout = "A" * 10_000

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=long_stdout,
                stderr="",
                returncode=0,
            )
            response = _call_bash(
                server, command="anything", cwd=str(tmp_path),
                stdout_path=str(target),
            )

        # Body truncation kicks in:
        assert response["truncated"] is True
        assert len(response["stdout"]) == 4000
        # ...but the file contains the FULL untruncated content:
        on_disk = target.read_text(encoding="utf-8")
        assert len(on_disk) == 10_000
        assert response["stdout_bytes_written"] == len(long_stdout.encode("utf-8"))


# ── 8. Backwards compatibility ────────────────────────────────────────


class TestStdoutPathBackwardCompat:
    def test_call_without_stdout_path_unchanged(self, tmp_path) -> None:
        """No stdout_path → response has no stdout_path / stdout_bytes_written
        fields, response shape exactly matches pre-CR-005a behaviour."""
        server = _bare_server(graph_file=str(tmp_path / "graqle.json"))
        cmd = 'cmd /c echo bc' if sys.platform == "win32" else 'echo bc'
        response = _call_bash(server, command=cmd, cwd=str(tmp_path))

        assert "stdout_path" not in response
        assert "stdout_bytes_written" not in response
        assert "stdout_path_error" not in response
        # Existing fields all present
        for key in ("command", "stdout", "stderr", "exit_code", "success", "truncated"):
            assert key in response, f"Missing existing field: {key}"


# ── 9. Input validation ───────────────────────────────────────────────


class TestStdoutPathInputValidation:
    def test_empty_string_rejected(self, tmp_path) -> None:
        server = _bare_server(graph_file=str(tmp_path / "graqle.json"))
        response = _call_bash(
            server, command="echo x", cwd=str(tmp_path), stdout_path="",
        )
        assert "stdout_path must be" in response.get("error", "")

    def test_whitespace_only_rejected(self, tmp_path) -> None:
        server = _bare_server(graph_file=str(tmp_path / "graqle.json"))
        response = _call_bash(
            server, command="echo x", cwd=str(tmp_path), stdout_path="   ",
        )
        assert "stdout_path must be" in response.get("error", "")

    def test_non_string_rejected(self, tmp_path) -> None:
        server = _bare_server(graph_file=str(tmp_path / "graqle.json"))
        response = _call_bash(
            server, command="echo x", cwd=str(tmp_path), stdout_path=12345,
        )
        assert "stdout_path must be" in response.get("error", "")

    def test_none_treated_as_unset(self, tmp_path) -> None:
        """stdout_path=None must behave the same as omitting the param entirely."""
        server = _bare_server(graph_file=str(tmp_path / "graqle.json"))
        cmd = 'cmd /c echo none' if sys.platform == "win32" else 'echo none'
        response = _call_bash(
            server, command=cmd, cwd=str(tmp_path), stdout_path=None,
        )
        assert "stdout_path" not in response
        assert response.get("success") is True


# ── 10. Project-root fallback when _graph_file is None ────────────────


class TestStdoutPathFallbackToCwd:
    """When ``self._graph_file is None`` (Neo4j-backed sessions),
    project_root falls back to ``Path.cwd().resolve()``. Verify the
    validation still works against cwd in that case."""

    def test_neo4j_session_uses_cwd_as_project_root(self, tmp_path, monkeypatch) -> None:
        server = _bare_server(graph_file=None)
        monkeypatch.chdir(tmp_path)

        target = tmp_path / "neo4j_session.log"
        cmd = 'cmd /c echo n4j' if sys.platform == "win32" else 'echo n4j'
        response = _call_bash(
            server, command=cmd, cwd=str(tmp_path),
            stdout_path=str(target),
        )
        assert response.get("success") is True
        assert target.exists()
        assert "n4j" in target.read_text(encoding="utf-8")
