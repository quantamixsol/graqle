"""Tests for contradiction detection."""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_dedup.test_contradictions
# risk: LOW (impact radius: 0 modules)
# dependencies: contradictions
# constraints: none
# ── /graqle:intelligence ──

from graqle.scanner.dedup.contradictions import detect_contradictions


class TestDetectContradictions:
    """Tests for detect_contradictions."""

    def test_numeric_mismatch(self):
        nodes = {
            "cfg::expiry": {
                "id": "cfg::expiry",
                "label": "token_expiry",
                "entity_type": "CONFIG",
                "properties": {"timeout": 3600},
            },
            "doc::expiry": {
                "id": "doc::expiry",
                "label": "token_expiry",
                "entity_type": "SECTION",
                "properties": {"timeout": 1800},
            },
        }
        results = detect_contradictions(nodes)
        assert len(results) == 1
        assert results[0]["type"] == "numeric_mismatch"
        assert results[0]["key"] == "timeout"
        assert results[0]["value_a"] == 3600
        assert results[0]["value_b"] == 1800

    def test_boolean_mismatch(self):
        nodes = {
            "code::strict": {
                "id": "code::strict",
                "label": "strict_mode",
                "entity_type": "CONFIG",
                "properties": {"enabled": True},
            },
            "doc::strict": {
                "id": "doc::strict",
                "label": "strict_mode",
                "entity_type": "DOCUMENT",
                "properties": {"enabled": False},
            },
        }
        results = detect_contradictions(nodes)
        assert len(results) == 1
        # Python bool is subclass of int, so may match numeric or boolean
        assert results[0]["type"] in ("boolean_mismatch", "numeric_mismatch")

    def test_value_mismatch(self):
        nodes = {
            "cfg::auth": {
                "id": "cfg::auth",
                "label": "auth_method",
                "entity_type": "CONFIG",
                "properties": {"method": "JWT"},
            },
            "doc::auth": {
                "id": "doc::auth",
                "label": "auth_method",
                "entity_type": "DOCUMENT",
                "properties": {"method": "session"},
            },
        }
        results = detect_contradictions(nodes)
        assert len(results) == 1
        assert results[0]["type"] == "value_mismatch"

    def test_no_contradiction_same_value(self):
        nodes = {
            "cfg::port": {
                "id": "cfg::port",
                "label": "server_port",
                "entity_type": "CONFIG",
                "properties": {"port": 8080},
            },
            "doc::port": {
                "id": "doc::port",
                "label": "server_port",
                "entity_type": "DOCUMENT",
                "properties": {"port": 8080},
            },
        }
        results = detect_contradictions(nodes)
        assert len(results) == 0

    def test_no_contradiction_same_source_type(self):
        """Two nodes from the same source type are not checked."""
        nodes = {
            "cfg::a": {
                "id": "cfg::a",
                "label": "timeout",
                "entity_type": "CONFIG",
                "properties": {"value": 100},
            },
            "cfg::b": {
                "id": "cfg::b",
                "label": "timeout",
                "entity_type": "CONFIG",
                "properties": {"value": 200},
            },
        }
        results = detect_contradictions(nodes)
        assert len(results) == 0

    def test_skips_metadata_keys(self):
        """Keys like 'source', 'path', 'merge_sources' are skipped."""
        nodes = {
            "a": {
                "id": "a",
                "label": "test_node",
                "entity_type": "CONFIG",
                "properties": {"source": "file_a.json", "path": "/a"},
            },
            "b": {
                "id": "b",
                "label": "test_node",
                "entity_type": "DOCUMENT",
                "properties": {"source": "docs/b.md", "path": "/b"},
            },
        }
        results = detect_contradictions(nodes)
        assert len(results) == 0

    def test_short_label_ignored(self):
        """Labels < 3 chars are skipped."""
        nodes = {
            "a": {"id": "a", "label": "ab", "entity_type": "CONFIG", "properties": {"v": 1}},
            "b": {"id": "b", "label": "ab", "entity_type": "DOCUMENT", "properties": {"v": 2}},
        }
        results = detect_contradictions(nodes)
        assert len(results) == 0

    def test_long_string_ignored(self):
        """String values > 100 chars are not compared."""
        long_a = "x" * 101
        long_b = "y" * 101
        nodes = {
            "a": {
                "id": "a",
                "label": "description_field",
                "entity_type": "CONFIG",
                "properties": {"text": long_a},
            },
            "b": {
                "id": "b",
                "label": "description_field",
                "entity_type": "DOCUMENT",
                "properties": {"text": long_b},
            },
        }
        results = detect_contradictions(nodes)
        assert len(results) == 0

    def test_multiple_contradictions(self):
        nodes = {
            "cfg1": {
                "id": "cfg1",
                "label": "settings",
                "entity_type": "CONFIG",
                "properties": {"timeout": 30, "retries": 3, "mode": "sync"},
            },
            "doc1": {
                "id": "doc1",
                "label": "settings",
                "entity_type": "DOCUMENT",
                "properties": {"timeout": 60, "retries": 5, "mode": "async"},
            },
        }
        results = detect_contradictions(nodes)
        assert len(results) == 3

    def test_case_insensitive_string_no_contradiction(self):
        """'JWT' and 'jwt' are not contradictions (case-insensitive comparison)."""
        nodes = {
            "a": {
                "id": "a",
                "label": "auth_type",
                "entity_type": "CONFIG",
                "properties": {"method": "JWT"},
            },
            "b": {
                "id": "b",
                "label": "auth_type",
                "entity_type": "DOCUMENT",
                "properties": {"method": "jwt"},
            },
        }
        results = detect_contradictions(nodes)
        assert len(results) == 0
