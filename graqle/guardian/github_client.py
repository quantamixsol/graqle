"""GitHub API client for PR Guardian — post/upsert comments, set status.

Minimal client using urllib (no external deps beyond stdlib).
Falls back gracefully if GITHUB_TOKEN is missing or API fails.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from graqle.guardian.comment import COMMENT_MARKER

logger = logging.getLogger("graqle.guardian.github_client")

_GITHUB_API = "https://api.github.com"


class GitHubClient:
    """Minimal GitHub API client for PR Guardian.

    Uses urllib to avoid adding requests as a dependency.
    All methods fail gracefully — a GitHub API error should never
    prevent governance analysis from completing.
    """

    def __init__(self, token: str = "", repo: str = "") -> None:
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self.repo = repo or os.environ.get("GITHUB_REPOSITORY", "")

    def _request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        """Make a GitHub API request."""
        url = f"{_GITHUB_API}{path}"
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "GraQle-PR-Guardian",
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"

        body = json.dumps(data).encode("utf-8") if data else None
        if body:
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            logger.warning("GitHub API error: %s %s → %s", method, path, e.code)
            try:
                error_body = e.read().decode("utf-8")
                logger.debug("Error body: %s", error_body[:500])
            except Exception:
                pass
            return {}
        except Exception:
            logger.warning("GitHub API request failed: %s %s", method, path)
            return {}

    def upsert_pr_comment(self, pr_number: int, body: str) -> int | None:
        """Create or update the PR Guardian comment on a PR.

        Finds existing comment by COMMENT_MARKER, updates if found,
        creates new if not. Returns comment ID or None on failure.
        """
        if not self.repo or not self.token:
            logger.info("No GitHub token/repo — skipping PR comment")
            return None

        # Find existing comment
        existing_id = self._find_guardian_comment(pr_number)

        if existing_id:
            result = self._request(
                "PATCH",
                f"/repos/{self.repo}/issues/comments/{existing_id}",
                {"body": body},
            )
            return existing_id if result else None
        else:
            result = self._request(
                "POST",
                f"/repos/{self.repo}/issues/{pr_number}/comments",
                {"body": body},
            )
            return result.get("id") if isinstance(result, dict) else None

    def set_commit_status(
        self,
        sha: str,
        state: str,
        description: str,
        target_url: str = "",
    ) -> bool:
        """Set a commit status check.

        Args:
            sha: Commit SHA to set status on.
            state: "success", "failure", "pending", or "error".
            description: Short description (max 140 chars).
            target_url: Optional URL to link to.
        """
        if not self.repo or not self.token:
            return False

        data: dict[str, str] = {
            "state": state,
            "description": description[:140],
            "context": "GraQle PR Guardian",
        }
        if target_url:
            data["target_url"] = target_url

        result = self._request(
            "POST",
            f"/repos/{self.repo}/statuses/{sha}",
            data,
        )
        return bool(result)

    def _find_guardian_comment(self, pr_number: int) -> int | None:
        """Find existing PR Guardian comment by marker."""
        comments = self._request(
            "GET",
            f"/repos/{self.repo}/issues/{pr_number}/comments",
        )
        if not isinstance(comments, list):
            return None

        for comment in comments:
            body = comment.get("body", "")
            if COMMENT_MARKER in body:
                return comment.get("id")

        return None
