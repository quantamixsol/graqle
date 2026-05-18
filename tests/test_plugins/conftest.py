"""Shared fixtures for tests/test_plugins/.

Two autouse fixtures compose at directory scope:

  1. ``_disable_shacl_gate`` (pre-cr-016) — R22 SHACL gate defaults to ON
     (fail-closed) in production code. Unit tests that call ``handle_tool()``
     on bare ``KogniDevServer`` instances (no governance trace established)
     would all be blocked. The fixture flips the gate off for every test
     under this directory and restores the original value on teardown.

  2. ``_cr016_env_isolation`` (cr-016) — guarantees a clean environment for
     ``GRAQLE_WORKTREE_ROOT``, ``GRAQLE_SERVE_CWD``, and ``GRAQLE_GRAPHS_BUCKET``
     before each test. Defends against CI-runner env pollution and cross-test
     leaks when exercising ``_project_root_from_graph_file``.

Both fixtures are independent and run in pytest's natural ordering.
"""

# ── graqle:intelligence ──
# module: tests.test_plugins.conftest
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, os
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import os

import pytest


# -------------------------------------------------------------------------
# Fixture 1: R22 SHACL gate disable (pre-cr-016, from public master)
# -------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _disable_shacl_gate():
    """Disable R22 SHACL gate for bare-server unit tests in this directory."""
    import graqle.plugins.mcp_dev_server as _mds
    old = _mds._SHACL_GATE_ENABLED
    _mds._SHACL_GATE_ENABLED = False
    yield
    _mds._SHACL_GATE_ENABLED = old


# -------------------------------------------------------------------------
# Fixture 2: cr-016 env-var isolation (GRAQLE_WORKTREE_ROOT et al.)
# -------------------------------------------------------------------------


# Env vars cr-016 cares about. Cleared at fixture entry; original values
# (if any) restored at teardown.
_CR016_ENV_VARS = (
    "GRAQLE_WORKTREE_ROOT",
    "GRAQLE_SERVE_CWD",
    "GRAQLE_GRAPHS_BUCKET",
)


@pytest.fixture(autouse=True)
def _cr016_env_isolation():
    """Guarantee a clean env for the 3 cr-016-relevant env vars.

    Snapshot original values, unset for the test body, restore on teardown.
    Uses os.environ.pop + setdefault rather than ``patch.dict`` so that any
    test that legitimately needs to set these vars (via monkeypatch.setenv
    or ``os.environ[...] = ...``) sees a clean baseline.
    """
    snapshot: dict[str, str | None] = {
        var: os.environ.get(var) for var in _CR016_ENV_VARS
    }
    for var in _CR016_ENV_VARS:
        os.environ.pop(var, None)
    try:
        yield
    finally:
        for var, value in snapshot.items():
            if value is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = value
