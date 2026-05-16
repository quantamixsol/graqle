"""CG-MKT-06 — EUR-Lex drift guard (MC-HLD-03).

Periodically fetches each ``eur-lex.europa.eu`` URL referenced in
GraQle's compliance docs, computes a content hash, and reports drift
versus a committed baseline. Used by a weekly CI job to flag the
moment an authoritative EU AI Act text changes — so the compliance
team can review what changed and whether GraQle's documentation
needs to track the update.

Why this matters for EU AI Act–aligned positioning: the deployer-facing
compliance docs in ``docs/compliance/eu-ai-act/`` reference specific
EUR-Lex URLs. If the regulator quietly amends one of those pages
(corrigendum, consolidated-text refresh, language-version change), our
docs may silently become stale — and a customer audit team that quotes
GraQle's mapping could end up citing a superseded text. The guard
catches the drift the day after it happens, not months later.

Operator workflow:

    1. **Initial baseline** (one-time per deployment):
       ``graq compliance eur-lex-refresh``
       — fetches every EUR-Lex URL referenced under ``docs/compliance/``,
         computes hashes, writes ``.graqle/eur-lex-baseline.json``.

    2. **Weekly CI check**:
       ``graq compliance eur-lex-check``
       — re-fetches the same URLs, compares hashes to baseline,
         exits 1 if any URL drifted, exits 0 if all match.

    3. **Reviewed acceptance**:
       After a human reviews what changed and updates docs if needed,
       rerun ``graq compliance eur-lex-refresh`` to bake the new
       baseline.

The hash is over the entire fetched HTML body. False positives from
trivial server-side changes (analytics scripts, dynamic banners) are
acceptable — every drift report deserves a human review pass.

This module has **no internal trade-secret references**.

Network access: this module is the ONLY GraQle compliance module that
performs outbound HTTP. The fetch is guarded by:

    - 30-second per-URL timeout
    - User-Agent header identifying the GraQle EUR-Lex guard
    - Read-only HTTP GET (never POST, PUT, DELETE)
    - Stdlib :mod:`urllib.request` (no third-party dep)

Operator can disable fetches in air-gapped environments by passing
``--offline`` to the CLI; the check will then warn rather than
attempt a network call.

References:
    - CG-MKT-06 in OPEN-TRACKER-CAPABILITY-GAPS.md
    - ADR-MARKETING-001 §11 (EU AI Act positioning constitution)
    - Companion CG-MKT-05 README snapshot-lock test
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib import error as urllib_error
from urllib import request as urllib_request

logger = logging.getLogger("graqle.compliance.eur_lex_guard")

#: User-Agent header used on all fetches.
USER_AGENT: str = "GraQle/EUR-Lex-Guard (compliance audit; +https://graqle.com)"

#: Per-URL fetch timeout in seconds.
FETCH_TIMEOUT_SECONDS: float = 30.0

#: Sentinel pass 2 INFO finding — cap response size to defend against
#: DoS via huge upstream response. 10 MiB is generous for a single
#: EUR-Lex page (real pages are typically 100-500 KB).
MAX_RESPONSE_BYTES: int = 10 * 1024 * 1024  # 10 MiB

#: Default path for the baseline file (operator-controlled).
DEFAULT_BASELINE_PATH: str = ".graqle/eur-lex-baseline.json"

# Regex for an eur-lex.europa.eu URL inside markdown. Matches both
# bare URLs and markdown link syntax ``[text](url)``. We capture the
# URL itself (group 1). Pinning to https only — http would be a
# downgrade attack surface.
_EUR_LEX_URL_RE: re.Pattern[str] = re.compile(
    r"https://eur-lex\.europa\.eu/[A-Za-z0-9_\-/?=&%:.,!#~]*[A-Za-z0-9_\-/?=&%]",
)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EurLexHash:
    """A single URL → hash pair for the baseline."""

    url: str
    sha256: str
    fetched_at_iso: str
    byte_size: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DriftReport:
    """Result of a baseline-vs-current comparison."""

    n_urls_checked: int
    n_unchanged: int
    n_drifted: int
    n_missing_from_baseline: int
    n_missing_from_current: int
    n_fetch_errors: int
    drifted: tuple[str, ...] = field(default_factory=tuple)
    missing_from_baseline: tuple[str, ...] = field(default_factory=tuple)
    missing_from_current: tuple[str, ...] = field(default_factory=tuple)
    fetch_errors: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def has_drift(self) -> bool:
        return (
            self.n_drifted > 0
            or self.n_missing_from_baseline > 0
            or self.n_missing_from_current > 0
            or self.n_fetch_errors > 0
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Convert tuple-of-tuples for fetch_errors -> list-of-lists
        d["fetch_errors"] = [list(t) for t in self.fetch_errors]
        return d


# ---------------------------------------------------------------------------
# URL enumeration
# ---------------------------------------------------------------------------


def enumerate_eur_lex_urls(
    search_roots: Iterable[Path],
    glob_pattern: str = "**/*.md",
) -> list[str]:
    """Walk ``search_roots`` and return a sorted, deduplicated URL list.

    Args:
        search_roots: Directories to recursively scan for markdown files.
        glob_pattern: Glob pattern for files to scan (defaults to all
            markdown files recursively).

    Returns:
        list[str]: Sorted unique list of eur-lex.europa.eu URLs.
    """
    found: set[str] = set()
    for root in search_roots:
        root = Path(root)
        if not root.exists():
            continue
        for md in root.glob(glob_pattern):
            if not md.is_file():
                continue
            try:
                text = md.read_text(encoding="utf-8")
            except OSError as exc:
                logger.debug("eur_lex_guard: cannot read %s: %s", md, exc)
                continue
            for m in _EUR_LEX_URL_RE.finditer(text):
                # Strip a trailing punctuation that the regex may have
                # captured (markdown ``)`` after URL, ``.`` at sentence
                # end). The trailing-punct set is small + curated.
                url = m.group(0).rstrip(").,;:!?")
                found.add(url)
    return sorted(found)


# ---------------------------------------------------------------------------
# Network fetch (online mode only)
# ---------------------------------------------------------------------------


def _fetch_url(url: str) -> bytes:
    """Fetch a URL and return its body bytes.

    Defense-in-depth (sentinel pass 2 MAJOR): URL is re-validated against
    the same regex caller enumeration uses, so this function refuses to
    accept any URL that didn't match the canonical pattern. Upstream
    callers (``enumerate_eur_lex_urls``) already filter, but defensive
    re-checking here means a future caller that bypasses enumeration
    still cannot make this helper reach an arbitrary host.

    Response is capped at :data:`MAX_RESPONSE_BYTES` (10 MiB) to prevent
    DoS via huge upstream response (sentinel pass 2 INFO).

    Raises:
        ValueError: If the URL fails the canonical regex validation.
        urllib_error.URLError: On any network failure.
        urllib_error.HTTPError: On HTTP error status.
    """
    if not _EUR_LEX_URL_RE.fullmatch(url):
        raise ValueError(
            f"_fetch_url refused: {url!r} does not match the "
            f"https://eur-lex.europa.eu/... canonical pattern. "
            f"Defense-in-depth gate per CG-MKT-06."
        )
    req = urllib_request.Request(
        url,
        headers={"User-Agent": USER_AGENT},
        method="GET",
    )
    # nosec — outbound GET to a well-known regulator domain; per-URL
    # timeout + size cap enforced; URL validated against canonical regex.
    with urllib_request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:  # noqa: S310
        return resp.read(MAX_RESPONSE_BYTES + 1)[:MAX_RESPONSE_BYTES]


def compute_url_hash(content: bytes) -> str:
    """Return ``SHA-256(content).hexdigest()``."""
    return hashlib.sha256(content).hexdigest()


# ---------------------------------------------------------------------------
# Baseline I/O
# ---------------------------------------------------------------------------


def load_baseline(path: Path) -> dict[str, EurLexHash]:
    """Load the baseline JSON file.

    Returns an empty dict when the file does not exist (the
    legitimate "no baseline yet" path — the first
    ``eur-lex-refresh`` call creates it).
    """
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"eur-lex baseline file {path} is not valid JSON: {exc}"
        ) from exc
    entries = data.get("entries", [])
    out: dict[str, EurLexHash] = {}
    for e in entries:
        url = e.get("url")
        sha = e.get("sha256")
        fetched = e.get("fetched_at_iso", "")
        size = int(e.get("byte_size", 0))
        if isinstance(url, str) and isinstance(sha, str):
            out[url] = EurLexHash(
                url=url, sha256=sha, fetched_at_iso=fetched, byte_size=size
            )
    return out


def save_baseline(
    entries: Iterable[EurLexHash], path: Path
) -> Path:
    """Write the baseline JSON file (overwrites)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "generated_at_iso": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "entries": [e.to_dict() for e in entries],
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def refresh_baseline(
    *,
    search_roots: Iterable[Path],
    baseline_path: Path,
    offline: bool = False,
) -> tuple[list[EurLexHash], list[tuple[str, str]]]:
    """Re-fetch every URL found under ``search_roots`` and rewrite baseline.

    Args:
        search_roots: Directories to scan for EUR-Lex URLs.
        baseline_path: Destination baseline JSON path.
        offline: When True, skip network fetches and write an empty
            baseline. Used by air-gapped operators who want to disable
            the guard without removing the configuration.

    Returns:
        (list[EurLexHash], list[(url, err)]): Successful entries +
        per-URL fetch errors.
    """
    urls = enumerate_eur_lex_urls(search_roots)
    entries: list[EurLexHash] = []
    errors: list[tuple[str, str]] = []
    if offline:
        save_baseline([], baseline_path)
        return [], []
    iso_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for url in urls:
        try:
            body = _fetch_url(url)
        except (urllib_error.URLError, urllib_error.HTTPError, OSError) as exc:
            errors.append((url, f"{type(exc).__name__}: {exc}"))
            continue
        entries.append(
            EurLexHash(
                url=url,
                sha256=compute_url_hash(body),
                fetched_at_iso=iso_now,
                byte_size=len(body),
            )
        )
    save_baseline(entries, baseline_path)
    return entries, errors


