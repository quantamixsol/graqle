"""SDK-B5 — Worktree GRAQ.md inheritance tests.

Verifies that when ChatAgentLoop is invoked from inside a git worktree,
the main repo's GRAQ.md is prepended to the walk-up chain so governance
policy is inherited rather than silently lost.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from graqle.chat.graq_md_loader import GraqMdLoader, GRAQ_MD_FILENAME


def _simulate_worktree(tmp_path: Path):
    """Build a fake main repo + worktree layout.

    Returns (main_repo, worktree).

    Structure:
        <tmp>/main/           ← main repo (has .git/ dir)
            .git/worktrees/wt-a/  ← worktree pointer dir
            GRAQ.md               ← main-repo policy
        <tmp>/wt/             ← worktree
            .git              ← FILE with `gitdir: <tmp>/main/.git/worktrees/wt-a`
            GRAQ.md           ← worktree-local override
    """
    main = tmp_path / "main"
    main_git = main / ".git"
    main_wt = main_git / "worktrees" / "wt-a"
    main_wt.mkdir(parents=True)
    (main / "GRAQ.md").write_text("# main-repo policy\n", encoding="utf-8")

    wt = tmp_path / "wt"
    wt.mkdir()
    # Git worktree marker: .git is a FILE pointing at gitdir
    (wt / ".git").write_text(f"gitdir: {main_wt.resolve()}\n", encoding="utf-8")
    (wt / "GRAQ.md").write_text("# worktree-local policy\n", encoding="utf-8")

    return main, wt


def test_worktree_inherits_main_repo_graq_md(tmp_path):
    main, wt = _simulate_worktree(tmp_path)
    loader = GraqMdLoader()
    layered = loader._walk_up_collect(wt)
    paths = [p for p, _ in layered]
    # Both files collected
    assert any(p == (main / "GRAQ.md").resolve() or str(p) == str(main / "GRAQ.md") for p in paths), (
        f"main repo GRAQ.md not inherited. collected: {[str(p) for p in paths]}"
    )
    assert any(p == (wt / "GRAQ.md").resolve() or str(p) == str(wt / "GRAQ.md") for p in paths), (
        f"worktree-local GRAQ.md missing. collected: {[str(p) for p in paths]}"
    )


def test_worktree_local_graq_md_appears_AFTER_main_in_walk_order(tmp_path):
    """Farthest-ancestor-first: main appears BEFORE worktree in the list.

    This preserves the 'closest-to-cwd wins' semantics: the last entry in the
    list gets applied last and therefore has the final say on conflicts.
    """
    main, wt = _simulate_worktree(tmp_path)
    loader = GraqMdLoader()
    layered = loader._walk_up_collect(wt)

    def _idx(needle):
        for i, (p, _) in enumerate(layered):
            if str(p).endswith(needle):
                return i
        return -1

    main_idx = _idx(str(main / "GRAQ.md"))
    wt_idx = _idx(str(wt / "GRAQ.md"))
    assert main_idx >= 0 and wt_idx >= 0
    assert main_idx < wt_idx, (
        f"main-repo GRAQ.md must come before worktree GRAQ.md. "
        f"main={main_idx}, wt={wt_idx}"
    )


def test_non_worktree_plain_repo_unchanged(tmp_path):
    """Plain repo (no worktree) must use the existing walk-up unchanged."""
    repo = tmp_path / "plain"
    (repo / ".git").mkdir(parents=True)
    (repo / "GRAQ.md").write_text("# plain policy\n", encoding="utf-8")

    loader = GraqMdLoader()
    layered = loader._walk_up_collect(repo)
    # Only the repo's own GRAQ.md is collected (not from parents that may not have one).
    assert any(str(p).endswith("plain/GRAQ.md") or str(p).endswith("plain\\GRAQ.md")
               for p, _ in layered)


def test_resolve_worktree_main_repo_returns_none_for_plain_repo(tmp_path):
    repo = tmp_path / "plain"
    (repo / ".git").mkdir(parents=True)
    assert GraqMdLoader._resolve_worktree_main_repo(repo) is None


def test_resolve_worktree_main_repo_returns_main_for_worktree(tmp_path):
    main, wt = _simulate_worktree(tmp_path)
    result = GraqMdLoader._resolve_worktree_main_repo(wt)
    assert result is not None
    assert result.resolve() == main.resolve()


def test_resolve_worktree_main_repo_handles_malformed_git_file(tmp_path):
    """A .git file that's not a valid gitdir pointer returns None (fail-closed)."""
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("not a valid gitdir pointer\n", encoding="utf-8")
    assert GraqMdLoader._resolve_worktree_main_repo(wt) is None


def test_resolve_worktree_main_repo_handles_empty_gitdir(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("gitdir:   \n", encoding="utf-8")
    assert GraqMdLoader._resolve_worktree_main_repo(wt) is None


def test_resolve_worktree_main_repo_no_git_anywhere(tmp_path):
    """No .git at all → None (not a repo)."""
    plain = tmp_path / "no_repo"
    plain.mkdir()
    assert GraqMdLoader._resolve_worktree_main_repo(plain) is None


def test_worktree_without_main_graq_md_still_collects_worktree_local(tmp_path):
    """Main repo has no GRAQ.md; worktree has one. Worktree file still collected."""
    main, wt = _simulate_worktree(tmp_path)
    (main / "GRAQ.md").unlink()  # remove main-repo policy

    loader = GraqMdLoader()
    layered = loader._walk_up_collect(wt)
    paths = [str(p) for p, _ in layered]
    # Worktree file still present
    assert any("wt" in p and p.endswith("GRAQ.md") for p in paths)


def test_visited_dedup_prevents_double_count(tmp_path):
    """If main repo is somehow the parent-of-parent of worktree start_dir
    (contrived but possible on some filesystems), don't collect the same
    GRAQ.md twice.
    """
    main, wt = _simulate_worktree(tmp_path)
    loader = GraqMdLoader()
    layered = loader._walk_up_collect(wt)
    # Collect all resolved paths — no duplicates
    seen = set()
    for p, _ in layered:
        key = str(p.resolve())
        assert key not in seen, f"duplicate entry for {key}"
        seen.add(key)
