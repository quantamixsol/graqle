#!/usr/bin/env python3
"""IP Content Scanner — fail fast on self-disclosing IP/patent meta-documents.

Used by .github/workflows/ip-content-gate.yml. Reads NUL-delimited Added/Modified
paths from the file given as argv[1], scans each one against a filename deny-list
and a first-100-lines content deny-list, and exits non-zero on any match.

Motivating example: ADR-151 (removed in PR #130). 62-line markdown placeholder
that named patent EP26167849.4, called a pattern "potentially novel", and listed
TS-1..TS-4 by label — all in the first 5 lines. Existing IP gate checked for
literal TS values, missed it. This scanner catches the meta-disclosure class.

Patterns are intentionally conservative: each one targets a phrase that would
not normally appear in legitimate public-facing markdown. False positives are
preferable to false negatives for IP risk.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


# Layer 1: filename patterns. Case-insensitive on the basename.
# Any match → block (unless the basename is in FILENAME_ALLOWLIST).
FILENAME_DENY = [
    re.compile(r"-ip-flag", re.IGNORECASE),
    re.compile(r"\bip[-_]review\b", re.IGNORECASE),
    re.compile(r"\bpatent[-_]?(draft|claim|filing|note)", re.IGNORECASE),
    re.compile(r"\btrade[-_]secret", re.IGNORECASE),
    re.compile(r"\bts[-_]\d+\b", re.IGNORECASE),
]

# Basenames (case-sensitive) that are explicitly permitted despite matching a
# FILENAME_DENY pattern. These are CI enforcement tools, not IP documents.
# WS-F (ADR-BIZ-001, 2026-06-25): the wheel gate and its workflow contain
# "trade_secret" / "trade-secret" in their names because they ARE the gate —
# they enforce the boundary, they do not disclose internals.
FILENAME_ALLOWLIST: frozenset[str] = frozenset([
    "trade_secret_wheel_gate.py",
    "trade-secret-wheel-gate.yml",
])


# Layer 2: content patterns. Scanned against the first 100 lines of any
# Added/Modified text file (extensions: .md .txt .rst .adoc, plus README*).
# Any single match → block.
CONTENT_DENY = [
    # Patent-document self-references
    (re.compile(r"^\s*\*?\*?Patent Reference:\*?\*?", re.MULTILINE), "Patent Reference: header"),
    (re.compile(r"FLAGGED\s+FOR\s+IP\s+REVIEW", re.IGNORECASE), "FLAGGED FOR IP REVIEW status"),
    (re.compile(r"\bClaims?\s+[A-Z]+(?:[-,]\s*[A-Z]+)+\b"), "Claim-letter range (e.g. Claims K-O)"),
    (re.compile(r"\bpending\s+counsel\b", re.IGNORECASE), "pending counsel"),
    (re.compile(r"\bpatent\s+counsel\b", re.IGNORECASE), "patent counsel"),
    (re.compile(r"\bdefensive\s+publication\b", re.IGNORECASE), "defensive publication"),

    # Self-disclosing novelty language (the ADR-151 fingerprint)
    (re.compile(r"\bpotentially\s+novel\b", re.IGNORECASE), "potentially novel"),
    (re.compile(r"\bnovel\s+architectural\s+pattern\b", re.IGNORECASE), "novel architectural pattern"),
    (re.compile(r"strengthens\s+the\s+\w+\s+patent\s+narrative", re.IGNORECASE), "strengthens patent narrative"),

    # Patent application numbers (EP, WO, US format).
    # GraQle's own published patent numbers (EP26167849.4, EP26162901.8,
    # EP26166054.2) are intentionally public per ADR-MARKETING-001 — they
    # appear on README.md, LinkedIn, and the v0.56.0+ PyPI wheels since
    # 2026-05-15. The scanner remains active for ANY OTHER patent number
    # that might appear (e.g. a draft application or a third-party patent),
    # but GraQle's own numbers are whitelisted as approved public references.
    # EP26166054.2 added 2026-05-19 (cr-019c) after cr-019/cr-021 each
    # tripped this gate on legitimate references to the CogniGraph divisional.
    (re.compile(r"\bEP\s?(?!26167849\.4\b|26162901\.8\b|26166054\.2\b)\d{6,}(?:\.\d+)?\b"), "European patent application number (other than GraQle's published EP26167849.4 / EP26162901.8 / EP26166054.2)"),
    (re.compile(r"\bWO\s?\d{4}/\d{4,}\b"), "WIPO patent application number"),
    (re.compile(r"\bUS\s?\d{4}/\d{6,}\b"), "US patent application number"),

    # Trade-secret label by name (without quoting any value)
    (re.compile(r"\bTS-[1-9]\b(?:\s*\.\.\s*TS-[1-9]\b)?"), "TS-N trade-secret label"),
    (re.compile(r"\btrade[-\s]?secret\s+(label|boundary|protection)\b", re.IGNORECASE), "trade-secret label/boundary/protection"),

    # Internal classification keywords that should never be on public
    (re.compile(r"\bINTERNAL\s+ONLY\b"), "INTERNAL ONLY classification"),
    (re.compile(r"\bCONFIDENTIAL\s*[—-]\s*DO\s+NOT\s+DISTRIBUTE\b", re.IGNORECASE), "CONFIDENTIAL — DO NOT DISTRIBUTE"),
]


# File extensions the content scan applies to. Other extensions skip Layer 2
# (Layer 1 still applies to any extension).
TEXT_EXTENSIONS = {".md", ".txt", ".rst", ".adoc", ".markdown"}

CONTENT_SCAN_LINES = 100

# Cap content reads at 1 MB. A markdown header/metadata block does not need
# more than this. Bounds CI cost and prevents resource-exhaustion if a path
# from `git diff` somehow points to a very large file.
MAX_FILE_SIZE_BYTES = 1 * 1024 * 1024


def iter_paths(nul_file: Path) -> list[str]:
    """Read NUL-delimited paths from a file."""
    raw = nul_file.read_bytes()
    return [p.decode("utf-8", errors="replace") for p in raw.split(b"\x00") if p]


def check_filename(path: str) -> list[str]:
    """Return list of FILENAME_DENY pattern descriptions that match this path."""
    name = Path(path).name
    if name in FILENAME_ALLOWLIST:
        return []
    return [pat.pattern for pat in FILENAME_DENY if pat.search(name)]


def _is_safe_repo_path(path: str, repo_root: Path) -> bool:
    """Reject paths that escape the repo root or are absolute.

    Defensive: `git diff --diff-filter=AM --name-only` should only emit
    repo-relative paths for tracked files, but anchor explicitly so that
    a malicious or malformed path cannot reach outside the repo.
    """
    p = Path(path)
    if p.is_absolute():
        return False
    try:
        resolved = (repo_root / p).resolve(strict=False)
        return resolved.is_relative_to(repo_root.resolve())
    except (OSError, ValueError):
        return False


def check_content(path: str, repo_root: Path) -> list[tuple[str, int]]:
    """Return list of (description, line_number) for content matches.

    Returns empty list if file unreadable, escapes repo root, exceeds size
    cap, or extension not in TEXT_EXTENSIONS.
    """
    if not _is_safe_repo_path(path, repo_root):
        return []
    p = repo_root / path
    if p.suffix.lower() not in TEXT_EXTENSIONS:
        return []
    if not p.exists():
        # Path may be added in the diff but not on disk yet (rare in CI checkout
        # since fetch-depth: 0 should have it). Treat as empty.
        return []
    try:
        size = p.stat().st_size
    except OSError:
        return []
    if size > MAX_FILE_SIZE_BYTES:
        # Refuse to scan oversized files. Block-by-default would be too noisy
        # for legitimate large docs; Layer 1 (filename) still applies to them.
        print(f"  (skipped content scan: {path} exceeds {MAX_FILE_SIZE_BYTES} bytes)")
        return []
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return []

    head = "\n".join(text.splitlines()[:CONTENT_SCAN_LINES])
    hits: list[tuple[str, int]] = []
    for pat, desc in CONTENT_DENY:
        for m in pat.finditer(head):
            line_no = head.count("\n", 0, m.start()) + 1
            hits.append((desc, line_no))
    return hits


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: ip_content_scan.py <nul-delimited-paths-file>", file=sys.stderr)
        return 2

    repo_root = Path.cwd().resolve()

    paths = iter_paths(Path(argv[1]))
    if not paths:
        print("IP Content Gate: no Added/Modified paths to scan.")
        return 0

    print(f"IP Content Gate: scanning {len(paths)} path(s)")

    violations: list[str] = []

    for path in paths:
        # Layer 1
        fname_hits = check_filename(path)
        for hit in fname_hits:
            violations.append(f"FILENAME: '{path}' matches deny pattern /{hit}/")

        # Layer 2
        content_hits = check_content(path, repo_root)
        for desc, line_no in content_hits:
            violations.append(f"CONTENT:  '{path}' line {line_no}: {desc}")

    if violations:
        print()
        print("::error::IP Content Gate BLOCKED — IP-disclosure markers detected:")
        for v in violations:
            print(f"::error::  {v}")
        print()
        print("These markers indicate the file may be an internal IP/patent")
        print("meta-document that should not be on a public repo. Common cases:")
        print("  - ADR with 'FLAGGED FOR IP REVIEW' header")
        print("  - Patent application reference (EP/WO/US numbers)")
        print("  - Self-disclosing novelty language ('potentially novel', etc.)")
        print("  - Trade-secret labels (TS-1..TS-N) named without quoting values")
        print()
        print("Resolution:")
        print("  1. If the document is internal: move it to the private repo.")
        print("  2. If the language is overstated: rephrase without IP markers.")
        print("  3. If counsel has cleared this content: contact repo maintainer")
        print("     to record the exception in scripts/ci/ip_content_scan.py.")
        return 1

    print("IP Content Gate: PASS — no IP-disclosure markers found.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
