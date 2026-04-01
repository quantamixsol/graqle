#!/usr/bin/env python3
"""Audit all branches for TS pattern leakage (ADR-140).

Usage:
    python scripts/audit_branches.py [--base main]

Scans the diff of each branch against base for trade secret patterns.
Exit code 1 if any branch contains TS leakage.
"""
from __future__ import annotations

import subprocess
import sys

from graqle.core.governance import _check_ts_leakage


def main(base: str = "main") -> int:
    """Audit all remote branches against base for TS leakage."""
    result = subprocess.run(
        ["git", "branch", "-r", "--format=%(refname:short)"],
        capture_output=True, text=True, check=True,
    )
    branches = [b.strip() for b in result.stdout.strip().splitlines() if b.strip()]

    failures: list[str] = []
    for branch in branches:
        if branch.endswith("/HEAD"):
            continue
        try:
            diff_result = subprocess.run(
                ["git", "diff", f"{base}...{branch}", "--", "*.py", "*.ts", "*.tsx", "*.js", "*.md"],
                capture_output=True, text=True, check=True,
            )
            diff = diff_result.stdout
            if not diff:
                continue
            blocked, reason = _check_ts_leakage(diff)
            if blocked:
                failures.append(f"  {branch}: {reason}")
                print(f"FAIL: {branch} — {reason}", file=sys.stderr)
            else:
                print(f"PASS: {branch}")
        except subprocess.CalledProcessError:
            print(f"SKIP: {branch} (no common ancestor with {base})", file=sys.stderr)

    if failures:
        print(f"\n{len(failures)} branch(es) contain TS leakage:", file=sys.stderr)
        for f in failures:
            print(f, file=sys.stderr)
        return 1

    print(f"\nAll {len(branches)} branches clean.")
    return 0


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] != "--base" else "main"
    if "--base" in sys.argv:
        idx = sys.argv.index("--base")
        if idx + 1 < len(sys.argv):
            base = sys.argv[idx + 1]
    sys.exit(main(base))
