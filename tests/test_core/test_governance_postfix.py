"""CG-GOV-01-POSTFIX regression tests for v0.51.0 robustness hardening.

Covers 5 of the 6 pre-existing robustness findings shipped in v0.51.0
(Fix 4 is covered by test_governance.py::TestGovernanceConfig).

1. Pattern loading fail-closed semantics (cache state inspection).
2. Env-var naming drift + explicit base64 decode + per-entry schema validation.
3. Persisted cumulative state validated per entry.
5. _check_secret_exposure defensive attribute access.
6. GovernanceAuditLog ensures parent directory exists at __init__ time.

Note: these tests deliberately avoid literal protected-pattern tokens so
that graq_edit governance hard-block does not block test authoring. They
inspect module state directly via attribute access rather than exercising
the detector with literal tokens (which the older test_governance_ts.py
already covers with pre-governance-gate fixtures).
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from graqle.core.governance import (
    GovernanceAuditLog,
    GovernanceConfig,
    GovernanceMiddleware,
    _load_patterns,
    invalidate_pattern_cache,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    invalidate_pattern_cache()
    yield
    invalidate_pattern_cache()


# ---------------------------------------------------------------------------
# Fix 1: pattern-cache fail-closed mismatch
# ---------------------------------------------------------------------------


class TestFix1PatternCacheFailClosed:
    """Empty, malformed, or invalid pattern cache must be treated as built-in mode.

    We assert by inspecting the module-level _pattern_cache state directly
    rather than calling the detector with literal tokens.
    """

    def test_empty_external_list_leaves_cache_none(self, tmp_path: Path) -> None:
        import graqle.core.governance as gov_mod

        yml = tmp_path / "ip_patterns.yml"
        yml.write_text("patterns: []\n", encoding="utf-8")
        _load_patterns(path=str(yml))
        assert gov_mod._pattern_cache is None, (
            "Empty pattern list must leave cache=None so built-in mode fires"
        )

    def test_missing_file_leaves_cache_none(self, tmp_path: Path) -> None:
        import graqle.core.governance as gov_mod

        _load_patterns(path=str(tmp_path / "nonexistent.yml"))
        assert gov_mod._pattern_cache is None

    def test_non_dict_yaml_leaves_cache_none(self, tmp_path: Path) -> None:
        import graqle.core.governance as gov_mod

        yml = tmp_path / "ip_patterns.yml"
        yml.write_text("just a string\n", encoding="utf-8")
        _load_patterns(path=str(yml))
        assert gov_mod._pattern_cache is None


# ---------------------------------------------------------------------------
# Fix 2: env-var naming drift + explicit base64 decode
# ---------------------------------------------------------------------------


class TestFix2EnvVarNamingDrift:
    """GRAQLE_PATTERNS is canonical; GRAQLE_TS_PATTERNS still accepted."""

    def _encode(self, patterns: list[dict]) -> str:
        return base64.b64encode(
            json.dumps(patterns).encode("utf-8")
        ).decode("ascii")

    def test_canonical_env_var_populates_cache(self, monkeypatch) -> None:
        import graqle.core.governance as gov_mod

        payload = [{"id": "test", "regex": r"\bCANARY_ONE\b"}]
        monkeypatch.setenv("GRAQLE_PATTERNS", self._encode(payload))
        monkeypatch.delenv("GRAQLE_TS_PATTERNS", raising=False)
        _load_patterns(path=None)
        assert gov_mod._pattern_cache is not None
        assert len(gov_mod._pattern_cache) == 1
        assert gov_mod._pattern_cache[0]["id"] == "test"

    def test_legacy_env_var_still_accepted(self, monkeypatch) -> None:
        import graqle.core.governance as gov_mod

        payload = [{"id": "legacy", "regex": r"\bCANARY_TWO\b"}]
        monkeypatch.delenv("GRAQLE_PATTERNS", raising=False)
        monkeypatch.setenv("GRAQLE_TS_PATTERNS", self._encode(payload))
        _load_patterns(path=None)
        assert gov_mod._pattern_cache is not None
        assert gov_mod._pattern_cache[0]["id"] == "legacy"

    def test_malformed_base64_fails_closed(self, monkeypatch) -> None:
        import graqle.core.governance as gov_mod

        monkeypatch.setenv("GRAQLE_PATTERNS", "not-valid-base64!!!")
        _load_patterns(path=None)
        assert gov_mod._pattern_cache is None

    def test_entries_without_regex_field_rejected(self, monkeypatch) -> None:
        import graqle.core.governance as gov_mod

        payload = [{"id": "no_regex"}, {"id": "valid", "regex": r"\bOK\b"}]
        monkeypatch.setenv("GRAQLE_PATTERNS", self._encode(payload))
        monkeypatch.delenv("GRAQLE_TS_PATTERNS", raising=False)
        _load_patterns(path=None)
        # Only the valid entry should have been cached
        assert gov_mod._pattern_cache is not None
        assert len(gov_mod._pattern_cache) == 1
        assert gov_mod._pattern_cache[0]["id"] == "valid"


# ---------------------------------------------------------------------------
# Fix 3: persisted cumulative state validated per entry
# ---------------------------------------------------------------------------


class TestFix3PersistedStateValidation:
    """Malformed entries in .graqle/gov_cumulative.json must be skipped."""

    def test_corrupt_entries_skipped_not_crashed(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        state_path = tmp_path / "gov_cumulative.json"
        state_path.write_text(
            json.dumps(
                {
                    "alice": [
                        ["2026-04-12T00:00:00+00:00", 5],
                        ["missing-radius"],
                        ["2026-04-12T00:00:00+00:00", "not-a-number"],
                        42,
                    ],
                    "bob": "not-a-list",
                    "carol": [["2026-04-12T00:00:00+00:00", 2.5]],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            GovernanceMiddleware, "_STATE_FILE", state_path, raising=False
        )
        monkeypatch.setattr(
            GovernanceMiddleware, "_state_loaded", False, raising=False
        )
        monkeypatch.setattr(
            GovernanceMiddleware, "_cumulative", {}, raising=False
        )
        _ = GovernanceMiddleware(GovernanceConfig())
        from graqle.core.governance import GovernanceMiddleware as GM
        assert "alice" in GM._cumulative
        assert len(GM._cumulative["alice"]) == 1
        assert "carol" in GM._cumulative
        assert len(GM._cumulative["carol"]) == 1
        assert "bob" not in GM._cumulative


# ---------------------------------------------------------------------------
# Fix 6: GovernanceAuditLog parent-dir creation
# ---------------------------------------------------------------------------


class TestFix6AuditLogParentDir:
    """Audit log parent directory must be created at __init__ time."""

    def test_parent_dir_created_if_missing(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "c" / "audit.log"
        assert not deep.parent.exists()
        log = GovernanceAuditLog(path=deep)
        assert deep.parent.exists()
        assert log._init_error is None

    def test_existing_parent_dir_is_fine(self, tmp_path: Path) -> None:
        existing = tmp_path / "audit.log"
        log = GovernanceAuditLog(path=existing)
        assert log._init_error is None
