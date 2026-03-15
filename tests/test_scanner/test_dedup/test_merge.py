"""Tests for the merge engine."""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_dedup.test_merge
# risk: LOW (impact radius: 0 modules)
# dependencies: merge
# constraints: none
# ── /graqle:intelligence ──

from graqle.scanner.dedup.merge import MergeEngine, MergeDecision


class TestMergeEngine:
    """Tests for MergeEngine."""

    def test_basic_merge(self):
        engine = MergeEngine()
        primary = {
            "id": "code::auth",
            "label": "auth_service",
            "entity_type": "FUNCTION",
            "description": "Auth",
            "properties": {"path": "src/auth.py"},
        }
        secondary = {
            "id": "doc::auth",
            "label": "auth_service",
            "entity_type": "SECTION",
            "description": "Authentication service handles token verification",
            "properties": {"page": 3},
        }
        decision = engine.merge(primary, secondary, confidence=0.95, method="test")
        assert decision.accepted is True
        assert decision.confidence == 0.95
        assert decision.method == "test"

    def test_longer_description_kept(self):
        engine = MergeEngine()
        primary = {
            "id": "a",
            "label": "x",
            "entity_type": "FUNCTION",
            "description": "Short",
            "properties": {},
        }
        secondary = {
            "id": "b",
            "label": "x",
            "entity_type": "SECTION",
            "description": "A much longer and more detailed description of the thing",
            "properties": {},
        }
        decision = engine.merge(primary, secondary)
        assert decision.merged_node["description"] == secondary["description"]

    def test_properties_fill_gaps(self):
        engine = MergeEngine()
        primary = {
            "id": "a",
            "label": "x",
            "entity_type": "FUNCTION",
            "properties": {"path": "src/auth.py"},
        }
        secondary = {
            "id": "b",
            "label": "x",
            "entity_type": "SECTION",
            "properties": {"page": 5, "author": "Alice"},
        }
        decision = engine.merge(primary, secondary)
        merged_props = decision.merged_node["properties"]
        assert merged_props["path"] == "src/auth.py"
        assert merged_props["page"] == 5
        assert merged_props["author"] == "Alice"

    def test_properties_no_overwrite(self):
        engine = MergeEngine()
        primary = {
            "id": "a",
            "label": "x",
            "entity_type": "FUNCTION",
            "properties": {"version": "1.0"},
        }
        secondary = {
            "id": "b",
            "label": "x",
            "entity_type": "SECTION",
            "properties": {"version": "2.0"},
        }
        decision = engine.merge(primary, secondary)
        # Primary's value preserved
        assert decision.merged_node["properties"]["version"] == "1.0"
        # Conflict recorded
        assert len(decision.conflicts) == 1
        assert "version" in decision.conflicts[0]

    def test_merge_provenance_tracked(self):
        engine = MergeEngine()
        primary = {"id": "a", "label": "x", "entity_type": "FUNCTION", "properties": {}}
        secondary = {"id": "b", "label": "x", "entity_type": "SECTION", "properties": {}}
        decision = engine.merge(primary, secondary, method="canonical_id", confidence=1.0)
        props = decision.merged_node["properties"]
        assert "merge_sources" in props
        assert "a" in props["merge_sources"]
        assert "b" in props["merge_sources"]
        assert props["merge_method"] == "canonical_id"
        assert props["merge_confidence"] == 1.0

    def test_source_priority_swaps_when_secondary_higher(self):
        """If secondary has higher source priority, it becomes primary."""
        engine = MergeEngine(source_priority=["code", "api_spec", "document"])
        # Pass document first, code second
        doc_node = {
            "id": "doc1",
            "label": "auth",
            "entity_type": "DOCUMENT",
            "description": "Doc description",
            "properties": {"page": 1},
        }
        code_node = {
            "id": "code1",
            "label": "auth",
            "entity_type": "FUNCTION",
            "description": "Code desc",
            "properties": {"path": "src/auth.py"},
        }
        decision = engine.merge(doc_node, code_node)
        # Code should become the primary after swap
        assert decision.primary_id == "code1"
        assert decision.secondary_id == "doc1"

    def test_custom_source_priority(self):
        engine = MergeEngine(source_priority=["document", "code"])
        doc = {"id": "d", "label": "x", "entity_type": "DOCUMENT", "properties": {}}
        code = {"id": "c", "label": "x", "entity_type": "FUNCTION", "properties": {}}
        decision = engine.merge(code, doc)
        # With reversed priority, document is higher authority
        assert decision.primary_id == "d"

    def test_default_priority(self):
        engine = MergeEngine()
        code = {"id": "c", "label": "x", "entity_type": "FUNCTION", "properties": {}}
        ep = {"id": "e", "label": "x", "entity_type": "ENDPOINT", "properties": {}}
        decision = engine.merge(ep, code)
        # Code has highest default priority
        assert decision.primary_id == "c"
