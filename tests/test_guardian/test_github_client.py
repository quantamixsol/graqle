"""Tests for graqle.guardian.github_client — GitHub API client."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from graqle.guardian.comment import COMMENT_MARKER
from graqle.guardian.github_client import GitHubClient


class TestGitHubClient:
    def test_init_defaults(self):
        client = GitHubClient()
        # Without env vars, token and repo are empty
        assert client.token == "" or isinstance(client.token, str)

    def test_init_with_explicit_values(self):
        client = GitHubClient(token="ghp_test", repo="owner/repo")
        assert client.token == "ghp_test"
        assert client.repo == "owner/repo"

    def test_upsert_skips_without_token(self):
        client = GitHubClient(token="", repo="")
        result = client.upsert_pr_comment(1, "test body")
        assert result is None

    def test_set_commit_status_skips_without_token(self):
        client = GitHubClient(token="", repo="")
        result = client.set_commit_status("abc123", "success", "OK")
        assert result is False


class TestFindGuardianComment:
    def test_finds_marker_in_comments(self):
        client = GitHubClient(token="test", repo="owner/repo")

        mock_comments = [
            {"id": 100, "body": "Some other comment"},
            {"id": 200, "body": f"{COMMENT_MARKER}\nGuardian report here"},
            {"id": 300, "body": "Another comment"},
        ]

        with patch.object(client, "_request", return_value=mock_comments):
            result = client._find_guardian_comment(1)
            assert result == 200

    def test_returns_none_when_no_marker(self):
        client = GitHubClient(token="test", repo="owner/repo")

        mock_comments = [
            {"id": 100, "body": "Some comment"},
        ]

        with patch.object(client, "_request", return_value=mock_comments):
            result = client._find_guardian_comment(1)
            assert result is None

    def test_returns_none_on_api_error(self):
        client = GitHubClient(token="test", repo="owner/repo")

        with patch.object(client, "_request", return_value={}):
            result = client._find_guardian_comment(1)
            assert result is None
