"""Integration tests for cr-016 GRAQLE_WORKTREE_ROOT — exercise the env var
through the real KogniDevServer handlers that call
``_project_root_from_graph_file``.

Three concrete callsites in graqle.plugins.mcp_dev_server.KogniDevServer:

  - ``_handle_config_audit`` (line 7311 — ConfigDriftAuditor root)
  - ``_handle_gate_status`` (line 12436 — graqle-gate.py path check)
  - ``_handle_gate_install`` (line 12553 — graqle-gate.py install path)

Each handler reads ``self._graph_file`` and passes it to
``_project_root_from_graph_file`` to derive the directory under which it
looks for ``.gcc/``, ``.claude/hooks/graqle-gate.py``, ``.claude/settings.json``,
etc. With ``GRAQLE_WORKTREE_ROOT`` set, all of these directory lookups
must rebase to the worktree directory rather than the canonical project
root that ``_graph_file``'s parent would have produced.

The conftest fixture guarantees clean env baseline.
"""

# ── graqle:intelligence ──
# module: tests.test_plugins.test_worktree_root_integration
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, asyncio, os, tempfile, pathlib, json
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from graqle.plugins.mcp_dev_server import KogniDevServer


# -------------------------------------------------------------------------
# Direct-call integration: realistic _graph_file state, assert resolution
# matches what each handler would see when calling
# self._project_root_from_graph_file(self._graph_file).
# -------------------------------------------------------------------------


