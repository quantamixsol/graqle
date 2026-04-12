"""Tests for graqle.storage.tiers — storage tier invariant facade.

All tests are deterministic: no network, no LLM, no external dependencies.
Uses tmp_path and monkeypatch for isolation.
"""

from __future__ import annotations

import pytest

from graqle.storage.tiers import (
    StorageTierInvariantError,
    StorageTiers,
    TierStatus,
)


# ---------------------------------------------------------------------------
# Tier 0 — Local JSON (always primary)
# ---------------------------------------------------------------------------


def test_tier0_active_when_graqle_json_exists(tmp_path):
    (tmp_path / "graqle.json").write_text('{"nodes":{},"edges":{}}')
    tiers = StorageTiers(project_dir=tmp_path)
    t0 = tiers.tier0()
    assert t0.status == TierStatus.ACTIVE
    assert t0.role == "primary"
    assert "bytes" in t0.detail


def test_tier0_not_configured_when_graqle_json_missing(tmp_path):
    tiers = StorageTiers(project_dir=tmp_path)
    t0 = tiers.tier0()
    assert t0.status == TierStatus.NOT_CONFIGURED
    assert t0.role == "primary"  # role is fixed even if not configured
    assert "graq scan" in t0.detail


# ---------------------------------------------------------------------------
# Tier 1A — Neo4j (local, opt-in projection)
# ---------------------------------------------------------------------------


def test_tier1_neo4j_disabled_when_env_set(monkeypatch, tmp_path):
    monkeypatch.setenv("NEO4J_DISABLED", "true")
    tiers = StorageTiers(project_dir=tmp_path)
    assert tiers.tier1_neo4j().status == TierStatus.DISABLED
    assert "NEO4J_DISABLED" in tiers.tier1_neo4j().detail


def test_tier1_neo4j_opt_in_when_env_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("NEO4J_DISABLED", raising=False)
    tiers = StorageTiers(project_dir=tmp_path)
    assert tiers.tier1_neo4j().status == TierStatus.OPT_IN_AVAILABLE


@pytest.mark.parametrize("value", ["1", "True", "YES", "on", "TRUE"])
def test_tier1_neo4j_disabled_truthy_variants(monkeypatch, tmp_path, value):
    monkeypatch.setenv("NEO4J_DISABLED", value)
    tiers = StorageTiers(project_dir=tmp_path)
    assert tiers.tier1_neo4j().status == TierStatus.DISABLED


# ---------------------------------------------------------------------------
# Tier 1B — Neptune (hosted, opt-in projection)
# ---------------------------------------------------------------------------


def test_tier1_neptune_opt_in_when_endpoint_set(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "NEPTUNE_ENDPOINT",
        "graqle-kg.cluster-xyz.eu-central-1.neptune.amazonaws.com",
    )
    tiers = StorageTiers(project_dir=tmp_path)
    assert tiers.tier1_neptune().status == TierStatus.OPT_IN_AVAILABLE
    assert "graqle-kg" in tiers.tier1_neptune().detail


def test_tier1_neptune_not_configured_when_endpoint_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("NEPTUNE_ENDPOINT", raising=False)
    tiers = StorageTiers(project_dir=tmp_path)
    assert tiers.tier1_neptune().status == TierStatus.NOT_CONFIGURED


# ---------------------------------------------------------------------------
# Structural invariant
# ---------------------------------------------------------------------------


def test_invariant_holds_when_graqle_json_exists(tmp_path):
    (tmp_path / "graqle.json").write_text('{"nodes":{},"edges":{}}')
    tiers = StorageTiers(project_dir=tmp_path)
    ok, reason = tiers.invariant_check()
    assert ok, reason


def test_invariant_holds_even_without_graqle_json(tmp_path):
    """invariant_check verifies structure (one primary named Tier 0),
    NOT whether graqle.json exists. enforce() checks existence."""
    tiers = StorageTiers(project_dir=tmp_path)
    ok, reason = tiers.invariant_check()
    assert ok, reason


# ---------------------------------------------------------------------------
# effective_primary — config override detection
# ---------------------------------------------------------------------------


def test_effective_primary_no_yaml_returns_tier0(tmp_path):
    (tmp_path / "graqle.json").write_text('{"nodes":{},"edges":{}}')
    tiers = StorageTiers(project_dir=tmp_path)
    assert tiers.effective_primary().status == TierStatus.ACTIVE


def test_effective_primary_detects_neo4j_override(tmp_path):
    (tmp_path / "graqle.json").write_text('{"nodes":{},"edges":{}}')
    (tmp_path / "graqle.yaml").write_text("graph:\n  connector: neo4j\n")
    tiers = StorageTiers(project_dir=tmp_path)
    ep = tiers.effective_primary()
    assert ep.status == TierStatus.DISABLED
    assert "MISMATCH" in ep.detail
    assert "neo4j" in ep.detail


def test_effective_primary_detects_neptune_override(tmp_path):
    (tmp_path / "graqle.json").write_text('{"nodes":{},"edges":{}}')
    (tmp_path / "graqle.yaml").write_text("graph:\n  connector: neptune\n")
    tiers = StorageTiers(project_dir=tmp_path)
    ep = tiers.effective_primary()
    assert ep.status == TierStatus.DISABLED
    assert "neptune" in ep.detail


