"""CR-003 PR-003a — edge-shrink guard boundary tests for _validate_graph_data.

Covers:
- Edge-shrink guard fires at >10% loss when old_edges > 100
- Guard does NOT fire when old_edges <= 100 (small-graph grace)
- Guard does NOT fire on growth (new_edges > old_edges)
- GRAQLE_ALLOW_EDGE_SHRINK env var allow-list (1, true, yes — case-insensitive)
- Invalid env var values get a warning and are treated as not-allowed
- EdgeShrinkError message handles old_edges == 0 without ZeroDivisionError
- Symmetric validation: refuse to save when 'links' is missing or non-list

See: .gsm/external/Change Requests/CR-003-kg-persistence-schema-parity.md
"""

# -- graqle:intelligence --
# module: tests.test_core.test_validate_graph_data_edge_shrink
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, graph, exceptions
# constraints: none
# -- /graqle:intelligence --

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graqle.core.exceptions import EdgeShrinkError
from graqle.core.graph import _validate_graph_data, _shrink_allowed


# -------- helpers --------


def _payload(num_nodes: int, num_edges: int) -> dict:
    """Minimal node_link_data payload."""
    return {
        "directed": True,
        "multigraph": False,
        "graph": {},
        "nodes": [{"id": f"n{i}"} for i in range(num_nodes)],
        "links": [
            {"source": f"n{i}", "target": f"n{(i+1) % max(1, num_nodes)}"}
            for i in range(num_edges)
        ],
    }


def _write_existing(tmp_path: Path, num_nodes: int, num_edges: int) -> Path:
    """Write a baseline graqle.json so the validator has something to compare against."""
    p = tmp_path / "existing.json"
    p.write_text(json.dumps(_payload(num_nodes, num_edges)), encoding="utf-8")
    return p


# -------- symmetric validation tests --------


def test_validate_rejects_missing_links_key(tmp_path):
    """links must be present and be a list."""
    bad = {
        "directed": True,
        "multigraph": False,
        "graph": {},
        "nodes": [{"id": "n0"}],
        # NO "links" key
    }
    with pytest.raises(ValueError, match="'links' .* must be a list"):
        _validate_graph_data(bad, existing_path=None)


def test_validate_rejects_non_list_links(tmp_path):
    """links being a dict (the very shape that allowed the regression) is rejected."""
    bad = {
        "directed": True,
        "multigraph": False,
        "graph": {},
        "nodes": [{"id": "n0"}],
        "links": {"e1": {"source": "n0", "target": "n0"}},  # WRONG shape
    }
    with pytest.raises(ValueError, match="'links' .* must be a list"):
        _validate_graph_data(bad, existing_path=None)


def test_validate_accepts_edges_alias(tmp_path):
    """Older payloads use 'edges' instead of 'links'. Both should be accepted."""
    payload = {
        "directed": True,
        "multigraph": False,
        "graph": {},
        "nodes": [{"id": "n0"}],
        "edges": [],  # alias for 'links'
    }
    # Should not raise
    _validate_graph_data(payload, existing_path=None)


# -------- edge-shrink guard boundary tests --------


def test_no_existing_file_does_not_fire(tmp_path):
    """When existing_path doesn't exist, guard cannot compare and must not fire."""
    payload = _payload(num_nodes=10, num_edges=0)
    _validate_graph_data(payload, existing_path=str(tmp_path / "nope.json"))


def test_growth_does_not_fire(tmp_path):
    """new_edges > old_edges is growth — must not raise."""
    existing = _write_existing(tmp_path, num_nodes=200, num_edges=200)
    payload = _payload(num_nodes=200, num_edges=500)
    _validate_graph_data(payload, existing_path=str(existing))


def test_small_baseline_does_not_fire(tmp_path):
    """When old_edges <= 100, guard is in grace period (small-graph rebuild)."""
    existing = _write_existing(tmp_path, num_nodes=200, num_edges=50)
    payload = _payload(num_nodes=200, num_edges=0)
    # Should NOT raise EdgeShrinkError because old_edges (50) is <= 100
    _validate_graph_data(payload, existing_path=str(existing))


def test_at_threshold_does_not_fire(tmp_path):
    """A 10% loss is exactly at the threshold; guard fires only when LOSS > threshold."""
    existing = _write_existing(tmp_path, num_nodes=500, num_edges=1000)
    payload = _payload(num_nodes=500, num_edges=900)  # exactly 10% loss
    # 1.0 - (900/1000) == 0.10 — NOT > 0.10, so no raise
    _validate_graph_data(payload, existing_path=str(existing))


def test_just_over_threshold_fires(tmp_path):
    """10.1% loss must raise EdgeShrinkError."""
    existing = _write_existing(tmp_path, num_nodes=500, num_edges=1000)
    payload = _payload(num_nodes=500, num_edges=899)  # 10.1% loss
    with pytest.raises(EdgeShrinkError) as exc_info:
        _validate_graph_data(payload, existing_path=str(existing))
    assert exc_info.value.old_edges == 1000
    assert exc_info.value.new_edges == 899


