"""Tests for environment auto-detection."""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_autodetect
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: os, pathlib, mock, autodetect
# constraints: none
# ── /graqle:intelligence ──

import os
from unittest.mock import patch

from graqle.scanner.autodetect import (
    _build_smart_excludes,
    _detect_backend,
    _detect_ide,
    _detect_languages,
    _detect_machine,
    detect_environment,
    suggest_mcp_config,
)


class TestDetectBackend:

    def test_aws_bedrock(self):
        with patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "AKIA...", "AWS_DEFAULT_REGION": "eu-central-1"}):
            backend, region = _detect_backend()
            assert backend == "bedrock"
            assert region == "eu-central-1"

    def test_anthropic(self):
        env = {"ANTHROPIC_API_KEY": "sk-ant-..."}
        with patch.dict(os.environ, env, clear=True):
            backend, region = _detect_backend()
            assert backend == "anthropic"
            assert region is None

    def test_openai(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-..."}, clear=True):
            backend, region = _detect_backend()
            assert backend == "openai"

    def test_local_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            backend, region = _detect_backend()
            assert backend == "local"


class TestDetectLanguages:

    def test_python_detected(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]")
        langs = _detect_languages(tmp_path)
        assert "python" in langs

    def test_typescript_detected(self, tmp_path):
        (tmp_path / "tsconfig.json").write_text("{}")
        langs = _detect_languages(tmp_path)
        assert "typescript" in langs

    def test_go_detected(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example")
        langs = _detect_languages(tmp_path)
        assert "go" in langs

    def test_rust_detected(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text("[package]")
        langs = _detect_languages(tmp_path)
        assert "rust" in langs

    def test_empty_dir(self, tmp_path):
        langs = _detect_languages(tmp_path)
        assert langs == []

    def test_multiple_languages(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]")
        (tmp_path / "tsconfig.json").write_text("{}")
        langs = _detect_languages(tmp_path)
        assert "python" in langs
        assert "typescript" in langs


class TestDetectIDE:

    def test_vscode(self, tmp_path):
        (tmp_path / ".vscode").mkdir()
        assert _detect_ide(tmp_path) == "vscode"

    def test_cursor(self, tmp_path):
        (tmp_path / ".cursor").mkdir()
        assert _detect_ide(tmp_path) == "cursor"

    def test_jetbrains(self, tmp_path):
        (tmp_path / ".idea").mkdir()
        assert _detect_ide(tmp_path) == "jetbrains"

    def test_none(self, tmp_path):
        assert _detect_ide(tmp_path) is None


class TestDetectMachine:

    def test_returns_valid_capacity(self):
        capacity, cpu, ram = _detect_machine()
        assert capacity in ("minimal", "standard", "capable", "powerful")
        assert cpu >= 1
        assert ram > 0


class TestBuildSmartExcludes:

    def test_always_includes_common(self, tmp_path):
        excludes = _build_smart_excludes(tmp_path, [])
        assert "node_modules/" in excludes
        assert ".git/" in excludes
        assert "__pycache__/" in excludes

    def test_rust_target(self, tmp_path):
        excludes = _build_smart_excludes(tmp_path, ["rust"])
        assert "target/" in excludes

    def test_java_gradle(self, tmp_path):
        excludes = _build_smart_excludes(tmp_path, ["java"])
        assert ".gradle/" in excludes


class TestDetectEnvironment:

    def test_full_detection(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".vscode").mkdir()

        env = detect_environment(tmp_path)
        assert "python" in env.languages
        assert env.has_git is True
        assert env.ide == "vscode"
        assert env.capacity in ("minimal", "standard", "capable", "powerful")
        assert len(env.smart_excludes) > 0


class TestSuggestMcpConfig:

    def test_vscode_config(self, tmp_path):
        config = suggest_mcp_config("vscode", tmp_path)
        assert config is not None
        assert "graqle" in config["mcpServers"]

    def test_no_ide_returns_none(self, tmp_path):
        assert suggest_mcp_config(None, tmp_path) is None

    def test_jetbrains_returns_none(self, tmp_path):
        assert suggest_mcp_config("jetbrains", tmp_path) is None
