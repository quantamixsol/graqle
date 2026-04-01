"""Tests for TS-BLOCK trade secret pattern detection (ADR-140).

Tests the externalized pattern loading, path exclusion, declassification,
and fail-closed semantics of the governance TS gate.
"""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from graqle.core.governance import (
    GovernanceConfig,
    GovernanceMiddleware,
    _check_ts_leakage,
    _is_declassified,
    _is_path_excluded,
    _load_ts_patterns,
    invalidate_ts_patterns_cache,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_cache():
    """Ensure each test starts with a clean TS pattern cache."""
    invalidate_ts_patterns_cache()
    yield
    invalidate_ts_patterns_cache()


# ---------------------------------------------------------------------------
# Built-in default patterns
# ---------------------------------------------------------------------------

class TestBuiltinPatterns:
    """Verify built-in TS-BLOCK patterns (no external file loaded)."""

    def test_ts1_w_J_blocked(self):
        blocked, reason = _check_ts_leakage("w_J = 0.7")
        assert blocked
        assert "w_J" in reason

    def test_ts1_w_A_blocked(self):
        blocked, reason = _check_ts_leakage("w_A = 0.3")
        assert blocked

    def test_ts2_jaccard_formula_blocked(self):
        blocked, reason = _check_ts_leakage("the jaccard formula is J = |A&B|/|AuB|")
        assert blocked

    def test_ts3_production_rule_blocked(self):
        blocked, reason = _check_ts_leakage("production rule: CLASS_I -> anchor + expand")
        assert blocked

    def test_ts4_theta_fold_blocked(self):
        blocked, reason = _check_ts_leakage("theta_fold = graph_size * 0.1")
        assert blocked

    def test_agreement_threshold_value_blocked(self):
        blocked, reason = _check_ts_leakage("AGREEMENT_THRESHOLD = 0.16")
        assert blocked

    def test_seventy_thirty_blend_blocked(self):
        blocked, reason = _check_ts_leakage("uses a 70/30 blend for confidence")
        assert blocked

    def test_clean_content_passes(self):
        blocked, reason = _check_ts_leakage("def hello(): return 'world'")
        assert not blocked
        assert reason == ""

    def test_empty_content_passes(self):
        blocked, reason = _check_ts_leakage("")
        assert not blocked


# ---------------------------------------------------------------------------
# Externalized pattern loading (env var)
# ---------------------------------------------------------------------------

class TestEnvVarPatterns:
    def test_load_from_env_base64(self):
        patterns = [
            {"id": "test-1", "regex": r"SECRET_SAUCE", "label": "Test Secret"}
        ]
        encoded = base64.b64encode(json.dumps(patterns).encode()).decode()
        with patch.dict(os.environ, {"GRAQLE_TS_PATTERNS": encoded}):
            loaded = _load_ts_patterns()
        assert len(loaded) == 1
        assert loaded[0]["id"] == "test-1"

    def test_env_patterns_used_in_check(self):
        patterns = [
            {"id": "test-1", "regex": r"MY_TRADE_SECRET", "label": "Custom TS"}
        ]
        encoded = base64.b64encode(json.dumps(patterns).encode()).decode()
        with patch.dict(os.environ, {"GRAQLE_TS_PATTERNS": encoded}):
            _load_ts_patterns()
        blocked, reason = _check_ts_leakage("code contains MY_TRADE_SECRET here")
        assert blocked
        assert "Custom TS" in reason

    def test_malformed_env_falls_back(self):
        with patch.dict(os.environ, {"GRAQLE_TS_PATTERNS": "not-valid-base64!!!"}):
            loaded = _load_ts_patterns()
        assert loaded == []  # fall back to empty (built-in defaults used)


# ---------------------------------------------------------------------------
# YAML file loading
# ---------------------------------------------------------------------------

class TestYamlPatterns:
    def test_load_from_yaml(self, tmp_path):
        yml = tmp_path / "ip_patterns.yml"
        yml.write_text(
            "patterns:\n"
            "  - id: yaml-1\n"
            "    regex: YAML_SECRET\n"
            "    label: YAML Secret\n",
            encoding="utf-8",
        )
        loaded = _load_ts_patterns(path=str(yml))
        assert len(loaded) == 1
        assert loaded[0]["id"] == "yaml-1"

    def test_yaml_with_exclude_paths(self, tmp_path):
        yml = tmp_path / "ip_patterns.yml"
        yml.write_text(
            "patterns:\n"
            "  - id: y1\n"
            "    regex: BLOCKED_THING\n"
            "exclude_paths:\n"
            "  - tests/fixtures/.*\n",
            encoding="utf-8",
        )
        _load_ts_patterns(path=str(yml))
        assert _is_path_excluded("tests/fixtures/sample.py")
        assert not _is_path_excluded("graqle/core/engine.py")

    def test_yaml_with_declassified(self, tmp_path):
        yml = tmp_path / "ip_patterns.yml"
        yml.write_text(
            "patterns:\n"
            "  - id: d1\n"
            "    regex: DECLASSIFIED_ITEM\n"
            "declassified:\n"
            "  d1:\n"
            "    - docs/public/.*\n",
            encoding="utf-8",
        )
        _load_ts_patterns(path=str(yml))
        assert _is_declassified("d1", "docs/public/guide.md")
        assert not _is_declassified("d1", "graqle/secret.py")

    def test_missing_yaml_falls_back(self):
        loaded = _load_ts_patterns(path="/nonexistent/path.yml")
        assert loaded == []


# ---------------------------------------------------------------------------
# Path exclusion
# ---------------------------------------------------------------------------

class TestPathExclusion:
    def test_excluded_path_skips_check(self, tmp_path):
        yml = tmp_path / "ip_patterns.yml"
        yml.write_text(
            "patterns:\n"
            "  - id: pe1\n"
            "    regex: FORBIDDEN\n"
            "exclude_paths:\n"
            "  - tests/.*\n",
            encoding="utf-8",
        )
        _load_ts_patterns(path=str(yml))
        blocked, _ = _check_ts_leakage("FORBIDDEN content", file_path="tests/test_foo.py")
        assert not blocked

    def test_non_excluded_path_still_blocks(self, tmp_path):
        yml = tmp_path / "ip_patterns.yml"
        yml.write_text(
            "patterns:\n"
            "  - id: pe2\n"
            "    regex: FORBIDDEN\n"
            "exclude_paths:\n"
            "  - tests/.*\n",
            encoding="utf-8",
        )
        _load_ts_patterns(path=str(yml))
        blocked, _ = _check_ts_leakage("FORBIDDEN content", file_path="graqle/core/engine.py")
        assert blocked


# ---------------------------------------------------------------------------
# Fail-closed semantics
# ---------------------------------------------------------------------------

class TestFailClosed:
    def test_invalid_regex_in_pattern_skipped(self):
        """Invalid regex should be skipped, not crash the gate."""
        patterns = [
            {"id": "bad", "regex": r"[invalid(regex", "label": "Bad"},
            {"id": "good", "regex": r"REAL_SECRET", "label": "Good"},
        ]
        encoded = base64.b64encode(json.dumps(patterns).encode()).decode()
        with patch.dict(os.environ, {"GRAQLE_TS_PATTERNS": encoded}):
            _load_ts_patterns()
        # Good pattern should still work
        blocked, reason = _check_ts_leakage("contains REAL_SECRET")
        assert blocked

    def test_empty_pattern_list_uses_defaults(self):
        """Empty external patterns should fall back to built-in defaults."""
        encoded = base64.b64encode(json.dumps([]).encode()).decode()
        with patch.dict(os.environ, {"GRAQLE_TS_PATTERNS": encoded}):
            loaded = _load_ts_patterns()
        assert loaded == []
        # Built-in defaults should still work
        blocked, _ = _check_ts_leakage("w_J = 0.7")
        assert blocked


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------

class TestCacheInvalidation:
    def test_invalidate_clears_cache(self):
        patterns = [{"id": "c1", "regex": "CACHED", "label": "Cached"}]
        encoded = base64.b64encode(json.dumps(patterns).encode()).decode()
        with patch.dict(os.environ, {"GRAQLE_TS_PATTERNS": encoded}):
            _load_ts_patterns()
        blocked, _ = _check_ts_leakage("CACHED value")
        assert blocked

        invalidate_ts_patterns_cache()
        # After invalidation, falls back to built-in defaults
        blocked, _ = _check_ts_leakage("CACHED value")
        assert not blocked  # "CACHED" is not a built-in pattern


# ---------------------------------------------------------------------------
# GovernanceConfig.ts_patterns_file wiring
# ---------------------------------------------------------------------------

class TestGovernanceConfigWiring:
    def test_ts_patterns_file_field_exists(self):
        cfg = GovernanceConfig()
        assert cfg.ts_patterns_file is None

    def test_ts_patterns_file_set(self):
        cfg = GovernanceConfig(ts_patterns_file="/path/to/patterns.yml")
        assert cfg.ts_patterns_file == "/path/to/patterns.yml"
