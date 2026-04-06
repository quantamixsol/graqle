"""Phase 10 Layer 1 tests — audit trail wiring, graq_gov_gate, anti-gaming.

# ── graqle:intelligence ──
# module: tests.test_generation.test_phase10_layer1
# risk: LOW (impact radius: 0 modules — test only)
# dependencies: __future__, pytest, threading, graqle.core.governance, graqle.plugins.mcp_dev_server
# constraints: Tests must not require live graph or LLM backend
# ── /graqle:intelligence ──
"""
from __future__ import annotations

import json
import threading
import time
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# 1. GovernanceMiddleware — cumulative radius anti-gaming
# ──────────────────────────────────────────────────────────────────────────────

class TestCumulativeRadiusAntiGaming:
    """Verify anti-gaming cumulative radius cap enforcement."""

    def _fresh_middleware(self):
        """Return a GovernanceMiddleware with clean cumulative state."""
        from graqle.core.governance import GovernanceMiddleware, GovernanceConfig
        GovernanceMiddleware._cumulative.clear()
        GovernanceMiddleware._state_loaded = True  # skip disk load in tests
        return GovernanceMiddleware(GovernanceConfig(cumulative_radius_cap=10, cumulative_window_hours=24))

    def test_first_change_within_cap_passes(self) -> None:
        m = self._fresh_middleware()
        r = m.check(diff="x", file_path="a.py", risk_level="LOW", impact_radius=5, actor="alice")
        assert not r.blocked, f"Should pass: {r.reason}"

    def test_second_change_within_cap_passes(self) -> None:
        m = self._fresh_middleware()
        m.check(diff="x", file_path="a.py", risk_level="LOW", impact_radius=4, actor="alice")
        r = m.check(diff="x", file_path="b.py", risk_level="LOW", impact_radius=4, actor="alice")
        assert not r.blocked  # 4+4=8 < 10

    def test_cumulative_over_cap_forces_t3_block(self) -> None:
        """Alice has radius=8 in window, then tries radius=5 → total=13 > 10 → T3 block."""
        from graqle.core.governance import GovernanceMiddleware
        m = self._fresh_middleware()
        m.check(diff="x", file_path="a.py", risk_level="MEDIUM", impact_radius=8, actor="alice",
                approved_by="lead", justification="approved")
        r = m.check(diff="x", file_path="b.py", risk_level="LOW", impact_radius=5, actor="alice")
        assert r.blocked
        assert r.tier == "T3"
        assert any("anti-gaming" in w.lower() or "cumulative" in w.lower() for w in r.warnings)

    def test_exactly_at_cap_passes(self) -> None:
        """radius=5 + radius=5 = exactly 10 = cap → should NOT trigger (> not >=)."""
        m = self._fresh_middleware()
        m.check(diff="x", file_path="a.py", risk_level="LOW", impact_radius=5, actor="bob")
        r = m.check(diff="x", file_path="b.py", risk_level="LOW", impact_radius=5, actor="bob")
        assert not r.blocked  # 5+5=10 == cap, not > cap

    def test_one_over_cap_triggers(self) -> None:
        m = self._fresh_middleware()
        m.check(diff="x", file_path="a.py", risk_level="LOW", impact_radius=5, actor="carol")
        r = m.check(diff="x", file_path="b.py", risk_level="LOW", impact_radius=6, actor="carol")
        assert r.blocked  # 5+6=11 > 10

    def test_anonymous_actor_no_cap_enforcement(self) -> None:
        """Anonymous (empty) actors bypass cumulative tracking."""
        m = self._fresh_middleware()
        for _ in range(5):
            r = m.check(diff="x", file_path="f.py", risk_level="LOW", impact_radius=5, actor="")
        # No actor → no cumulative tracking → no block from cap
        assert not r.blocked

    def test_different_actors_independent_caps(self) -> None:
        m = self._fresh_middleware()
        # alice fills up her cap
        m.check(diff="x", file_path="a.py", risk_level="MEDIUM", impact_radius=8, actor="alice",
                approved_by="lead", justification="ok")
        # bob is independent — his cap is still 0
        r = m.check(diff="x", file_path="b.py", risk_level="LOW", impact_radius=5, actor="bob")
        assert not r.blocked

    def test_concurrent_same_actor_atomic(self) -> None:
        """Two concurrent calls from same actor with combined radius > cap — exactly one should pass."""
        from graqle.core.governance import GovernanceMiddleware
        m = self._fresh_middleware()
        results = []

        def do_check():
            r = m.check(diff="x", file_path="c.py", risk_level="LOW", impact_radius=6, actor="dave")
            results.append(r.blocked)

        t1 = threading.Thread(target=do_check)
        t2 = threading.Thread(target=do_check)
        t1.start(); t2.start()
        t1.join(); t2.join()

        # Exactly one should be blocked (12 > 10)
        assert len(results) == 2
        blocked_count = sum(1 for b in results if b)
        assert blocked_count == 1, f"Expected exactly 1 blocked, got {blocked_count}: {results}"

    def test_state_persisted_to_file(self, tmp_path) -> None:
        """Cumulative state is written to .graqle/gov_cumulative.json after each pass."""
        from graqle.core.governance import GovernanceMiddleware, GovernanceConfig
        GovernanceMiddleware._cumulative.clear()
        GovernanceMiddleware._state_loaded = True
        # Point state file to tmp directory
        original = GovernanceMiddleware._STATE_FILE
        GovernanceMiddleware._STATE_FILE = tmp_path / "gov_cumulative.json"
        try:
            m = GovernanceMiddleware(GovernanceConfig())
            m.check(diff="x", file_path="a.py", risk_level="LOW", impact_radius=2, actor="eve")
            assert GovernanceMiddleware._STATE_FILE.exists()
            data = json.loads(GovernanceMiddleware._STATE_FILE.read_text())
            assert "eve" in data
            assert len(data["eve"]) == 1
            assert data["eve"][0][1] == 2  # radius recorded
        finally:
            GovernanceMiddleware._STATE_FILE = original
            GovernanceMiddleware._cumulative.clear()

    def test_ts_block_not_recorded_in_cumulative(self) -> None:
        """TS-BLOCK stops before cumulative tracking — no radius pollution."""
        from graqle.core.governance import GovernanceMiddleware
        m = self._fresh_middleware()
        GovernanceMiddleware._cumulative.clear()
        r = m.check(diff="w_J = 0.7", file_path="a.py", risk_level="LOW", impact_radius=5, actor="frank")
        assert r.blocked
        assert r.tier == "TS-BLOCK"
        # TS-BLOCK returned before cumulative — radius should NOT be recorded
        from graqle.core.governance import GovernanceMiddleware as GM
        assert len(GM._cumulative.get("frank", [])) == 0


