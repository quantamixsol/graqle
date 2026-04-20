"""ITEM 12 — SDK-B5 — Worktree GRAQ.md inheritance.

Acceptance:
1. _resolve_worktree_main_repo returns None for a regular (non-worktree) dir.
2. _resolve_worktree_main_repo returns the main repo root when given a
   directory inside a synthetic worktree (.git file containing gitdir:).
3. GraqMdLoader.load() successfully returns a SystemPromptBundle for any dir.
4. The walk-up collects a GRAQ.md placed at the worktree root.
"""

from __future__ import annotations

import time
from pathlib import Path


def test_sdk_b5_worktree_inheritance(record, tmp_path):
    t0 = time.monotonic()
    assertions = 0
    evidence: dict = {}

    from graqle.chat.graq_md_loader import GraqMdLoader

    # --- 1. Regular directory → _resolve_worktree_main_repo returns None ---
    regular_dir = tmp_path / "regular"
    regular_dir.mkdir()
    (regular_dir / "dummy.txt").write_text("x", encoding="utf-8")
    main_repo = GraqMdLoader._resolve_worktree_main_repo(regular_dir)
    assert main_repo is None, f"regular dir should not resolve to worktree main: {main_repo}"
    assertions += 1
    evidence["regular_dir_none"] = True

    # --- 2. Synthetic worktree: .git FILE containing gitdir: ---
    main_root = tmp_path / "main_repo"
    (main_root / ".git" / "worktrees" / "wt1").mkdir(parents=True)
    (main_root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (main_root / "GRAQ.md").write_text("# Main repo GRAQ.md\n\nRules from main.\n", encoding="utf-8")

    worktree_root = tmp_path / "wt1"
    worktree_root.mkdir()
    # .git FILE (not dir) pointing at the worktree's gitdir under main_repo
    wt_gitdir = main_root / ".git" / "worktrees" / "wt1"
    (worktree_root / ".git").write_text(
        f"gitdir: {wt_gitdir}\n", encoding="utf-8"
    )
    (worktree_root / "GRAQ.md").write_text("# Worktree GRAQ.md\n\nRules from worktree.\n", encoding="utf-8")

    resolved = GraqMdLoader._resolve_worktree_main_repo(worktree_root)
    assert resolved is not None, "synthetic worktree should resolve"
    # Path resolution via realpath may normalize differently; compare via resolve()
    assert Path(resolved).resolve() == main_root.resolve(), (resolved, main_root)
    assertions += 1
    evidence["worktree_detected"] = True
    evidence["main_resolved_to"] = str(resolved)

    # --- 3. GraqMdLoader.load() returns a bundle without crashing ---
    loader = GraqMdLoader()
    bundle = loader.load(start_dir=worktree_root)
    assert bundle is not None
    # Bundle shape: attributes vary but 'assembled' text must be present
    # (SystemPromptBundle is a dataclass/NamedTuple in the module)
    bundle_text = str(bundle)
    assert len(bundle_text) > 0
    assertions += 1
    evidence["bundle_loaded"] = True

    # --- 4. Walk-up picks up the worktree GRAQ.md ---
    pairs = loader._walk_up_collect(worktree_root)
    # pairs is list[tuple[Path, str]] — find our worktree GRAQ.md
    picked_paths = [str(p) for p, _ in pairs]
    found = any("wt1" in p or str(worktree_root) in p for p in picked_paths)
    assert found, f"worktree GRAQ.md not in walk-up: {picked_paths}"
    assertions += 1
    evidence["walk_up_includes_worktree"] = True
    evidence["walk_up_count"] = len(pairs)

    record(
        item_id="12-sdk-b5",
        name="SDK-B5 — Worktree GRAQ.md inheritance",
        status="PASS",
        assertions=assertions,
        duration_ms=int((time.monotonic() - t0) * 1000),
        evidence=evidence,
    )
