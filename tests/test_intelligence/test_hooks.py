"""Tests for graqle.intelligence.hooks — Pre-commit hook generator."""

# ── graqle:intelligence ──
# module: tests.test_intelligence.test_hooks
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, pathlib, pytest, hooks
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from pathlib import Path

import pytest

from graqle.intelligence.hooks import (
    HOOK_MARKER_START,
    HOOK_MARKER_END,
    install_hook,
    uninstall_hook,
    has_hook,
)


def _setup_git_dir(root: Path) -> Path:
    """Create a minimal .git/hooks directory."""
    hooks_dir = root / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    return hooks_dir


class TestInstallHook:
    """Tests for install_hook."""

    def test_install_new_hook(self, tmp_path: Path) -> None:
        _setup_git_dir(tmp_path)
        assert install_hook(tmp_path) is True

        hook_path = tmp_path / ".git" / "hooks" / "pre-commit"
        assert hook_path.exists()
        content = hook_path.read_text(encoding="utf-8")
        assert "#!/bin/sh" in content
        assert HOOK_MARKER_START in content
        assert "graq verify" in content

    def test_install_appends_to_existing(self, tmp_path: Path) -> None:
        hooks_dir = _setup_git_dir(tmp_path)
        existing_hook = hooks_dir / "pre-commit"
        existing_hook.write_text("#!/bin/sh\necho 'existing hook'\n", encoding="utf-8")

        assert install_hook(tmp_path) is True

        content = existing_hook.read_text(encoding="utf-8")
        assert "existing hook" in content
        assert HOOK_MARKER_START in content

    def test_install_idempotent(self, tmp_path: Path) -> None:
        _setup_git_dir(tmp_path)
        install_hook(tmp_path)
        assert install_hook(tmp_path) is False  # Already installed

    def test_install_no_git_dir(self, tmp_path: Path) -> None:
        assert install_hook(tmp_path) is False


class TestUninstallHook:
    """Tests for uninstall_hook."""

    def test_uninstall_removes_graqle_section(self, tmp_path: Path) -> None:
        hooks_dir = _setup_git_dir(tmp_path)
        install_hook(tmp_path)
        assert has_hook(tmp_path) is True

        assert uninstall_hook(tmp_path) is True
        assert has_hook(tmp_path) is False

    def test_uninstall_preserves_other_hooks(self, tmp_path: Path) -> None:
        hooks_dir = _setup_git_dir(tmp_path)
        existing = "#!/bin/sh\necho 'my custom hook'\n"
        (hooks_dir / "pre-commit").write_text(existing, encoding="utf-8")

        install_hook(tmp_path)
        uninstall_hook(tmp_path)

        content = (hooks_dir / "pre-commit").read_text(encoding="utf-8")
        assert "my custom hook" in content
        assert HOOK_MARKER_START not in content

    def test_uninstall_removes_file_if_empty(self, tmp_path: Path) -> None:
        _setup_git_dir(tmp_path)
        install_hook(tmp_path)
        uninstall_hook(tmp_path)

        hook_path = tmp_path / ".git" / "hooks" / "pre-commit"
        assert not hook_path.exists()

    def test_uninstall_no_hook(self, tmp_path: Path) -> None:
        _setup_git_dir(tmp_path)
        assert uninstall_hook(tmp_path) is False


class TestHasHook:
    """Tests for has_hook."""

    def test_has_hook_true(self, tmp_path: Path) -> None:
        _setup_git_dir(tmp_path)
        install_hook(tmp_path)
        assert has_hook(tmp_path) is True

    def test_has_hook_false(self, tmp_path: Path) -> None:
        _setup_git_dir(tmp_path)
        assert has_hook(tmp_path) is False

    def test_has_hook_no_git(self, tmp_path: Path) -> None:
        assert has_hook(tmp_path) is False