def check_drift(
    *,
    search_roots: Iterable[Path],
    baseline_path: Path,
    offline: bool = False,
) -> DriftReport:
    """Re-fetch every URL and compare against the baseline.

    Args:
        search_roots: Directories to scan for EUR-Lex URLs.
        baseline_path: Source baseline JSON path. When missing, every
            URL is reported as ``missing_from_baseline``.
        offline: When True, return a "no checks performed" report
            (used by air-gapped operators).

    Returns:
        DriftReport: Summary of drift state.
    """
    baseline = load_baseline(baseline_path)
    urls_in_docs = set(enumerate_eur_lex_urls(search_roots))
    baseline_urls = set(baseline.keys())

    missing_from_baseline = tuple(sorted(urls_in_docs - baseline_urls))
    missing_from_current = tuple(sorted(baseline_urls - urls_in_docs))

    drifted: list[str] = []
    errors: list[tuple[str, str]] = []
    n_unchanged = 0

    if offline:
        return DriftReport(
            n_urls_checked=0,
            n_unchanged=0,
            n_drifted=0,
            n_missing_from_baseline=len(missing_from_baseline),
            n_missing_from_current=len(missing_from_current),
            n_fetch_errors=0,
            missing_from_baseline=missing_from_baseline,
            missing_from_current=missing_from_current,
        )

    # Fetch only URLs present in BOTH (drift check applies there).
    overlap = sorted(urls_in_docs & baseline_urls)
    for url in overlap:
        try:
            body = _fetch_url(url)
        except (urllib_error.URLError, urllib_error.HTTPError, OSError) as exc:
            errors.append((url, f"{type(exc).__name__}: {exc}"))
            continue
        current_hash = compute_url_hash(body)
        if current_hash != baseline[url].sha256:
            drifted.append(url)
        else:
            n_unchanged += 1

    return DriftReport(
        n_urls_checked=len(overlap),
        n_unchanged=n_unchanged,
        n_drifted=len(drifted),
        n_missing_from_baseline=len(missing_from_baseline),
        n_missing_from_current=len(missing_from_current),
        n_fetch_errors=len(errors),
        drifted=tuple(drifted),
        missing_from_baseline=missing_from_baseline,
        missing_from_current=missing_from_current,
        fetch_errors=tuple(errors),
    )
