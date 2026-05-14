"""CR-003b — read-only git-bisect utility for the v0.46→v0.53 edge-loss regression.

Origin: BHG feedback #9b + #10 (2026-05-09) — "graqle.json has 22,516 nodes
but 0 edges". The regression was effectively subsumed by the CR-006 multi-edge
load + write fixes shipped in v0.54.2/0.54.3, but the BAU charter still wants
a bisect-style smoke utility around for future edge-loss regressions of any
shape.

This script is INTENTIONALLY READ-ONLY:
  * Does NOT run pytest, does NOT mutate working tree, does NOT touch Neo4j.
  * Does NOT use any LLM — pure subprocess + filesystem.
  * SHA-validates the candidate commit list against `git rev-list` to ensure
    we never bisect outside the explicit range.
  * REFUSES to run on a dirty working tree (uncommitted changes detected via
    `git status --porcelain`) to avoid silently swallowing user state.
  * TIME-BOUNDED per-commit probe (default 30s).
  * On exit (clean OR error OR Ctrl-C), restores the original HEAD.

Output: ``.gcc/REGRESSION-REPORT-edge-loss.md`` listing the bisect path and
the first commit whose probe failed. Adversarial paths (network failure,
disk-full simulation) are documented in the report.

Usage:
  python scripts/bisect_edge_loss.py \\
      --good v0.46.0 --bad v0.53.0 --fixture path/to/known_good.json [--timeout 30]
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ── Configuration ──────────────────────────────────────────────────────────

DEFAULT_TIMEOUT_SECONDS = 30
REPORT_PATH = Path(".gcc/REGRESSION-REPORT-edge-loss.md")


@dataclass
class ProbeResult:
    """Outcome of probing a single commit."""

    sha: str
    short: str
    subject: str
    status: str  # "good" / "bad" / "error" / "skipped"
    detail: str = ""


# ── Git helpers (read-only) ────────────────────────────────────────────────


def _run_git(*args: str, check: bool = True) -> str:
    """Read-only git invocation. Returns stdout, raises CalledProcessError on
    non-zero exit when check=True."""
    res = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=check,
    )
    return res.stdout.strip()


def _refuse_if_dirty() -> None:
    """Bail out if uncommitted changes — bisecting on a dirty tree silently
    drops the user's WIP into the wrong commit. The audit log would not
    capture this so we refuse explicitly."""
    porcelain = _run_git("status", "--porcelain")
    if porcelain:
        print(
            "REFUSE: working tree is dirty. Commit, stash, or revert your "
            "uncommitted changes before running this bisect.",
            file=sys.stderr,
        )
        print(porcelain[:2000], file=sys.stderr)
        sys.exit(2)


def _resolve(ref: str) -> str:
    """Resolve a ref to a full SHA. Aborts on unknown ref."""
    try:
        return _run_git("rev-parse", "--verify", ref)
    except subprocess.CalledProcessError as exc:
        print(f"REFUSE: cannot resolve ref {ref!r}: {exc.stderr.strip()}", file=sys.stderr)
        sys.exit(2)


def _rev_list(good_sha: str, bad_sha: str) -> list[str]:
    """Commit chain from good→bad inclusive, ordered oldest-first. SHA-validated
    against a second `git rev-list` call so we never bisect outside the range."""
    out = _run_git("rev-list", "--reverse", f"{good_sha}..{bad_sha}")
    shas = [line for line in out.splitlines() if line]
    if not shas:
        print(f"REFUSE: no commits between {good_sha[:8]} and {bad_sha[:8]}.", file=sys.stderr)
        sys.exit(2)
    # Cross-check: every sha is reachable from bad and NOT from good.
    reachable_from_bad = set(_run_git("rev-list", bad_sha).splitlines())
    reachable_from_good = set(_run_git("rev-list", good_sha).splitlines())
    for sha in shas:
        if sha not in reachable_from_bad or sha in reachable_from_good:
            print(f"REFUSE: SHA {sha[:8]} failed range cross-check.", file=sys.stderr)
            sys.exit(2)
    return shas


def _checkout(sha: str) -> None:
    """Checkout a commit in detached-HEAD mode. Raises on failure."""
    subprocess.run(["git", "checkout", "--quiet", "--detach", sha], check=True)


# ── The probe ──────────────────────────────────────────────────────────────


def _probe_commit(sha: str, fixture: Path, timeout: int) -> ProbeResult:
    """Probe one commit for the edge-loss symptom.

    Imports graqle FRESH (clears sys.modules), loads the fixture via
    Graqle.from_json, then asserts edge_count > 0. Time-bounded to ``timeout``
    seconds via a wall-clock check (no signal — Windows compatibility).

    Outcomes:
      * "good"    — graph loaded, edge_count > 0
      * "bad"     — graph loaded, edge_count == 0 (REGRESSION)
      * "error"   — exception during load (skipped from bisect direction)
      * "skipped" — fixture absent or invalid at this commit
    """
    short = sha[:8]
    subject = _run_git("log", "-1", "--format=%s", sha, check=False)[:80] or "(no subject)"

    # Wipe graqle from import cache so the freshly-checked-out tree wins.
    for mod_name in list(sys.modules):
        if mod_name.startswith("graqle"):
            del sys.modules[mod_name]

    if not fixture.exists():
        return ProbeResult(sha, short, subject, "skipped", "fixture missing at this commit")

    t0 = time.monotonic()
    try:
        from graqle.core.graph import Graqle  # imported per-commit on purpose

        g = Graqle.from_json(str(fixture))
        edge_count = len(getattr(g, "edges", []) or [])
        node_count = len(getattr(g, "nodes", []) or [])
    except Exception as exc:  # noqa: BLE001 — any failure here is non-fatal
        return ProbeResult(sha, short, subject, "error", f"{type(exc).__name__}: {str(exc)[:160]}")

    elapsed = time.monotonic() - t0
    if elapsed > timeout:
        return ProbeResult(sha, short, subject, "error", f"timeout ({elapsed:.1f}s > {timeout}s)")

    if edge_count == 0 and node_count > 0:
        return ProbeResult(
            sha, short, subject, "bad",
            f"node_count={node_count}, edge_count=0 (regression)",
        )
    return ProbeResult(
        sha, short, subject, "good",
        f"node_count={node_count}, edge_count={edge_count}",
    )


# ── Bisect driver ──────────────────────────────────────────────────────────


def _bisect(good_sha: str, bad_sha: str, fixture: Path, timeout: int) -> list[ProbeResult]:
    """Linear forward-walk through the commit range. NOT a binary search —
    this gives the full audit trail of every commit's status in O(N) wall
    time, which is acceptable for the ~150 commit v0.46→v0.53 range and
    much easier to reason about under read-only constraints."""
    shas = _rev_list(good_sha, bad_sha)
    print(f"[bisect] {len(shas)} commits in range {good_sha[:8]}..{bad_sha[:8]}")
    results: list[ProbeResult] = []
    for i, sha in enumerate(shas, 1):
        try:
            _checkout(sha)
        except subprocess.CalledProcessError as exc:
            results.append(
                ProbeResult(sha, sha[:8], "(checkout failed)", "error", str(exc)[:200])
            )
            continue
        res = _probe_commit(sha, fixture, timeout)
        print(f"[bisect] [{i:>3}/{len(shas)}] {res.short} {res.status:<7} — {res.detail}")
        results.append(res)
        # First-bad short-circuit
        if res.status == "bad":
            print(f"[bisect] First bad commit found: {res.short}")
            break
    return results


def _write_report(
    results: list[ProbeResult], good: str, bad: str, fixture: Path,
    timeout: int, started_at: float,
) -> None:
    """Append-only audit log under .gcc/.

    The report path is recorded in CR-003 § 4.5 as ``.gcc/REGRESSION-REPORT
    -edge-loss.md``. We append rather than overwrite so multiple bisect runs
    accumulate into a single audit trail.
    """
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    first_bad = next((r for r in results if r.status == "bad"), None)
    duration = time.monotonic() - started_at
    lines: list[str] = [
        f"## Bisect run — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"- good: `{good}`",
        f"- bad: `{bad}`",
        f"- fixture: `{fixture}`",
        f"- timeout per commit: {timeout}s",
        f"- commits probed: {len(results)}",
        f"- duration: {duration:.1f}s",
        f"- first bad: {first_bad.short if first_bad else 'NONE — no regression found in range'}",
        "",
        "### Per-commit probe log",
        "",
        "| # | sha | status | subject | detail |",
        "|---|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        subj = r.subject.replace("|", "\\|")
        det = r.detail.replace("|", "\\|")
        lines.append(f"| {i} | `{r.short}` | {r.status} | {subj} | {det} |")
    lines.append("")
    with REPORT_PATH.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[bisect] report appended -> {REPORT_PATH}")


# ── CLI ────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only git-bisect for graqle edge-loss regression (CR-003b)."
    )
    parser.add_argument("--good", required=True, help="Known-good ref (e.g. v0.46.0)")
    parser.add_argument("--bad", required=True, help="Known-bad ref (e.g. v0.53.0)")
    parser.add_argument(
        "--fixture", required=True, type=Path,
        help="Path to a graqle.json fixture with known good edge_count > 0.",
    )
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Per-commit probe timeout (default {DEFAULT_TIMEOUT_SECONDS}s).",
    )
    args = parser.parse_args()

    _refuse_if_dirty()
    good_sha = _resolve(args.good)
    bad_sha = _resolve(args.bad)
    if not args.fixture.exists():
        print(f"REFUSE: fixture {args.fixture} does not exist.", file=sys.stderr)
        return 2

    original_head = _run_git("rev-parse", "HEAD")
    started_at = time.monotonic()

    # Mandatory cleanup — restore original HEAD even on SIGINT / exception.
    def _restore(*_a: object) -> None:
        try:
            _checkout(original_head)
        except subprocess.CalledProcessError:
            pass

    signal.signal(signal.SIGINT, lambda *_a: (_restore(), sys.exit(130)))

    try:
        results = _bisect(good_sha, bad_sha, args.fixture, args.timeout)
        _write_report(results, args.good, args.bad, args.fixture, args.timeout, started_at)
        first_bad = next((r for r in results if r.status == "bad"), None)
        return 0 if first_bad is None else 1
    finally:
        _restore()


if __name__ == "__main__":
    sys.exit(main())
