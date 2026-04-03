"""Tests for C1 security gate: LLM content redaction.

Verifies that sensitive node properties are scrubbed before being
sent to external LLM backends during reasoning.
"""

from __future__ import annotations

import pytest

from graqle.core.redaction import (
    DEFAULT_SENSITIVE_KEYS,
    _is_sensitive_key,
    redact_chunks,
    redact_node_properties,
    redact_text,
)


class TestRedactNodeProperties:
    """Test the pure redaction function for node properties."""

    def test_default_sensitive_keys_redacted(self):
        props = {
            "label": "auth_service",
            "password": "hunter2",
            "api_key": "sk-1234",
            "secret": "my-secret",
            "token": "jwt-abc",
            "credential": "cred-xyz",
            "description": "Auth service node",
        }
        result = redact_node_properties(props)
        assert result["label"] == "auth_service"
        assert result["description"] == "Auth service node"
        assert result["password"] == "[REDACTED]"
        assert result["api_key"] == "[REDACTED]"
        assert result["secret"] == "[REDACTED]"
        assert result["token"] == "[REDACTED]"
        assert result["credential"] == "[REDACTED]"

    def test_non_sensitive_keys_preserved(self):
        props = {
            "label": "my_module",
            "entity_type": "PythonModule",
            "line_count": 42,
            "imports": ["os", "sys"],
        }
        result = redact_node_properties(props)
        assert result == props

    def test_substring_matching(self):
        """db_password, X_Api_Key etc. should match via substring."""
        props = {
            "db_password": "secret123",
            "auth_token_v2": "tok-abc",
            "private_key_pem": "-----BEGIN RSA-----",
            "access_key_id": "AKIA...",
            "name": "safe_value",
        }
        result = redact_node_properties(props)
        assert result["db_password"] == "[REDACTED]"
        assert result["auth_token_v2"] == "[REDACTED]"
        assert result["private_key_pem"] == "[REDACTED]"
        assert result["access_key_id"] == "[REDACTED]"
        assert result["name"] == "safe_value"

    def test_case_insensitive_matching(self):
        props = {
            "DB_PASSWORD": "secret",
            "Api_Key": "key123",
            "SECRET_VALUE": "hidden",
        }
        result = redact_node_properties(props)
        assert result["DB_PASSWORD"] == "[REDACTED]"
        assert result["Api_Key"] == "[REDACTED]"
        assert result["SECRET_VALUE"] == "[REDACTED]"

    def test_custom_sensitive_keys(self):
        props = {
            "internal_score": 0.95,
            "name": "safe",
        }
        custom_keys = frozenset({"internal_score"})
        result = redact_node_properties(props, sensitive_keys=custom_keys)
        assert result["internal_score"] == "[REDACTED]"
        assert result["name"] == "safe"

    def test_custom_marker(self):
        props = {"password": "secret"}
        result = redact_node_properties(props, marker="***")
        assert result["password"] == "***"

    def test_never_mutates_input(self):
        original = {"password": "hunter2", "name": "test"}
        original_copy = dict(original)
        redact_node_properties(original)
        assert original == original_copy

    def test_empty_dict(self):
        assert redact_node_properties({}) == {}

    def test_internal_keys_redacted(self):
        props = {
            "_embedding_cache": [0.1, 0.2],
            "_activation_score": 0.95,
            "name": "safe",
        }
        result = redact_node_properties(props)
        assert result["_embedding_cache"] == "[REDACTED]"
        assert result["_activation_score"] == "[REDACTED]"
        assert result["name"] == "safe"


