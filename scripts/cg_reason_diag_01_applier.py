"""CG-REASON-DIAG-01 deterministic applier.

Writes exact-string replacements to three files. Fails closed on any mismatch.
Run from graqle-sdk/ root. Idempotent (detects already-applied state and skips).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if not (ROOT / "graqle" / "orchestration" / "aggregation.py").exists():
    print(f"ERROR: not running from graqle-sdk/. ROOT={ROOT}", file=sys.stderr)
    sys.exit(1)


def _replace_exact(path: Path, old: str, new: str, *, context: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text and old not in text:
        print(f"SKIP  {context}: already applied")
        return
    count = text.count(old)
    if count == 0:
        print(f"FAIL  {context}: old_content not found in {path}", file=sys.stderr)
        sys.exit(2)
    if count > 1:
        print(f"FAIL  {context}: old_content matches {count} times (need 1) in {path}", file=sys.stderr)
        sys.exit(3)
    new_text = text.replace(old, new, 1)
    path.write_text(new_text, encoding="utf-8", newline="\n")
    # Disk-verify
    read_back = path.read_text(encoding="utf-8")
    if new not in read_back:
        print(f"FAIL  {context}: post-write disk-verify did not find new_content", file=sys.stderr)
        sys.exit(4)
    print(f"OK    {context}: applied + disk-verified ({path.name})")


# ─────────────────────────────────────────────────────────────────────────
# Layer 1+2: aggregation.py — SDK probe helper + zero-success predicate +
# fallback-branch diagnostic attachment
# ─────────────────────────────────────────────────────────────────────────

AGG = ROOT / "graqle" / "orchestration" / "aggregation.py"

# 1a. Imports + module-level helpers (insert AFTER `logger = logging.getLogger(...)`)
AGG_OLD_HEADER = '''logger = logging.getLogger("graqle.aggregation")


# Legacy prompt (backward compatible)'''

AGG_NEW_HEADER = '''logger = logging.getLogger("graqle.aggregation")


# ─────────────────────────────────────────────────────────────────────────
# CG-REASON-DIAG-01 — missing-LLM-SDK diagnostic
#
# When graq_reason produces zero-successful-message output AND none of
# openai / anthropic / boto3 is importable, surface a diagnostic in the
# MCP response envelope. Detection lives here (aggregator has the zero-
# success signal); emission is wired through orchestrator metadata and
# the MCP handler. Never fires on happy path, rate-limit errors, or when
# [api] extras are installed.
# ─────────────────────────────────────────────────────────────────────────
import importlib.util as _importlib_util
from threading import Lock as _Lock

_LLM_SDK_NAMES = ("anthropic", "boto3", "openai")  # sorted canonical
_missing_sdks_cache: list[str] | None = None
_missing_sdks_lock = _Lock()


def _detect_missing_llm_sdks() -> list[str]:
    """Return sorted list of LLM SDK module names that cannot be imported.

    Memoized for process lifetime (SDK availability is STATIC per process
    contract for production MCP server deployments). Thread-safe
    double-checked init. ImportError/ValueError from find_spec are
    caught and treated as "present" (fail-closed: no spurious
    diagnostic); any other exception propagates as a real bug.

    ENVIRONMENT CONTRACT: The probe assumes SDK import availability is
    static for the process lifetime. Out of scope: mid-process pip
    install/uninstall, custom importlib meta_path hooks that lazy-load,
    namespace packages that materialize post-probe, pytest monkeypatch
    of sys.modules without calling _reset_missing_sdks_cache().

    Test-only invalidation: _reset_missing_sdks_cache().
    """
    global _missing_sdks_cache
    cached = _missing_sdks_cache
    if cached is not None:
        return list(cached)
    with _missing_sdks_lock:
        if _missing_sdks_cache is not None:
            return list(_missing_sdks_cache)
        missing: list[str] = []
        for name in _LLM_SDK_NAMES:
            try:
                spec = _importlib_util.find_spec(name)
            except (ImportError, ValueError) as exc:
                logger.debug(
                    "CG-REASON-DIAG-01: find_spec(%s) failed (%s); "
                    "treating as present (fail-closed)",
                    name, exc,
                )
                continue  # fail-closed: do not flag as missing
            if spec is None:
                missing.append(name)
        _missing_sdks_cache = missing
        return list(missing)


def _reset_missing_sdks_cache() -> None:
    """Test-only helper: clear the memoized SDK-availability cache."""
    global _missing_sdks_cache
    with _missing_sdks_lock:
        _missing_sdks_cache = None


def _is_zero_success_fallback(
    messages: dict[str, "Message"],
) -> bool:
    """True iff the aggregator has no usable agent output.

    Uses aggregator outcome state (the raw messages dict), not content
    heuristics. Returns True when:
      1. messages is empty (no agents ran — e.g. empty graph)
      2. every message is an observer report (source_node_id ==
         "__observer__")

    Returns False when at least one non-observer message exists, even
    if that message has low or zero confidence. Low-confidence-but-
    produced is a DIFFERENT failure mode (handled by the existing
    best-of-messages fallback) and MUST NOT trigger the diagnostic.

    MESSAGE PROVENANCE CONTRACT:
      - source_node_id: non-empty string in production; "__observer__"
        is the reserved observer sentinel. Unknown/missing/non-string
        values are treated as AGENT-produced (pessimistic — prefer
        false-negative silence over false-positive diagnostic).
      - confidence: float 0.0-1.0.
      - content: string, may be empty on error returns.
    """
    if not messages:
        return True
    non_observer_exists = False
    for m in messages.values():
        src = getattr(m, "source_node_id", None)
        if src == "__observer__":
            continue
        non_observer_exists = True
        break
    return not non_observer_exists


# Legacy prompt (backward compatible)'''

_replace_exact(AGG, AGG_OLD_HEADER, AGG_NEW_HEADER, context="aggregation.py :: module helpers")


# 1b. Fallback branch — attach missing_llm_sdks to trunc_info
AGG_OLD_FALLBACK = '''        if not filtered:
            # Fall back to best single message if all filtered
            if messages:
                best = max(messages.values(), key=lambda m: m.confidence)
                return best.content, _no_trunc
            return "No reasoning produced.", _no_trunc'''

AGG_NEW_FALLBACK = '''        if not filtered:
            # CG-REASON-DIAG-01 — attach diagnostic only on true zero-success.
            # trunc_info is the existing metadata carrier (see `candidates`
            # wiring above). Orchestrator promotes it to ReasoningResult
            # metadata; MCP handler surfaces it in the response envelope.
            diag_trunc = dict(_no_trunc)
            if _is_zero_success_fallback(messages):
                _missing = _detect_missing_llm_sdks()
                if _missing:
                    diag_trunc["missing_llm_sdks"] = _missing
            # Fall back to best single message if all filtered
            if messages:
                best = max(messages.values(), key=lambda m: m.confidence)
                return best.content, diag_trunc
            return "No reasoning produced.", diag_trunc'''

_replace_exact(AGG, AGG_OLD_FALLBACK, AGG_NEW_FALLBACK, context="aggregation.py :: fallback branch")


# ─────────────────────────────────────────────────────────────────────────
# Layer 3: orchestrator.py — metadata pass-through
# ─────────────────────────────────────────────────────────────────────────

ORCH = ROOT / "graqle" / "orchestration" / "orchestrator.py"

ORCH_OLD = '''        _ambiguous = synthesis_trunc_info.get("candidates")
        if _ambiguous:
            metadata["ambiguous_options"] = _ambiguous

        result = ReasoningResult('''

ORCH_NEW = '''        _ambiguous = synthesis_trunc_info.get("candidates")
        if _ambiguous:
            metadata["ambiguous_options"] = _ambiguous

        # CG-REASON-DIAG-01 — missing-LLM-SDK diagnostic pass-through.
        # Aggregator attaches a sorted list at the zero-success fallback
        # branch. We promote it to metadata; MCP handler renders the
        # user-facing diagnostic. Type-guarded to reject malformed values.
        _missing_sdks = synthesis_trunc_info.get("missing_llm_sdks")
        if isinstance(_missing_sdks, list) and _missing_sdks:
            metadata["missing_llm_sdks"] = list(_missing_sdks)

        result = ReasoningResult('''

_replace_exact(ORCH, ORCH_OLD, ORCH_NEW, context="orchestrator.py :: metadata pass-through")


# ─────────────────────────────────────────────────────────────────────────
# Layer 4+5: mcp_dev_server.py — envelope + capability flag
# ─────────────────────────────────────────────────────────────────────────

MCP = ROOT / "graqle" / "plugins" / "mcp_dev_server.py"

# 4a. Envelope: emit diagnostic on success path (right AFTER ambiguous_options)
MCP_OLD_ENVELOPE = '''            _ambiguous = (result.metadata or {}).get("ambiguous_options")
            if _ambiguous:
                result_dict["ambiguous_options"] = _ambiguous
            duration_ms = (_time.monotonic() - t0) * 1000'''

MCP_NEW_ENVELOPE = '''            _ambiguous = (result.metadata or {}).get("ambiguous_options")
            if _ambiguous:
                result_dict["ambiguous_options"] = _ambiguous
            # CG-REASON-DIAG-01 — missing-LLM-SDK diagnostic (success envelope
            # only). Error envelopes are built in a disjoint try/except
            # branch below and never touch these keys. Fields are optional
            # and additive per the VS Code extension schema contract.
            _missing_sdks_md = (result.metadata or {}).get("missing_llm_sdks")
            if _missing_sdks_md:
                _missing_list = list(_missing_sdks_md)
                result_dict["diagnostic"] = (
                    "Missing LLM SDK(s): "
                    + ", ".join(_missing_list)
                    + ". Install with: pip install graqle[api]"
                )
                result_dict["diagnostic_code"] = "MISSING_LLM_SDK"
                result_dict["missing_sdks"] = _missing_list
            duration_ms = (_time.monotonic() - t0) * 1000'''

_replace_exact(MCP, MCP_OLD_ENVELOPE, MCP_NEW_ENVELOPE, context="mcp_dev_server.py :: _handle_reason envelope")


# 4b. Capability flags — two occurrences (top-level capabilities + nested)
MCP_OLD_CAP1 = '''                "graq_reason": {
                            "ambiguous_options": True,
                        },'''

MCP_NEW_CAP1 = '''                "graq_reason": {
                            "ambiguous_options": True,
                            "missing_sdks_diagnostic": True,
                        },'''

# This exact form does not exist; there are two variants. Try the indentations present.

# Variant at ~10960 (read showed 24-space indent for graq_reason key):
MCP_OLD_CAP_A = '''                        "graq_reason": {
                            "ambiguous_options": True,
                        },'''

MCP_NEW_CAP_A = '''                        "graq_reason": {
                            "ambiguous_options": True,
                            "missing_sdks_diagnostic": True,
                        },'''

# Count matches first
_mcp_text = MCP.read_text(encoding="utf-8")
_cap_matches = _mcp_text.count(MCP_OLD_CAP_A)
print(f"INFO  capability block matches: {_cap_matches}")

if _cap_matches == 2:
    # Replace both occurrences — one top-level, one nested
    new_text = _mcp_text.replace(MCP_OLD_CAP_A, MCP_NEW_CAP_A)
    MCP.write_text(new_text, encoding="utf-8", newline="\n")
    rb = MCP.read_text(encoding="utf-8")
    if rb.count("missing_sdks_diagnostic") != 2:
        print("FAIL  capability block: disk-verify did not find 2 occurrences", file=sys.stderr)
        sys.exit(5)
    print("OK    mcp_dev_server.py :: capability flags (2 occurrences): applied + disk-verified")
elif _cap_matches == 1:
    _replace_exact(MCP, MCP_OLD_CAP_A, MCP_NEW_CAP_A, context="mcp_dev_server.py :: capability flag (single)")
elif _cap_matches == 0:
    # Already applied? Check if already has flag
    if _mcp_text.count("missing_sdks_diagnostic") >= 1:
        print("SKIP  capability block: already applied")
    else:
        print(f"FAIL  capability block: pattern not found (0 matches)", file=sys.stderr)
        sys.exit(6)
else:
    print(f"FAIL  capability block: too many matches ({_cap_matches})", file=sys.stderr)
    sys.exit(7)


print("\n=== CG-REASON-DIAG-01 applier: ALL STEPS COMPLETE ===")
