"""Comprehensive test suite for GraQle Phantom plugin.

Test categories:
    1. SMOKE TESTS — Plugin loads, config works, no import errors
    2. UNIT TESTS — Individual components (config, session, auditors, etc.)
    3. CHAIN TESTS — Component interactions (engine → session → auditor)
    4. INTEGRATION TESTS — MCP tool registration + handler dispatch
    5. REGRESSION TESTS — Prove zero impact on existing SCORCH/MCP tools
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# ===========================================================================
# 1. SMOKE TESTS — Plugin loads without errors
# ===========================================================================


class TestPhantomSmoke:
    """Prove the plugin can be imported and basic structures are valid."""

    def test_import_phantom_package(self):
        """Phantom package imports without error."""
        from graqle.plugins.phantom import PhantomEngine, PhantomConfig
        assert PhantomEngine is not None
        assert PhantomConfig is not None

    def test_import_phantom_config(self):
        """PhantomConfig can be instantiated with defaults."""
        from graqle.plugins.phantom.config import PhantomConfig
        config = PhantomConfig()
        assert config.output_dir == "./scorch-output/phantom"
        assert config.headless is True
        assert config.max_sessions == 5

    def test_import_phantom_engine(self):
        """PhantomEngine can be instantiated without Playwright."""
        from graqle.plugins.phantom.engine import PhantomEngine
        engine = PhantomEngine()
        assert engine.config is not None

    def test_import_all_auditors(self):
        """All 10 auditor modules import without error."""
        from graqle.plugins.phantom.auditors import (
            behavioral, accessibility, mobile, security,
            brand, conversion, performance, seo, i18n, content,
        )
        assert behavioral.BehavioralAuditor is not None
        assert accessibility.AccessibilityAuditor is not None
        assert mobile.MobileAuditor is not None
        assert security.SecurityAuditor is not None
        assert brand.BrandAuditor is not None
        assert conversion.ConversionAuditor is not None
        assert performance.PerformanceAuditor is not None
        assert seo.SEOAuditor is not None
        assert i18n.I18nAuditor is not None
        assert content.ContentAuditor is not None

    def test_import_core_modules(self):
        """All core modules import without error."""
        from graqle.plugins.phantom.core.navigator import Navigator
        from graqle.plugins.phantom.core.interactor import Interactor
        from graqle.plugins.phantom.core.capturer import Capturer
        from graqle.plugins.phantom.core.analyzer import VisionAnalyzer
        from graqle.plugins.phantom.core.reporter import Reporter
        assert Navigator is not None
        assert Interactor is not None
        assert Capturer is not None
        assert VisionAnalyzer is not None
        assert Reporter is not None

    def test_import_feedback_modules(self):
        """Feedback modules import without error."""
        from graqle.plugins.phantom.feedback.learner import KGLearner
        from graqle.plugins.phantom.feedback.loop import FeedbackLoop
        assert KGLearner is not None
        assert FeedbackLoop is not None

    def test_import_session_manager(self):
        """Session manager imports without error."""
        from graqle.plugins.phantom.session import SessionManager, VIEWPORTS
        assert SessionManager is not None
        assert "desktop" in VIEWPORTS
        assert "mobile" in VIEWPORTS
        assert "tablet" in VIEWPORTS

    def test_phantom_init_exports(self):
        """__init__.py exports the right symbols."""
        import graqle.plugins.phantom as phantom
        assert hasattr(phantom, "PhantomEngine")
        assert hasattr(phantom, "PhantomConfig")
        assert "PhantomEngine" in phantom.__all__
        assert "PhantomConfig" in phantom.__all__


# ===========================================================================
# 2. UNIT TESTS — Individual component behavior
# ===========================================================================


class TestPhantomConfig:
    """PhantomConfig Pydantic model tests."""

    def test_default_config(self):
        from graqle.plugins.phantom.config import PhantomConfig
        config = PhantomConfig()
        assert config.headless is True
        assert config.default_wait_after == 2000
        assert config.screenshot_quality == 80
        assert "Mozilla" in config.user_agent

    def test_config_custom_values(self):
        from graqle.plugins.phantom.config import PhantomConfig
        config = PhantomConfig(
            headless=False,
            output_dir="/tmp/phantom-test",
            max_sessions=10,
        )
        assert config.headless is False
        assert config.output_dir == "/tmp/phantom-test"
        assert config.max_sessions == 10

    def test_config_bedrock_defaults(self, tmp_path, monkeypatch):
        # Run in a clean dir so graqle.yaml region doesn't override the default
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
        monkeypatch.delenv("AWS_REGION", raising=False)
        from graqle.plugins.phantom.config import PhantomConfig
        config = PhantomConfig()
        assert config.bedrock.region == "us-east-1"
        assert "sonnet" in config.bedrock.model_id

    def test_config_brand_rules_defaults(self):
        from graqle.plugins.phantom.config import PhantomConfig
        config = PhantomConfig()
        assert config.brand_rules.min_touch_target_px == 44
        assert config.brand_rules.wcag_contrast_ratio == 4.5

    def test_config_to_json_from_json(self, tmp_path):
        from graqle.plugins.phantom.config import PhantomConfig
        config = PhantomConfig(headless=False, max_sessions=7)
        path = str(tmp_path / "phantom.json")
        config.to_json(path)
        loaded = PhantomConfig.from_json(path)
        assert loaded.headless is False
        assert loaded.max_sessions == 7

    def test_config_normalize_keys(self):
        from graqle.plugins.phantom.config import _normalize_keys
        result = _normalize_keys({"outputDir": "/tmp", "maxSessions": 3})
        assert result["output_dir"] == "/tmp"
        assert result["max_sessions"] == 3


class TestViewportPresets:
    def test_all_presets_exist(self):
        from graqle.plugins.phantom.config import VIEWPORT_PRESETS
        assert "mobile" in VIEWPORT_PRESETS
        assert "tablet" in VIEWPORT_PRESETS
        assert "desktop" in VIEWPORT_PRESETS

    def test_mobile_dimensions(self):
        from graqle.plugins.phantom.config import VIEWPORT_PRESETS
        mobile = VIEWPORT_PRESETS["mobile"]
        assert mobile.width == 390
        assert mobile.height == 844

    def test_desktop_dimensions(self):
        from graqle.plugins.phantom.config import VIEWPORT_PRESETS
        desktop = VIEWPORT_PRESETS["desktop"]
        assert desktop.width == 1920
        assert desktop.height == 1080


class TestSessionManager:
    """Session manager tests (mocked Playwright)."""

    def test_session_manager_init(self):
        from graqle.plugins.phantom.session import SessionManager
        sm = SessionManager()
        assert sm._sessions == {}
        assert sm._playwright is None

    def test_list_sessions_empty(self):
        from graqle.plugins.phantom.session import SessionManager
        sm = SessionManager()
        assert sm.list_sessions() == []

    def test_get_nonexistent_session_raises(self):
        from graqle.plugins.phantom.session import SessionManager
        sm = SessionManager()
        with pytest.raises(KeyError, match="not found"):
            sm.get("phantom_nonexistent")

    def test_viewport_mapping(self):
        from graqle.plugins.phantom.session import VIEWPORTS
        assert VIEWPORTS["mobile"]["width"] == 390
        assert VIEWPORTS["desktop"]["width"] == 1920
        assert VIEWPORTS["tablet"]["width"] == 768


class TestReporter:
    """Reporter generates correct output formats."""

    def test_generate_reports(self, tmp_path):
        from graqle.plugins.phantom.core.reporter import Reporter
        reporter = Reporter()
        result = reporter.generate(
            url="https://example.com",
            dimensions={"behavioral": {"dead_clicks": 2}},
            summary={"total_issues": 2, "critical": 0, "high": 1, "medium": 1, "low": 0, "grade": "B+"},
            output_dir=str(tmp_path),
        )
        assert Path(result["json"]).exists()
        assert Path(result["markdown"]).exists()

        # Verify JSON content
        with open(result["json"]) as f:
            report = json.load(f)
        assert report["url"] == "https://example.com"
        assert report["summary"]["grade"] == "B+"

    def test_markdown_format(self, tmp_path):
        from graqle.plugins.phantom.core.reporter import Reporter
        reporter = Reporter()
        result = reporter.generate(
            url="https://test.example.com",
            dimensions={},
            summary={"total_issues": 0, "critical": 0, "high": 0, "medium": 0, "low": 0, "grade": "A"},
            output_dir=str(tmp_path),
        )
        md_content = Path(result["markdown"]).read_text()
        assert "# Phantom Audit Report" in md_content
        assert "https://test.example.com" in md_content
        assert "Grade" in md_content


class TestFeedbackLoop:
    """Feedback loop comparison tests."""

    def test_no_previous_report(self):
        from graqle.plugins.phantom.feedback.loop import FeedbackLoop
        loop = FeedbackLoop()
        result = loop.compare({"summary": {"total_issues": 5}}, previous_path=None)
        assert result["comparison"] == "no_previous"

    def test_file_not_found(self):
        from graqle.plugins.phantom.feedback.loop import FeedbackLoop
        loop = FeedbackLoop()
        result = loop.compare({"summary": {}}, previous_path="/nonexistent/report.json")
        assert result["comparison"] == "file_not_found"

    def test_comparison_improvement(self, tmp_path):
        from graqle.plugins.phantom.feedback.loop import FeedbackLoop

        # Write previous report
        prev = {"summary": {"total_issues": 10, "critical": 2, "high": 3, "medium": 3, "low": 2, "grade": "C"}}
        prev_path = tmp_path / "prev.json"
        prev_path.write_text(json.dumps(prev))

        current = {"summary": {"total_issues": 5, "critical": 1, "high": 1, "medium": 2, "low": 1, "grade": "B"}}

        loop = FeedbackLoop()
        result = loop.compare(current, previous_path=str(prev_path))

        assert result["comparison"] == "complete"
        assert result["improved"] is True
        assert result["delta"] == -5
        assert result["improvement_pct"] == 50.0
        assert result["previous_grade"] == "C"
        assert result["current_grade"] == "B"


class TestVisionAnalyzer:
    """Vision analyzer unit tests (no Bedrock calls)."""

    def test_parse_findings_empty(self):
        from graqle.plugins.phantom.core.analyzer import VisionAnalyzer
        analyzer = VisionAnalyzer()
        findings = analyzer._parse_findings("")
        assert findings == []

    def test_parse_findings_with_content(self):
        from graqle.plugins.phantom.core.analyzer import VisionAnalyzer
        analyzer = VisionAnalyzer()
        text = """
