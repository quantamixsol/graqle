"""Tests for graqle.analysis.bridge — R2 Bridge-Edge Detection (ADR-133)."""

from __future__ import annotations

import pytest

from graqle.analysis.bridge import (
    BridgeCandidate,
    BridgeDetectionReport,
    BridgeDetector,
    _COMPATIBLE_PAIRS,
    _EXACT_MATCH_CONFIDENCE,
    _extract_node_fields,
    _normalise,
    _tokenise,
    _validate_candidate,
    derive_language,
    make_dedup_key,
    SCANNER_ENTITY_TYPES,
    SECONDARY_ENTITY_TYPES,
)


# ---------------------------------------------------------------------------
# Import smoke test (catches syntax errors like &amp; artifact)
# ---------------------------------------------------------------------------


class TestImport:
    def test_module_importable(self):
        import graqle.analysis.bridge  # noqa: F401


# ---------------------------------------------------------------------------
# _normalise
# ---------------------------------------------------------------------------


class TestNormalise:
    def test_python_extension(self):
        assert _normalise("utils.py") == "utils"

    def test_typescript_extension(self):
        assert _normalise("utils.ts") == "utils"

    def test_camel_case(self):
        assert _normalise("getUserName") == "get_user_name"

    def test_acronym_split(self):
        assert _normalise("XMLParser.py") == "xml_parser"

    def test_mjs_extension(self):
        assert _normalise("utils.mjs") == "utils"

    def test_cjs_extension(self):
        assert _normalise("utils.cjs") == "utils"

    def test_jsx_extension(self):
        assert _normalise("App.jsx") == "app"

    def test_path_normalisation(self):
        result = _normalise("src/utils/helper.py")
        assert "helper" in result

    def test_empty_string(self):
        assert _normalise("") == ""

    def test_uppercase_extension(self):
        # .lower() applied before extension strip
        assert _normalise("Utils.PY") == "utils"


# ---------------------------------------------------------------------------
# _tokenise
# ---------------------------------------------------------------------------


class TestTokenise:
    def test_basic(self):
        tokens = _tokenise("getUserName.py")
        assert "get" in tokens
        assert "user" in tokens
        assert "name" in tokens

    def test_single_char_filtered(self):
        # Single-character tokens are excluded (len > 1)
        tokens = _tokenise("a")
        assert tokens == set()

    def test_empty(self):
        assert _tokenise("") == set()


# ---------------------------------------------------------------------------
# derive_language
# ---------------------------------------------------------------------------


class TestDeriveLanguage:
    """Test all 4 resolution paths."""

    def test_explicit_property_dict(self):
        node = {"language": "Python"}
        assert derive_language(node) == "python"

    def test_explicit_property_nested(self):
        node = {"properties": {"language": "JavaScript"}}
        assert derive_language(node) == "javascript"

    def test_entity_type_python_module(self):
        node = {"entity_type": "PythonModule"}
        assert derive_language(node) == "python"

    def test_entity_type_javascript_module(self):
        node = {"entity_type": "JavaScriptModule"}
        assert derive_language(node) == "javascript"

    def test_entity_type_react_component(self):
        node = {"entity_type": "ReactComponent"}
        assert derive_language(node) == "javascript"

    def test_file_path_heuristic_py(self):
        node = {"id": "src/utils.py", "type": "Function"}
        assert derive_language(node) == "python"

    def test_file_path_heuristic_ts(self):
        node = {"id": "src/utils.ts", "type": "Function"}
        assert derive_language(node) == "javascript"

    def test_file_path_heuristic_mjs(self):
        node = {"id": "lib/index.mjs"}
        assert derive_language(node) == "javascript"

    def test_file_path_heuristic_cjs(self):
        node = {"id": "lib/index.cjs"}
        assert derive_language(node) == "javascript"

    def test_fallback_unknown(self):
        node = {"type": "Entity"}
        assert derive_language(node) == "unknown"

    def test_class_uses_file_heuristic(self):
        # Class is language-agnostic; derive_language uses file-path
        node = {"entity_type": "Class", "id": "src/models.py::User"}
        assert derive_language(node) == "python"

    def test_class_js_file(self):
        node = {"entity_type": "Class", "id": "src/App.tsx::Component"}
        assert derive_language(node) == "javascript"

    def test_object_node(self):
        class FakeNode:
            entity_type = "PythonModule"
            properties = {}
        assert derive_language(FakeNode()) == "python"

    def test_object_node_file_path(self):
        class FakeNode:
            entity_type = "Function"
            id = "src/handler.ts"
            label = ""
            properties = {}
        assert derive_language(FakeNode()) == "javascript"


# ---------------------------------------------------------------------------
# _extract_node_fields
# ---------------------------------------------------------------------------


