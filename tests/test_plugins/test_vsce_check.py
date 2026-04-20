"""G3 — graq_vsce_check MCP tool tests (Marketplace API, mocked)."""
from __future__ import annotations

import asyncio
import json
import socket
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from graqle.plugins.mcp_dev_server import KogniDevServer, TOOL_DEFINITIONS


@pytest.fixture
def server():
    srv = KogniDevServer.__new__(KogniDevServer)
    srv._session_started = True
    srv._plan_active = True
    srv._cg01_bypass = True
    srv._cg02_bypass = True
    srv._cg03_bypass = True
    srv.read_only = False
    srv._config = type("Cfg", (), {"governance": None})()
    return srv


def _call(server, args):
    return asyncio.run(server._handle_vsce_check(args))


def _fake_response(body: bytes, status: int = 200):
    """Build a fake urllib response context manager."""
    resp = MagicMock()
    resp.read.return_value = body
    resp.status = status
    resp.__enter__ = lambda self: resp
    resp.__exit__ = lambda *a: None
    return resp


def _canned_marketplace_payload(versions: list[str]) -> bytes:
    return json.dumps({
        "results": [{
            "extensions": [{
                "versions": [{"version": v} for v in versions],
            }],
        }],
    }).encode("utf-8")


# ═══════════════════════════════════════════════════════════════════════
# Tool registration (graq_* + kogni_* parity)
# ═══════════════════════════════════════════════════════════════════════

def test_graq_vsce_check_registered():
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert "graq_vsce_check" in names


def test_kogni_vsce_check_alias_present():
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert "kogni_vsce_check" in names


def test_schema_parity_graq_vs_kogni():
    graq = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_vsce_check")
    kogni = next(t for t in TOOL_DEFINITIONS if t["name"] == "kogni_vsce_check")
    assert graq["inputSchema"] == kogni["inputSchema"]
    assert graq["description"] == kogni["description"]


# ═══════════════════════════════════════════════════════════════════════
# Happy path: version does NOT exist
# ═══════════════════════════════════════════════════════════════════════

def test_version_not_in_marketplace(server):
    body = _canned_marketplace_payload(["0.4.12", "0.4.13", "0.4.14"])
    with patch("urllib.request.urlopen", return_value=_fake_response(body)):
        result = _call(server, {"version": "0.4.15"})
    data = json.loads(result)
    assert data["ok"] is True
    assert data["exists"] is False
    assert data["suggestedBump"] == ""
    assert data["currentVersion"] == "0.4.12"  # first in list (whatever order API returns)


# ═══════════════════════════════════════════════════════════════════════
# Happy path: version EXISTS → suggestedBump computed
# ═══════════════════════════════════════════════════════════════════════

def test_version_exists_computes_suggested_bump(server):
    body = _canned_marketplace_payload(["0.4.14", "0.4.15", "0.4.13"])
    with patch("urllib.request.urlopen", return_value=_fake_response(body)):
        result = _call(server, {"version": "0.4.15"})
    data = json.loads(result)
    assert data["ok"] is True
    assert data["exists"] is True
    # Max triple is (0,4,15) → next patch (0,4,16)
    assert data["suggestedBump"] == "0.4.16"


def test_suggested_bump_across_minor_boundary(server):
    body = _canned_marketplace_payload(["0.4.15", "0.5.0", "0.5.1"])
    with patch("urllib.request.urlopen", return_value=_fake_response(body)):
        result = _call(server, {"version": "0.5.1"})
    data = json.loads(result)
    assert data["exists"] is True
    assert data["suggestedBump"] == "0.5.2"


# ═══════════════════════════════════════════════════════════════════════
# Version normalization ('v0.4.15' → '0.4.15')
# ═══════════════════════════════════════════════════════════════════════

def test_leading_v_stripped(server):
    body = _canned_marketplace_payload(["0.4.15"])
    with patch("urllib.request.urlopen", return_value=_fake_response(body)):
        result = _call(server, {"version": "v0.4.15"})
    data = json.loads(result)
    assert data["exists"] is True
    assert data["version"] == "0.4.15"


# ═══════════════════════════════════════════════════════════════════════
# Strict semver rejection (pre-release, build metadata, incomplete)
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("bad", ["", "   ", "v", "v1", "0.4", "1.2.3-beta", "1.2.3+build", "1.a.b"])
def test_invalid_version_rejected(server, bad):
    result = _call(server, {"version": bad})
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "INVALID_VERSION"


def test_non_string_version_rejected(server):
    result = _call(server, {"version": 42})
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "INVALID_VERSION"


def test_missing_version_rejected(server):
    result = _call(server, {})
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "INVALID_VERSION"


# ═══════════════════════════════════════════════════════════════════════
# Publisher / extension slug validation
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("bad_pub", ["UPPERCASE", "has space", "dots.here", "sym$bol", ""])
def test_invalid_publisher_rejected(server, bad_pub):
    result = _call(server, {"version": "0.1.0", "publisher": bad_pub})
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "INVALID_PUBLISHER"