class TestEnvVarFlowsThroughHandlers:
    """Set GRAQLE_WORKTREE_ROOT, set realistic _graph_file values, and verify
    the path resolution that each handler does internally returns the
    worktree-root-rebased path."""

    def test_config_audit_handler_resolution_path(self, tmp_path):
        """Mirror the path resolution in _handle_config_audit @ line 7311:
            root = self._project_root_from_graph_file(
                getattr(self, "_graph_file", None)
            )
        With WORKTREE_ROOT set, root must equal WORKTREE_ROOT regardless
        of what _graph_file says.
        """
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        graph_dir = tmp_path / "canonical_graph_dir"
        graph_dir.mkdir()
        graph_json = graph_dir / "graqle.json"
        graph_json.write_text("{}")

        os.environ["GRAQLE_WORKTREE_ROOT"] = str(worktree)
        server = KogniDevServer(read_only=True)
        server._graph_file = str(graph_json)

        # Exact line the handler executes:
        root = server._project_root_from_graph_file(
            getattr(server, "_graph_file", None)
        )

        assert root == worktree.resolve()
        # Anti-assertion: NOT the graph_file's parent (the pre-cr-016 path).
        assert root != graph_dir.resolve()

    def test_gate_status_handler_resolution_path(self, tmp_path):
        """Mirror the path resolution in _handle_gate_status @ line 12436:
            project_root = self._project_root_from_graph_file(_raw)
            gate_path = project_root / ".claude" / "hooks" / "graqle-gate.py"
        Asserts the gate_path is under the worktree dir.
        """
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / ".claude" / "hooks").mkdir(parents=True)
        gate_file = worktree / ".claude" / "hooks" / "graqle-gate.py"
        gate_file.write_text("# stub gate")

        canonical = tmp_path / "canonical"
        canonical.mkdir()
        graph_json = canonical / "graqle.json"
        graph_json.write_text("{}")

        os.environ["GRAQLE_WORKTREE_ROOT"] = str(worktree)
        server = KogniDevServer(read_only=True)
        server._graph_file = str(graph_json)

        # Reproduce the handler's logic
        _raw = getattr(server, "_graph_file", None)
        project_root = server._project_root_from_graph_file(_raw)
        resolved_gate = project_root / ".claude" / "hooks" / "graqle-gate.py"

        assert project_root == worktree.resolve()
        # The stub gate file we created in the worktree exists at the
        # resolved path; if cr-016 weren't picked up, the handler would
        # look in `canonical/.claude/...` and find nothing.
        assert resolved_gate.exists()
        assert resolved_gate.read_text() == "# stub gate"

    def test_gate_install_handler_resolution_path(self, tmp_path):
        """Mirror the path resolution in _handle_gate_install @ line 12553."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        canonical = tmp_path / "canonical"
        canonical.mkdir()
        graph_json = canonical / "graqle.json"
        graph_json.write_text("{}")

        os.environ["GRAQLE_WORKTREE_ROOT"] = str(worktree)
        server = KogniDevServer(read_only=True)
        server._graph_file = str(graph_json)

        _raw = getattr(server, "_graph_file", None)
        project_root = server._project_root_from_graph_file(_raw)

        assert project_root == worktree.resolve()


# -------------------------------------------------------------------------
# Async handler integration: actually invoke the async handler, parse the
# JSON response, assert the embedded path matches WORKTREE_ROOT.
# -------------------------------------------------------------------------


class TestAsyncHandlerJSONResponse:
    """Exercise the async handler end-to-end; parse the response JSON;
    assert the resolved path appears in the output. This is the closest
    we can get in a unit test to the user-visible MCP-tool behaviour."""

    @pytest.mark.asyncio
    async def test_handle_gate_status_sees_worktree_gate_file(self, tmp_path):
        """Place a stub graqle-gate.py at worktree/.claude/hooks/ and NOT at
        canonical/.claude/hooks/. With GRAQLE_WORKTREE_ROOT set, the handler
        must report ``installed: True`` because it correctly looks under the
        worktree (where the file exists), not under canonical (where it
        doesn't).

        This proves the env var flows all the way through to the file-system
        lookup the handler performs after path resolution.
        """
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / ".claude" / "hooks").mkdir(parents=True)
        (worktree / ".claude" / "hooks" / "graqle-gate.py").write_text("# stub")

        canonical = tmp_path / "canonical"
        canonical.mkdir()
        # Intentionally NO .claude/hooks here.
        graph_json = canonical / "graqle.json"
        graph_json.write_text("{}")

        os.environ["GRAQLE_WORKTREE_ROOT"] = str(worktree)
        server = KogniDevServer(read_only=True)
        server._graph_file = str(graph_json)

        # self_test=False to skip subprocess + 5s timeout on a stub file.
        result_str = await server._handle_gate_status({"self_test": False})
        result = json.loads(result_str)

        # Discriminator: the handler found the gate file → it looked in the
        # worktree, not the canonical graph dir.
        assert result["installed"] is True, (
            f"Expected installed=True when gate file exists under worktree "
            f"and WORKTREE_ROOT is set. Got: {result}"
        )
        # Relative path is reported regardless (privacy invariant); just
        # sanity-check the schema.
        assert result["hook_path"].endswith("graqle-gate.py")

    @pytest.mark.asyncio
    async def test_handle_gate_status_no_env_var_falls_back_to_canonical(
        self, tmp_path
    ):
        """REGRESSION-CRITICAL: with GRAQLE_WORKTREE_ROOT unset, the handler
        must use the graph_file's parent. We place the gate file under
        ``canonical/`` (NOT worktree/), expect ``installed: True``."""
        canonical = tmp_path / "canonical"
        canonical.mkdir()
        (canonical / ".claude" / "hooks").mkdir(parents=True)
        (canonical / ".claude" / "hooks" / "graqle-gate.py").write_text("# stub")
        graph_json = canonical / "graqle.json"
        graph_json.write_text("{}")

        worktree = tmp_path / "worktree_unused"
        worktree.mkdir()
        # Intentionally NO .claude/hooks here. WORKTREE_ROOT also NOT set.

        # Belt-and-braces: conftest already guarantees the env is clean.
        assert "GRAQLE_WORKTREE_ROOT" not in os.environ

        server = KogniDevServer(read_only=True)
        server._graph_file = str(graph_json)

        # Direct-call cross-check
        root = server._project_root_from_graph_file(server._graph_file)
        assert root == canonical.resolve()

        # Handler must find the gate under canonical/
        result_str = await server._handle_gate_status({"self_test": False})
        result = json.loads(result_str)
        assert result["installed"] is True, (
            f"Expected installed=True when WORKTREE_ROOT unset and gate file "
            f"exists at canonical (graph_file parent). Got: {result}"
        )