# ──────────────────────────────────────────────────────────────────────────────
# 2. graq_gov_gate MCP tool registration
# ──────────────────────────────────────────────────────────────────────────────

class TestGraqGovGateTool:
    """Verify graq_gov_gate is properly registered, dispatched, and write-gated."""

    def test_graq_gov_gate_in_tool_definitions(self) -> None:
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        names = [t["name"] for t in TOOL_DEFINITIONS]
        assert "graq_gov_gate" in names

    def test_kogni_gov_gate_alias_exists(self) -> None:
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        names = [t["name"] for t in TOOL_DEFINITIONS]
        assert "kogni_gov_gate" in names

    def test_total_tool_count_updated(self) -> None:
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        assert len(TOOL_DEFINITIONS) == 120  # +4: graq_github_pr/diff + kogni aliases (HFCI-001+002)

    def test_graq_gov_gate_in_write_tools(self) -> None:
        from graqle.plugins.mcp_dev_server import _WRITE_TOOLS
        assert "graq_gov_gate" in _WRITE_TOOLS
        assert "kogni_gov_gate" in _WRITE_TOOLS

    def test_graq_gov_gate_has_schema(self) -> None:
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        defn = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_gov_gate")
        schema = defn["inputSchema"]
        assert "file_path" in schema["properties"]
        assert "diff" in schema["properties"]
        assert "risk_level" in schema["properties"]
        assert "approved_by" in schema["properties"]

    def test_graq_gov_gate_in_routing(self) -> None:
        from graqle.routing import MCP_TOOL_TO_TASK
        assert "graq_gov_gate" in MCP_TOOL_TO_TASK
        assert MCP_TOOL_TO_TASK["graq_gov_gate"] == "gate"
        assert "kogni_gov_gate" in MCP_TOOL_TO_TASK

    def test_graq_gov_gate_dispatched_not_unknown(self) -> None:
        """handle_tool must not return 'Unknown tool' for graq_gov_gate."""
        import asyncio
        from graqle.plugins.mcp_dev_server import KogniDevServer
        server = KogniDevServer.__new__(KogniDevServer)
        server.config_path = "graqle.yaml"
        server.read_only = False
        server._graph = None
        server._config = None
        server._gov = None

        async def run():
            result = await server.handle_tool("graq_gov_gate", {"file_path": "x.py"})
            return json.loads(result)

        r = asyncio.run(run())
        assert "Unknown tool" not in str(r)

    def test_graq_gov_gate_t1_passes(self) -> None:
        """LOW risk, radius=1 → T1 auto-pass, not blocked."""
        import asyncio
        from graqle.core.governance import GovernanceMiddleware
        GovernanceMiddleware._cumulative.clear()
        GovernanceMiddleware._state_loaded = True
        from graqle.plugins.mcp_dev_server import KogniDevServer
        server = KogniDevServer.__new__(KogniDevServer)
        server.config_path = "graqle.yaml"
        server.read_only = False
        server._graph = None
        server._config = None
        server._gov = None

        async def run():
            return json.loads(await server.handle_tool("graq_gov_gate", {
                "file_path": "src/utils.py",
                "risk_level": "LOW",
                "impact_radius": 1,
            }))

        r = asyncio.run(run())
        assert not r.get("blocked"), f"Should pass T1: {r}"
        assert r.get("tier") == "T1"

    def test_graq_gov_gate_ts_block_returns_error(self) -> None:
        """TS-1 pattern in diff → blocked=True, error=GOVERNANCE_GATE."""
        import asyncio
        from graqle.plugins.mcp_dev_server import KogniDevServer
        server = KogniDevServer.__new__(KogniDevServer)
        server.config_path = "graqle.yaml"
        server.read_only = False
        server._graph = None
        server._config = None
        server._gov = None

        async def run():
            return json.loads(await server.handle_tool("graq_gov_gate", {
                "file_path": "src/core.py",
                "diff": "config w_J = 0.7 internal",
            }))

        r = asyncio.run(run())
        assert r.get("blocked") is True
        assert r.get("error") == "GOVERNANCE_GATE"
        assert r.get("tier") == "TS-BLOCK"

    def test_graq_gov_gate_blocked_in_readonly_mode(self) -> None:
        """graq_gov_gate is blocked in read-only mode (it writes KG nodes)."""
        import asyncio
        from graqle.plugins.mcp_dev_server import KogniDevServer
        server = KogniDevServer.__new__(KogniDevServer)
        server.config_path = "graqle.yaml"
        server.read_only = True
        server._graph = None
        server._config = None
        server._gov = None

        async def run():
            return json.loads(await server.handle_tool("graq_gov_gate", {"file_path": "x.py"}))

        r = asyncio.run(run())
        assert "read_only" in str(r).lower() or "error" in r