# Visual Hierarchy
The main dashboard has significant issues with competing sections.
Minor spacing problem between cards.
"""
        findings = analyzer._parse_findings(text)
        assert len(findings) >= 1
        # "significant" should trigger "high" severity
        assert any(f["severity"] == "high" for f in findings)

    def test_estimate_cost(self):
        from graqle.plugins.phantom.core.analyzer import VisionAnalyzer
        cost = VisionAnalyzer._estimate_cost({"input_tokens": 1000, "output_tokens": 500}, "sonnet")
        assert cost > 0
        assert cost < 0.1  # Should be pennies


class TestEngineSummaryCalculation:
    """Test the audit summary calculation logic."""

    def test_perfect_score(self):
        from graqle.plugins.phantom.engine import PhantomEngine
        engine = PhantomEngine()
        summary = engine._calculate_summary({})
        assert summary["grade"] == "A"
        assert summary["total_issues"] == 0

    def test_critical_security(self):
        from graqle.plugins.phantom.engine import PhantomEngine
        engine = PhantomEngine()
        summary = engine._calculate_summary({
            "security": {"missing_headers": ["CSP", "HSTS", "X-Frame", "X-Content"]},
        })
        assert summary["critical"] >= 1

    def test_grade_scaling(self):
        from graqle.plugins.phantom.engine import PhantomEngine
        engine = PhantomEngine()
        # Many issues should give low grade
        summary = engine._calculate_summary({
            "security": {"missing_headers": ["a", "b", "c", "d", "e"]},
            "accessibility": {"contrast_violations": 5, "missing_aria_labels": 10, "unlabeled_inputs": 5},
            "mobile": {"small_touch_targets": 50},
            "behavioral": {"dead_clicks": 10},
            "seo": {"title_ok": False, "meta_description_ok": False},
            "brand": {"button_inconsistent": True, "off_brand_color_count": 10},
        })
        # Many issues should give a grade worse than A
        assert summary["grade"] not in ("A", "A-"), f"Expected low grade, got {summary['grade']}"


# ===========================================================================
# 3. CHAIN TESTS — Component interaction
# ===========================================================================


class TestPhantomEngineChaining:
    """Test that engine correctly wires to sub-components."""

    def test_engine_lazy_loads_components(self):
        """Engine properties don't create instances until accessed."""
        from graqle.plugins.phantom.engine import PhantomEngine
        engine = PhantomEngine()
        # Internal attributes should be None before access
        assert engine._sessions is None
        assert engine._navigator is None
        assert engine._interactor is None
        assert engine._capturer is None
        assert engine._analyzer is None
        assert engine._reporter is None

    def test_engine_navigator_property(self):
        from graqle.plugins.phantom.engine import PhantomEngine
        engine = PhantomEngine()
        nav = engine.navigator
        from graqle.plugins.phantom.core.navigator import Navigator
        assert isinstance(nav, Navigator)
        # Accessing again returns same instance
        assert engine.navigator is nav

    def test_engine_interactor_property(self):
        from graqle.plugins.phantom.engine import PhantomEngine
        engine = PhantomEngine()
        inter = engine.interactor
        from graqle.plugins.phantom.core.interactor import Interactor
        assert isinstance(inter, Interactor)

    def test_engine_reporter_property(self):
        from graqle.plugins.phantom.engine import PhantomEngine
        engine = PhantomEngine()
        rep = engine.reporter
        from graqle.plugins.phantom.core.reporter import Reporter
        assert isinstance(rep, Reporter)

    def test_engine_get_auditor(self):
        """Engine can resolve all 10 auditor dimensions."""
        from graqle.plugins.phantom.engine import PhantomEngine
        engine = PhantomEngine()
        for dim in ["behavioral", "accessibility", "mobile", "security",
                     "brand", "conversion", "performance", "seo", "i18n", "content"]:
            auditor = engine._get_auditor(dim)
            assert hasattr(auditor, "audit"), f"Auditor {dim} missing audit method"

    def test_engine_get_auditor_invalid(self):
        """Engine raises KeyError for unknown dimension."""
        from graqle.plugins.phantom.engine import PhantomEngine
        engine = PhantomEngine()
        with pytest.raises(KeyError):
            engine._get_auditor("nonexistent")


