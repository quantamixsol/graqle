#!/usr/bin/env python3
"""ADR Visibility Gate — require explicit `visibility: public` frontmatter on
any newly-added ADR file landing on this PUBLIC repo.

Used by .github/workflows/adr-visibility-gate.yml. Reads NUL-delimited Added
paths from argv[1], identifies the ADR-naming subset, and enforces that each
matching file declares `visibility: public` in YAML frontmatter.

Why: ADR-151 (removed in PR #130) landed because there was no machine-checked
visibility decision at file-creation time. P0 (path-deny) blocks the historical
.gsm/decisions/ path; this gate is defense-in-depth for any new ADR home, and
forces an explicit per-document decision.

Triggered file patterns (case-insensitive on the path):
  - .gsm/decisions/**/*.md
  - docs/adr/**/*.md
  - any path with a basename starting with ADR-{digit}

Pre-existing ADR files are grandfathered: this scanner only looks at Added (A)
diff entries. P0 + P1 cover the other cases.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


# Required header — must appear in the YAML frontmatter block.
# Accepts: visibility: public OR visibility: "public" OR visibility: 'public'
VISIBILITY_PUBLIC_RE = re.compile(
    r"""^\s*visibility\s*:\s*['"]?public['"]?\s*$""",
    re.MULTILINE,
)

# Match any visibility declaration so we can give a precise error if the value
# is wrong (e.g. visibility: private or visibility: internal).
VISIBILITY_ANY_RE = re.compile(
    r"""^\s*visibility\s*:\s*['"]?(?P<value>[^'"\s]+)['"]?\s*$""",
    re.MULTILINE,
)


# Trigger patterns — paths that look like ADRs.
TRIGGER_PATTERNS = [
    re.compile(r"^\.gsm/decisions/.*\.md$", re.IGNORECASE),
    re.compile(r"^docs/adr/.*\.md$", re.IGNORECASE),
    re.compile(r"(^|/)ADR-\d+[^/]*\.md$", re.IGNORECASE),
]


# Defensive caps — same rationale as P1.
MAX_FILE_SIZE_BYTES = 1 * 1024 * 1024
FRONTMATTER_SCAN_LINES = 30  # frontmatter must be at top; cap reads.

# Cap on total ADR files scanned in a single CI run. A legitimate PR rarely
# adds more than 5 ADRs at once; 200 is a generous ceiling that still bounds
# CI cost on a pathological diff.
MAX_ADR_FILES = 200


def is_adr(path: str) -> bool:
    return any(pat.search(path) for pat in TRIGGER_PATTERNS)


def iter_paths(nul_file: Path) -> list[str]:
    raw = nul_file.read_bytes()
    return [p.decode("utf-8", errors="replace") for p in raw.split(b"\x00") if p]


def _is_safe_repo_path(path: str, repo_root: Path) -> bool:
    p = Path(path)
    if p.is_absolute():
        return False
    try:
        resolved = (repo_root / p).resolve(strict=False)
        return resolved.is_relative_to(repo_root.resolve())
    except (OSError, ValueError):
        return False


def extract_frontmatter_block(text: str) -> str | None:
    """Return the content between the first two `---` lines, or None.

    A YAML frontmatter block in markdown is:
        ---
        key: value
        ---
        ...
    Looks for the opening fence at line 1 (markdown convention).
    """
    lines = text.splitlines()[:FRONTMATTER_SCAN_LINES]
    if not lines or lines[0].strip() != "---":
        return None
    body: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            return "\n".join(body)
        body.append(line)
    # No closing fence found within the cap — treat as no frontmatter.
    return None


def check_adr(path: str, repo_root: Path) -> str | None:
    """Return None if the ADR is OK, or an error message if it's invalid."""
    if not _is_safe_repo_path(path, repo_root):
        # Refuse to read out-of-tree paths. Treat as "no error" — out-of-tree
        # ADRs are nonsensical and the diff source should never produce them.
        return None
    p = repo_root / path
    if not p.exists():
        return None
    try:
        if p.stat().st_size > MAX_FILE_SIZE_BYTES:
            return f"file exceeds {MAX_FILE_SIZE_BYTES} bytes — refusing to scan"
        text = p.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return None

    fm = extract_frontmatter_block(text)
    if fm is None:
        return (
            "missing YAML frontmatter. ADR files on this public repo MUST start with:\n"
            "          ---\n"
            "          visibility: public\n"
            "          ---"
        )

    if VISIBILITY_PUBLIC_RE.search(fm):
        return None

    other = VISIBILITY_ANY_RE.search(fm)
    if other:
        value = other.group("value")
        return (
            f"frontmatter declares `visibility: {value}` — this PUBLIC repo "
            f"only accepts `visibility: public`. If this ADR is internal, "
            f"move it to the private repo (research-development-graqle)."
        )

    return (
        "frontmatter present but missing `visibility:` key. Add a line:\n"
        "          visibility: public"
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: adr_visibility_scan.py <nul-delimited-paths-file>", file=sys.stderr)
        return 2

    repo_root = Path.cwd().resolve()
    paths = iter_paths(Path(argv[1]))
    if not paths:
        print("ADR Visibility Gate: no Added paths to scan.")
        return 0

    adr_paths = [p for p in paths if is_adr(p)]
    if not adr_paths:
        print(f"ADR Visibility Gate: 0 of {len(paths)} added path(s) are ADRs. PASS.")
        return 0

    if len(adr_paths) > MAX_ADR_FILES:
        print(
            f"::error::ADR Visibility Gate BLOCKED — diff contains {len(adr_paths)} "
            f"ADR files; cap is {MAX_ADR_FILES}. Split this change into smaller PRs."
        )
        return 1

    print(f"ADR Visibility Gate: scanning {len(adr_paths)} ADR path(s)")

    violations: list[str] = []
    for path in adr_paths:
        err = check_adr(path, repo_root)
        if err:
            violations.append(f"'{path}': {err}")

    if violations:
        print()
        print("::error::ADR Visibility Gate BLOCKED — ADRs missing or wrong visibility:")
        for v in violations:
            for line in v.splitlines():
                print(f"::error::  {line}")
        print()
        print("Why: every new ADR on this public repo must declare an explicit")
        print("visibility decision. This prevents the ADR-151-class leak where")
        print("an internal-only document landed on public because no one made a")
        print("conscious public-vs-private call at authoring time.")
        print()
        print("Resolution:")
        print("  1. Add YAML frontmatter to the top of each ADR:")
        print("       ---")
        print("       visibility: public")
        print("       ---")
        print("  2. If the ADR is internal, move it to the private repo")
        print("     (research-development-graqle) and remove from this PR.")
        return 1

    print(f"ADR Visibility Gate: PASS ({len(adr_paths)} ADR(s) declare visibility: public)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
