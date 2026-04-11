"""TB-F1.3 regression tests for graqle.chat.settings_loader.

Coverage driven by pre-impl graq_review at 93% confidence:

  Happy paths:
    - Missing file → ChatSettings defaults (no raise, info log)
    - Valid file → typed ChatSettings
    - Custom path override

  Fail-closed paths (every error taxonomy entry):
    - InvalidJsonError on malformed JSON
    - SchemaViolationError on wrong type
    - SchemaViolationError on out-of-range value
    - UnknownKeyError on unknown top-level key (additionalProperties:false)
    - SchemaViolationError if root is not a JSON object

  Defaults:
    - ChatSettings() is valid with all defaults
    - Partial files fill remaining defaults
"""

# ── graqle:intelligence ──
# module: tests.test_chat.test_settings_loader
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, json, graqle.chat.settings_loader
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graqle.chat.settings_loader import (
    CHAT_SETTINGS_SCHEMA,
    ChatSettings,
    ChatSettingsError,
    InvalidJsonError,
    SchemaViolationError,
    SettingsLoader,
    UnknownKeyError,
)


def _write(path: Path, payload: dict | str) -> None:
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")


# ── happy paths ───────────────────────────────────────────────────────


def test_defaults_when_file_missing(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    p = tmp_path / "missing.json"
    import logging
    with caplog.at_level(logging.INFO, logger="graqle.chat.settings_loader"):
        s = SettingsLoader(p).load()
    assert isinstance(s, ChatSettings)
    assert s.max_burst_calls == 100
    assert s.max_continuations_chat == 3
    assert s.session_permission_cache_enabled is True
    assert s.governance_tier_overrides == {}
    assert s.per_tool_timeouts == {}
    assert any("not found" in r.message for r in caplog.records)


def test_valid_full_settings_file(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    _write(p, {
        "governance_tier_overrides": {"graq_write": "RED", "graq_read": "GREEN"},
        "max_burst_calls": 42,
        "per_tool_timeouts": {"graq_reason": 60.0, "graq_bash": 30.0},
        "session_permission_cache_enabled": False,
        "max_continuations_chat": 5,
    })
    s = SettingsLoader(p).load()
    assert s.max_burst_calls == 42
    assert s.max_continuations_chat == 5
    assert s.session_permission_cache_enabled is False
    assert s.governance_tier_overrides == {"graq_write": "RED", "graq_read": "GREEN"}
    assert s.per_tool_timeouts == {"graq_reason": 60.0, "graq_bash": 30.0}


def test_partial_settings_file_fills_defaults(tmp_path: Path) -> None:
    """A file that sets only some keys leaves the rest at defaults."""
    p = tmp_path / "settings.json"
    _write(p, {"max_burst_calls": 10})
    s = SettingsLoader(p).load()
    assert s.max_burst_calls == 10
    assert s.max_continuations_chat == 3  # default preserved
    assert s.session_permission_cache_enabled is True  # default preserved


def test_empty_object_loads_defaults(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    _write(p, {})
    s = SettingsLoader(p).load()
    assert s.max_burst_calls == 100


# ── fail-closed error paths ───────────────────────────────────────────


def test_invalid_json_raises_InvalidJsonError(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    p.write_text('{"this is": not valid json', encoding="utf-8")
    with pytest.raises(InvalidJsonError, match="not valid JSON"):
        SettingsLoader(p).load()


def test_wrong_type_raises_SchemaViolationError(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    _write(p, {"max_burst_calls": "not an integer"})
    with pytest.raises(SchemaViolationError):
        SettingsLoader(p).load()


def test_out_of_range_raises_SchemaViolationError(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    _write(p, {"max_burst_calls": 9999})  # > max of 500
    with pytest.raises(SchemaViolationError):
        SettingsLoader(p).load()


def test_max_continuations_out_of_range(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    _write(p, {"max_continuations_chat": 99})
    with pytest.raises(SchemaViolationError):
        SettingsLoader(p).load()


def test_unknown_top_level_key_raises_UnknownKeyError(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    _write(p, {"bogus_unknown_field": 42})
    with pytest.raises(UnknownKeyError):
        SettingsLoader(p).load()


def test_root_not_object_raises_SchemaViolationError(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    p.write_text('["not", "an", "object"]', encoding="utf-8")
    with pytest.raises(SchemaViolationError, match="must be a JSON object"):
        SettingsLoader(p).load()


def test_invalid_governance_tier_value_raises(tmp_path: Path) -> None:
    """governance_tier_overrides values must be one of GREEN/YELLOW/RED."""
    p = tmp_path / "settings.json"
    _write(p, {"governance_tier_overrides": {"graq_write": "PURPLE"}})
    with pytest.raises(SchemaViolationError):
        SettingsLoader(p).load()


def test_per_tool_timeout_zero_rejected(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    _write(p, {"per_tool_timeouts": {"graq_reason": 0}})  # exclusiveMinimum: 0
    with pytest.raises(SchemaViolationError):
        SettingsLoader(p).load()


# ── dataclass defaults ────────────────────────────────────────────────


def test_chat_settings_defaults_are_valid() -> None:
    s = ChatSettings()
    d = s.to_dict()
    assert d["max_burst_calls"] == 100
    assert d["max_continuations_chat"] == 3
    assert d["session_permission_cache_enabled"] is True


def test_error_hierarchy() -> None:
    """All specific errors are subclasses of ChatSettingsError."""
    assert issubclass(InvalidJsonError, ChatSettingsError)
    assert issubclass(SchemaViolationError, ChatSettingsError)
    assert issubclass(UnknownKeyError, ChatSettingsError)


# ── schema is internally consistent ──────────────────────────────────


def test_schema_has_additional_properties_false() -> None:
    """Regression guard: the schema MUST reject unknown top-level keys."""
    assert CHAT_SETTINGS_SCHEMA.get("additionalProperties") is False


def test_schema_has_all_expected_properties() -> None:
    """The schema must declare every field on ChatSettings."""
    props = CHAT_SETTINGS_SCHEMA["properties"]
    expected = {
        "governance_tier_overrides",
        "max_burst_calls",
        "per_tool_timeouts",
        "session_permission_cache_enabled",
        "max_continuations_chat",
    }
    assert set(props.keys()) == expected


def test_loader_default_path_is_user_home(tmp_path: Path) -> None:
    """Default path is ~/.graqle/settings.json when not overridden."""
    loader = SettingsLoader()
    assert str(loader.path).endswith("settings.json")
    assert ".graqle" in str(loader.path)