# ===========================================================================
# 4. INTEGRATION TESTS — MCP tool registration + handler dispatch
# ===========================================================================


class TestPhantomMCPIntegration:
    """Prove Phantom tools are correctly registered in MCP server."""

    def test_phantom_tools_in_definitions(self):
        """All 8 Phantom tools appear in TOOL_DEFINITIONS."""
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        names = {t["name"] for t in TOOL_DEFINITIONS}
        phantom_tools = {
            "graq_phantom_browse",
            "graq_phantom_click",
            "graq_phantom_type",
            "graq_phantom_screenshot",
            "graq_phantom_audit",
            "graq_phantom_flow",
            "graq_phantom_discover",
            "graq_phantom_session",
        }
        assert phantom_tools.issubset(names), f"Missing: {phantom_tools - names}"

    def test_phantom_kogni_aliases_in_definitions(self):
        """All 8 kogni_phantom_* aliases appear in TOOL_DEFINITIONS."""
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        names = {t["name"] for t in TOOL_DEFINITIONS}
        kogni_tools = {
            "kogni_phantom_browse",
            "kogni_phantom_click",
            "kogni_phantom_type",
            "kogni_phantom_screenshot",
            "kogni_phantom_audit",
            "kogni_phantom_flow",
            "kogni_phantom_discover",
            "kogni_phantom_session",
        }
        assert kogni_tools.issubset(names), f"Missing: {kogni_tools - names}"

    def test_phantom_tools_have_valid_schemas(self):
        """All Phantom tool schemas are well-formed."""
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        phantom = [t for t in TOOL_DEFINITIONS if "phantom" in t["name"]]
        for tool in phantom:
            assert "inputSchema" in tool
            schema = tool["inputSchema"]
            assert schema["type"] == "object"
            assert "properties" in schema
            assert isinstance(schema["properties"], dict)

    def test_phantom_browse_requires_url(self):
        """graq_phantom_browse has 'url' as required field."""
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        browse = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_phantom_browse")
        assert "url" in browse["inputSchema"].get("required", [])

    def test_phantom_click_requires_session_and_target(self):
        """graq_phantom_click requires session_id and target."""
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        click = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_phantom_click")
        required = click["inputSchema"].get("required", [])
        assert "session_id" in required
        assert "target" in required

    def test_phantom_handlers_in_server(self):
        """Server has all 8 Phantom handler methods."""
        from graqle.plugins.mcp_dev_server import KogniDevServer
        server = KogniDevServer.__new__(KogniDevServer)
        for handler_name in [
            "_handle_phantom_browse",
            "_handle_phantom_click",
            "_handle_phantom_type",
            "_handle_phantom_screenshot",
            "_handle_phantom_audit",
            "_handle_phantom_flow",
            "_handle_phantom_discover",
            "_handle_phantom_session",
        ]:
            assert hasattr(server, handler_name), f"Missing handler: {handler_name}"

    @pytest.mark.asyncio
    async def test_phantom_handler_returns_import_error_gracefully(self):
        """Phantom handlers return JSON error if Phantom import fails."""
        from graqle.plugins.mcp_dev_server import KogniDevServer

        server = KogniDevServer.__new__(KogniDevServer)
        server.config_path = "graqle.yaml"
        server.read_only = False
        server._graph = MagicMock()
        server._config = None
        server._graph_file = "graqle.json"
        server._graph_mtime = 9999999999.0

        # Make _phantom_engine raise ImportError
        with patch.object(server, "_phantom_engine", side_effect=ImportError("Phantom not available")):
            result = await server._handle_phantom_browse({"url": "https://example.com"})
            data = json.loads(result)
            assert "error" in data
            assert "not available" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_phantom_handler_dispatch_in_handle_tool(self):
        """handle_tool correctly routes to Phantom handlers."""
        from graqle.plugins.mcp_dev_server import KogniDevServer

        server = KogniDevServer.__new__(KogniDevServer)
        server.config_path = "graqle.yaml"
        server.read_only = False
        server._graph = MagicMock()
        server._config = None
        server._graph_file = "graqle.json"
        server._graph_mtime = 9999999999.0

        # Mock the phantom engine to return success
        mock_engine = MagicMock()
        mock_engine.browse = AsyncMock(return_value={"session_id": "test", "url": "https://example.com"})
        server._phantom = mock_engine

        result = await server.handle_tool("graq_phantom_browse", {"url": "https://example.com"})
        data = json.loads(result)
        assert data["session_id"] == "test"

    @pytest.mark.asyncio
    async def test_kogni_phantom_alias_dispatch(self):
        """kogni_phantom_* aliases route to the same handlers."""
        from graqle.plugins.mcp_dev_server import KogniDevServer

        server = KogniDevServer.__new__(KogniDevServer)
        server.config_path = "graqle.yaml"
        server.read_only = False
        server._graph = MagicMock()
        server._config = None
        server._graph_file = "graqle.json"
        server._graph_mtime = 9999999999.0

        mock_engine = MagicMock()
        mock_engine.browse = AsyncMock(return_value={"session_id": "alias_test"})
        server._phantom = mock_engine

        result = await server.handle_tool("kogni_phantom_browse", {"url": "https://example.com"})
        data = json.loads(result)
        assert data["session_id"] == "alias_test"


