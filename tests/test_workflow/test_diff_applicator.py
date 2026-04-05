# tests/test_workflow/test_diff_applicator.py
"""
Tests for DiffApplicator — atomic diff application with git-stash rollback.

Covers:
- Atomic file writing (new files, overwrite)
- Git stash creation and rollback
- Non-git-repo fallback behavior
- Error handling (permissions, disk full simulation)
- Edge cases (empty diff, missing parent dirs)
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess

from graqle.workflow.diff_applicator import DiffApplicator, _is_protected_file


@pytest.fixture
def work_dir(tmp_path):
    """Create a temporary working directory."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "existing.py").write_text("def old(): pass\n")
    return tmp_path


@pytest.fixture
def applicator(work_dir):
    return DiffApplicator(work_dir)


# ============================================================================
# Atomic File Write Tests (6 tests)
# ============================================================================


class TestWriteFileAtomic:
    """write_file_atomic() behavior."""

    def test_write_new_file(self, applicator, work_dir):
        """Write a new file atomically."""
        target = work_dir / "src" / "new_file.py"
        result = applicator.write_file_atomic(str(target), "def new(): pass\n")
        assert result.success
        assert target.exists()
        assert target.read_text() == "def new(): pass\n"

    def test_write_overwrites_existing(self, applicator, work_dir):
        """Write overwrites existing file."""
        target = work_dir / "src" / "existing.py"
        result = applicator.write_file_atomic(str(target), "def updated(): pass\n")
        assert result.success
        assert target.read_text() == "def updated(): pass\n"

    def test_write_creates_parent_dirs(self, applicator, work_dir):
        """Write creates parent directories if they don't exist."""
        target = work_dir / "deep" / "nested" / "file.py"
        result = applicator.write_file_atomic(str(target), "content")
        assert result.success
        assert target.exists()

    def test_write_returns_modified_files(self, applicator, work_dir):
        """Write result includes the file in modified_files."""
        target = work_dir / "src" / "new.py"
        result = applicator.write_file_atomic(str(target), "content")
        assert str(target) in result.modified_files

    def test_write_empty_content(self, applicator, work_dir):
        """Writing empty content succeeds."""
        target = work_dir / "empty.py"
        result = applicator.write_file_atomic(str(target), "")
        assert result.success
        assert target.read_text() == ""

    def test_write_tmp_cleaned_on_success(self, applicator, work_dir):
        """Temporary file is cleaned up after successful write."""
        target = work_dir / "clean.py"
        applicator.write_file_atomic(str(target), "content")
        tmp = target.with_suffix(".py.tmp")
        assert not tmp.exists()


# ============================================================================
# Git Stash Tests (4 tests)
# ============================================================================


