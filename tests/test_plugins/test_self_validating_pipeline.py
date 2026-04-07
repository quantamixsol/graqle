"""Tests for self-validating generate pipeline (AUTONOMY-100-BLUEPRINT).

GAP 1: _validate_syntax (ast.parse)
GAP 2: _validate_diff_context + _reanchor_diff (difflib)
GAP 3: _build_correction_prompt (error feedback)
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from graqle.plugins.mcp_dev_server import KogniDevServer


@pytest.fixture
def server(tmp_path):
    srv = KogniDevServer.__new__(KogniDevServer)
    srv._graph = MagicMock()
    srv._graph.nodes = {}
    srv._graph_file = str(tmp_path / "graqle.json")
    srv._session_cache = {}
    return srv


# ---------------------------------------------------------------------------
# GAP 1: _extract_code_from_response
# ---------------------------------------------------------------------------

class TestExtractCode:
    def test_strips_markdown_fences(self, server):
        raw = "```python\ndef foo():\n    pass\n```"
        result = server._extract_code_from_response(raw, "generate")
        assert "```" not in result
        assert "def foo():" in result

    def test_plain_code_unchanged(self, server):
        raw = "def bar():\n    return 42"
        result = server._extract_code_from_response(raw, "generate")
        assert result == raw

    def test_empty_input(self, server):
        result = server._extract_code_from_response("", "generate")
        assert result == ""


# ---------------------------------------------------------------------------
# GAP 1: _validate_syntax
# ---------------------------------------------------------------------------

class TestValidateSyntax:
    def test_valid_python_passes(self, server):
        code = "def foo():\n    return 42\n"
        result = server._validate_syntax(code, "test.py")
        assert result["valid"] is True
        assert result["errors"] == []

    def test_syntax_error_detected(self, server):
        code = "def foo(\n    return 42\n"
        result = server._validate_syntax(code, "test.py")
        assert result["valid"] is False
        assert len(result["errors"]) > 0
        assert "SyntaxError" in result["errors"][0]

    def test_non_python_skips_validation(self, server):
        code = "this is not python: {yaml: true}"
        result = server._validate_syntax(code, "config.yaml")
        assert result["valid"] is True

    def test_none_file_path_validates(self, server):
        code = "x = 1\ny = 2\n"
        result = server._validate_syntax(code, None)
        assert result["valid"] is True


# ---------------------------------------------------------------------------
# GAP 2: _validate_diff_context
# ---------------------------------------------------------------------------

class TestValidateDiffContext:
    def test_new_file_passes(self, server, tmp_path):
        diff = "@@ -0,0 +1,3 @@\n+def foo():\n+    pass\n"
        result = server._validate_diff_context(diff, str(tmp_path / "new.py"))
        assert result["valid"] is True

    def test_matching_context_passes(self, server, tmp_path):
        f = tmp_path / "existing.py"
        f.write_text("def foo():\n    return 42\n\ndef bar():\n    pass\n")
        diff = "@@ -1,3 +1,3 @@\n def foo():\n-    return 42\n+    return 99\n"
        result = server._validate_diff_context(diff, str(f))
        assert result["valid"] is True

    def test_mismatched_context_fails(self, server, tmp_path):
        f = tmp_path / "real.py"
        f.write_text("def actual_function():\n    pass\n")
        diff = "@@ -1,2 +1,2 @@\n def completely_wrong_name():\n-    pass\n+    return 1\n"
        result = server._validate_diff_context(diff, str(f))
        assert len(result["errors"]) > 0


# ---------------------------------------------------------------------------
# GAP 2: _reanchor_diff
# ---------------------------------------------------------------------------

class TestReanchorDiff:
    def test_fixes_drifted_context(self, server, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("def hello_world():\n    print('hello')\n")
        # Diff with slightly wrong context line
        diff = "@@ -1,2 +1,2 @@\n def hello_wrld():\n-    print('hello')\n+    print('goodbye')\n"
        result = server._reanchor_diff(diff, str(f))
        assert "hello_world" in result

    def test_nonexistent_file_returns_original(self, server, tmp_path):
        diff = "@@ -1 +1 @@\n def foo():\n"
        result = server._reanchor_diff(diff, str(tmp_path / "nope.py"))
        assert result == diff


# ---------------------------------------------------------------------------
# GAP 3: _build_correction_prompt
# ---------------------------------------------------------------------------

class TestBuildCorrectionPrompt:
    def test_includes_errors(self, server):
        prompt = server._build_correction_prompt(
            "write a function", "def foo(\n", ["SyntaxError at line 1: unexpected EOF"], 1
        )
        assert "SyntaxError" in prompt
        assert "attempt 1/3" in prompt

    def test_includes_original_request(self, server):
        prompt = server._build_correction_prompt(
            "write hello world", "print('hi'", ["SyntaxError"], 2
        )
        assert "write hello world" in prompt
        assert "attempt 2/3" in prompt