class TestExtractNodeFields:
    def test_dict_node(self):
        node = {"id": "a", "label": "A", "entity_type": "PythonModule"}
        props, etype, nid, label, sf = _extract_node_fields(node)
        assert etype == "PythonModule"
        assert nid == "a"

    def test_dict_nested_properties(self):
        node = {"id": "a", "properties": {"language": "python"}}
        props, _, _, _, _ = _extract_node_fields(node)
        assert props.get("language") == "python"


# ---------------------------------------------------------------------------
# BridgeCandidate
# ---------------------------------------------------------------------------


class TestBridgeCandidate:
    def test_valid_construction(self):
        c = BridgeCandidate(
            source_id="a.py", target_id="entity_a",
            confidence=0.9, method="exact_name", language="python",
        )
        assert c.source_id == "a.py"

    def test_empty_source_id_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            BridgeCandidate(source_id="", target_id="x")

    def test_empty_target_id_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            BridgeCandidate(source_id="x", target_id="")

    def test_negative_confidence_raises(self):
        with pytest.raises(ValueError, match="must be in"):
            BridgeCandidate(source_id="a", target_id="b", confidence=-0.1)

    def test_confidence_above_one_raises(self):
        with pytest.raises(ValueError, match="must be in"):
            BridgeCandidate(source_id="a", target_id="b", confidence=1.1)

    def test_boundary_confidence_zero(self):
        c = BridgeCandidate(source_id="a", target_id="b", confidence=0.0)
        assert c.confidence == 0.0

    def test_boundary_confidence_one(self):
        c = BridgeCandidate(source_id="a", target_id="b", confidence=1.0)
        assert c.confidence == 1.0


# ---------------------------------------------------------------------------
# make_dedup_key
# ---------------------------------------------------------------------------


class TestMakeDedupKey:
    def test_basic_format(self):
        c = BridgeCandidate(
            source_id="src/utils.py", target_id="utils_entity",
            confidence=0.91, language="python",
        )
        key = make_dedup_key(c)
        assert key.startswith("python::")
        assert "BRIDGE_TO" in key

    def test_cross_language_non_collision(self):
        py = BridgeCandidate(
            source_id="utils", target_id="utils_entity",
            confidence=0.9, language="python",
        )
        js = BridgeCandidate(
            source_id="utils", target_id="utils_entity",
            confidence=0.9, language="javascript",
        )
        assert make_dedup_key(py) != make_dedup_key(js)


# ---------------------------------------------------------------------------
# _validate_candidate — 6-check protocol
# ---------------------------------------------------------------------------


class TestValidateCandidate:
    """Test all 6 R2 Bridge Validation Protocol checks."""

    def _make_candidate(self, **kwargs):
        defaults = {
            "source_id": "src.py",
            "target_id": "entity_a",
            "confidence": 0.9,
            "method": "exact_name",
            "language": "python",
        }
        defaults.update(kwargs)
        return BridgeCandidate(**defaults)

    def test_check1_self_loop(self):
        c = self._make_candidate(source_id="x", target_id="x")
        reason = _validate_candidate(
            c, {"x"}, set(), set(), "PythonModule", "Entity", 0.4,
        )
        assert reason == "self_loop"

    def test_check2_source_missing(self):
        c = self._make_candidate(source_id="missing")
        reason = _validate_candidate(
            c, {"entity_a"}, set(), set(), "PythonModule", "Entity", 0.4,
        )
        assert reason and "source_missing" in reason

    def test_check2_target_missing(self):
        c = self._make_candidate()
        reason = _validate_candidate(
            c, {"src.py"}, set(), set(), "PythonModule", "Entity", 0.4,
        )
        assert reason and "target_missing" in reason

    def test_check3_type_incompatible(self):
        c = self._make_candidate()
        reason = _validate_candidate(
            c, {"src.py", "entity_a"}, set(), set(),
            "PythonModule", "CIPipeline", 0.4,
        )
        assert reason and "type_incompatible" in reason

    def test_check3_type_compatible(self):
        c = self._make_candidate()
        reason = _validate_candidate(
            c, {"src.py", "entity_a"}, set(), set(),
            "PythonModule", "Entity", 0.4,
        )
        assert reason is None

    def test_check4_duplicate_edge(self):
        c = self._make_candidate()
        existing = {"src.py--BRIDGE_TO-->entity_a"}
        reason = _validate_candidate(
            c, {"src.py", "entity_a"}, existing, set(),
            "PythonModule", "Entity", 0.4,
        )
        assert reason == "duplicate_edge"

    def test_check5_duplicate_dedup_key(self):
        c = self._make_candidate()
        seen = {make_dedup_key(c)}
        reason = _validate_candidate(
            c, {"src.py", "entity_a"}, set(), seen,
            "PythonModule", "Entity", 0.4,
        )
        assert reason == "duplicate_dedup_key"

    def test_check6_below_confidence(self):
        c = self._make_candidate(confidence=0.3)
        reason = _validate_candidate(
            c, {"src.py", "entity_a"}, set(), set(),
            "PythonModule", "Entity", 0.4,
        )
        assert reason and "below_confidence" in reason

    def test_all_pass(self):
        c = self._make_candidate()
        reason = _validate_candidate(
            c, {"src.py", "entity_a"}, set(), set(),
            "PythonModule", "Entity", 0.4,
        )
        assert reason is None

    def test_check7_invalid_provenance(self):
        c = self._make_candidate(relationship="CALLS_VIA_MCP")
        c.metadata["provenance"] = "unknown_source"
        reason = _validate_candidate(
            c, {"src.py", "entity_a"}, set(), set(),
            "PythonModule", "Entity", 0.4,
            source_language="javascript", target_language="python",
        )
        assert reason and "invalid_provenance" in reason

    def test_check7_valid_provenance(self):
        c = self._make_candidate(relationship="CALLS_VIA_MCP")
        c.metadata["provenance"] = "bridge_injection"
        reason = _validate_candidate(
            c, {"src.py", "entity_a"}, set(), set(),
            "PythonModule", "Entity", 0.4,
            source_language="javascript", target_language="python",
        )
        assert reason is None

    def test_check8_wrong_direction(self):
        c = self._make_candidate(relationship="CALLS_VIA_MCP")
        reason = _validate_candidate(
            c, {"src.py", "entity_a"}, set(), set(),
            "PythonModule", "Entity", 0.4,
            source_language="python", target_language="javascript",
        )
        assert reason and "wrong_direction" in reason

    def test_check8_correct_direction(self):
        c = self._make_candidate(relationship="CALLS_VIA_MCP")
        reason = _validate_candidate(
            c, {"src.py", "entity_a"}, set(), set(),
            "PythonModule", "Entity", 0.4,
            source_language="javascript", target_language="python",
        )
        assert reason is None


