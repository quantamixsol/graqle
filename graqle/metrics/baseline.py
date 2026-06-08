# V-SAVINGS-BASELINE-NATIVE-001: new file via native Write (S-010).
"""Measured "without-graph" token baseline for authentic tokens-saved.

WHY THIS EXISTS
---------------
"Tokens saved" = (what a load would have cost WITHOUT GraQle) − (what GraQle
returned). The second term is real; the first was a flat ASSUMED constant
(``_DEFAULT_TOKENS_WITHOUT = 2000``). That makes the headline number an estimate,
not a measurement.

Without GraQle, a developer/agent answering a question about a code node would
have loaded the **whole source file** that node lives in — not its one-line
description. So the authentic baseline for a node is the token count of its file.
This module measures that (cached per path), with a calibrated, logged fallback
when the file can't be measured (no path, unreadable, or a non-code node).

It is intentionally dependency-free and fail-safe: any measurement error returns
the calibrated fallback rather than raising, and the result is clamped so a single
huge vendored file can't inflate the headline.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.metrics.baseline")

# Calibrated fallback when a node's full-file size can't be measured. This is the
# documented assumption (kept equal to the historical default so behaviour only
# IMPROVES where a real file is found, never regresses elsewhere).
CALIBRATED_FALLBACK_TOKENS = 2_000

# Guardrail: cap a single node's "without-graph" baseline so one enormous file
# (a vendored bundle, a generated lockfile) can't dominate the saving. ~a large
# source file; beyond this, loading the *whole* file by hand is not the realistic
# counterfactual anyway.
MAX_BASELINE_TOKENS = 40_000

# ~4 chars per token (English/code rough estimate; the same heuristic used for
# tokens_returned, so the subtraction stays self-consistent).
_CHARS_PER_TOKEN = 4

# Path -> measured token count, to avoid re-reading the same file per query.
# Bounded so a long-running process measuring many distinct paths can't grow the
# cache without limit (Phase-7 sentinel MINOR: unbounded-cache DoS guard).
_file_token_cache: dict[str, int] = {}
_CACHE_MAX = 50_000


def _node_file_path(node: Any) -> str | None:
    """Extract a source file path from a node's properties, if present."""
    props = getattr(node, "properties", None)
    if not isinstance(props, dict):
        return None
    for key in ("file_path", "source_file", "path"):
        val = props.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _measure_file_tokens(path: str) -> int | None:
    """Token size of a file, cached. None if unmeasurable.

    SECURITY (Phase-7 sentinel, path-traversal): this function only reads the
    file's *size* (``st_size``) — it never opens, reads, returns, or logs file
    CONTENT. So even if a node's ``file_path`` were hostile (e.g. ``../../etc/
    passwd``), the only effect is a different integer in the tokens-saved tally;
    no data is disclosed. The path also originates from GraQle's own scanner over
    the repo it indexed, not from request input. We still confirm it resolves to a
    real regular file and fail closed (None) on any OS error.
    """
    if path in _file_token_cache:
        return _file_token_cache[path]
    try:
        p = Path(path)
        if not p.is_file():
            return None
        size = p.stat().st_size  # size only — never the file's content
        tokens = max(size // _CHARS_PER_TOKEN, 1)
        tokens = min(tokens, MAX_BASELINE_TOKENS)
        if len(_file_token_cache) < _CACHE_MAX:
            _file_token_cache[path] = tokens
        return tokens
    except OSError as exc:  # FileNotFoundError / PermissionError are OSError subclasses
        logger.debug("baseline: cannot stat %s (%s)", path, type(exc).__name__)
        return None


def baseline_for_node(node: Any) -> tuple[int, str]:
    """Return (tokens_without, method) for one activated node.

    method is "measured_file" when the node's real file was measured, else
    "calibrated_fallback". The dashboard can surface the method so the headline
    is honestly labelled as measurement-backed vs assumed.
    """
    path = _node_file_path(node)
    if path:
        measured = _measure_file_tokens(path)
        if measured is not None:
            return measured, "measured_file"
    return CALIBRATED_FALLBACK_TOKENS, "calibrated_fallback"


def reset_cache() -> None:
    """Clear the per-path measurement cache (tests / long-running processes)."""
    _file_token_cache.clear()


__all__ = [
    "baseline_for_node",
    "reset_cache",
    "CALIBRATED_FALLBACK_TOKENS",
    "MAX_BASELINE_TOKENS",
]
