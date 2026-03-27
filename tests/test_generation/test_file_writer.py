"""
tests/test_generation/test_file_writer.py
T2.1 — Tests for apply_diff(), ApplyResult, atomic write, and rollback.
10 tests.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from graqle.core.file_writer import ApplyResult, apply_diff


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ORIGINAL = """\
def greet(name):
    return f"Hello, {name}"
"""

DIFF_ADD_DOCSTRING = """\
--- a/greet.py
+++ b/greet.py
@@ -1,2 +1,4 @@
 def greet(name):
+    \"\"\"Greet a person by name.\"\"\"
     return f"Hello, {name}"
"""

DIFF_CHANGE_RETURN = """\
--- a/greet.py
+++ b/greet.py
@@ -1,2 +1,2 @@
 def greet(name):
-    return f"Hello, {name}"
+    return f"Hi, {name}!"
"""

DIFF_EMPTY_HUNKS = """\
--- a/greet.py
+++ b/greet.py
"""


@pytest.fixture
def tmp_py_file(tmp_path: Path) -> Path:
    f = tmp_path / "greet.py"
    f.write_text(ORIGINAL, encoding="utf-8")
    return f


@pytest.fixture
def tmp_txt_file(tmp_path: Path) -> Path:
    f = tmp_path / "notes.txt"
    f.write_text("line one\nline two\n", encoding="utf-8")
    return f


# ---------------------------------------------------------------------------
# ApplyResult — data class
# ---------------------------------------------------------------------------

class TestApplyResult:
    def test_to_dict_keys(self) -> None:
        r = ApplyResult(
            success=True, lines_changed=3, backup_path="/tmp/foo.bak",
            error="", file_path="foo.py", dry_run=False,
        )
        d = r.to_dict()
        assert set(d.keys()) == {"success", "lines_changed", "backup_path", "error", "file_path", "dry_run"}

    def test_dry_run_default_false(self) -> None:
        r = ApplyResult(success=True, lines_changed=0, backup_path="", error="", file_path="x.py")
        assert r.dry_run is False


# ---------------------------------------------------------------------------
# apply_diff — error paths
# ---------------------------------------------------------------------------

class TestApplyDiffErrors:
    def test_file_not_found(self, tmp_path: Path) -> None:
        result = apply_diff(tmp_path / "nonexistent.py", DIFF_ADD_DOCSTRING)
        assert result.success is False
        assert "not found" in result.error.lower()

    def test_empty_diff_returns_error(self, tmp_py_file: Path) -> None:
        result = apply_diff(tmp_py_file, "   ")
        assert result.success is False
        assert "empty" in result.error.lower()

    def test_diff_no_hunks_returns_error(self, tmp_py_file: Path) -> None:
        result = apply_diff(tmp_py_file, DIFF_EMPTY_HUNKS)
        assert result.success is False
        assert "hunk" in result.error.lower()


# ---------------------------------------------------------------------------
# apply_diff — dry_run (no writes)
# ---------------------------------------------------------------------------

class TestApplyDiffDryRun:
    def test_dry_run_returns_success(self, tmp_py_file: Path) -> None:
        result = apply_diff(tmp_py_file, DIFF_ADD_DOCSTRING, dry_run=True)
        assert result.success is True
        assert result.dry_run is True

    def test_dry_run_does_not_modify_file(self, tmp_py_file: Path) -> None:
        original_content = tmp_py_file.read_text()
        apply_diff(tmp_py_file, DIFF_ADD_DOCSTRING, dry_run=True)
        assert tmp_py_file.read_text() == original_content

    def test_dry_run_no_backup_created(self, tmp_py_file: Path) -> None:
        result = apply_diff(tmp_py_file, DIFF_ADD_DOCSTRING, dry_run=True)
        assert result.backup_path == ""

    def test_dry_run_reports_lines_changed(self, tmp_py_file: Path) -> None:
        result = apply_diff(tmp_py_file, DIFF_CHANGE_RETURN, dry_run=True)
        assert result.lines_changed == 2  # 1 removed + 1 added


# ---------------------------------------------------------------------------
# apply_diff — real write (dry_run=False)
# ---------------------------------------------------------------------------

class TestApplyDiffWrite:
    def test_write_modifies_file(self, tmp_py_file: Path) -> None:
        result = apply_diff(tmp_py_file, DIFF_CHANGE_RETURN, dry_run=False,
                            skip_syntax_check=True)
        assert result.success is True
        new_content = tmp_py_file.read_text()
        assert "Hi," in new_content

    def test_write_creates_backup(self, tmp_py_file: Path) -> None:
        result = apply_diff(tmp_py_file, DIFF_CHANGE_RETURN, dry_run=False,
                            skip_syntax_check=True)
        assert result.backup_path != ""
        assert Path(result.backup_path).exists()

    def test_rollback_restores_original(self, tmp_py_file: Path, monkeypatch) -> None:
        """Simulate a failed write: backup exists, rollback restores original."""
        original_content = tmp_py_file.read_text()

        # Patch os.replace to fail after backup is written
        real_replace = os.replace

        call_count = {"n": 0}

        def failing_replace(src: str, dst: str) -> None:
            call_count["n"] += 1
            raise OSError("Simulated write failure")

        monkeypatch.setattr(os, "replace", failing_replace)

        result = apply_diff(tmp_py_file, DIFF_CHANGE_RETURN, dry_run=False,
                            skip_syntax_check=True)

        monkeypatch.setattr(os, "replace", real_replace)

        # The file should be restored to original content
        assert tmp_py_file.read_text() == original_content
        assert result.success is False
        assert "rolled back" in result.error.lower()
