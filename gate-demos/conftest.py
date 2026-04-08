"""Shared fixtures for gate demo tests.

Creates a REAL KogniDevServer with governance config loaded from graqle.yaml.
No mocks — the server instance is the same one that runs in production MCP.
"""

import json
import pytest
from pathlib import Path

# Find the graqle-sdk root (where graqle.yaml lives)
SDK_ROOT = Path(__file__).parent.parent
CONFIG_PATH = SDK_ROOT / "graqle.yaml"


@pytest.fixture
def fresh_server():
    """Create a fresh KogniDevServer with NO session started and NO plan active.

    This gives each test a clean slate to verify gate enforcement.
    The server loads the real graqle.yaml config (with governance section).
    """
    from graqle.plugins.mcp_dev_server import KogniDevServer

    server = KogniDevServer.__new__(KogniDevServer)
    server.__init__(config_path=str(CONFIG_PATH))

    # Force config load so governance gates are available
    server._load_graph()

    # Verify governance is loaded
    gov = getattr(getattr(server, "_config", None), "governance", None)
    assert gov is not None, (
        "Governance config not found in graqle.yaml. "
        "Add a 'governance:' section with session_gate_enabled, plan_mandatory, etc."
    )

    return server


@pytest.fixture
def server_with_session(fresh_server):
    """Server with session started (CG-01 passed) but NO plan active."""
    fresh_server._session_started = True
    return fresh_server


@pytest.fixture
def server_with_plan(server_with_session):
    """Server with session started AND plan active (CG-01 + CG-02 passed)."""
    server_with_session._plan_active = True
    return server_with_session


def parse_response(raw: str) -> dict:
    """Parse JSON response from handle_tool, stripping tool_hints wrapper."""
    return json.loads(raw)
