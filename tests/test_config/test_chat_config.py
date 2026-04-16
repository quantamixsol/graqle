"""T05 (v0.51.6) — ChatConfig acceptance tests.

Binary acceptance per .gcc/branches/hotfix-v0.51.6/EXECUTION-PATH.md §T05:
- A graqle.yaml with a chat: block loads correctly
- Values flow through to GraqleConfig.chat
- Defaults preserved (backward compat with yamls that omit chat:)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from graqle.config.settings import ChatConfig, GraqleConfig


class TestChatConfigDefaults:
    def test_default_factory_present(self):
        cfg = GraqleConfig()
        assert isinstance(cfg.chat, ChatConfig)

    def test_default_disabled(self):
        cfg = GraqleConfig.default()
        assert cfg.chat.enabled is False

    def test_default_task_type(self):
        assert ChatConfig().default_task_type == "chat_triage"

    def test_default_max_turn_seconds(self):
        assert ChatConfig().max_turn_seconds == 300

    def test_default_permission_mode(self):
        assert ChatConfig().permission_mode == "ask"


class TestChatConfigFromYaml:
    def test_yaml_without_chat_block_uses_defaults(self, tmp_path: Path):
        """Backward compat: yamls predating v0.51.6 must still load."""
        yaml_file = tmp_path / "graqle.yaml"
        yaml_file.write_text(
            "model:\n"
            "  backend: local\n"
            "  model: stub\n",
            encoding="utf-8",
        )
        cfg = GraqleConfig.from_yaml(str(yaml_file))
        assert cfg.chat.enabled is False
        assert cfg.chat.default_task_type == "chat_triage"
        assert cfg.chat.max_turn_seconds == 300
        assert cfg.chat.permission_mode == "ask"

    def test_yaml_with_chat_block_loads(self, tmp_path: Path):
        yaml_file = tmp_path / "graqle.yaml"
        yaml_file.write_text(
            "chat:\n"
            "  enabled: true\n"
            "  default_task_type: chat_reason\n"
            "  max_turn_seconds: 60\n"
            "  permission_mode: auto_allow\n",
            encoding="utf-8",
        )
        cfg = GraqleConfig.from_yaml(str(yaml_file))
        assert cfg.chat.enabled is True
        assert cfg.chat.default_task_type == "chat_reason"
        assert cfg.chat.max_turn_seconds == 60
        assert cfg.chat.permission_mode == "auto_allow"

    def test_yaml_with_partial_chat_block_merges_with_defaults(self, tmp_path: Path):
        yaml_file = tmp_path / "graqle.yaml"
        yaml_file.write_text(
            "chat:\n"
            "  enabled: true\n",  # only one key set
            encoding="utf-8",
        )
        cfg = GraqleConfig.from_yaml(str(yaml_file))
        assert cfg.chat.enabled is True
        # Other fields keep their defaults
        assert cfg.chat.default_task_type == "chat_triage"
        assert cfg.chat.max_turn_seconds == 300
        assert cfg.chat.permission_mode == "ask"


class TestChatConfigFieldsExposedToCallers:
    """Forward-looking guard: T03 handlers will read these field names.

    If any name changes, T03 (graq_chat_* MCP registration) will fail
    at handler import — these assertions catch the rename early.
    """

    def test_field_names_stable(self):
        cfg = ChatConfig()
        assert hasattr(cfg, "enabled")
        assert hasattr(cfg, "default_task_type")
        assert hasattr(cfg, "max_turn_seconds")
        assert hasattr(cfg, "permission_mode")

    @pytest.mark.parametrize("mode", ["ask", "auto_allow", "deny"])
    def test_permission_mode_accepts_documented_values(self, mode: str):
        cfg = ChatConfig(permission_mode=mode)
        assert cfg.permission_mode == mode
