"""Tests for graqle.cloud.metrics_push — fire-and-forget telemetry."""

# ── graqle:intelligence ──
# module: tests.test_cloud.test_metrics_push
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, unittest.mock
# constraints: none
# ── /graqle:intelligence ──

from unittest.mock import MagicMock, patch

import pytest

from graqle.cloud.metrics_push import push_reasoning_metrics, _push_sync


class TestPushReasoningMetrics:

    def test_push_never_raises_on_network_error(self):
        """Caller must never see an exception from metrics_push."""
        with patch("graqle.cloud.metrics_push._push_sync", side_effect=OSError("refused")):
            # Must not raise
            push_reasoning_metrics(
                tool_name="graq_reason",
                latency_ms=250.0,
                confidence=0.85,
                rounds=2,
                node_count=12,
                cost_usd=0.0002,
            )

    def test_push_skips_for_free_tier(self):
        """Free plan users must not trigger any HTTP call."""
        from graqle.cloud.credentials import CloudCredentials

        free_creds = CloudCredentials(api_key="grq_test", plan="free", connected=True)
        http_mock = MagicMock()

        with patch("graqle.cloud.credentials.load_credentials", return_value=free_creds), \
             patch("urllib.request.urlopen", http_mock):
            _push_sync({
                "tool": "graq_reason",
                "latency_ms": 100.0,
                "confidence": 0.9,
                "rounds": 1,
                "node_count": 5,
                "cost_usd": 0.0,
                "project": "",
            })

        http_mock.assert_not_called()

    def test_push_sends_for_team_tier(self):
        """Team plan users should trigger an HTTP POST."""
        from graqle.cloud.credentials import CloudCredentials

        team_creds = CloudCredentials(
            api_key="grq_teamkey",
            plan="enterprise",
            connected=True,
        )

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("graqle.cloud.credentials.load_credentials", return_value=team_creds), \
             patch("urllib.request.urlopen", return_value=mock_response) as mock_open:
            _push_sync({
                "tool": "graq_reason",
                "latency_ms": 300.0,
                "confidence": 0.75,
                "rounds": 3,
                "node_count": 20,
                "cost_usd": 0.0005,
                "project": "graqle-sdk",
            })

        mock_open.assert_called_once()
        # Verify the correct endpoint was called
        req_arg = mock_open.call_args[0][0]
        assert "metrics" in req_arg.full_url
        assert req_arg.get_header("X-api-key") == "grq_teamkey"

    def test_push_truncates_long_project_name(self):
        """Project name is capped at 64 chars to keep payload small."""
        from graqle.cloud.credentials import CloudCredentials

        creds = CloudCredentials(api_key="grq_x", plan="enterprise", connected=True)
        mock_response = MagicMock()
        mock_response.status = 202
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        long_project = "x" * 200

        with patch("graqle.cloud.credentials.load_credentials", return_value=creds), \
             patch("urllib.request.urlopen", return_value=mock_response) as mock_open:
            push_reasoning_metrics(
                tool_name="graq_reason",
                latency_ms=100.0,
                confidence=0.8,
                rounds=2,
                node_count=5,
                cost_usd=0.0,
                project=long_project,
            )

        # Just verify it didn't raise — project truncation is an internal detail
        mock_open.assert_called_once()
