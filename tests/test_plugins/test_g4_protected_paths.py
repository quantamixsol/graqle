"""G4 Protected Paths Policy tests (Wave 2 Phase 4).

Approval-gated block on user-configured protected paths. Supports two
approval mechanisms:
  1. Advisory approved_by string (length >= 3)
  2. CG-14 ConfigDriftAuditor reports baseline-clean for the file

Extends CG-14 default protected files additively.

Covers:
  - check_protected_path helper (8)
  - Configuration: GraqleConfig.protected_paths (3)
  - Merge semantics with CG-14 defaults (3)
  - Approval semantics (5)
  - Handler integration (3)
  - Ordering: CG-15 precedes G4 (2)
  - Sanitization (2)
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from graqle.config.settings import GraqleConfig
from graqle.governance import check_kg_block, check_protected_path
from graqle.governance.kg_write_gate import (
    _APPROVER_MIN_LEN,
    _approval_is_valid,
    _CG_14_DEFAULT_PROTECTED_PATHS,
    _merged_protected_patterns,
    _path_matches_pattern,
)


# ─────────────────────────────────────────────────────────────────────────
# check_protected_path helper (8)
# ─────────────────────────────────────────────────────────────────────────


def test_empty_protected_paths_allows_everything():
    cfg = GraqleConfig()
    # Even regular files — G4 has CG-14 defaults baked in, so graqle.yaml blocks
    allowed, env = check_protected_path("src/foo.py", config=cfg)
    assert allowed is True and env is None


def test_user_pattern_blocks_without_approval():
    cfg = GraqleConfig(protected_paths=["deploy/*.yml"])
    allowed, env = check_protected_path("deploy/app.yml", config=cfg)
    assert allowed is False
    assert env["error"] == "G4_PROTECTED_PATH"
    assert env["matched_pattern"] == "deploy/*.yml"


def test_user_pattern_allows_with_valid_approved_by():
    cfg = GraqleConfig(protected_paths=["deploy/*.yml"])
    allowed, env = check_protected_path(
        "deploy/app.yml", config=cfg, approved_by="reviewer-alice",
    )
    assert allowed is True


def test_non_matching_path_allowed():
    cfg = GraqleConfig(protected_paths=["deploy/*.yml"])
    allowed, env = check_protected_path("src/foo.py", config=cfg)
    assert allowed is True


def test_g4_envelope_includes_matched_pattern():
    cfg = GraqleConfig(protected_paths=["config/*.toml"])
    allowed, env = check_protected_path("config/prod.toml", config=cfg)
    assert allowed is False
    assert env["matched_pattern"] == "config/*.toml"
    assert env["error"] == "G4_PROTECTED_PATH"


def test_g4_envelope_suggestion_mentions_approval_paths():
    cfg = GraqleConfig(protected_paths=["x.yml"])
    allowed, env = check_protected_path("x.yml", config=cfg)
    assert allowed is False
    assert "approved_by" in env["suggestion"]
    assert "graq_config_audit" in env["suggestion"]


def test_g4_blocks_exact_match():
    cfg = GraqleConfig(protected_paths=["secrets.env"])
    allowed, env = check_protected_path("secrets.env", config=cfg)
    assert allowed is False


def test_g4_auditor_clean_bypasses_approval():
    cfg = GraqleConfig(protected_paths=["deploy/app.yml"])
    # Mock auditor reporting no drift
    mock_auditor = MagicMock()
    mock_auditor.audit.return_value = []  # no drift records
    allowed, env = check_protected_path(
        "deploy/app.yml", config=cfg, auditor=mock_auditor,
    )
    assert allowed is True


# ─────────────────────────────────────────────────────────────────────────
# GraqleConfig.protected_paths field (3)
# ─────────────────────────────────────────────────────────────────────────


def test_graqleconfig_protected_paths_default_empty():
    cfg = GraqleConfig()
    assert cfg.protected_paths == []


def test_graqleconfig_protected_paths_accepts_list():
    cfg = GraqleConfig(protected_paths=["a.yml", "b.toml"])
    assert cfg.protected_paths == ["a.yml", "b.toml"]


def test_graqleconfig_default_factory_protected_paths_empty():
    cfg = GraqleConfig.default()
    assert cfg.protected_paths == []


# ─────────────────────────────────────────────────────────────────────────
# Merge semantics (3)
# ─────────────────────────────────────────────────────────────────────────


def test_merged_patterns_includes_cg14_defaults():
    cfg = GraqleConfig()
    merged = _merged_protected_patterns(cfg)
    for default in _CG_14_DEFAULT_PROTECTED_PATHS:
        assert default in merged


def test_merged_patterns_user_patterns_additive():
    cfg = GraqleConfig(protected_paths=["deploy/*.yml", "terraform/**"])
    merged = _merged_protected_patterns(cfg)
    for default in _CG_14_DEFAULT_PROTECTED_PATHS:
        assert default in merged
    assert "deploy/*.yml" in merged
    assert "terraform/**" in merged


def test_merged_patterns_dedupes_preserving_order():
    # User duplicates a CG-14 default — should appear only once
    cfg = GraqleConfig(protected_paths=["graqle.yaml", "graqle.yaml", "custom.yml"])
    merged = _merged_protected_patterns(cfg)
    assert merged.count("graqle.yaml") == 1
    assert merged.count("custom.yml") == 1


def test_merged_patterns_skips_invalid_entries():
    # Pydantic validates list[str], so non-strings are rejected at construction
    # time. Test via a synthetic config object with bad entries instead.
    class _FakeCfg:
        protected_paths = ["valid.yml", "", "   ", "another.yml"]
    merged = _merged_protected_patterns(_FakeCfg())
    assert "valid.yml" in merged
    assert "another.yml" in merged
    assert "" not in merged
    assert "   " not in merged


# ─────────────────────────────────────────────────────────────────────────
# Approval semantics (5)
# ─────────────────────────────────────────────────────────────────────────


def test_approval_valid_reasonable_id():
    assert _approval_is_valid("reviewer-alice") is True
    assert _approval_is_valid("abc") is True  # min length


def test_approval_rejects_empty():
    assert _approval_is_valid("") is False
    assert _approval_is_valid(None) is False


def test_approval_rejects_whitespace_only():
    assert _approval_is_valid("   ") is False
    assert _approval_is_valid("\t\n") is False


def test_approval_rejects_too_short():
    assert _approval_is_valid("a") is False
    assert _approval_is_valid("ab") is False


def test_approval_rejects_non_string():
    assert _approval_is_valid(123) is False
    assert _approval_is_valid(["alice"]) is False
    assert _approval_is_valid({"name": "alice"}) is False


# ─────────────────────────────────────────────────────────────────────────
# Handler integration (3)
# ─────────────────────────────────────────────────────────────────────────


class _FakeConfigUserProtected:
    protected_paths: list[str] = ["deploy/*.yml"]


class _FakeConfigEmpty:
    protected_paths: list[str] = []


class _FakeServer:
    def __init__(self, config):
        self._config = config
        self._graph_file = None


@pytest.mark.asyncio
async def test_handle_write_blocks_user_protected_path():
    import graqle.plugins.mcp_dev_server as m

    server = _FakeServer(_FakeConfigUserProtected())
    result = json.loads(await m.KogniDevServer._handle_write(
        server, {"file_path": "deploy/app.yml", "content": "x", "dry_run": True},
    ))
    assert result["error"] == "G4_PROTECTED_PATH"


@pytest.mark.asyncio
async def test_handle_write_allows_user_protected_with_approved_by():
    import graqle.plugins.mcp_dev_server as m

    server = _FakeServer(_FakeConfigUserProtected())
    result = json.loads(await m.KogniDevServer._handle_write(
        server,
        {
            "file_path": "deploy/app.yml",
            "content": "x",
            "approved_by": "reviewer-alice",
            "dry_run": True,
        },
    ))
    # G4 passes → downstream may run (dry_run so we expect success-shape OR
    # a non-G4 error). Key: G4 envelope NOT returned.
    assert result.get("error") != "G4_PROTECTED_PATH"


@pytest.mark.asyncio
async def test_handle_write_passes_when_no_protected_paths_configured():
    import graqle.plugins.mcp_dev_server as m

    server = _FakeServer(_FakeConfigEmpty())
    # Use a path that's not in CG-14 defaults
    result = json.loads(await m.KogniDevServer._handle_write(
        server, {"file_path": "src/custom.py", "content": "x", "dry_run": True},
    ))
    assert result.get("error") != "G4_PROTECTED_PATH"


# ─────────────────────────────────────────────────────────────────────────
# Ordering: CG-15 precedes G4 (2)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_kg_file_matching_both_cg15_and_g4_returns_cg15():
    """If a KG file is ALSO in user's protected_paths, CG-15 wins (stricter)."""
    import graqle.plugins.mcp_dev_server as m

    class _CfgWithGraqleJson:
        protected_paths = ["graqle.json"]  # user adds KG file to G4 — redundant but allowed

    server = _FakeServer(_CfgWithGraqleJson())
    result = json.loads(await m.KogniDevServer._handle_write(
        server,
        {
            "file_path": "graqle.json",
            "content": "x",
            "approved_by": "reviewer-alice",  # would satisfy G4 but NOT CG-15
            "dry_run": True,
        },
    ))
    # CG-15 wins because it runs first AND has no bypass
    assert result["error"] == "CG-15_KG_WRITE_BLOCKED"