# ──────────────────────────────────────────────────────────────────────────────
# 3. GOVERNANCE_BYPASS node wiring in handlers
# ──────────────────────────────────────────────────────────────────────────────

class TestGovernanceBypassNodeWiring:
    """Verify bypass nodes are written for T2/T3 in _handle_edit/_handle_generate."""

    def test_t2_bypass_node_written_on_edit(self) -> None:
        """T2 gate pass in _handle_edit writes a GOVERNANCE_BYPASS node to KG."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch
        from graqle.core.governance import GovernanceMiddleware, GateResult

        # Mock T2 gate result (passes, tier=T2)
        mock_gate = GateResult(
            tier="T2", blocked=False, requires_approval=False,
            gate_score=0.75, reason="T2 pass", bypass_allowed=True,
            risk_level="MEDIUM", impact_radius=4, file_path="x.py",
            threshold_at_time=0.70,
        )

        nodes_added = []

        mock_creds = MagicMock()
        mock_creds.plan = "enterprise"

        with patch("graqle.cloud.credentials.load_credentials", return_value=mock_creds):
            with patch("graqle.plugins.mcp_dev_server.KogniDevServer._handle_preflight",
                       new_callable=AsyncMock,
                       return_value=json.dumps({"risk_level": "MEDIUM", "impact_radius": 4})):
                with patch("graqle.core.governance.GovernanceMiddleware.check", return_value=mock_gate):
                    with patch("graqle.plugins.mcp_dev_server.KogniDevServer._load_graph") as mock_load:
                        mock_graph = MagicMock()
                        mock_graph.add_node = lambda n: nodes_added.append(n)
                        mock_load.return_value = mock_graph
                        with patch("graqle.plugins.mcp_dev_server.KogniDevServer._save_graph"):
                            from graqle.plugins.mcp_dev_server import KogniDevServer
                            server = KogniDevServer.__new__(KogniDevServer)
                            server.config_path = "graqle.yaml"
                            server.read_only = False
                            server._graph = None
                            server._config = None
                            server._gov = None

                            async def run():
                                # Will fail at apply_diff but bypass node write happens before that
                                try:
                                    await server.handle_tool("graq_edit", {
                                        "file_path": "x.py",
                                        "diff": "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new",
                                        "dry_run": True,
                                    })
                                except Exception:
                                    pass

                            asyncio.run(run())

        bypass_nodes = [n for n in nodes_added if getattr(n, "entity_type", "") == "GOVERNANCE_BYPASS"]
        assert len(bypass_nodes) >= 1, f"Expected bypass node, got nodes: {nodes_added}"

    def test_t1_no_bypass_node_written(self) -> None:
        """T1 auto-pass does NOT write bypass node (not a bypass — it's a pass)."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch
        from graqle.core.governance import GateResult

        mock_gate = GateResult(
            tier="T1", blocked=False, requires_approval=False,
            gate_score=0.1, reason="T1 pass", bypass_allowed=True,
            risk_level="LOW", impact_radius=1, file_path="x.py",
            threshold_at_time=0.70,
        )

        nodes_added = []

        mock_creds = MagicMock()
        mock_creds.plan = "enterprise"

        with patch("graqle.cloud.credentials.load_credentials", return_value=mock_creds):
            with patch("graqle.plugins.mcp_dev_server.KogniDevServer._handle_preflight",
                       new_callable=AsyncMock,
                       return_value=json.dumps({"risk_level": "LOW", "impact_radius": 1})):
                with patch("graqle.core.governance.GovernanceMiddleware.check", return_value=mock_gate):
                    with patch("graqle.plugins.mcp_dev_server.KogniDevServer._load_graph") as mock_load:
                        mock_graph = MagicMock()
                        mock_graph.add_node = lambda n: nodes_added.append(n)
                        mock_load.return_value = mock_graph
                        with patch("graqle.plugins.mcp_dev_server.KogniDevServer._save_graph"):
                            from graqle.plugins.mcp_dev_server import KogniDevServer
                            server = KogniDevServer.__new__(KogniDevServer)
                            server.config_path = "graqle.yaml"
                            server.read_only = False
                            server._graph = None
                            server._config = None
                            server._gov = None

                            async def run():
                                try:
                                    await server.handle_tool("graq_edit", {
                                        "file_path": "x.py",
                                        "diff": "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new",
                                        "dry_run": True,
                                    })
                                except Exception:
                                    pass

                            asyncio.run(run())

        bypass_nodes = [n for n in nodes_added if getattr(n, "entity_type", "") == "GOVERNANCE_BYPASS"]
        assert len(bypass_nodes) == 0, "T1 should NOT write bypass node"

    def test_blocked_gate_no_bypass_node(self) -> None:
        """Blocked gate (TS-BLOCK/T3) does NOT write bypass node — it returns error."""
        import asyncio
        from unittest.mock import AsyncMock, patch
        from graqle.core.governance import GateResult

        mock_gate = GateResult(
            tier="TS-BLOCK", blocked=True, requires_approval=False,
            gate_score=1.0, reason="TS-BLOCK", bypass_allowed=False,
            risk_level="LOW", impact_radius=0, file_path="x.py",
            threshold_at_time=0.0,
        )

        nodes_added = []

        from unittest.mock import MagicMock
        mock_creds = MagicMock()
        mock_creds.plan = "enterprise"

        with patch("graqle.cloud.credentials.load_credentials", return_value=mock_creds):
            with patch("graqle.plugins.mcp_dev_server.KogniDevServer._handle_preflight",
                       new_callable=AsyncMock,
                       return_value=json.dumps({"risk_level": "LOW", "impact_radius": 0})):
                with patch("graqle.core.governance.GovernanceMiddleware.check", return_value=mock_gate):
                    with patch("graqle.plugins.mcp_dev_server.KogniDevServer._load_graph") as mock_load:
                        mock_graph = MagicMock()
                        mock_graph.add_node = lambda n: nodes_added.append(n)
                        mock_load.return_value = mock_graph
                        with patch("graqle.plugins.mcp_dev_server.KogniDevServer._save_graph"):
                            from graqle.plugins.mcp_dev_server import KogniDevServer
                            server = KogniDevServer.__new__(KogniDevServer)
                            server.config_path = "graqle.yaml"
                            server.read_only = False
                            server._graph = None
                            server._config = None
                            server._gov = None

                            async def run():
                                return json.loads(await server.handle_tool("graq_edit", {
                                    "file_path": "x.py",
                                    "diff": "w_J = 0.7",
                                    "dry_run": True,
                                }))

                            r = asyncio.run(run())

        assert r.get("error") == "GOVERNANCE_GATE"
        bypass_nodes = [n for n in nodes_added if getattr(n, "entity_type", "") == "GOVERNANCE_BYPASS"]
        assert len(bypass_nodes) == 0, "Blocked gate must not write bypass node"


# ──────────────────────────────────────────────────────────────────────────────
# 4. Dedup classifier — GOVERNANCE_BYPASS audit priority
# ──────────────────────────────────────────────────────────────────────────────

class TestDeduplicatorAuditPriority:
    """Verify GOVERNANCE_BYPASS and TOOL_EXECUTION get lowest dedup priority."""

    def test_governance_bypass_classified_as_audit(self) -> None:
        from graqle.scanner.dedup import DedupOrchestrator
        result = DedupOrchestrator._classify_source({"entity_type": "GOVERNANCE_BYPASS"})
        assert result == "audit"

    def test_tool_execution_classified_as_audit(self) -> None:
        from graqle.scanner.dedup import DedupOrchestrator
        result = DedupOrchestrator._classify_source({"entity_type": "TOOL_EXECUTION"})
        assert result == "audit"

    def test_audit_lowest_priority_in_config(self) -> None:
        from graqle.scanner.dedup import DedupOptions
        opts = DedupOptions()
        assert "audit" in opts.source_priority
        audit_idx = opts.source_priority.index("audit")
        code_idx = opts.source_priority.index("code")
        assert audit_idx > code_idx, "audit must have lower priority than code"

    def test_code_node_wins_over_audit_in_merge(self) -> None:
        """Code node must win merge against GOVERNANCE_BYPASS node — code is higher priority."""
        from graqle.scanner.dedup import DedupOrchestrator, DedupOptions
        # Build a graph where code node has same canonical label as audit node
        # Orchestrator._classify_source returns "code" for FUNCTION and "audit" for GOVERNANCE_BYPASS
        # source_priority: code > audit — so code wins
        code_node = {"id": "n1", "entity_type": "FUNCTION", "label": "foo", "properties": {}}
        audit_node = {"id": "n2", "entity_type": "GOVERNANCE_BYPASS", "label": "foo", "properties": {}}
        nodes = {"n1": code_node, "n2": audit_node}
        edges: dict = {}
        orch = DedupOrchestrator(nodes, edges, DedupOptions(canonical_ids=False))
        report = orch.run()
        # After dedup: n1 (code) should survive — audit node is lower priority
        # (unifier may merge them; code should win; n2 removed or n1 kept as primary)
        assert "n1" in orch._nodes, "Code node must survive dedup"
        assert orch._nodes["n1"].get("entity_type") == "FUNCTION", "Surviving node must be FUNCTION type"
