"""Tests for scripts/ci/ip_content_scan.py — filename allowlist and deny logic.

Sentinel review (graq_review focus=all, 2026-06-25) required explicit coverage
of the FILENAME_ALLOWLIST bypass path added in the WS-F CI fix (PR #216).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Load ip_content_scan without sys.path mutation to avoid xdist isolation issues.
_SCANNER_PATH = Path(__file__).parent.parent.parent / "scripts" / "ci" / "ip_content_scan.py"
_spec = importlib.util.spec_from_file_location("ip_content_scan", _SCANNER_PATH)
assert _spec and _spec.loader, f"Cannot load ip_content_scan from {_SCANNER_PATH}"
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

check_filename = _mod.check_filename
FILENAME_ALLOWLIST = _mod.FILENAME_ALLOWLIST


class TestFilenameAllowlist:
    """check_filename() allowlist short-circuit — the security-relevant bypass path."""

    def test_allowlisted_basename_returns_empty(self) -> None:
        assert check_filename("trade_secret_wheel_gate.py") == []

    def test_allowlisted_yaml_basename_returns_empty(self) -> None:
        assert check_filename("trade-secret-wheel-gate.yml") == []

    def test_allowlisted_basename_in_subdirectory_returns_empty(self) -> None:
        """Allowlist check uses Path.name (basename only) — subdirs don't matter."""
        assert check_filename("scripts/ci/trade_secret_wheel_gate.py") == []

    def test_allowlisted_basename_case_insensitive(self) -> None:
        """Allowlist check is case-insensitive to match FILENAME_DENY re.IGNORECASE semantics."""
        assert check_filename("Trade_Secret_Wheel_Gate.py") == []
        assert check_filename("TRADE_SECRET_WHEEL_GATE.PY") == []
        assert check_filename("trade-secret-wheel-gate.YML") == []

    def test_non_allowlisted_trade_secret_filename_is_blocked(self) -> None:
        """A *different* file whose name contains 'trade_secret' is NOT allowlisted."""
        hits = check_filename("trade_secret_analysis.md")
        assert any(r"trade[-_]secret" in h for h in hits), (
            f"Expected trade_secret deny pattern to fire, got: {hits}"
        )

    def test_non_allowlisted_trade_secret_filename_mixed_case_blocked(self) -> None:
        """Mixed-case trade-secret filename not in allowlist must still be blocked."""
        hits = check_filename("Trade_Secret_Analysis.MD")
        assert len(hits) > 0, (
            "Mixed-case trade_secret filename should be blocked by FILENAME_DENY (re.IGNORECASE)"
        )

    def test_ordinary_filename_passes(self) -> None:
        assert check_filename("graqle/governance/gate.py") == []

    def test_allowlist_entries_are_lowercase(self) -> None:
        """All FILENAME_ALLOWLIST entries are lowercase — invariant for the .lower() check."""
        for entry in FILENAME_ALLOWLIST:
            assert entry == entry.lower(), f"Allowlist entry not lowercase: {entry!r}"

    def test_ts_numbered_filename_is_blocked(self) -> None:
        hits = check_filename("ts-1-weight-values.md")
        assert any(r"ts[-_]\d" in h for h in hits), f"Expected ts-N deny pattern, got: {hits}"

    def test_patent_draft_filename_is_blocked(self) -> None:
        hits = check_filename("patent-draft-claims.md")
        assert any("patent" in h for h in hits), f"Expected patent deny pattern, got: {hits}"

    def test_empty_string_does_not_raise(self) -> None:
        """Degenerate: empty path string must return empty list, not raise."""
        assert check_filename("") == []

    def test_root_slash_does_not_raise(self) -> None:
        """Degenerate: bare '/' must return empty list, not raise."""
        assert check_filename("/") == []