@pytest.mark.parametrize("bad_ext", ["UPPERCASE", "has space", "dots.here", ""])
def test_invalid_extension_rejected(server, bad_ext):
    result = _call(server, {"version": "0.1.0", "extension": bad_ext})
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "INVALID_EXTENSION"


# ═══════════════════════════════════════════════════════════════════════
# Network error mapping (Revision 2 fix: exhaustive urllib exception map)
# ═══════════════════════════════════════════════════════════════════════

def test_timeout_maps_to_marketplace_timeout(server):
    with patch("urllib.request.urlopen", side_effect=socket.timeout("timed out")):
        result = _call(server, {"version": "0.1.0"})
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "marketplace_timeout"


def test_http_error_maps_to_marketplace_unreachable(server):
    err = urllib.error.HTTPError(
        url="...", code=503, msg="Service Unavailable", hdrs=None, fp=None,
    )
    with patch("urllib.request.urlopen", side_effect=err):
        result = _call(server, {"version": "0.1.0"})
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "marketplace_unreachable"


def test_url_error_with_timeout_reason(server):
    err = urllib.error.URLError(reason=socket.timeout("timed out"))
    with patch("urllib.request.urlopen", side_effect=err):
        result = _call(server, {"version": "0.1.0"})
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "marketplace_timeout"


def test_generic_url_error(server):
    err = urllib.error.URLError(reason="connection refused")
    with patch("urllib.request.urlopen", side_effect=err):
        result = _call(server, {"version": "0.1.0"})
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "marketplace_unreachable"


def test_non_200_response(server):
    body = b"<html>Bad gateway</html>"
    with patch("urllib.request.urlopen", return_value=_fake_response(body, status=502)):
        result = _call(server, {"version": "0.1.0"})
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "marketplace_unreachable"


# ═══════════════════════════════════════════════════════════════════════
# Payload shape guards (Revision 2 fix: defensive nested access)
# ═══════════════════════════════════════════════════════════════════════

def test_empty_results_list(server):
    body = json.dumps({"results": []}).encode("utf-8")
    with patch("urllib.request.urlopen", return_value=_fake_response(body)):
        result = _call(server, {"version": "0.1.0"})
    data = json.loads(result)
    # Extension not found → exists=False, empty versions
    assert data["ok"] is True
    assert data["exists"] is False
    assert data["versions"] == []


def test_missing_extensions_key(server):
    body = json.dumps({"results": [{}]}).encode("utf-8")
    with patch("urllib.request.urlopen", return_value=_fake_response(body)):
        result = _call(server, {"version": "0.1.0"})
    data = json.loads(result)
    assert data["ok"] is True
    assert data["exists"] is False


def test_missing_versions_key(server):
    body = json.dumps({
        "results": [{"extensions": [{}]}],
    }).encode("utf-8")
    with patch("urllib.request.urlopen", return_value=_fake_response(body)):
        result = _call(server, {"version": "0.1.0"})
    data = json.loads(result)
    assert data["ok"] is True
    assert data["exists"] is False


def test_malformed_json_response(server):
    with patch("urllib.request.urlopen", return_value=_fake_response(b"{not valid")):
        result = _call(server, {"version": "0.1.0"})
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "marketplace_unreachable"


def test_non_dict_response(server):
    with patch("urllib.request.urlopen", return_value=_fake_response(b"[]")):
        result = _call(server, {"version": "0.1.0"})
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "marketplace_unreachable"


def test_versions_list_filters_malformed_entries(server):
    """Non-semver entries in versions[] are silently filtered."""
    body = json.dumps({
        "results": [{
            "extensions": [{
                "versions": [
                    {"version": "0.4.15"},
                    {"version": "malformed"},
                    {"version": "1.2.3-beta"},  # pre-release filtered
                    {},  # missing version key
                    {"version": 42},  # non-string
                    {"version": "0.5.0"},
                ],
            }],
        }],
    }).encode("utf-8")
    with patch("urllib.request.urlopen", return_value=_fake_response(body)):
        result = _call(server, {"version": "0.4.15"})
    data = json.loads(result)
    assert data["ok"] is True
    assert data["exists"] is True
    # Only the two stable semvers make it through
    assert set(data["versions"]) == {"0.4.15", "0.5.0"}


# ═══════════════════════════════════════════════════════════════════════
# Timeout sanity
# ═══════════════════════════════════════════════════════════════════════

def test_timeout_clamps_out_of_range(server):
    """timeout=0, negative, or >60 falls back to default 5.0."""
    body = _canned_marketplace_payload(["0.1.0"])
    with patch("urllib.request.urlopen", return_value=_fake_response(body)) as mock_open:
        _call(server, {"version": "0.1.0", "timeout": -1})
        # urlopen called with timeout=5.0 (default)
        _, kwargs = mock_open.call_args
        assert kwargs.get("timeout") == 5.0


# ═══════════════════════════════════════════════════════════════════════
# Non-dict args
# ═══════════════════════════════════════════════════════════════════════

def test_non_dict_args_rejected(server):
    result = _call(server, None)
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "INVALID_ARGUMENTS"