class TestGitStash:
    """Git stash creation and rollback."""

    def test_not_git_repo_returns_none(self, applicator):
        """create_stash() returns None when not in a git repo."""
        with patch.object(applicator, '_is_git_repo', return_value=False):
            result = applicator.create_stash()
            assert result is None

    def test_rollback_not_git_repo_returns_error(self, applicator):
        """rollback() returns error when not in git repo."""
        with patch.object(applicator, '_is_git_repo', return_value=False):
            result = applicator.rollback("stash@{0}")
            assert not result.success

    def test_rollback_rejects_invalid_token(self, applicator):
        """rollback() rejects tokens that don't match stash@{N} format."""
        with patch.object(applicator, '_is_git_repo', return_value=True):
            result = applicator.rollback("--index")
            assert not result.success
            assert "Invalid stash token" in result.stderr

    def test_rollback_rejects_command_injection(self, applicator):
        """rollback() rejects command injection attempts."""
        with patch.object(applicator, '_is_git_repo', return_value=True):
            result = applicator.rollback("; rm -rf /")
            assert not result.success
            assert "Invalid stash token" in result.stderr

    def test_rollback_accepts_valid_token(self, applicator):
        """rollback() accepts properly formatted stash@{N} tokens."""
        with patch.object(applicator, '_is_git_repo', return_value=True):
            with patch.object(applicator, '_run_git') as mock_git:
                mock_git.return_value = MagicMock(
                    returncode=0, stdout="ok", stderr=""
                )
                result = applicator.rollback("stash@{0}")
                assert result.success

    def test_create_stash_with_no_changes(self, applicator):
        """create_stash() returns None when there are no changes."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "true"

        mock_stash = MagicMock()
        mock_stash.returncode = 1  # nothing to stash
        mock_stash.stdout = "No local changes to save"

        with patch.object(applicator, '_is_git_repo', return_value=True):
            with patch.object(applicator, '_run_git') as mock_git:
                # First call is git add, second is git stash push
                mock_git.side_effect = [mock_result, mock_stash]
                result = applicator.create_stash()
                assert result is None

    def test_rollback_subprocess_error(self, applicator):
        """rollback() handles subprocess errors gracefully."""
        with patch.object(applicator, '_is_git_repo', return_value=True):
            with patch.object(applicator, '_run_git', side_effect=subprocess.SubprocessError("fail")):
                result = applicator.rollback("stash@{0}")
                assert not result.success
                assert "Rollback failed" in result.stderr


# ============================================================================
# apply_diff_atomic Tests (3 tests)
# ============================================================================


class TestApplyDiffAtomic:
    """apply_diff_atomic() wrapping file_writer."""

    def test_apply_diff_returns_execution_result(self, applicator, work_dir):
        """apply_diff_atomic returns an ExecutionResult."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.lines_changed = 3
        mock_result.backup_path = "/tmp/backup"

        with patch("graqle.core.file_writer.apply_diff", return_value=mock_result):
            result = applicator.apply_diff_atomic(
                str(work_dir / "src" / "existing.py"),
                "--- a/existing.py\n+++ b/existing.py\n@@ -1 +1 @@\n-old\n+new",
            )
            assert result.success
            assert result.rollback_token == "/tmp/backup"

    def test_apply_diff_failure_returns_error(self, applicator, work_dir):
        """Failed diff application returns error result."""
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "Hunk failed to apply"

        with patch("graqle.core.file_writer.apply_diff", return_value=mock_result):
            result = applicator.apply_diff_atomic(
                str(work_dir / "src" / "existing.py"),
                "bad diff content",
            )
            assert not result.success
            assert "Hunk failed" in result.stderr

    def test_apply_diff_exception_handled(self, applicator, work_dir):
        """Exception from file_writer is handled gracefully."""
        with patch("graqle.core.file_writer.apply_diff", side_effect=ValueError("bad diff")):
            result = applicator.apply_diff_atomic(
                str(work_dir / "src" / "existing.py"),
                "diff content",
            )
            assert not result.success
            assert "error" in result.stderr.lower()


# ============================================================================
# P0: Governance Gate — Protected File Tests (8 tests)
# ============================================================================


class TestProtectedFileGate:
    """Governance gate prevents modification of protected files."""

    def test_env_file_blocked(self, applicator):
        """Cannot apply diff to .env file."""
        result = applicator.apply_diff_atomic("/project/.env", "diff")
        assert not result.success
        assert "GOVERNANCE BLOCK" in result.stderr

    def test_env_local_blocked(self, applicator):
        """Cannot apply diff to .env.local."""
        result = applicator.apply_diff_atomic("/project/.env.local", "diff")
        assert not result.success
        assert "GOVERNANCE BLOCK" in result.stderr

    def test_credentials_file_blocked(self, applicator):
        """Cannot write to credentials file."""
        result = applicator.write_file_atomic("/project/credentials.json", "content")
        assert not result.success
        assert "GOVERNANCE BLOCK" in result.stderr

    def test_secrets_file_blocked(self, applicator):
        """Cannot write to secrets file."""
        result = applicator.write_file_atomic("/project/secrets.yaml", "content")
        assert not result.success

    def test_trade_secret_blocked(self, applicator):
        """Cannot modify trade_secret files."""
        result = applicator.apply_diff_atomic(
            "/project/src/trade_secret_values.py", "diff"
        )
        assert not result.success
        assert "GOVERNANCE BLOCK" in result.stderr

    def test_ip_gate_blocked(self, applicator):
        """Cannot modify ip_gate files."""
        result = applicator.write_file_atomic(
            "/project/graqle/ip_gate.py", "content"
        )
        assert not result.success

    def test_normal_file_allowed(self, applicator, work_dir):
        """Normal source files ARE allowed."""
        target = work_dir / "src" / "normal_code.py"
        result = applicator.write_file_atomic(str(target), "def foo(): pass")
        assert result.success

    def test_is_protected_file_function(self):
        """_is_protected_file correctly identifies patterns."""
        assert _is_protected_file(".env") is True
        assert _is_protected_file("/project/.env.local") is True
        assert _is_protected_file("/project/src/credentials.json") is True
        assert _is_protected_file("/project/src/main.py") is False
        assert _is_protected_file("/project/tests/test_auth.py") is False
