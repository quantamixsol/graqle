"""Tests for graqle.scanner.json_parser — JSON classifier and scanner."""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_json_parser
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, json, pathlib, pytest, json_parser
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graqle.scanner.json_parser import (
    JSONClassification,
    JSONScanOptions,
    JSONScanResult,
    JSONScanner,
    classify_json,
)


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------


class TestClassifyJSON:
    def test_known_filename_package_json(self, tmp_path: Path) -> None:
        fp = tmp_path / "package.json"
        fp.write_text("{}")
        c = classify_json(fp)
        assert c.category == "DEPENDENCY_MANIFEST"
        assert c.confidence == 1.0

    def test_known_filename_openapi(self, tmp_path: Path) -> None:
        fp = tmp_path / "openapi.json"
        fp.write_text("{}")
        c = classify_json(fp)
        assert c.category == "API_SPEC"

    def test_known_filename_tsconfig(self, tmp_path: Path) -> None:
        fp = tmp_path / "tsconfig.json"
        fp.write_text("{}")
        c = classify_json(fp)
        assert c.category == "TOOL_CONFIG"

    def test_known_filename_skip_lockfile(self, tmp_path: Path) -> None:
        fp = tmp_path / "package-lock.json"
        fp.write_text("{}")
        c = classify_json(fp)
        assert c.category == "SKIP"

    def test_content_openapi_key(self, tmp_path: Path) -> None:
        fp = tmp_path / "api.json"
        data = {"openapi": "3.0.0", "info": {}, "paths": {}}
        c = classify_json(fp, data)
        assert c.category == "API_SPEC"

    def test_content_npm_manifest(self, tmp_path: Path) -> None:
        fp = tmp_path / "manifest.json"
        data = {"dependencies": {"react": "^18"}, "scripts": {"build": "next"}}
        c = classify_json(fp, data)
        assert c.category == "DEPENDENCY_MANIFEST"

    def test_content_typescript_config(self, tmp_path: Path) -> None:
        fp = tmp_path / "ts.json"
        data = {"compilerOptions": {"strict": True}}
        c = classify_json(fp, data)
        assert c.category == "TOOL_CONFIG"

    def test_content_cloudformation(self, tmp_path: Path) -> None:
        fp = tmp_path / "stack.json"
        data = {"AWSTemplateFormatVersion": "2010-09-09", "Resources": {}}
        c = classify_json(fp, data)
        assert c.category == "INFRA_CONFIG"

    def test_content_serverless(self, tmp_path: Path) -> None:
        fp = tmp_path / "sls.json"
        data = {"service": "my-api", "provider": {}, "functions": {}}
        c = classify_json(fp, data)
        assert c.category == "INFRA_CONFIG"

    def test_content_pipfile(self, tmp_path: Path) -> None:
        fp = tmp_path / "deps.json"
        data = {"packages": {"flask": "*"}}
        c = classify_json(fp, data)
        assert c.category == "DEPENDENCY_MANIFEST"

    def test_schema_file_pattern(self, tmp_path: Path) -> None:
        fp = tmp_path / "user.schema.json"
        fp.write_text("{}")
        c = classify_json(fp)
        assert c.category == "SCHEMA_FILE"

    def test_default_app_config(self, tmp_path: Path) -> None:
        fp = tmp_path / "settings.json"
        fp.write_text('{"debug": true}')
        data = {"debug": True}
        c = classify_json(fp, data)
        assert c.category == "APP_CONFIG"

    def test_no_data_unknown(self, tmp_path: Path) -> None:
        fp = tmp_path / "random.json"
        fp.write_text("{}")
        c = classify_json(fp)
        assert c.category == "UNKNOWN"

    def test_rules_key_tool_config(self, tmp_path: Path) -> None:
        fp = tmp_path / "lint.json"
        data = {"rules": {"no-console": "error"}}
        c = classify_json(fp, data)
        assert c.category == "TOOL_CONFIG"

    def test_schema_key(self, tmp_path: Path) -> None:
        fp = tmp_path / "def.json"
        data = {"$schema": "http://json-schema.org/draft-07/schema#"}
        c = classify_json(fp, data)
        assert c.category == "SCHEMA_FILE"


