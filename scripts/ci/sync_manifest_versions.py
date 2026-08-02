#!/usr/bin/env python3
"""Sync every distribution manifest to the released version (CR-DIST-06).

Why this exists
---------------
Three manifests carry a hand-maintained version string. Nothing updated them, so
they drifted to ``0.80.0`` while PyPI served ``0.83.0`` — three releases stale.

That drift is *not* a paywall leak: the Claude Code / Codex plugins invoke ``graq``
from the user's own environment and pin no version, so a stale manifest never
installs old code. It is a **listing** problem — a directory entry that advertises
a version we no longer ship, which reads as an abandoned project.

``server.json`` is a special case. The MCP Registry workflow already rewrites it
from the tag *inside the CI checkout* before publishing, so the published registry
entry has always been correct. But that rewrite is never committed, so the file in
git stays stale forever. This script fixes the repo copy too, which keeps the two
in agreement and stops the next person "fixing" a bug that isn't there.

Usage
-----
    python scripts/ci/sync_manifest_versions.py 0.83.0     # write
    python scripts/ci/sync_manifest_versions.py 0.83.0 --check   # verify only

``--check`` exits 1 when anything is out of sync, so CI can fail a release that
would ship a stale listing.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

# (path, list-of-dotted-key-paths-to-set). A dotted path may index a list: "packages.0.version".
TARGETS: list[tuple[str, list[str]]] = [
    ("server.json", ["version", "packages.0.version"]),
    ("plugins/claude-code/graqle/.claude-plugin/plugin.json", ["version"]),
    ("plugins/codex/graqle/.codex-plugin/plugin.json", ["version"]),
    # The marketplace manifests are what a directory reviewer fetches. Their version
    # is NESTED under plugins[0] — a top-level grep for '"version"' finds only
    # metadata.version and misses it, which is exactly how these two were left out
    # of the first pass of this CR.
    #
    # metadata.version is deliberately NOT synced: it is the marketplace *schema*
    # version (1.0.0), not the SDK release. Syncing it would corrupt the manifest.
    (".claude-plugin/marketplace.json", ["plugins.0.version"]),
    (".agents/plugins/marketplace.json", ["plugins.0.version"]),
]

# PEP 440 core release + optional pre/post/dev suffix. Deliberately strict: a
# malformed version must not be written into a public listing.
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[abc]|rc)?\d*(?:\.(?:post|dev)\d+)?$")


def _set_path(obj, dotted: str, value: str) -> bool:
    """Set ``dotted`` on ``obj``. Returns True if the value actually changed.

    Missing keys are an error, not a silent no-op: a manifest that lost its
    version field would otherwise sync "successfully" while staying stale.
    """
    parts = dotted.split(".")
    cur = obj
    for p in parts[:-1]:
        if isinstance(cur, list):
            cur = cur[int(p)]
        else:
            if p not in cur:
                raise KeyError(dotted)
            cur = cur[p]
    last = parts[-1]
    if isinstance(cur, list):
        idx = int(last)
        old, cur[idx] = cur[idx], value
        return old != value
    if last not in cur:
        raise KeyError(dotted)
    old, cur[last] = cur[last], value
    return old != value


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("version", help="Release version, e.g. 0.83.0 (a leading 'v' is stripped)")
    ap.add_argument("--check", action="store_true",
                    help="Report drift and exit 1 without writing anything.")
    ap.add_argument("--root", default=".", help="Repo root (default: cwd)")
    args = ap.parse_args()

    version = args.version.lstrip("v").strip()
    if not _VERSION_RE.match(version):
        print(f"ERROR: {version!r} is not a valid release version", file=sys.stderr)
        return 2

    root = pathlib.Path(args.root)
    drifted: list[str] = []
    missing: list[str] = []

    for rel, keys in TARGETS:
        path = root / rel
        if not path.exists():
            # A manifest that has been removed is not a failure — but say so, or a
            # silently-skipped file looks identical to a synced one.
            missing.append(rel)
            continue

        data = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for key in keys:
            try:
                changed |= _set_path(data, key, version)
            except (KeyError, IndexError, ValueError) as exc:
                print(f"ERROR: {rel}: cannot resolve '{key}' ({exc})", file=sys.stderr)
                return 2

        if not changed:
            print(f"  ok      {rel}")
            continue

        drifted.append(rel)
        if args.check:
            print(f"  DRIFT   {rel}  (expected {version})")
        else:
            # Trailing newline + 2-space indent matches how these files are stored,
            # so a sync produces a one-line diff rather than reformatting the file.
            # ensure_ascii=False: these manifests contain real UTF-8 (an em-dash in
            # the marketplace description). Default json.dumps would rewrite it as
            # —, turning a one-line version bump into a mojibake diff on a file
            # that directory reviewers read.
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            print(f"  synced  {rel}  -> {version}")

    for rel in missing:
        print(f"  absent  {rel} (skipped)")

    if args.check and drifted:
        print(
            f"\n{len(drifted)} manifest(s) stale. Run:\n"
            f"    python scripts/ci/sync_manifest_versions.py {version}",
            file=sys.stderr,
        )
        return 1

    if not drifted:
        print(f"\nAll manifests already at {version}.")
    else:
        print(f"\n{len(drifted)} manifest(s) synced to {version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
