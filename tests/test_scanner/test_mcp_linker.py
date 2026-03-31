"""Tests for graqle.scanner.mcp_linker — cross-language MCP tool resolution (ADR-131).

Tests the ACTUAL graqle.scanner.mcp_linker module, not a self-contained copy.
Confidence values (0.9/0.8/0.7/0.6) are non-proprietary test fixtures.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from graqle.scanner.mcp_linker import (
    CrossLangEdge,
    UnresolvedEdge,
    _load_confidence_config,
    build_alias_map,
    emit_kg_edges,
    reset_confidence_cache,
    resolve_cross_language,
)


# ---------------------------------------------------------------------------
# Lightweight mock dataclasses for test fixtures
# ---------------------------------------------------------------------------


@dataclass
class MockCallSite:
    """Mimics a scanner-produced MCP call-site record."""

    tool_name: str
    file_path: str = "client.ts"
    line: int = 1
    node_id: str = "ts_node_1"
    is_dynamic: bool = False


@dataclass
class MockHandler:
    """Mimics a scanner-produced MCP handler record."""

    bare_name: str
    handler_name: str = ""
    file_path: str = "mcp_dev_server.py"
    node_id: str = "py_node_1"


# ---------------------------------------------------------------------------
# Non-proprietary test confidence values
# ---------------------------------------------------------------------------

CONF_DIRECT = 0.9
CONF_PREFIX = 0.8
CONF_ALIAS = 0.7
CONF_REGISTRY = 0.6

_TEST_CONFIDENCE_CONFIG = {
    "direct_match": CONF_DIRECT,
    "prefix_strip": CONF_PREFIX,
    "alias_strip": CONF_ALIAS,
    "registry_fallback": CONF_REGISTRY,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handlers(*bare_names: str) -> list[MockHandler]:
    return [
        MockHandler(
            bare_name=name,
            handler_name=f"_handle_{name}",
            node_id=f"py_{name}",
        )
        for name in bare_names
    ]


def _make_call(tool: str, **kwargs: Any) -> MockCallSite:
    return MockCallSite(tool_name=tool, **kwargs)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_confidence_cache()
    yield
    reset_confidence_cache()


@pytest.fixture()
def handlers() -> list[MockHandler]:
    return _make_handlers("reason", "context", "inspect")


@pytest.fixture()
def alias_map() -> dict[str, str]:
    return {"kogni_reason": "graq_reason", "kogni_context": "graq_context"}


@pytest.fixture()
def registry_bindings() -> dict[str, str]:
    return {"special_tool": "reason"}


# ===========================================================================
# 1. test_direct_bare_name_match
# ===========================================================================


def test_direct_bare_name_match(handlers: list[MockHandler]) -> None:
    """callTool('reason') resolves to handler with bare_name='reason'."""
    call = _make_call("reason")
    resolved, unresolved = resolve_cross_language(
        call_sites=[call],
        handlers=handlers,
        alias_map={},
        confidence_config=_TEST_CONFIDENCE_CONFIG,
    )
    assert len(resolved) == 1
    assert isinstance(resolved[0], CrossLangEdge)
    assert resolved[0].bare_name == "reason"
    assert resolved[0].resolution_path == "direct_match"


# ===========================================================================
# 2. test_prefix_strip_match
# ===========================================================================


def test_prefix_strip_match(handlers: list[MockHandler]) -> None:
    """callTool('graq_reason') strips prefix to match bare_name='reason'."""
    call = _make_call("graq_reason")
    resolved, unresolved = resolve_cross_language(
        call_sites=[call],
        handlers=handlers,
        alias_map={},
        confidence_config=_TEST_CONFIDENCE_CONFIG,
    )
    assert len(resolved) == 1
    assert resolved[0].bare_name == "reason"
    assert resolved[0].resolution_path == "prefix_strip"


# ===========================================================================
# 3. test_alias_resolution
# ===========================================================================


def test_alias_resolution(
    handlers: list[MockHandler], alias_map: dict[str, str]
) -> None:
    """callTool('kogni_reason') resolves via alias map."""
    call = _make_call("kogni_reason")
    resolved, unresolved = resolve_cross_language(
        call_sites=[call],
        handlers=handlers,
        alias_map=alias_map,
        confidence_config=_TEST_CONFIDENCE_CONFIG,
    )
    assert len(resolved) == 1
    assert resolved[0].bare_name == "reason"
    assert resolved[0].resolution_path == "alias_strip"


# ===========================================================================
# 4. test_registry_fallback
# ===========================================================================


def test_registry_fallback(
    handlers: list[MockHandler], registry_bindings: dict[str, str]
) -> None:
    """Tool found via registry_bindings when no direct/prefix/alias match."""
    call = _make_call("special_tool")
    resolved, unresolved = resolve_cross_language(
        call_sites=[call],
        handlers=handlers,
        alias_map={},
        registry_bindings=registry_bindings,
        confidence_config=_TEST_CONFIDENCE_CONFIG,
    )
    assert len(resolved) == 1
    assert resolved[0].resolution_path == "registry_fallback"


# ===========================================================================
# 5. test_unresolved_missing_handler
# ===========================================================================


def test_unresolved_missing_handler(handlers: list[MockHandler]) -> None:
    """Unknown tool produces UnresolvedEdge with MISSING_HANDLER reason."""
    call = _make_call("totally_unknown_tool_xyz")
    resolved, unresolved = resolve_cross_language(
        call_sites=[call],
        handlers=handlers,
        alias_map={},
        confidence_config=_TEST_CONFIDENCE_CONFIG,
    )
    assert len(unresolved) == 1
    assert isinstance(unresolved[0], UnresolvedEdge)
    assert "MISSING" in unresolved[0].reason.upper() or "UNRESOLVED" in unresolved[0].reason.upper()


# ===========================================================================
# 6. test_unresolved_dynamic
# ===========================================================================


def test_unresolved_dynamic(handlers: list[MockHandler]) -> None:
    """is_dynamic=True call site produces UNRESOLVED_DYNAMIC."""
    call = _make_call("reason", is_dynamic=True)
    resolved, unresolved = resolve_cross_language(
        call_sites=[call],
        handlers=handlers,
        alias_map={},
        confidence_config=_TEST_CONFIDENCE_CONFIG,
    )
    assert len(unresolved) == 1
    assert "DYNAMIC" in unresolved[0].reason.upper()


# ===========================================================================
# 7. test_alias_map_builder
# ===========================================================================


def test_alias_map_builder() -> None:
    """build_alias_map produces kogni_* -> graq_* mappings."""
    handlers = _make_handlers("reason", "search")
    result = build_alias_map(handlers)
    assert "kogni_reason" in result
    assert result["kogni_reason"] == "graq_reason"
    assert "kogni_search" in result
    assert result["kogni_search"] == "graq_search"


# ===========================================================================
# 8. test_emit_skips_missing_target
# ===========================================================================


def test_emit_skips_missing_target() -> None:
    """emit_kg_edges skips edges when target node is not in graph."""
    call = _make_call("reason")
    handler = _make_handlers("reason")[0]
    edge = CrossLangEdge(
        source=call,
        target=handler,
        tool_name="reason",
        bare_name="reason",
    )

    graph = MagicMock()
    graph.has_node = MagicMock(side_effect=lambda n: n == "ts_node_1")

    stats = emit_kg_edges([edge], [], graph)
    assert stats["skipped"] >= 1


# ===========================================================================
# 9. test_emit_creates_valid_edge
# ===========================================================================


def test_emit_creates_valid_edge() -> None:
    """emit_kg_edges creates edge when both source and target nodes exist."""
    call = _make_call("reason")
    handler = _make_handlers("reason")[0]
    edge = CrossLangEdge(
        source=call,
        target=handler,
        tool_name="reason",
        bare_name="reason",
    )

    graph = MagicMock()
    graph.has_node = MagicMock(return_value=True)

    stats = emit_kg_edges([edge], [], graph)
    assert stats["created"] >= 1


# ===========================================================================
# 10. test_confidence_defaults_are_opaque
# ===========================================================================


def test_confidence_defaults_raise_configuration_error() -> None:
    """_load_confidence_config raises ConfigurationError when config is missing."""
    from graqle.scanner.mcp_linker import ConfigurationError

    with pytest.raises(ConfigurationError, match="missing or incomplete"):
        _load_confidence_config(config_path=Path("/nonexistent/path.json"))


# ===========================================================================
# 11. test_confidence_from_file
# ===========================================================================


def test_confidence_from_file(tmp_path: Path) -> None:
    """_load_confidence_config loads values from a JSON file."""
    conf_data = {
        "direct_match": CONF_DIRECT,
        "prefix_strip": CONF_PREFIX,
        "alias_strip": CONF_ALIAS,
        "registry_fallback": CONF_REGISTRY,
    }
    conf_file = tmp_path / "confidence.json"
    conf_file.write_text(json.dumps(conf_data))

    config = _load_confidence_config(config_path=conf_file)
    assert config["direct_match"] == CONF_DIRECT
    assert config["prefix_strip"] == CONF_PREFIX
    assert config["alias_strip"] == CONF_ALIAS
    assert config["registry_fallback"] == CONF_REGISTRY


# ===========================================================================
# 12. test_resolution_priority
# ===========================================================================


def test_resolution_priority() -> None:
    """Direct bare-name match wins over prefix_strip when both could match."""
    handlers = [
        MockHandler(bare_name="reason", node_id="py_reason"),
    ]
    # 'reason' matches directly, 'graq_reason' would match via prefix strip
    call_direct = _make_call("reason")
    call_prefix = _make_call("graq_reason")

    resolved_d, _ = resolve_cross_language([call_direct], handlers, alias_map={}, confidence_config=_TEST_CONFIDENCE_CONFIG)
    resolved_p, _ = resolve_cross_language([call_prefix], handlers, alias_map={}, confidence_config=_TEST_CONFIDENCE_CONFIG)

    assert len(resolved_d) == 1
    assert resolved_d[0].resolution_path == "direct_match"
    assert len(resolved_p) == 1
    assert resolved_p[0].resolution_path == "prefix_strip"


# ===========================================================================
# 13. test_unconfigured_confidence_goes_to_unresolved (B1 blocker fix)
# ===========================================================================


def test_unconfigured_confidence_raises() -> None:
    """When no confidence config exists, _load_confidence_config raises
    ConfigurationError (B1 blocker fix — fail-fast, not warn-and-continue)."""
    from graqle.scanner.mcp_linker import ConfigurationError

    handlers = _make_handlers("reason")
    call = _make_call("reason")
    # Deliberately omit confidence_config — defaults are None, raises on load
    with pytest.raises(ConfigurationError):
        resolve_cross_language(
            call_sites=[call],
            handlers=handlers,
            alias_map={},
            # No confidence_config → _load_confidence_config() → raises
        )