# ---------------------------------------------------------------------------
# JSONScanner tests
# ---------------------------------------------------------------------------


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a minimal project with JSON files."""
    # package.json
    pkg = tmp_path / "package.json"
    pkg.write_text(json.dumps({
        "name": "test-project",
        "dependencies": {"react": "^18.2.0", "next": "^14.0.0"},
        "devDependencies": {"typescript": "^5.0.0"},
        "scripts": {"build": "next build", "dev": "next dev"},
    }))

    # tsconfig.json
    ts = tmp_path / "tsconfig.json"
    ts.write_text(json.dumps({
        "compilerOptions": {
            "strict": True,
            "target": "es2020",
            "module": "esnext",
        }
    }))

    # config dir
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "auth.json").write_text(json.dumps({
        "token_expiry": 3600,
        "algorithm": "RS256",
        "issuer": "my-app",
    }))

    # openapi spec
    api = tmp_path / "openapi.json"
    api.write_text(json.dumps({
        "openapi": "3.0.0",
        "info": {"title": "My API", "version": "1.0.0"},
        "paths": {
            "/api/auth/login": {
                "post": {
                    "summary": "Login",
                    "operationId": "login",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/AuthResponse"}
                                }
                            }
                        }
                    }
                }
            },
            "/api/users": {
                "get": {
                    "summary": "List users",
                    "responses": {"200": {}}
                }
            }
        },
        "components": {
            "schemas": {
                "AuthResponse": {
                    "type": "object",
                    "properties": {
                        "token": {"type": "string"},
                        "user": {"type": "object"},
                    },
                    "required": ["token"],
                }
            }
        }
    }))

    # lockfile (should be skipped)
    lock = tmp_path / "package-lock.json"
    lock.write_text(json.dumps({"lockfileVersion": 3}))

    return tmp_path


class TestJSONScanner:
    def test_scan_finds_files(self, project_dir: Path) -> None:
        nodes: dict = {}
        edges: dict = {}
        scanner = JSONScanner(nodes, edges)
        result = scanner.scan_directory(project_dir)
        assert result.files_scanned >= 3  # package.json, tsconfig, auth.json, openapi

    def test_lockfile_skipped(self, project_dir: Path) -> None:
        nodes: dict = {}
        edges: dict = {}
        scanner = JSONScanner(nodes, edges)
        result = scanner.scan_directory(project_dir)
        # package-lock.json should be skipped
        node_ids = list(nodes.keys())
        assert not any("package-lock" in nid for nid in node_ids)

    def test_dependency_nodes_created(self, project_dir: Path) -> None:
        nodes: dict = {}
        edges: dict = {}
        scanner = JSONScanner(nodes, edges)
        scanner.scan_directory(project_dir)
        dep_nodes = [n for n in nodes.values() if n["entity_type"] == "DEPENDENCY"]
        assert len(dep_nodes) >= 3  # react, next, typescript

    def test_script_nodes_created(self, project_dir: Path) -> None:
        nodes: dict = {}
        edges: dict = {}
        scanner = JSONScanner(nodes, edges)
        scanner.scan_directory(project_dir)
        script_nodes = [n for n in nodes.values() if n["entity_type"] == "SCRIPT"]
        assert len(script_nodes) >= 2  # build, dev

    def test_endpoint_nodes_created(self, project_dir: Path) -> None:
        nodes: dict = {}
        edges: dict = {}
        scanner = JSONScanner(nodes, edges)
        scanner.scan_directory(project_dir)
        endpoints = [n for n in nodes.values() if n["entity_type"] == "ENDPOINT"]
        assert len(endpoints) >= 2  # POST /api/auth/login, GET /api/users

    def test_schema_nodes_created(self, project_dir: Path) -> None:
        nodes: dict = {}
        edges: dict = {}
        scanner = JSONScanner(nodes, edges)
        scanner.scan_directory(project_dir)
        schemas = [n for n in nodes.values() if n["entity_type"] == "SCHEMA"]
        assert len(schemas) >= 1  # AuthResponse

    def test_tool_rule_nodes_created(self, project_dir: Path) -> None:
        nodes: dict = {}
        edges: dict = {}
        scanner = JSONScanner(nodes, edges)
        scanner.scan_directory(project_dir)
        rules = [n for n in nodes.values() if n["entity_type"] == "TOOL_RULE"]
        assert len(rules) >= 2  # strict, target, module

    def test_config_nodes_created(self, project_dir: Path) -> None:
        nodes: dict = {}
        edges: dict = {}
        scanner = JSONScanner(nodes, edges)
        scanner.scan_directory(project_dir)
        configs = [n for n in nodes.values() if n["entity_type"] == "CONFIG"]
        assert len(configs) >= 1  # auth config values

    def test_depends_on_edges(self, project_dir: Path) -> None:
        nodes: dict = {}
        edges: dict = {}
        scanner = JSONScanner(nodes, edges)
        scanner.scan_directory(project_dir)
        dep_edges = [e for e in edges.values() if e["relationship"] == "DEPENDS_ON"]
        assert len(dep_edges) >= 3

    def test_returns_edge_for_endpoint(self, project_dir: Path) -> None:
        nodes: dict = {}
        edges: dict = {}
        scanner = JSONScanner(nodes, edges)
        scanner.scan_directory(project_dir)
        returns_edges = [e for e in edges.values() if e["relationship"] == "RETURNS"]
        assert len(returns_edges) >= 1

    def test_json_file_nodes_created(self, project_dir: Path) -> None:
        nodes: dict = {}
        edges: dict = {}
        scanner = JSONScanner(nodes, edges)
        scanner.scan_directory(project_dir)
        json_nodes = [n for n in nodes if n.startswith("json::")]
        assert len(json_nodes) >= 3

    def test_categories_found(self, project_dir: Path) -> None:
        nodes: dict = {}
        edges: dict = {}
        scanner = JSONScanner(nodes, edges)
        result = scanner.scan_directory(project_dir)
        assert "DEPENDENCY_MANIFEST" in result.categories_found
        assert "API_SPEC" in result.categories_found

    def test_scan_single_file(self, project_dir: Path) -> None:
        nodes: dict = {}
        edges: dict = {}
        scanner = JSONScanner(nodes, edges)
        result = scanner.scan_file(project_dir / "package.json")
        assert result.files_scanned == 1
        assert result.nodes_added >= 4  # 3 deps + 2 scripts + json file node

    def test_empty_directory(self, tmp_path: Path) -> None:
        nodes: dict = {}
        edges: dict = {}
        scanner = JSONScanner(nodes, edges)
        result = scanner.scan_directory(tmp_path)
        assert result.files_scanned == 0
        assert result.nodes_added == 0

    def test_invalid_json_errored(self, tmp_path: Path) -> None:
        (tmp_path / "bad.json").write_text("not valid json{{{")
        nodes: dict = {}
        edges: dict = {}
        scanner = JSONScanner(nodes, edges)
        result = scanner.scan_directory(tmp_path)
        assert result.files_errored >= 1

    def test_progress_callback(self, project_dir: Path) -> None:
        nodes: dict = {}
        edges: dict = {}
        scanner = JSONScanner(nodes, edges)
        calls = []
        scanner.scan_directory(project_dir, progress_callback=lambda fp, i, t: calls.append(i))
        assert len(calls) > 0

    def test_category_disabled(self, project_dir: Path) -> None:
        nodes: dict = {}
        edges: dict = {}
        opts = JSONScanOptions(categories={
            "DEPENDENCY_MANIFEST": False,  # disable deps
            "API_SPEC": True,
            "TOOL_CONFIG": True,
            "APP_CONFIG": True,
            "INFRA_CONFIG": True,
            "SCHEMA_FILE": True,
            "DATA_FILE": False,
        })
        scanner = JSONScanner(nodes, edges, options=opts)
        scanner.scan_directory(project_dir)
        dep_nodes = [n for n in nodes.values() if n["entity_type"] == "DEPENDENCY"]
        assert len(dep_nodes) == 0

    def test_node_modules_skipped(self, project_dir: Path) -> None:
        nm = project_dir / "node_modules" / "react"
        nm.mkdir(parents=True)
        (nm / "package.json").write_text(json.dumps({"name": "react"}))
        nodes: dict = {}
        edges: dict = {}
        scanner = JSONScanner(nodes, edges)
        scanner.scan_directory(project_dir)
        nm_nodes = [n for n in nodes if "node_modules" in n]
        assert len(nm_nodes) == 0

    def test_duration_recorded(self, project_dir: Path) -> None:
        nodes: dict = {}
        edges: dict = {}
        scanner = JSONScanner(nodes, edges)
        result = scanner.scan_directory(project_dir)
        assert result.duration_seconds >= 0