# ===========================================================================
# 5. REGRESSION TESTS — Prove zero impact on existing tools
# ===========================================================================


class TestZeroRegression:
    """CRITICAL: Prove that adding Phantom did NOT break any existing tools.

    These tests verify:
    1. All pre-existing tool definitions are still present and unchanged
    2. All pre-existing handlers still exist and are callable
    3. Tool counts are correct (additive only)
    4. No existing tool schema was modified
    """

    def test_existing_graq_tools_still_present(self):
        """All 29 pre-existing graq_* tools are still in TOOL_DEFINITIONS."""
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        names = {t["name"] for t in TOOL_DEFINITIONS}

        existing_tools = {
            "graq_context", "graq_inspect", "graq_reason", "graq_reason_batch",
            "graq_preflight", "graq_lessons", "graq_impact", "graq_safety_check",
            "graq_learn", "graq_reload", "graq_audit", "graq_runtime",
            "graq_route", "graq_lifecycle", "graq_drace", "graq_gate",
            "graq_scorch_audit", "graq_scorch_behavioral", "graq_scorch_report",
            "graq_scorch_a11y", "graq_scorch_perf", "graq_scorch_seo",
            "graq_scorch_mobile", "graq_scorch_i18n", "graq_scorch_security",
            "graq_scorch_conversion", "graq_scorch_brand", "graq_scorch_auth_flow",
            "graq_scorch_diff",
        }
        missing = existing_tools - names
        assert not missing, f"REGRESSION: Existing tools disappeared: {missing}"

    def test_existing_kogni_aliases_still_present(self):
        """All 27 pre-existing kogni_* aliases are still in TOOL_DEFINITIONS."""
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        names = {t["name"] for t in TOOL_DEFINITIONS}

        existing_aliases = {
            "kogni_context", "kogni_inspect", "kogni_reason", "kogni_reason_batch",
            "kogni_preflight", "kogni_lessons", "kogni_impact", "kogni_safety_check",
            "kogni_learn", "kogni_runtime", "kogni_route", "kogni_lifecycle",
            "kogni_drace", "kogni_gate",
            "kogni_scorch_audit", "kogni_scorch_behavioral", "kogni_scorch_report",
            "kogni_scorch_a11y", "kogni_scorch_perf", "kogni_scorch_seo",
            "kogni_scorch_mobile", "kogni_scorch_i18n", "kogni_scorch_security",
            "kogni_scorch_conversion", "kogni_scorch_brand", "kogni_scorch_auth_flow",
            "kogni_scorch_diff",
        }
        missing = existing_aliases - names
        assert not missing, f"REGRESSION: Existing aliases disappeared: {missing}"

    def test_tool_count_is_additive_only(self):
        """Tool count grows additively only — never shrinks. v0.38.0 Phase 3.5: 98 total."""
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS

        graq_tools = [t for t in TOOL_DEFINITIONS if t["name"].startswith("graq_")]
        kogni_tools = [t for t in TOOL_DEFINITIONS if t["name"].startswith("kogni_")]

        # v0.38.0 Phase 3.5: +10 graq_* (read/write/grep/glob/bash + 5 git) + 10 kogni_* = 98 total
        # graq_reload + graq_audit are graq_* only (no kogni_* alias) → 49 graq + 49 kogni = 98
        assert len(graq_tools) >= 38, f"graq_* tools must not decrease, got {len(graq_tools)}"
        assert len(kogni_tools) >= 36, f"kogni_* tools must not decrease, got {len(kogni_tools)}"
        assert len(TOOL_DEFINITIONS) == 112, f"Expected 112 total tools, got {len(TOOL_DEFINITIONS)}"

    def test_existing_tool_schemas_unchanged(self):
        """Spot-check that existing tool schemas were not modified."""
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        tool_map = {t["name"]: t for t in TOOL_DEFINITIONS}

        # graq_context must still require "task"
        ctx = tool_map["graq_context"]
        assert "task" in ctx["inputSchema"]["properties"]
        assert "task" in ctx["inputSchema"].get("required", [])

        # graq_impact must still have "component" required
        impact = tool_map["graq_impact"]
        assert "component" in impact["inputSchema"]["properties"]
        assert "component" in impact["inputSchema"].get("required", [])

        # graq_reason must still have "question" required
        reason = tool_map["graq_reason"]
        assert "question" in reason["inputSchema"]["properties"]
        assert "question" in reason["inputSchema"].get("required", [])

        # graq_learn must still have "description" in properties
        learn = tool_map["graq_learn"]
        assert "description" in learn["inputSchema"]["properties"]

    def test_existing_handlers_still_exist(self):
        """All pre-existing handler methods are still on KogniDevServer."""
        from graqle.plugins.mcp_dev_server import KogniDevServer
        server = KogniDevServer.__new__(KogniDevServer)

        existing_handlers = [
            "_handle_context", "_handle_inspect", "_handle_reason",
            "_handle_reason_batch", "_handle_preflight", "_handle_lessons",
            "_handle_impact", "_handle_safety_check", "_handle_learn",
            "_handle_reload", "_handle_audit", "_handle_runtime",
            "_handle_route", "_handle_lifecycle", "_handle_gate", "_handle_drace",
            "_handle_scorch_audit", "_handle_scorch_behavioral",
            "_handle_scorch_report", "_handle_scorch_a11y",
            "_handle_scorch_perf", "_handle_scorch_seo",
            "_handle_scorch_mobile", "_handle_scorch_i18n",
            "_handle_scorch_security", "_handle_scorch_conversion",
            "_handle_scorch_brand", "_handle_scorch_auth_flow",
            "_handle_scorch_diff",
        ]
        for handler in existing_handlers:
            assert hasattr(server, handler), f"REGRESSION: Handler {handler} disappeared!"

    @pytest.mark.asyncio
    async def test_existing_handler_still_works(self):
        """graq_context handler still works after Phantom addition."""
        from graqle.plugins.mcp_dev_server import KogniDevServer

        server = KogniDevServer.__new__(KogniDevServer)
        server.config_path = "graqle.yaml"
        server.read_only = False
        server._config = None
        server._graph_file = "graqle.json"
        server._graph_mtime = 9999999999.0
        server._gov = None
        server._neo4j_traversal = None

        # Build mock graph
        mock_graph = MagicMock()
        mock_graph.nodes = {
            "test-node": MagicMock(
                id="test-node", label="Test", entity_type="service",
                description="A test node", properties={}, degree=1, status="ACTIVE",
            )
        }
        mock_graph.edges = {}
        mock_graph.stats = MagicMock(
            total_nodes=1, total_edges=0, avg_degree=0.0,
            density=0.0, connected_components=1, hub_nodes=[],
        )
        server._graph = mock_graph

        result = await server.handle_tool("graq_context", {"task": "test"})
        data = json.loads(result)
        # Should return context, not an error
        assert "error" not in data or "unknown" not in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_existing_inspect_handler_still_works(self):
        """graq_inspect handler still works after Phantom addition."""
        from graqle.plugins.mcp_dev_server import KogniDevServer

        server = KogniDevServer.__new__(KogniDevServer)
        server.config_path = "graqle.yaml"
        server.read_only = False
        server._config = None
        server._graph_file = "graqle.json"
        server._graph_mtime = 9999999999.0
        server._gov = None
        server._neo4j_traversal = None

        mock_graph = MagicMock()
        mock_graph.nodes = {}
        mock_graph.edges = {}
        mock_graph.stats = MagicMock(
            total_nodes=0, total_edges=0, avg_degree=0.0,
            density=0.0, connected_components=0, hub_nodes=[],
        )
        server._graph = mock_graph

        result = await server.handle_tool("graq_inspect", {"stats": True})
        data = json.loads(result)
        assert "error" not in data or "unknown" not in data.get("error", "").lower()

    def test_read_only_mode_still_blocks_write_tools(self):
        """Read-only mode still blocks graq_learn/graq_reload (not broken by Phantom)."""
        from graqle.plugins.mcp_dev_server import KogniDevServer, _WRITE_TOOLS
        server = KogniDevServer(read_only=True)
        tools = server.list_tools()
        tool_names = {t["name"] for t in tools}
        for write_tool in _WRITE_TOOLS:
            assert write_tool not in tool_names, f"REGRESSION: {write_tool} leaked through read-only"

    def test_unknown_tool_still_returns_error(self):
        """Unknown tools still return proper error (not broken by Phantom dispatch)."""
        import asyncio
        from graqle.plugins.mcp_dev_server import KogniDevServer

        server = KogniDevServer.__new__(KogniDevServer)
        server.config_path = "graqle.yaml"
        server.read_only = False
        server._graph = MagicMock()
        server._config = None
        server._graph_file = "graqle.json"
        server._graph_mtime = 9999999999.0

        result = asyncio.run(server.handle_tool("graq_nonexistent_tool", {}))
        data = json.loads(result)
        assert "error" in data
        assert "Unknown tool" in data["error"]

    def test_plugins_init_unchanged(self):
        """graqle.plugins.__init__ still exports MCPServer and KogniDevServer."""
        from graqle.plugins import MCPServer, MCPConfig, KogniDevServer
        assert MCPServer is not None
        assert MCPConfig is not None
        assert KogniDevServer is not None


# ===========================================================================
# 6. CLI TESTS — Phantom CLI commands exist and don't crash on import
# ===========================================================================


class TestPhantomCLI:
    """Verify Phantom CLI is registered correctly."""

    def test_phantom_app_import(self):
        from graqle.cli.commands.phantom import phantom_app
        assert phantom_app is not None

    def test_phantom_app_has_commands(self):
        from graqle.cli.commands.phantom import phantom_app
        # Typer stores registered commands
        registered = {cmd.name for cmd in phantom_app.registered_commands}
        assert "browse" in registered
        assert "audit" in registered
        assert "discover" in registered
        assert "flow" in registered

    def test_main_app_has_phantom(self):
        """Phantom is registered in the main graq CLI app."""
        from graqle.cli.main import app
        group_names = {g.name for g in app.registered_groups}
        assert "phantom" in group_names
