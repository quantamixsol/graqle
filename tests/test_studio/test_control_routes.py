"""Tests for graqle.studio.routes.control — Control Plane & Badge API."""

# ── graqle:intelligence ──
# module: tests.test_studio.test_control_routes
# risk: LOW (impact radius: 0 modules)
# dependencies: json, pathlib, pytest, fastapi, testclient +1 more
# constraints: none
# ── /graqle:intelligence ──

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from graqle.studio.routes.control import router

# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def app_with_control(tmp_path: Path):
    """Create FastAPI app with control router and test data."""
    app = FastAPI()

    graqle_dir = tmp_path / ".graqle"
    audit_dir = graqle_dir / "governance" / "audit"
    audit_dir.mkdir(parents=True)

    # Create scorecard
    scorecard = {
        "health": "HEALTHY",
        "nodes": 4892,
        "chunk_coverage": 100.0,
        "description_coverage": 100.0,
    }
    (graqle_dir / "scorecard.json").write_text(json.dumps(scorecard), encoding="utf-8")

    # Create audit session with DRACE score
    session = {
        "session_id": "session-1",
        "started": "2026-03-15T10:00:00+00:00",
        "task": "Test session",
        "status": "completed",
        "entries": [],
        "drace_score": 0.85,
    }
    (audit_dir / "20260315_100000.json").write_text(json.dumps(session), encoding="utf-8")

    # Create graqle.yaml
    (tmp_path / "graqle.yaml").write_text(
        "graph:\n  connector: neo4j\n", encoding="utf-8"
    )

    app.state.studio_state = {"root": str(tmp_path)}
    app.include_router(router, prefix="/control")

    return TestClient(app)


@pytest.fixture
def app_empty(tmp_path: Path):
    """App with minimal .graqle dir."""
    app = FastAPI()
    (tmp_path / ".graqle").mkdir()
    app.state.studio_state = {"root": str(tmp_path)}
    app.include_router(router, prefix="/control")
    return TestClient(app)


# ── Instance Tests ──────────────────────────────────────────────────


class TestInstances:
    def test_list_instances(self, app_with_control):
        r = app_with_control.get("/control/instances")
        assert r.status_code == 200
        data = r.json()
        assert "instances" in data
        assert "total" in data
        assert data["total"] >= 1

    def test_current_instance(self, app_with_control):
        r = app_with_control.get("/control/instances")
        data = r.json()
        assert "current" in data

    def test_instance_has_fields(self, app_with_control):
        r = app_with_control.get("/control/instances")
        instances = r.json()["instances"]
        if instances:
            inst = instances[0]
            assert "name" in inst
            assert "health" in inst
            assert "nodes" in inst
            assert "connector" in inst

    def test_instance_detail_not_found(self, app_with_control):
        r = app_with_control.get("/control/instance/nonexistent_xyz")
        data = r.json()
        assert "error" in data


# ── Badge Tests ─────────────────────────────────────────────────────


class TestBadges:
    def test_drace_badge_svg(self, app_with_control):
        r = app_with_control.get("/control/badges/drace")
        assert r.status_code == 200
        assert "image/svg+xml" in r.headers["content-type"]
        assert "<svg" in r.text
        assert "0.85" in r.text  # DRACE score

    def test_health_badge_svg(self, app_with_control):
        r = app_with_control.get("/control/badges/health")
        assert r.status_code == 200
        assert "<svg" in r.text
        assert "HEALTHY" in r.text

    def test_nodes_badge_svg(self, app_with_control):
        r = app_with_control.get("/control/badges/nodes")
        assert r.status_code == 200
        assert "<svg" in r.text
        assert "4892" in r.text

    def test_empty_drace_badge(self, app_empty):
        r = app_empty.get("/control/badges/drace")
        assert r.status_code == 200
        assert "N/A" in r.text

    def test_empty_health_badge(self, app_empty):
        r = app_empty.get("/control/badges/health")
        assert r.status_code == 200
        assert "UNKNOWN" in r.text


# ── Share Config Tests ──────────────────────────────────────────────


class TestShareConfig:
    def test_share_config(self, app_with_control):
        r = app_with_control.get("/control/share/config")
        assert r.status_code == 200
        data = r.json()
        assert "badges" in data
        assert "drace" in data["badges"]
        assert "health" in data["badges"]
        assert "nodes" in data["badges"]

    def test_markdown_format(self, app_with_control):
        r = app_with_control.get("/control/share/config")
        drace = r.json()["badges"]["drace"]
        assert "markdown" in drace
        assert drace["markdown"].startswith("![DRACE]")

    def test_html_format(self, app_with_control):
        r = app_with_control.get("/control/share/config")
        drace = r.json()["badges"]["drace"]
        assert "html" in drace
        assert "<img" in drace["html"]
