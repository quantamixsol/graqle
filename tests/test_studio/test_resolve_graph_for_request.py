"""Tests for the SF-07 _resolve_graph_for_request helper (CR-022, v0.57.4)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graqle.studio.routes.api import _PROJECT_NAME_RE, _resolve_graph_for_request


def _make_request(headers: dict | None = None, default_graph=None):
    """Build a minimal request mock with studio_state attached to app.state."""
    request = MagicMock()
    request.headers = headers or {}
    request.app.state.studio_state = {"graph": default_graph}
    return request


class TestResolveGraphForRequest:

    @pytest.mark.asyncio
    async def test_no_header_returns_default_graph(self):
        sentinel = object()
        request = _make_request(headers={}, default_graph=sentinel)
        result = await _resolve_graph_for_request(request)
        assert result is sentinel

    @pytest.mark.asyncio
    async def test_empty_header_returns_default_graph(self):
        sentinel = object()
        request = _make_request(headers={"x-project-name": ""}, default_graph=sentinel)
        result = await _resolve_graph_for_request(request)
        assert result is sentinel

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bad_name",
        [
            "../../etc/passwd",
            "project/subpath",
            "foo\\bar",
            "name\x00null",
            "x" * 200,  # too long
            "",  # zero length (also caught by "not project" guard)
        ],
    )
    async def test_malformed_header_falls_back_to_default(self, bad_name):
        sentinel = object()
        request = _make_request(headers={"x-project-name": bad_name}, default_graph=sentinel)
        result = await _resolve_graph_for_request(request)
        assert result is sentinel

    @pytest.mark.asyncio
    async def test_load_raises_falls_back_to_default(self):
        sentinel = object()
        request = _make_request(
            headers={"x-project-name": "Brand_Collaboration"}, default_graph=sentinel
        )
        with patch(
            "graqle.studio.routes.api._load_project_graph",
            new=AsyncMock(side_effect=RuntimeError("S3 IAM denied")),
        ):
            result = await _resolve_graph_for_request(request)
        assert result is sentinel

    @pytest.mark.asyncio
    async def test_load_returns_none_falls_back_to_default(self):
        sentinel = object()
        request = _make_request(
            headers={"x-project-name": "Brand_Collaboration"}, default_graph=sentinel
        )
        with patch(
            "graqle.studio.routes.api._load_project_graph",
            new=AsyncMock(return_value=None),
        ):
            result = await _resolve_graph_for_request(request)
        assert result is sentinel

    @pytest.mark.asyncio
    async def test_load_returns_graph_used_in_place_of_default(self):
        default_graph = object()
        project_graph = object()
        request = _make_request(
            headers={"x-project-name": "Brand_Collaboration"}, default_graph=default_graph
        )
        with patch(
            "graqle.studio.routes.api._load_project_graph",
            new=AsyncMock(return_value=project_graph),
        ):
            result = await _resolve_graph_for_request(request)
        assert result is project_graph
        assert result is not default_graph


class TestProjectNameRegex:

    @pytest.mark.parametrize(
        "name",
        [
            "Brand_Collaboration",
            "CopyForge",
            "graqle-sdk",
            "brandio frontend",
            "A.B-C_D",
            "a",
            "x" * 128,  # max length
        ],
    )
    def test_accepts_well_formed(self, name):
        assert _PROJECT_NAME_RE.match(name)

    @pytest.mark.parametrize(
        "name",
        [
            "../../etc",
            "foo/bar",
            "foo\\bar",
            "name\x00null",
            "name\n",
            "x" * 129,  # one over max
            "",
        ],
    )
    def test_rejects_malformed(self, name):
        assert not _PROJECT_NAME_RE.match(name)
