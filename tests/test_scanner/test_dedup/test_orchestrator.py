"""Tests for the DedupOrchestrator."""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_dedup.test_orchestrator
# risk: LOW (impact radius: 0 modules)
# dependencies: dedup
# constraints: none
# ── /graqle:intelligence ──

from graqle.scanner.dedup import DedupOptions, DedupOrchestrator


class TestDedupOrchestrator:
    """Tests for the full deduplication pipeline."""

    def test_canonical_merge_duplicate_nodes(self):
        """Two nodes with same canonical ID get merged."""
        nodes = {
            "func::a": {
                "id": "func::a",
                "label": "verify_token",
                "entity_type": "FUNCTION",
                "description": "Verify JWT token",
                "properties": {"path": "src/auth.py"},
            },
            "func::b": {
                "id": "func::b",
                "label": "verify_token",
                "entity_type": "FUNCTION",
                "description": "Short",
                "properties": {"path": "src/auth.py", "lines": 42},
            },
        }
        edges = {}
        dedup = DedupOrchestrator(nodes, edges)
        report = dedup.run()

        assert report.canonical_merges == 1
        assert len(nodes) == 1
        # Longer description kept
        remaining = list(nodes.values())[0]
        assert "Verify JWT" in remaining["description"]
        # Properties merged
        assert remaining["properties"]["lines"] == 42

    def test_no_merge_different_canonical(self):
        """Nodes with different canonical IDs stay separate."""
        nodes = {
            "func::a": {
                "id": "func::a",
                "label": "verify_token",
                "entity_type": "FUNCTION",
                "properties": {"path": "src/auth.py"},
            },
            "func::b": {
                "id": "func::b",
                "label": "login",
                "entity_type": "FUNCTION",
                "properties": {"path": "src/auth.py"},
            },
        }
        edges = {}
        dedup = DedupOrchestrator(nodes, edges)
        report = dedup.run()

        assert report.canonical_merges == 0
        assert len(nodes) == 2

    def test_unification_cross_source(self):
        """Code node and document node with matching names get unified."""
        nodes = {
            "code::auth": {
                "id": "code::auth",
                "label": "auth_service",
                "entity_type": "FUNCTION",
                "description": "Auth",
                "properties": {"path": "src/auth.py"},
            },
            "doc::auth": {
                "id": "doc::auth",
                "label": "auth_service",
                "entity_type": "SECTION",
                "description": "The authentication service provides JWT verification",
                "properties": {"page": 5},
            },
        }
        edges = {}
        opts = DedupOptions(auto_merge_above=0.5)  # lower threshold for test
        dedup = DedupOrchestrator(nodes, edges, opts)
        report = dedup.run()

        assert report.unifier_merges >= 1
        assert len(nodes) == 1
        # Code is primary (higher authority)
        remaining = list(nodes.values())[0]
        assert remaining["id"] == "code::auth"

    def test_edges_rewired_on_merge(self):
        """After merge, edges pointing to secondary are rewired to primary."""
        nodes = {
            "func::a": {
                "id": "func::a",
                "label": "verify_token",
                "entity_type": "FUNCTION",
                "properties": {"path": "src/auth.py"},
            },
            "func::b": {
                "id": "func::b",
                "label": "verify_token",
                "entity_type": "FUNCTION",
                "properties": {"path": "src/auth.py"},
            },
            "other": {
                "id": "other",
                "label": "login",
                "entity_type": "FUNCTION",
                "properties": {"path": "src/login.py"},
            },
        }
        edges = {
            "other___CALLS___func::b": {
                "id": "other___CALLS___func::b",
                "source": "other",
                "target": "func::b",
                "relationship": "CALLS",
            },
        }
        dedup = DedupOrchestrator(nodes, edges)
        report = dedup.run()

        assert report.canonical_merges == 1
        # Edge should be rewired to func::a
        assert len(edges) == 1
        edge = list(edges.values())[0]
        assert edge["target"] == "func::a"
        assert edge["source"] == "other"

    def test_self_loop_edges_removed(self):
        """Edges that would create self-loops after merge are removed."""
        nodes = {
            "a": {
                "id": "a",
                "label": "auth",
                "entity_type": "FUNCTION",
                "properties": {"path": "src/auth.py"},
            },
            "b": {
                "id": "b",
                "label": "auth",
                "entity_type": "FUNCTION",
                "properties": {"path": "src/auth.py"},
            },
        }
        edges = {
            "a___CALLS___b": {
                "id": "a___CALLS___b",
                "source": "a",
                "target": "b",
                "relationship": "CALLS",
            },
        }
        dedup = DedupOrchestrator(nodes, edges)
        report = dedup.run()

        assert report.canonical_merges == 1
        # Self-loop edge should be removed
        assert len(edges) == 0

    def test_contradiction_detection(self):
        """Contradictions are detected when nodes share label but can't merge."""
        # Use different labels so unifier doesn't merge them,
        # but same normalised label for contradiction detection
        nodes = {
            "cfg::timeout": {
                "id": "cfg::timeout",
                "label": "timeout",
                "entity_type": "CONFIG",
                "properties": {"source": "config.json", "key": "timeout", "value": 30},
            },
            "doc::timeout": {
                "id": "doc::timeout",
                "label": "Timeout",
                "entity_type": "DOCUMENT",
                "properties": {"value": 60},
            },
        }
        edges = {}
        # Disable entity matching so both nodes survive for contradiction check
        opts = DedupOptions(entity_matching=False)
        dedup = DedupOrchestrator(nodes, edges, opts)
        report = dedup.run()

        assert len(report.contradictions) >= 1
        assert report.contradictions[0]["type"] == "numeric_mismatch"

    def test_report_node_counts(self):
        nodes = {
            "a": {
                "id": "a",
                "label": "auth",
                "entity_type": "FUNCTION",
                "properties": {"path": "src/auth.py"},
            },
            "b": {
                "id": "b",
                "label": "auth",
                "entity_type": "FUNCTION",
                "properties": {"path": "src/auth.py"},
            },
        }
        edges = {}
        dedup = DedupOrchestrator(nodes, edges)
        report = dedup.run()

        assert report.total_nodes_before == 2
        assert report.total_nodes_after == 1
        assert report.duration_seconds >= 0

    def test_disabled_layers(self):
        """Disabling canonical and entity matching should skip those layers."""
        nodes = {
            "a": {
                "id": "a",
                "label": "auth",
                "entity_type": "FUNCTION",
                "properties": {"path": "src/auth.py"},
            },
            "b": {
                "id": "b",
                "label": "auth",
                "entity_type": "FUNCTION",
                "properties": {"path": "src/auth.py"},
            },
        }
        edges = {}
        opts = DedupOptions(canonical_ids=False, entity_matching=False)
        dedup = DedupOrchestrator(nodes, edges, opts)
        report = dedup.run()

        assert report.canonical_merges == 0
        assert report.unifier_merges == 0
        assert len(nodes) == 2  # No merges happened

    def test_empty_graph(self):
        nodes = {}
        edges = {}
        dedup = DedupOrchestrator(nodes, edges)
        report = dedup.run()
        assert report.total_nodes_before == 0
        assert report.total_nodes_after == 0
        assert report.canonical_merges == 0

    def test_reject_below_threshold(self):
        """Matches below reject_below threshold are not merged."""
        nodes = {
            "code::auth_handler": {
                "id": "code::auth_handler",
                "label": "auth_handler",
                "entity_type": "FUNCTION",
                "properties": {"path": "src/auth.py"},
            },
            "doc::auth_doc": {
                "id": "doc::auth_doc",
                "label": "auth_documentation_notes",
                "entity_type": "SECTION",
                "properties": {"page": 1},
            },
        }
        edges = {}
        # Very high threshold — nothing should match
        opts = DedupOptions(auto_merge_above=0.99, reject_below=0.98)
        dedup = DedupOrchestrator(nodes, edges, opts)
        report = dedup.run()
        assert len(nodes) == 2  # No merges