class TestRedactChunks:
    """Test chunk text scrubbing."""

    def test_scrubs_key_value_patterns(self):
        chunks = [
            {"text": "Module info\npassword: hunter2\nname: auth", "type": "synthesized"},
        ]
        result = redact_chunks(chunks)
        assert "hunter2" not in result[0]["text"]
        assert "name: auth" in result[0]["text"]

    def test_preserves_non_dict_chunks(self):
        chunks = ["plain string chunk"]
        result = redact_chunks(chunks)
        assert result == chunks

    def test_never_mutates_input(self):
        original = [{"text": "secret: abc123", "type": "synth"}]
        import copy
        original_copy = copy.deepcopy(original)
        redact_chunks(original)
        assert original == original_copy

    def test_empty_list(self):
        assert redact_chunks([]) == []

    def test_multiple_sensitive_lines(self):
        chunks = [
            {
                "text": "api_key: sk-1234\ntoken: jwt-abc\nlabel: safe",
                "type": "synthesized",
            },
        ]
        result = redact_chunks(chunks)
        assert "sk-1234" not in result[0]["text"]
        assert "jwt-abc" not in result[0]["text"]
        assert "safe" in result[0]["text"]


class TestRedactText:
    """Test free-text redaction."""

    def test_redacts_inline_credentials(self):
        text = "Config:\ndb_password: secret123\nhost: localhost"
        result = redact_text(text)
        assert "secret123" not in result
        assert "localhost" in result

    def test_empty_string(self):
        assert redact_text("") == ""

    def test_no_sensitive_content(self):
        text = "Module: auth_service. Functions: login, logout."
        assert redact_text(text) == text


class TestIsSensitiveKey:
    """Test the key matching function."""

    def test_exact_match(self):
        assert _is_sensitive_key("password", DEFAULT_SENSITIVE_KEYS)
        assert _is_sensitive_key("api_key", DEFAULT_SENSITIVE_KEYS)

    def test_substring_match(self):
        assert _is_sensitive_key("db_password_hash", DEFAULT_SENSITIVE_KEYS)
        assert _is_sensitive_key("oauth_token", DEFAULT_SENSITIVE_KEYS)

    def test_case_insensitive(self):
        assert _is_sensitive_key("PASSWORD", DEFAULT_SENSITIVE_KEYS)
        assert _is_sensitive_key("Api_Key", DEFAULT_SENSITIVE_KEYS)

    def test_non_sensitive(self):
        assert not _is_sensitive_key("name", DEFAULT_SENSITIVE_KEYS)
        assert not _is_sensitive_key("description", DEFAULT_SENSITIVE_KEYS)
        assert not _is_sensitive_key("line_count", DEFAULT_SENSITIVE_KEYS)

    def test_internal_keys(self):
        assert _is_sensitive_key("_embedding_cache", DEFAULT_SENSITIVE_KEYS)


class TestDefaultSensitiveKeys:
    """Verify the default sensitive keys cover common credential patterns."""

    @pytest.mark.parametrize("key", [
        "password", "secret", "token", "api_key", "apikey",
        "credential", "private_key", "auth_token", "access_key",
        "secret_key", "ssn", "pii",
    ])
    def test_default_key_present(self, key):
        assert key in DEFAULT_SENSITIVE_KEYS


class TestLLMRedactionConfig:
    """Test the configuration model."""

    def test_default_config(self):
        from graqle.config.settings import LLMRedactionConfig
        cfg = LLMRedactionConfig()
        assert cfg.enabled is True
        assert cfg.sensitive_keys == []
        assert cfg.redaction_marker == "[REDACTED]"

    def test_custom_config(self):
        from graqle.config.settings import LLMRedactionConfig
        cfg = LLMRedactionConfig(
            enabled=True,
            sensitive_keys=["custom_key"],
            redaction_marker="***",
        )
        assert cfg.sensitive_keys == ["custom_key"]
        assert cfg.redaction_marker == "***"

    def test_disabled_config(self):
        from graqle.config.settings import LLMRedactionConfig
        cfg = LLMRedactionConfig(enabled=False)
        assert cfg.enabled is False

    def test_graqle_config_has_llm_redaction(self):
        from graqle.config.settings import GraqleConfig
        cfg = GraqleConfig()
        assert hasattr(cfg, "llm_redaction")
        assert cfg.llm_redaction.enabled is True
