"""Tests for graqle.backends.gemini — Google Gemini API backend."""

# ── graqle:intelligence ──
# module: tests.test_backends.test_gemini
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, json, mock, pytest, gemini
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graqle.backends.gemini import GEMINI_PRICING, GeminiBackend


class TestGeminiBackendInit:
    def test_default_model(self):
        backend = GeminiBackend(api_key="test-key")
        assert backend._model == "gemini-2.0-flash"

    def test_custom_model(self):
        backend = GeminiBackend(model="gemini-2.5-pro", api_key="test-key")
        assert backend._model == "gemini-2.5-pro"

    def test_api_key_from_param(self):
        backend = GeminiBackend(api_key="my-key")
        assert backend._api_key == "my-key"

    def test_api_key_from_gemini_env(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "env-key"}):
            backend = GeminiBackend()
        assert backend._api_key == "env-key"

    def test_api_key_from_google_env(self):
        with patch.dict("os.environ", {"GOOGLE_API_KEY": "google-key"}, clear=False):
            # Ensure GEMINI_API_KEY is not set
            import os
            os.environ.pop("GEMINI_API_KEY", None)
            backend = GeminiBackend()
        assert backend._api_key == "google-key"

    def test_name_property(self):
        backend = GeminiBackend(model="gemini-2.0-flash", api_key="k")
        assert backend.name == "gemini:gemini-2.0-flash"


class TestGeminiPricing:
    def test_known_model_cost(self):
        backend = GeminiBackend(model="gemini-2.0-flash", api_key="k")
        assert backend.cost_per_1k_tokens == 0.00010

    def test_unknown_model_fallback_cost(self):
        backend = GeminiBackend(model="gemini-99-ultra", api_key="k")
        assert backend.cost_per_1k_tokens == 0.0005

    def test_pricing_table_has_entries(self):
        assert len(GEMINI_PRICING) >= 4


class TestGeminiGenerate:
    @pytest.mark.asyncio
    async def test_missing_api_key_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            backend = GeminiBackend(api_key=None)
            backend._api_key = None
            with pytest.raises(ValueError, match="GEMINI_API_KEY"):
                await backend.generate("test prompt")

    @pytest.mark.asyncio
    async def test_successful_generation(self):
        backend = GeminiBackend(api_key="test-key")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Hello from Gemini!"}]
                    }
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await backend.generate("test prompt")

        assert result == "Hello from Gemini!"
        # Verify correct URL format
        call_args = mock_client.post.call_args
        url = call_args[0][0]
        assert "generativelanguage.googleapis.com" in url
        assert "generateContent" in url
        assert "key=test-key" in url

    @pytest.mark.asyncio
    async def test_empty_candidates(self):
        backend = GeminiBackend(api_key="test-key")

        mock_response = MagicMock()
        mock_response.json.return_value = {"candidates": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await backend.generate("test")

        assert result == ""

    @pytest.mark.asyncio
    async def test_request_body_format(self):
        backend = GeminiBackend(api_key="test-key")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await backend.generate(
                "test prompt",
                max_tokens=1024,
                temperature=0.7,
                stop=["STOP"],
            )

        call_args = mock_client.post.call_args
        body = call_args[1]["json"]
        assert body["contents"][0]["parts"][0]["text"] == "test prompt"
        assert body["generationConfig"]["maxOutputTokens"] == 1024
        assert body["generationConfig"]["temperature"] == 0.7
        assert body["generationConfig"]["stopSequences"] == ["STOP"]
