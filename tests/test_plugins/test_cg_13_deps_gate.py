"""CG-13 Dependency Gate tests (Wave 2 Phase 6)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from graqle.governance.deps_gate import (
    _KNOWN_BAD_PACKAGES,
    _KNOWN_GOOD_PACKAGES,
    _VALID_MANAGERS,
    _approval_is_valid,
    _is_unsupported_spec,
    _normalize_package_name,
    _typosquat_candidate,
    build_deps_dry_run_response,
    build_deps_live_response,
    check_deps_install,
)


# Constants (1)


def test_valid_managers_constant():
    assert _VALID_MANAGERS == ("pip", "npm", "yarn")


# Manager validation (2)


def test_invalid_manager():
    allowed, env = check_deps_install("brew", ["foo"])
    assert not allowed
    assert env["error"] == "CG-13_INVALID_MANAGER"


@pytest.mark.parametrize("manager", ["pip", "npm", "yarn"])
def test_valid_managers_pass_stage(manager):
    allowed, env = check_deps_install(manager, ["openai"])
    # pip allows openai; npm/yarn — openai is in known-good list → passes typosquat
    assert allowed is True or env.get("error") != "CG-13_INVALID_MANAGER"


# Packages validation (4)


def test_packages_must_be_list():
    allowed, env = check_deps_install("pip", "openai")
    assert not allowed
    assert env["error"] == "CG-13_INVALID_PACKAGES"


def test_packages_empty_list():
    allowed, env = check_deps_install("pip", [])
    assert not allowed
    assert env["error"] == "CG-13_INVALID_PACKAGES"


def test_packages_non_string_items():
    allowed, env = check_deps_install("pip", ["ok", 123])
    assert not allowed
    assert env["error"] == "CG-13_INVALID_PACKAGES"


def test_packages_whitespace_only():
    allowed, env = check_deps_install("pip", ["   "])
    assert not allowed
    assert env["error"] == "CG-13_INVALID_PACKAGES"


# Unsupported specs (3)


@pytest.mark.parametrize("bad_spec", [
    "-e git+https://evil.com/repo",
    "git+https://github.com/foo",
    "http://example.com/pkg.whl",
    "./local/path",
    "/absolute/path",
    "file:///tmp/x",
])
def test_unsupported_spec_forms(bad_spec):
    allowed, env = check_deps_install("pip", [bad_spec])
    assert not allowed
    assert env["error"] == "CG-13_UNSUPPORTED_SPEC"


def test_is_unsupported_spec_direct():
    assert _is_unsupported_spec("git+https://x") is True
    assert _is_unsupported_spec("openai") is False
    assert _is_unsupported_spec("openai==1.0") is False


def test_allowed_version_specs():
    allowed, env = check_deps_install("pip", ["openai==1.0", "anthropic>=0.5,<1.0"])
    # These are known-good packages with version pins; should pass
    assert allowed is True


# Known-bad (3)


@pytest.mark.parametrize("bad", ["lietllm-proxy", "python-openai", "openai-proxy"])
def test_known_bad_blocked(bad):
    allowed, env = check_deps_install("pip", [bad])
    assert not allowed
    assert env["error"] == "CG-13_KNOWN_BAD_PACKAGE"


def test_known_bad_seed_contains_expected():
    assert "lietllm-proxy" in _KNOWN_BAD_PACKAGES
    assert "python-openai" in _KNOWN_BAD_PACKAGES


# Typosquat (4)


@pytest.mark.parametrize("squat", ["openai-python", "openai_extra", "open-ai"])
def test_typosquat_detected(squat):
    allowed, env = check_deps_install("pip", [squat])
    # Depending on exact edit distance / suffix logic, some of these may
    # land in typosquat or known-bad. Either way, NOT allowed.
    assert not allowed
    assert env["error"] in (
        "CG-13_TYPOSQUAT_SUSPECTED",
        "CG-13_KNOWN_BAD_PACKAGE",
    )


def test_legitimate_packages_not_flagged():
    allowed, env = check_deps_install(
        "pip", ["openai", "anthropic", "litellm", "boto3"],
    )
    assert allowed is True


def test_typosquat_candidate_direct():
    assert _typosquat_candidate("openai-python", "pip") == "openai"
    assert _typosquat_candidate("openai", "pip") is None  # legitimate
    assert _typosquat_candidate("unknownpkg12345", "pip") is None  # unknown


def test_known_good_list_includes_openai():
    assert "openai" in _KNOWN_GOOD_PACKAGES
    assert "anthropic" in _KNOWN_GOOD_PACKAGES


# Normalization (3)


def test_normalize_pip_extras_stripped():
    assert _normalize_package_name("pip", "openai[extras]==1.0") == "openai"


def test_normalize_pip_dash_underscore():
    # PEP 503 normalization: underscore → dash
    assert _normalize_package_name("pip", "my_package") == "my-package"


def test_normalize_npm_scope():
    assert _normalize_package_name("npm", "@scope/pkg@1.0") == "@scope/pkg"


# Dry-run (2)


def test_dry_run_default_allows_without_approval():
    allowed, env = check_deps_install("pip", ["openai"])
    # Default dry_run=True, so no approval needed
    assert allowed is True


def test_dry_run_true_explicit_allows_without_approval():
    allowed, env = check_deps_install(
        "pip", ["openai"], dry_run=True,
    )
    assert allowed is True


# Live install approval (4)


def test_live_install_requires_approval():
    allowed, env = check_deps_install(
        "pip", ["openai"], dry_run=False,
    )
    assert not allowed
    assert env["error"] == "CG-13_APPROVAL_REQUIRED"


def test_live_install_with_bare_id_allowed():
    allowed, env = check_deps_install(
        "pip", ["openai"], dry_run=False, approved_by="alice",
    )
    assert allowed is True


def test_live_install_short_id_rejected():
    allowed, env = check_deps_install(
        "pip", ["openai"], dry_run=False, approved_by="ab",  # length 2
    )
    assert not allowed
    assert env["error"] == "CG-13_APPROVAL_REQUIRED"


def test_live_install_structured_approval_accepted():
    allowed, env = check_deps_install(
        "pip", ["openai"],
        dry_run=False,
        approved_by="reviewer-alice:2026-04-23T12:34:56Z",
    )
    assert allowed is True


def test_approval_validator_direct():
    assert _approval_is_valid("alice") is True  # legacy bare
    assert _approval_is_valid("alice:2026-04-23T12:34:56Z") is True  # structured
    assert _approval_is_valid("ab") is False  # too short
    assert _approval_is_valid("") is False
    assert _approval_is_valid(None) is False
    assert _approval_is_valid(123) is False


# Response builders (2)


def test_build_deps_dry_run_response():
    out = build_deps_dry_run_response("pip", ["openai"])
    assert out["action"] == "deps_install"
    assert out["manager"] == "pip"
    assert out["dry_run"] is True
    assert out["status"] == "approved_dry_run"


def test_build_deps_live_response():
    out = build_deps_live_response("pip", ["openai"], "alice")
    assert out["action"] == "deps_install"
    assert out["dry_run"] is False
    assert out["approved_by"] == "alice"
    assert out["status"] == "approved_live"


# MCP handler integration (3)


@pytest.mark.asyncio
async def test_handler_invalid_manager_envelope():
    import graqle.plugins.mcp_dev_server as m

    class _Srv: pass
    result = json.loads(await m.KogniDevServer._handle_deps_install(
        _Srv(), {"manager": "brew", "packages": ["foo"]},
    ))
    assert result["error"] == "CG-13_INVALID_MANAGER"


@pytest.mark.asyncio
async def test_handler_dry_run_default_returns_plan():
    import graqle.plugins.mcp_dev_server as m

    class _Srv: pass
    result = json.loads(await m.KogniDevServer._handle_deps_install(
        _Srv(), {"manager": "pip", "packages": ["openai"]},
    ))
    assert result["action"] == "deps_install"
    assert result["dry_run"] is True
    assert result["status"] == "approved_dry_run"


@pytest.mark.asyncio
async def test_handler_live_install_with_approval():
    import graqle.plugins.mcp_dev_server as m

    class _Srv: pass
    result = json.loads(await m.KogniDevServer._handle_deps_install(
        _Srv(),
        {
            "manager": "pip", "packages": ["openai"],
            "dry_run": False, "approved_by": "alice",
        },
    ))
    assert result["status"] == "approved_live"
    assert result["approved_by"] == "alice"


# Schema (2)


def test_graq_deps_install_schema():
    import graqle.plugins.mcp_dev_server as m

    tool = next(
        (t for t in m.TOOL_DEFINITIONS if t["name"] == "graq_deps_install"),
        None,
    )
    assert tool is not None
    props = tool["inputSchema"]["properties"]
    assert props["manager"]["enum"] == ["pip", "npm", "yarn"]
    assert props["dry_run"]["default"] is True
    assert tool["inputSchema"]["required"] == ["manager", "packages"]


def test_tool_count_incremented():
    import graqle.plugins.mcp_dev_server as m

    names = [t["name"] for t in m.TOOL_DEFINITIONS]
    assert "graq_deps_install" in names
    assert "graq_config_audit" in names  # Phase 3 preserved
    assert "graq_web_search" in names    # existing preserved
    # No duplicates
    assert len(names) == len(set(names))
