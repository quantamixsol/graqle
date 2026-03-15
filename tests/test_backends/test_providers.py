"""Tests for graqle.backends.providers — multi-provider preset registry."""

# ── graqle:intelligence ──
# module: tests.test_backends.test_providers
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, os, mock, pytest, providers
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from graqle.backends.providers import (
    PROVIDER_PRESETS,
    create_provider_backend,
    get_provider_env_var,
    get_provider_names,
)


class TestProviderPresets:
    """Test the PROVIDER_PRESETS registry structure."""

    def test_all_presets_have_required_keys(self):
        required = {"env_var", "endpoint", "label", "default_model", "models"}
        for name, preset in PROVIDER_PRESETS.items():
            missing = required - set(preset.keys())
            assert not missing, f"Provider '{name}' missing keys: {missing}"

    def test_all_endpoints_are_https(self):
        for name, preset in PROVIDER_PRESETS.items():
            assert preset["endpoint"].startswith("https://"), (
                f"Provider '{name}' endpoint should use HTTPS"
            )

    def test_all_have_at_least_one_model(self):
        for name, preset in PROVIDER_PRESETS.items():
            assert len(preset["models"]) > 0, (
                f"Provider '{name}' has no models"
            )

    def test_default_model_in_models_dict(self):
        for name, preset in PROVIDER_PRESETS.items():
            assert preset["default_model"] in preset["models"], (
                f"Provider '{name}' default_model not in models dict"
            )

    def test_model_costs_are_positive(self):
        for name, preset in PROVIDER_PRESETS.items():
            for model, cost in preset["models"].items():
                assert cost > 0, (
                    f"Provider '{name}' model '{model}' has non-positive cost"
                )

    def test_known_providers_exist(self):
        expected = {"groq", "deepseek", "together", "mistral",
                    "openrouter", "fireworks", "cohere"}
        assert expected.issubset(set(PROVIDER_PRESETS.keys()))


class TestGetProviderNames:
    def test_returns_list(self):
        names = get_provider_names()
        assert isinstance(names, list)
        assert len(names) >= 7

    def test_includes_groq(self):
        assert "groq" in get_provider_names()


class TestGetProviderEnvVar:
    def test_known_provider(self):
        assert get_provider_env_var("groq") == "GROQ_API_KEY"
        assert get_provider_env_var("deepseek") == "DEEPSEEK_API_KEY"

    def test_unknown_provider(self):
        assert get_provider_env_var("nonexistent") is None


class TestCreateProviderBackend:
    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            create_provider_backend("totally_fake_provider")

    def test_missing_api_key_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            # Ensure env var is not set
            env_var = PROVIDER_PRESETS["groq"]["env_var"]
            with patch.dict(os.environ, {env_var: ""}, clear=False):
                os.environ.pop(env_var, None)
                with pytest.raises(ValueError, match="GROQ_API_KEY"):
                    create_provider_backend("groq")

    def test_creates_backend_with_explicit_key(self):
        backend = create_provider_backend(
            "groq", model="llama-3.1-8b-instant", api_key="test-key-123"
        )
        assert backend is not None
        assert "custom:" in backend.name
        assert backend.cost_per_1k_tokens == 0.00005

    def test_creates_backend_with_env_key(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}):
            backend = create_provider_backend("deepseek")
        assert backend is not None
        assert backend.cost_per_1k_tokens == 0.00014  # deepseek-chat default

    def test_uses_default_model_when_none(self):
        backend = create_provider_backend(
            "mistral", api_key="test-key"
        )
        # Should use mistral-small-latest as default
        assert backend.cost_per_1k_tokens == 0.00020

    def test_fallback_cost_for_unknown_model(self):
        backend = create_provider_backend(
            "groq", model="some-future-model", api_key="test-key"
        )
        # Unknown model gets fallback cost of 0.001
        assert backend.cost_per_1k_tokens == 0.001

    def test_endpoint_override(self):
        backend = create_provider_backend(
            "groq",
            api_key="test-key",
            endpoint="https://my-proxy.example.com/v1/chat",
        )
        assert "my-proxy" in backend.name

    def test_all_providers_create_successfully(self):
        """Every provider should create a backend when given an API key."""
        for provider in PROVIDER_PRESETS:
            backend = create_provider_backend(provider, api_key="test-key")
            assert backend is not None, f"Failed to create backend for {provider}"
