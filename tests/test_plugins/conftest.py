"""Shared fixtures for tests/test_plugins/.

This conftest exists primarily to ensure environment-variable isolation for
the cr-016 GRAQLE_WORKTREE_ROOT test suite. Without this, env vars set by
the CI runner (or leaked from prior tests within the same pytest process)
would silently pollute test outcomes and produce flaky precedence assertions.

The fixture is module-scoped to ``autouse=True`` so every test under
``tests/test_plugins/`` starts with a guaranteed-clean environment for the
three env vars that ``_project_root_from_graph_file`` consults:

  - ``GRAQLE_WORKTREE_ROOT``  (cr-016, highest priority)
  - ``GRAQLE_SERVE_CWD``       (existing, mid-priority)
  - ``GRAQLE_GRAPHS_BUCKET``   (defensive — used elsewhere in mcp_dev_server)

We snapshot+restore the FULL ``os.environ`` to defend against tests that
might set unrelated env vars (e.g., AWS_PROFILE) that pollute downstream.
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

    The fixture also asserts post-test that no test leaked one of the
    cr-016 env vars without explicit cleanup; a leak fails the test loudly
    rather than silently polluting subsequent tests.
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
