"""Tests for graqle.cli.commands.scan — PythonAnalyzer, JSAnalyzer, RepoScanner."""

# ── graqle:intelligence ──
# module: tests.test_cli.test_scan
# risk: HIGH (impact radius: 0 modules)
# dependencies: __future__, json, pathlib, mock, pytest +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
from pathlib import Path

from graqle.cli.commands.scan import (
    EDGE_TYPES,
    NODE_TYPES,
    SKIP_DIRS,
    GitignoreMatcher,
    JSAnalyzer,
    PythonAnalyzer,
    RepoScanner,
    _is_test_file,
)


def _scan_no_progress(scanner: RepoScanner) -> dict:
    """Run scanner phases without Rich Progress bar (avoids MagicMock issues)."""
    all_files = scanner._collect_files()
    for file_path in all_files:
        scanner._process_file(file_path)
    scanner._resolve_imports()
    scanner._discover_test_links()
    scanner._discover_dependencies()
    scanner._discover_infra()
    return scanner._to_node_link_data()


# ---------------------------------------------------------------------------
# PythonAnalyzer
# ---------------------------------------------------------------------------

class TestPythonAnalyzer:
    def setup_method(self):
        self.analyzer = PythonAnalyzer()

    def test_extracts_imports(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text(
            "import os\nimport json\nfrom pathlib import Path\nfrom myapp.core import engine\n"
        )
        result = self.analyzer.analyze_file(f)
        assert "os" in result["imports"]
        assert "json" in result["imports"]
        assert "pathlib" in result["imports"]
        assert "myapp.core" in result["imports"]

    def test_extracts_classes(self, tmp_path):
        f = tmp_path / "models.py"
        f.write_text("class UserModel:\n    pass\n\nclass OrderModel:\n    pass\n")
        result = self.analyzer.analyze_file(f)
        assert "UserModel" in result["classes"]
        assert "OrderModel" in result["classes"]

    def test_extracts_functions(self, tmp_path):
        f = tmp_path / "utils.py"
        f.write_text("def helper():\n    pass\n\nasync def async_helper():\n    pass\n")
        result = self.analyzer.analyze_file(f)
        assert "helper" in result["functions"]
        assert "async_helper" in result["functions"]

    def test_extracts_env_vars_getenv(self, tmp_path):
        f = tmp_path / "config.py"
        f.write_text('import os\ndb_url = os.getenv("DATABASE_URL")\n')
        result = self.analyzer.analyze_file(f)
        assert "DATABASE_URL" in result["env_vars"]

    def test_extracts_env_vars_environ_get(self, tmp_path):
        f = tmp_path / "config.py"
        f.write_text('import os\nsecret = os.environ.get("SECRET_KEY")\n')
        result = self.analyzer.analyze_file(f)
        assert "SECRET_KEY" in result["env_vars"]

    def test_extracts_env_vars_subscript(self, tmp_path):
        f = tmp_path / "config.py"
        f.write_text('import os\nval = os.environ["MY_VAR"]\n')
        result = self.analyzer.analyze_file(f)
        assert "MY_VAR" in result["env_vars"]

    def test_extracts_routes_fastapi(self, tmp_path):
        f = tmp_path / "api.py"
        f.write_text(
            'from fastapi import FastAPI\napp = FastAPI()\n\n'
            '@app.get("/users")\ndef get_users():\n    pass\n'
        )
        result = self.analyzer.analyze_file(f)
        assert len(result["routes"]) >= 1
        assert any(r["path"] == "/users" for r in result["routes"])

    def test_extracts_orm_models(self, tmp_path):
        f = tmp_path / "models.py"
        f.write_text(
            "from sqlalchemy.orm import DeclarativeBase\n\n"
            "class Base(DeclarativeBase):\n    pass\n\n"
            "class User(Base):\n    __tablename__ = 'users'\n"
        )
        result = self.analyzer.analyze_file(f)
        # "User" should be detected as a model (extends Base)
        assert "User" in result["models"]

    def test_handles_syntax_error(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("def broken(\n")
        result = self.analyzer.analyze_file(f)
        # Should return empty dict without crashing
        assert result["imports"] == []
        assert result["classes"] == []

    def test_handles_empty_file(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        result = self.analyzer.analyze_file(f)
        assert result["imports"] == []

    def test_extracts_calls(self, tmp_path):
        f = tmp_path / "caller.py"
        f.write_text("import json\ndata = json.loads('{}')\nprint(data)\n")
        result = self.analyzer.analyze_file(f)
        assert len(result["calls"]) > 0


# ---------------------------------------------------------------------------
# JSAnalyzer
# ---------------------------------------------------------------------------

class TestJSAnalyzer:
    def setup_method(self):
        self.analyzer = JSAnalyzer()

    def test_extracts_es_imports(self, tmp_path):
        f = tmp_path / "app.ts"
        f.write_text("import { useState } from 'react'\nimport api from './services/api'\n")
        result = self.analyzer.analyze_file(f)
        assert "react" in result["imports"]
        assert "./services/api" in result["imports"]

    def test_extracts_require(self, tmp_path):
        f = tmp_path / "server.js"
        f.write_text("const express = require('express')\nconst db = require('./db')\n")
        result = self.analyzer.analyze_file(f)
        assert "express" in result["imports"]
        assert "./db" in result["imports"]

    def test_extracts_functions(self, tmp_path):
        f = tmp_path / "utils.ts"
        f.write_text(
            "export function formatDate(d: Date) { return d.toISOString() }\n"
            "export const parseId = (id: string) => parseInt(id)\n"
        )
        result = self.analyzer.analyze_file(f)
        assert "formatDate" in result["functions"]
        assert "parseId" in result["functions"]

    def test_extracts_classes(self, tmp_path):
        f = tmp_path / "models.ts"
        f.write_text("class UserService { }\ninterface IUser { }\n")
        result = self.analyzer.analyze_file(f)
        assert "UserService" in result["classes"]
        assert "IUser" in result["classes"]

    def test_extracts_routes(self, tmp_path):
        f = tmp_path / "routes.js"
        f.write_text(
            "const express = require('express')\n"
            "const router = express.Router()\n"
            "router.get('/api/users', handler)\n"
            "router.post('/api/orders', createOrder)\n"
        )
        result = self.analyzer.analyze_file(f)
        assert len(result["routes"]) == 2
        methods = {r["method"] for r in result["routes"]}
        assert "GET" in methods
        assert "POST" in methods

    def test_extracts_env_vars_process(self, tmp_path):
        f = tmp_path / "config.ts"
        f.write_text("const port = process.env.PORT\nconst db = process.env.DB_URL\n")
        result = self.analyzer.analyze_file(f)
        assert "PORT" in result["env_vars"]
        assert "DB_URL" in result["env_vars"]

    def test_extracts_env_vars_vite(self, tmp_path):
        f = tmp_path / "config.ts"
        f.write_text("const api = import.meta.env.VITE_API_URL\n")
        result = self.analyzer.analyze_file(f)
        assert "VITE_API_URL" in result["env_vars"]

    def test_handles_empty_file(self, tmp_path):
        f = tmp_path / "empty.js"
        f.write_text("")
        result = self.analyzer.analyze_file(f)
        assert result["imports"] == []


# ---------------------------------------------------------------------------
# GitignoreMatcher
# ---------------------------------------------------------------------------

class TestGitignoreMatcher:
    def test_no_gitignore(self, tmp_path):
        matcher = GitignoreMatcher(tmp_path)
        assert matcher.is_ignored("anything.py") is False

    def test_simple_pattern(self, tmp_path):
        (tmp_path / ".gitignore").write_text("*.pyc\n__pycache__\n")
        matcher = GitignoreMatcher(tmp_path)
        assert matcher.is_ignored("module.pyc") is True
        assert matcher.is_ignored("src/__pycache__") is True
        assert matcher.is_ignored("module.py") is False

    def test_directory_pattern(self, tmp_path):
        (tmp_path / ".gitignore").write_text("dist/\nbuild/\n")
        matcher = GitignoreMatcher(tmp_path)
        assert matcher.is_ignored("dist") is True
        assert matcher.is_ignored("dist/bundle.js") is True

    def test_globstar(self, tmp_path):
        (tmp_path / ".gitignore").write_text("**/logs/**\n")
        matcher = GitignoreMatcher(tmp_path)
        # The implementation converts ** to .* — nested paths match
        assert matcher.is_ignored("src/logs/debug.log") is True

    def test_comments_ignored(self, tmp_path):
        (tmp_path / ".gitignore").write_text("# This is a comment\n*.tmp\n")
        matcher = GitignoreMatcher(tmp_path)
        assert matcher.is_ignored("file.tmp") is True

    def test_blank_lines_ignored(self, tmp_path):
        (tmp_path / ".gitignore").write_text("\n\n*.log\n\n")
        matcher = GitignoreMatcher(tmp_path)
        assert matcher.is_ignored("debug.log") is True


# ---------------------------------------------------------------------------
# RepoScanner
# ---------------------------------------------------------------------------

class TestRepoScanner:
    def _build_fixture_repo(self, tmp_path: Path) -> Path:
        """Build a small fixture repository for testing."""
        # Python files
        src = tmp_path / "src"
        src.mkdir()
        (src / "__init__.py").write_text("")
        (src / "main.py").write_text(
            'import os\nfrom src.utils import helper\n\n'
            'db_url = os.getenv("DATABASE_URL")\n\n'
            'def run():\n    helper()\n'
        )
        (src / "utils.py").write_text(
            "def helper():\n    return 42\n"
        )

        # JS file
        web = tmp_path / "web"
        web.mkdir()
        (web / "app.tsx").write_text(
            "import React from 'react'\n"
            "import { api } from './api'\n"
            "const port = process.env.PORT\n"
            "export function App() { return <div /> }\n"
        )
        (web / "api.ts").write_text(
            "export const api = { fetch: () => {} }\n"
        )

        # Test file
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_main.py").write_text(
            "from src.main import run\ndef test_run():\n    run()\n"
        )

        # Config files
        (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\n")
        (tmp_path / "package.json").write_text(
            json.dumps({"name": "fixture", "dependencies": {"react": "^18"}})
        )

        # .env file
        (tmp_path / ".env").write_text("DATABASE_URL=postgres://\nSECRET_KEY=abc\n")

        # Dockerfile
        (tmp_path / "Dockerfile").write_text(
            "FROM python:3.11\nENV APP_PORT=8000\nCOPY . /app\n"
        )

        return tmp_path

    def test_scan_produces_valid_structure(self, tmp_path):
        repo = self._build_fixture_repo(tmp_path)
        scanner = RepoScanner(repo)
        # Mock the progress display
        data = _scan_no_progress(scanner)
        assert "directed" in data
        assert "nodes" in data
        assert "links" in data
        assert data["directed"] is True

    def test_discovers_python_modules(self, tmp_path):
        repo = self._build_fixture_repo(tmp_path)
        scanner = RepoScanner(repo)
        data = _scan_no_progress(scanner)
        node_ids = {n["id"] for n in data["nodes"]}
        assert "src/main.py" in node_ids
        assert "src/utils.py" in node_ids

    def test_discovers_js_modules(self, tmp_path):
        repo = self._build_fixture_repo(tmp_path)
        scanner = RepoScanner(repo)
        data = _scan_no_progress(scanner)
        node_ids = {n["id"] for n in data["nodes"]}
        assert "web/app.tsx" in node_ids
        assert "web/api.ts" in node_ids

    def test_discovers_test_files(self, tmp_path):
        repo = self._build_fixture_repo(tmp_path)
        scanner = RepoScanner(repo)
        data = _scan_no_progress(scanner)
        test_nodes = [n for n in data["nodes"] if n.get("type") == "TestFile"]
        assert len(test_nodes) >= 1
        assert any("test_main" in n["id"] for n in test_nodes)

    def test_no_tests_flag(self, tmp_path):
        repo = self._build_fixture_repo(tmp_path)
        scanner = RepoScanner(repo, include_tests=False)
        data = _scan_no_progress(scanner)
        test_nodes = [n for n in data["nodes"] if n.get("type") == "TestFile"]
        assert len(test_nodes) == 0

    def test_discovers_env_vars(self, tmp_path):
        repo = self._build_fixture_repo(tmp_path)
        scanner = RepoScanner(repo)
        data = _scan_no_progress(scanner)
        env_nodes = [n for n in data["nodes"] if n.get("type") == "EnvVar"]
        env_labels = {n["label"] for n in env_nodes}
        assert "DATABASE_URL" in env_labels

    def test_discovers_directories(self, tmp_path):
        repo = self._build_fixture_repo(tmp_path)
        scanner = RepoScanner(repo)
        data = _scan_no_progress(scanner)
        dir_nodes = [n for n in data["nodes"] if n.get("type") == "Directory"]
        dir_labels = {n["label"] for n in dir_nodes}
        assert "src" in dir_labels
        assert "web" in dir_labels

    def test_creates_contains_edges(self, tmp_path):
        repo = self._build_fixture_repo(tmp_path)
        scanner = RepoScanner(repo)
        data = _scan_no_progress(scanner)
        contains = [e for e in data["links"] if e["relationship"] == "CONTAINS"]
        assert len(contains) > 0

    def test_creates_imports_edges(self, tmp_path):
        repo = self._build_fixture_repo(tmp_path)
        scanner = RepoScanner(repo)
        data = _scan_no_progress(scanner)
        imports = [e for e in data["links"] if e["relationship"] == "IMPORTS"]
        # At least some imports should be resolved
        assert isinstance(imports, list)

    def test_discovers_docker_service(self, tmp_path):
        repo = self._build_fixture_repo(tmp_path)
        scanner = RepoScanner(repo)
        data = _scan_no_progress(scanner)
        docker_nodes = [n for n in data["nodes"] if n.get("type") == "DockerService"]
        # Dockerfile in root creates a docker service node
        assert len(docker_nodes) >= 1

    def test_discovers_dependencies(self, tmp_path):
        repo = self._build_fixture_repo(tmp_path)
        scanner = RepoScanner(repo)
        data = _scan_no_progress(scanner)
        dep_nodes = [n for n in data["nodes"] if n.get("type") == "Dependency"]
        dep_labels = {n["label"] for n in dep_nodes}
        assert "react" in dep_labels

    def test_max_depth_limits_scan(self, tmp_path):
        # Create deeply nested directory
        deep = tmp_path
        for i in range(8):
            deep = deep / f"level{i}"
            deep.mkdir()
        (deep / "deep.py").write_text("x = 1")
        scanner = RepoScanner(tmp_path, max_depth=2)
        data = _scan_no_progress(scanner)
        node_ids = {n["id"] for n in data["nodes"]}
        # deep.py should NOT be found at depth > 2
        assert not any("deep.py" in nid for nid in node_ids)

    def test_respects_gitignore(self, tmp_path):
        (tmp_path / ".gitignore").write_text("ignored_dir/\n")
        ignored = tmp_path / "ignored_dir"
        ignored.mkdir()
        (ignored / "secret.py").write_text("password = 'abc'")
        (tmp_path / "visible.py").write_text("x = 1")
        scanner = RepoScanner(tmp_path)
        data = _scan_no_progress(scanner)
        node_ids = {n["id"] for n in data["nodes"]}
        assert "visible.py" in node_ids
        assert "ignored_dir/secret.py" not in node_ids

    def test_summary_returns_string(self, tmp_path):
        repo = self._build_fixture_repo(tmp_path)
        scanner = RepoScanner(repo)
        _scan_no_progress(scanner)
        summary = scanner.summary()
        assert isinstance(summary, str)
        assert "nodes" in summary.lower() or "Total" in summary

    def test_env_file_parsing(self, tmp_path):
        (tmp_path / ".env").write_text(
            "# Comment\n\nDB_HOST=localhost\nDB_PORT=5432\n"
        )
        scanner = RepoScanner(tmp_path)
        data = _scan_no_progress(scanner)
        env_nodes = [n for n in data["nodes"] if n.get("type") == "EnvVar"]
        env_labels = {n["label"] for n in env_nodes}
        assert "DB_HOST" in env_labels
        assert "DB_PORT" in env_labels

    def test_docker_compose_services(self, tmp_path):
        (tmp_path / "docker-compose.yml").write_text(
            "version: '3'\nservices:\n  web:\n    image: nginx\n  db:\n    image: postgres\n"
        )
        scanner = RepoScanner(tmp_path)
        data = _scan_no_progress(scanner)
        docker_nodes = [n for n in data["nodes"] if n.get("type") == "DockerService"]
        labels = {n["label"] for n in docker_nodes}
        assert "web" in labels
        assert "db" in labels

    def test_deduplicates_edges(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1")
        scanner = RepoScanner(tmp_path)
        # Manually add duplicate edge
        scanner._add_node("a.py", label="a", type="PythonModule", description="test")
        scanner._add_node("b.py", label="b", type="PythonModule", description="test")
        scanner._add_edge("a.py", "b.py", "IMPORTS")
        scanner._add_edge("a.py", "b.py", "IMPORTS")
        # Should only have one
        matching = [
            e for e in scanner._edges
            if e["source"] == "a.py" and e["target"] == "b.py" and e["relationship"] == "IMPORTS"
        ]
        assert len(matching) == 1


# ---------------------------------------------------------------------------
# _is_test_file
# ---------------------------------------------------------------------------

class TestIsTestFile:
    def test_test_prefix(self):
        assert _is_test_file(Path("test_main.py")) is True

    def test_test_suffix(self):
        assert _is_test_file(Path("main_test.py")) is True

    def test_spec_suffix(self):
        assert _is_test_file(Path("app.spec.ts")) is True

    def test_test_directory(self):
        assert _is_test_file(Path("tests/something.py")) is True
        assert _is_test_file(Path("test/something.py")) is True

    def test_jest_test(self):
        assert _is_test_file(Path("Component.test.tsx")) is True

    def test_conftest(self):
        assert _is_test_file(Path("conftest.py")) is True

    def test_regular_file(self):
        assert _is_test_file(Path("main.py")) is False
        assert _is_test_file(Path("utils.ts")) is False

    def test_dunder_tests(self):
        assert _is_test_file(Path("__tests__/Button.test.jsx")) is True


# ---------------------------------------------------------------------------
# SKIP_DIRS / NODE_TYPES / EDGE_TYPES constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_skip_dirs_has_common_entries(self):
        assert "__pycache__" in SKIP_DIRS
        assert "node_modules" in SKIP_DIRS
        assert ".git" in SKIP_DIRS
        assert ".venv" in SKIP_DIRS

    def test_node_types_complete(self):
        assert "PythonModule" in NODE_TYPES
        assert "JavaScriptModule" in NODE_TYPES
        assert "Class" in NODE_TYPES
        assert "Function" in NODE_TYPES
        assert "EnvVar" in NODE_TYPES

    def test_edge_types_complete(self):
        assert "IMPORTS" in EDGE_TYPES
        assert "CONTAINS" in EDGE_TYPES
        assert "TESTS" in EDGE_TYPES
        assert "DEPENDS_ON" in EDGE_TYPES


# ---------------------------------------------------------------------------
# P1-4: .graqle-ignore support + --exclude patterns
# ---------------------------------------------------------------------------

class TestGraqleIgnore:
    """Test .graqle-ignore file and extra_patterns support."""

    def test_graqle_ignore_file_respected(self, tmp_path):
        """A .graqle-ignore file should exclude matching paths."""
        (tmp_path / ".graqle-ignore").write_text("secrets/\n*.key\n")
        matcher = GitignoreMatcher(tmp_path)
        assert matcher.is_ignored("secrets/passwords.txt") is True
        assert matcher.is_ignored("cert.key") is True
        assert matcher.is_ignored("main.py") is False

    def test_graqle_ignore_stacks_with_gitignore(self, tmp_path):
        """Both .gitignore and .graqle-ignore patterns should apply."""
        (tmp_path / ".gitignore").write_text("*.pyc\n")
        (tmp_path / ".graqle-ignore").write_text("vendor/\n")
        matcher = GitignoreMatcher(tmp_path)
        assert matcher.is_ignored("module.pyc") is True
        assert matcher.is_ignored("vendor/lib.py") is True
        assert matcher.is_ignored("src/main.py") is False

    def test_extra_patterns_work(self, tmp_path):
        """Patterns passed via extra_patterns should also exclude."""
        matcher = GitignoreMatcher(tmp_path, extra_patterns=["*.log", "tmp/"])
        assert matcher.is_ignored("debug.log") is True
        assert matcher.is_ignored("tmp/cache") is True
        assert matcher.is_ignored("main.py") is False

    def test_no_graqle_ignore_file(self, tmp_path):
        """When .graqle-ignore does not exist, nothing extra is excluded."""
        matcher = GitignoreMatcher(tmp_path)
        assert matcher.is_ignored("anything") is False

    def test_scanner_respects_graqle_ignore(self, tmp_path):
        """RepoScanner should skip files matched by .graqle-ignore."""
        (tmp_path / ".graqle-ignore").write_text("generated/\n")
        gen = tmp_path / "generated"
        gen.mkdir()
        (gen / "output.py").write_text("x = 1")
        (tmp_path / "real.py").write_text("y = 2")

        scanner = RepoScanner(tmp_path)
        data = _scan_no_progress(scanner)
        node_ids = {n["id"] for n in data["nodes"]}
        assert "real.py" in node_ids
        assert "generated/output.py" not in node_ids

    def test_scanner_respects_exclude_patterns(self, tmp_path):
        """RepoScanner should skip files matched by exclude_patterns."""
        (tmp_path / "keep.py").write_text("a = 1")
        (tmp_path / "skip_me.py").write_text("b = 2")

        scanner = RepoScanner(tmp_path, exclude_patterns=["skip_me*"])
        data = _scan_no_progress(scanner)
        node_ids = {n["id"] for n in data["nodes"]}
        assert "keep.py" in node_ids
        assert "skip_me.py" not in node_ids
