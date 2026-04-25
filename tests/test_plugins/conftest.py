"""Shared fixtures for tests/test_plugins/.

R22 SHACL gate defaults ON (fail-closed). Unit tests that call handle_tool()
on bare KogniDevServer instances (no governance trace) would all be blocked.
This module-level autouse fixture disables the gate for the whole directory.
"""
import pytest


@pytest.fixture(autouse=True)
def _disable_shacl_gate():
    """Disable R22 SHACL gate for bare-server unit tests in this directory."""
    import graqle.plugins.mcp_dev_server as _mds
    old = _mds._SHACL_GATE_ENABLED
    _mds._SHACL_GATE_ENABLED = False
    yield
    _mds._SHACL_GATE_ENABLED = old