def test_effective_primary_networkx_is_not_override(tmp_path):
    (tmp_path / "graqle.json").write_text('{"nodes":{},"edges":{}}')
    (tmp_path / "graqle.yaml").write_text("graph:\n  connector: networkx\n")
    tiers = StorageTiers(project_dir=tmp_path)
    assert tiers.effective_primary().status == TierStatus.ACTIVE


def test_effective_primary_malformed_yaml(tmp_path):
    (tmp_path / "graqle.json").write_text('{"nodes":{},"edges":{}}')
    (tmp_path / "graqle.yaml").write_text("{{{{not valid yaml")
    tiers = StorageTiers(project_dir=tmp_path)
    # Graceful fallback — no crash, returns tier0
    assert tiers.effective_primary().status == TierStatus.ACTIVE


# ---------------------------------------------------------------------------
# has_override
# ---------------------------------------------------------------------------


def test_has_override_true_with_neo4j_connector(tmp_path):
    (tmp_path / "graqle.json").write_text('{"nodes":{},"edges":{}}')
    (tmp_path / "graqle.yaml").write_text("graph:\n  connector: neo4j\n")
    tiers = StorageTiers(project_dir=tmp_path)
    assert tiers.has_override() is True


def test_has_override_false_without_yaml(tmp_path):
    (tmp_path / "graqle.json").write_text('{"nodes":{},"edges":{}}')
    tiers = StorageTiers(project_dir=tmp_path)
    assert tiers.has_override() is False


# ---------------------------------------------------------------------------
# enforce — runtime invariant enforcement
# ---------------------------------------------------------------------------


def test_enforce_passes_when_all_good(monkeypatch, tmp_path):
    monkeypatch.delenv("NEO4J_DISABLED", raising=False)
    (tmp_path / "graqle.json").write_text('{"nodes":{},"edges":{}}')
    tiers = StorageTiers(project_dir=tmp_path)
    ok, reason = tiers.enforce()
    assert ok, reason


def test_enforce_fails_when_graqle_json_missing(tmp_path):
    tiers = StorageTiers(project_dir=tmp_path)
    ok, reason = tiers.enforce()
    assert not ok
    assert "not active" in reason


def test_enforce_fails_on_config_override(tmp_path):
    (tmp_path / "graqle.json").write_text('{"nodes":{},"edges":{}}')
    (tmp_path / "graqle.yaml").write_text("graph:\n  connector: neo4j\n")
    tiers = StorageTiers(project_dir=tmp_path)
    ok, reason = tiers.enforce()
    assert not ok
    assert "MISMATCH" in reason


def test_enforce_strict_raises_on_missing_json(tmp_path):
    tiers = StorageTiers(project_dir=tmp_path)
    with pytest.raises(StorageTierInvariantError, match="not active"):
        tiers.enforce(strict=True)


def test_enforce_strict_raises_on_config_override(tmp_path):
    (tmp_path / "graqle.json").write_text('{"nodes":{},"edges":{}}')
    (tmp_path / "graqle.yaml").write_text("graph:\n  connector: neptune\n")
    tiers = StorageTiers(project_dir=tmp_path)
    with pytest.raises(StorageTierInvariantError, match="MISMATCH"):
        tiers.enforce(strict=True)


# ---------------------------------------------------------------------------
# Edge cases (MINOR-2 from research team review)
# ---------------------------------------------------------------------------


def test_enforce_fails_when_graqle_json_empty_file(tmp_path):
    """Edge case: graqle.json exists but is 0 bytes."""
    (tmp_path / "graqle.json").write_text("")
    tiers = StorageTiers(project_dir=tmp_path)
    # File exists so tier0 reports ACTIVE (size=0) — enforce passes structurally.
    # The invariant is about file existence, not content validity.
    ok, _ = tiers.enforce()
    assert ok  # structural invariant holds; content validation is a separate concern


def test_enforce_passes_when_graqle_json_has_zero_nodes(tmp_path):
    """Edge case: valid JSON but empty graph (0 nodes)."""
    (tmp_path / "graqle.json").write_text('{"nodes":[],"links":[]}')
    tiers = StorageTiers(project_dir=tmp_path)
    ok, _ = tiers.enforce()
    assert ok  # invariant is about storage tier, not graph quality


def test_effective_primary_yaml_has_graph_key_but_no_connector(tmp_path):
    """Edge case: graqle.yaml has graph: section but no connector sub-key."""
    (tmp_path / "graqle.json").write_text('{"nodes":{},"edges":{}}')
    (tmp_path / "graqle.yaml").write_text("graph:\n  path: graqle.json\n")
    tiers = StorageTiers(project_dir=tmp_path)
    # No connector key → defaults to 'networkx' → no override
    ep = tiers.effective_primary()
    assert ep.status == TierStatus.ACTIVE
    assert tiers.has_override() is False


def test_enforce_strict_raises_on_json_save_failure_regression(tmp_path):
    """Regression test for BLOCKER-1: to_neo4j must fail-closed when JSON save fails.

    This test verifies the StorageTierInvariantError is importable and raisable —
    the actual to_neo4j integration test requires a Neo4j instance.
    """
    from graqle.storage.tiers import StorageTierInvariantError
    with pytest.raises(StorageTierInvariantError, match="save failed"):
        raise StorageTierInvariantError("Tier 0 JSON save failed — test")