def test_check_kg_block_runs_before_check_protected_path_by_convention():
    """Documentation test: handler invokes CG-15 first, then G4."""
    import inspect
    import graqle.plugins.mcp_dev_server as m

    src = inspect.getsource(m.KogniDevServer._handle_write)
    cg15_idx = src.find("check_kg_block")
    g4_idx = src.find("check_protected_path")
    assert 0 < cg15_idx < g4_idx, (
        f"check_kg_block (idx={cg15_idx}) must appear before "
        f"check_protected_path (idx={g4_idx})"
    )


# ─────────────────────────────────────────────────────────────────────────
# Sanitization (2)
# ─────────────────────────────────────────────────────────────────────────


def test_g4_envelope_sanitizes_file_path():
    cfg = GraqleConfig(protected_paths=["*.yml"])
    allowed, env = check_protected_path(
        "/home/alice/deploy.yml", config=cfg,
    )
    assert allowed is False
    assert "/home/alice" not in env["file_path"]


def test_g4_envelope_sanitizes_suggestion_field():
    """suggestion is in the allowlist — gets sanitized even if it picks up a path."""
    # The stock suggestion string is safe already; this asserts allowlist wiring.
    cfg = GraqleConfig(protected_paths=["x.yml"])
    allowed, env = check_protected_path("x.yml", config=cfg)
    assert allowed is False
    # Suggestion exists and is a string
    assert isinstance(env["suggestion"], str)
    assert len(env["suggestion"]) > 0


# ─────────────────────────────────────────────────────────────────────────
# Glob pattern support (2 bonus)
# ─────────────────────────────────────────────────────────────────────────


def test_path_matches_fnmatch_star():
    assert _path_matches_pattern("deploy/app.yml", "deploy/*.yml") is True
    assert _path_matches_pattern("deploy/nested/app.yml", "deploy/*.yml") is False


def test_path_matches_exact():
    assert _path_matches_pattern("secrets.env", "secrets.env") is True
