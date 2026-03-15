"""Tests for canonical ID computation."""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_dedup.test_canonical
# risk: LOW (impact radius: 0 modules)
# dependencies: canonical
# constraints: none
# ── /graqle:intelligence ──

from graqle.scanner.dedup.canonical import compute_canonical_id


class TestComputeCanonicalId:
    """Tests for compute_canonical_id."""

    def test_function_node(self):
        node = {
            "id": "func::auth.py::verify_token",
            "label": "verify_token",
            "entity_type": "FUNCTION",
            "properties": {"path": "src/auth.py"},
        }
        cid = compute_canonical_id(node)
        assert cid is not None
        assert len(cid) == 16

    def test_same_function_same_id(self):
        """Same function produces the same canonical ID regardless of node id."""
        node_a = {
            "id": "func::a",
            "label": "verify_token",
            "entity_type": "FUNCTION",
            "properties": {"path": "src/auth.py"},
        }
        node_b = {
            "id": "func::b",
            "label": "verify_token",
            "entity_type": "FUNCTION",
            "properties": {"path": "src/auth.py"},
        }
        assert compute_canonical_id(node_a) == compute_canonical_id(node_b)

    def test_different_functions_different_ids(self):
        node_a = {
            "id": "a",
            "label": "verify_token",
            "entity_type": "FUNCTION",
            "properties": {"path": "src/auth.py"},
        }
        node_b = {
            "id": "b",
            "label": "login",
            "entity_type": "FUNCTION",
            "properties": {"path": "src/auth.py"},
        }
        assert compute_canonical_id(node_a) != compute_canonical_id(node_b)

    def test_function_no_path_returns_none(self):
        node = {
            "id": "x",
            "label": "verify_token",
            "entity_type": "FUNCTION",
            "properties": {},
        }
        assert compute_canonical_id(node) is None

    def test_endpoint_node(self):
        node = {
            "id": "ep1",
            "label": "POST /api/login",
            "entity_type": "ENDPOINT",
            "properties": {"method": "POST", "route": "/api/login"},
        }
        cid = compute_canonical_id(node)
        assert cid is not None
        assert len(cid) == 16

    def test_endpoint_no_method_returns_none(self):
        node = {
            "id": "ep1",
            "label": "login",
            "entity_type": "ENDPOINT",
            "properties": {"route": "/api/login"},
        }
        assert compute_canonical_id(node) is None

    def test_config_node(self):
        node = {
            "id": "cfg1",
            "label": "token_expiry",
            "entity_type": "CONFIG",
            "properties": {"source": "config/auth.json", "key": "token_expiry"},
        }
        cid = compute_canonical_id(node)
        assert cid is not None

    def test_config_no_source_returns_none(self):
        node = {
            "id": "cfg1",
            "label": "token_expiry",
            "entity_type": "CONFIG",
            "properties": {"key": "token_expiry"},
        }
        assert compute_canonical_id(node) is None

    def test_dependency_node(self):
        node = {
            "id": "dep1",
            "label": "react",
            "entity_type": "DEPENDENCY",
            "properties": {"manager": "npm"},
        }
        cid = compute_canonical_id(node)
        assert cid is not None

    def test_dependency_no_manager_returns_none(self):
        node = {
            "id": "dep1",
            "label": "react",
            "entity_type": "DEPENDENCY",
            "properties": {},
        }
        assert compute_canonical_id(node) is None

    def test_document_node(self):
        node = {
            "id": "doc1",
            "label": "architecture.md",
            "entity_type": "DOCUMENT",
            "properties": {"path": "docs/architecture.md"},
        }
        cid = compute_canonical_id(node)
        assert cid is not None

    def test_document_no_path_returns_none(self):
        node = {
            "id": "doc1",
            "label": "architecture.md",
            "entity_type": "DOCUMENT",
            "properties": {},
        }
        assert compute_canonical_id(node) is None

    def test_section_node(self):
        node = {
            "id": "sec1",
            "label": "Auth Layer",
            "entity_type": "SECTION",
            "properties": {"path": "docs/architecture.md"},
        }
        cid = compute_canonical_id(node)
        assert cid is not None

    def test_resource_node(self):
        node = {
            "id": "res1",
            "label": "UsersTable",
            "entity_type": "RESOURCE",
            "properties": {"aws_type": "AWS::DynamoDB::Table"},
        }
        cid = compute_canonical_id(node)
        assert cid is not None

    def test_resource_no_aws_type_returns_none(self):
        node = {
            "id": "res1",
            "label": "UsersTable",
            "entity_type": "RESOURCE",
            "properties": {},
        }
        assert compute_canonical_id(node) is None

    def test_schema_node(self):
        node = {
            "id": "sch1",
            "label": "AuthResponse",
            "entity_type": "SCHEMA",
            "properties": {},
        }
        cid = compute_canonical_id(node)
        assert cid is not None

    def test_tool_rule_node(self):
        node = {
            "id": "rule1",
            "label": "strict",
            "entity_type": "TOOL_RULE",
            "properties": {"tool": "typescript", "key": "strict"},
        }
        cid = compute_canonical_id(node)
        assert cid is not None

    def test_tool_rule_no_tool_returns_none(self):
        node = {
            "id": "rule1",
            "label": "strict",
            "entity_type": "TOOL_RULE",
            "properties": {},
        }
        assert compute_canonical_id(node) is None

    def test_script_node(self):
        node = {
            "id": "scr1",
            "label": "build",
            "entity_type": "SCRIPT",
            "properties": {"manager": "npm"},
        }
        cid = compute_canonical_id(node)
        assert cid is not None

    def test_unknown_type_returns_none(self):
        node = {
            "id": "x",
            "label": "something",
            "entity_type": "UNKNOWN_TYPE",
            "properties": {},
        }
        assert compute_canonical_id(node) is None

    def test_class_node(self):
        node = {
            "id": "cls1",
            "label": "AuthService",
            "entity_type": "CLASS",
            "properties": {"path": "src/auth.py"},
        }
        cid = compute_canonical_id(node)
        assert cid is not None

    def test_module_node(self):
        node = {
            "id": "mod1",
            "label": "auth",
            "entity_type": "PYTHONMODULE",
            "properties": {"path": "src/auth.py"},
        }
        cid = compute_canonical_id(node)
        assert cid is not None