def test_catastrophic_loss_fires(tmp_path):
    """The exact regression shape: 22516/27690 -> 22516/0 must raise."""
    # Use scaled-down version (we don't need 22516 nodes for the assertion)
    existing = _write_existing(tmp_path, num_nodes=500, num_edges=600)
    payload = _payload(num_nodes=500, num_edges=0)
    with pytest.raises(EdgeShrinkError) as exc_info:
        _validate_graph_data(payload, existing_path=str(existing))
    assert exc_info.value.old_edges == 600
    assert exc_info.value.new_edges == 0


# -------- env-var allow-list tests --------


def test_env_allow_1(monkeypatch, tmp_path):
    monkeypatch.setenv("GRAQLE_ALLOW_EDGE_SHRINK", "1")
    existing = _write_existing(tmp_path, num_nodes=500, num_edges=1000)
    payload = _payload(num_nodes=500, num_edges=0)
    # Must not raise — but should emit audit log line
    _validate_graph_data(payload, existing_path=str(existing))


@pytest.mark.parametrize("val", ["true", "TRUE", "yes", "YES", "Yes", "1", "yEs"])
def test_env_allow_case_insensitive(monkeypatch, val):
    monkeypatch.setenv("GRAQLE_ALLOW_EDGE_SHRINK", val)
    assert _shrink_allowed() is True


@pytest.mark.parametrize("val", ["", "0", "false", "no", "FALSE"])
def test_env_disallow(monkeypatch, val):
    monkeypatch.setenv("GRAQLE_ALLOW_EDGE_SHRINK", val)
    assert _shrink_allowed() is False


def test_env_invalid_warns_and_disallows(monkeypatch, caplog):
    monkeypatch.setenv("GRAQLE_ALLOW_EDGE_SHRINK", "garbage")
    import logging
    with caplog.at_level(logging.WARNING, logger="graqle"):
        result = _shrink_allowed()
    assert result is False
    assert any("GRAQLE_ALLOW_EDGE_SHRINK" in rec.message for rec in caplog.records)


def test_env_with_whitespace_stripped(monkeypatch):
    """Trailing/leading whitespace must not break allow-list match."""
    monkeypatch.setenv("GRAQLE_ALLOW_EDGE_SHRINK", "  yEs  ")
    assert _shrink_allowed() is True


# -------- division-by-zero defensive guard --------


def test_edge_shrink_error_zero_old_does_not_crash():
    """EdgeShrinkError(old=0, new=0) must not raise ZeroDivisionError on construction.

    The constructor's loss_pct calculation guards via max(1, old_edges); this
    asserts the message renders cleanly even if a future caller passes 0.
    """
    err = EdgeShrinkError(old_edges=0, new_edges=0, threshold=0.10)
    msg = str(err)
    assert "0 -> 0" in msg
    assert "ZeroDivisionError" not in msg


def test_edge_shrink_error_attributes_preserved():
    """EdgeShrinkError carries old/new/threshold as attributes for caller introspection."""
    err = EdgeShrinkError(old_edges=1000, new_edges=500, threshold=0.10)
    assert err.old_edges == 1000
    assert err.new_edges == 500
    assert err.threshold == 0.10
    assert "50.0% loss" in str(err)


# -------- audit-log PII / path-disclosure protection (security pass) --------


def test_audit_log_hashes_user_and_uses_basename(monkeypatch, caplog, tmp_path):
    """The audit log line must NOT contain the raw username or the full path.

    OWASP A09:2021 — production log aggregators ingest warning-level logs;
    raw USER/USERNAME and full filesystem paths are PII / reconnaissance
    surfaces. CR-003 PR-003a security pass mandates SHA-256(8) user hash
    + basename(path) only.
    """
    import logging
    monkeypatch.setenv("USER", "haris-secret-username")
    monkeypatch.setenv("USERNAME", "haris-secret-username")
    monkeypatch.setenv("GRAQLE_ALLOW_EDGE_SHRINK", "1")

    existing = _write_existing(tmp_path, num_nodes=500, num_edges=1000)
    payload = _payload(num_nodes=500, num_edges=0)
    with caplog.at_level(logging.WARNING, logger="graqle"):
        _validate_graph_data(payload, existing_path=str(existing))

    audit_lines = [r.message for r in caplog.records if "EDGE_SHRINK_ALLOWED" in r.message]
    assert audit_lines, "expected an EDGE_SHRINK_ALLOWED audit log line"
    joined = " ".join(audit_lines)

    # Raw username must NOT appear.
    assert "haris-secret-username" not in joined, "raw USER leaked into audit log"
    # Full path must NOT appear (only basename).
    assert str(tmp_path) not in joined, "full filesystem path leaked into audit log"
    # New schema fields must be present.
    assert "user_hash=" in joined, "expected user_hash= in audit line"
    assert "file=" in joined, "expected file= (basename) in audit line"
    # Basename of the existing file must appear.
    assert "existing.json" in joined