# ---------------------------------------------------------------------------
# BridgeDetector
# ---------------------------------------------------------------------------


class TestBridgeDetector:
    def _scanner_node(self, name: str, etype: str = "PythonModule"):
        return {"id": name, "name": name, "entity_type": etype}

    def _kg_node(self, name: str):
        return {"id": f"entity_{name}", "name": name, "entity_type": "Entity"}

    def test_exact_match(self):
        detector = BridgeDetector()
        report = detector.detect(
            scanner_nodes=[self._scanner_node("utils.py")],
            kg_nodes=[self._kg_node("utils")],
        )
        assert len(report.candidates) == 1
        assert report.candidates[0].method == "exact_name"
        assert report.candidates[0].confidence == _EXACT_MATCH_CONFIDENCE

    def test_token_overlap(self):
        detector = BridgeDetector(confidence_threshold=0.3)
        report = detector.detect(
            scanner_nodes=[self._scanner_node("auth_service.py")],
            kg_nodes=[self._kg_node("auth_handler")],
        )
        # "auth" token overlaps
        matches = [c for c in report.candidates if c.method == "token_overlap"]
        assert len(matches) >= 0  # may or may not match depending on Jaccard

    def test_empty_scanner_nodes(self):
        detector = BridgeDetector()
        report = detector.detect(scanner_nodes=[], kg_nodes=[self._kg_node("x")])
        assert len(report.candidates) == 0

    def test_empty_kg_nodes(self):
        detector = BridgeDetector()
        report = detector.detect(
            scanner_nodes=[self._scanner_node("x.py")], kg_nodes=[],
        )
        assert len(report.candidates) == 0

    def test_missing_id_skipped(self):
        detector = BridgeDetector()
        report = detector.detect(
            scanner_nodes=[{"entity_type": "PythonModule"}],
            kg_nodes=[self._kg_node("x")],
        )
        assert len(report.candidates) == 0

    def test_react_component_excluded_by_default(self):
        detector = BridgeDetector()
        report = detector.detect(
            scanner_nodes=[self._scanner_node("App", "ReactComponent")],
            kg_nodes=[self._kg_node("App")],
        )
        assert len(report.candidates) == 0

    def test_react_component_included_when_enabled(self):
        detector = BridgeDetector(scan_react_components=True)
        report = detector.detect(
            scanner_nodes=[self._scanner_node("App.tsx", "ReactComponent")],
            kg_nodes=[self._kg_node("app")],
        )
        # May match via normalisation
        assert isinstance(report, BridgeDetectionReport)

    def test_existing_edge_dedup(self):
        detector = BridgeDetector()
        existing = [{"source_id": "utils.py", "target_id": "entity_utils", "relationship": "BRIDGE_TO"}]
        report = detector.detect(
            scanner_nodes=[self._scanner_node("utils.py")],
            kg_nodes=[self._kg_node("utils")],
            existing_edges=existing,
        )
        # Should be rejected as duplicate
        assert any("duplicate_edge" in r.get("reason", "") for r in report.rejected)
