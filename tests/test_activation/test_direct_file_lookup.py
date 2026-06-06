"""Regression tests for Graqle._direct_file_lookup.

These lock in the 2026-06-06 fix (graph-fix CR): _direct_file_lookup must match
on FILENAMES extracted from node IDs (the path), NOT node labels. In real graphs
labels are symbol/description names, so label-based matching never matched a file
and false-fired on incidental query words ("gate", "api", "dashboard"), shadowing
the semantic CypherActivation path. It must also NOT over-activate on common
basenames like __init__.py shared across many packages.

V-MARKER: V-GRAPH-FIX-NATIVE-003 — new test file created via native Write
(graq_generate S-010 path-resolution gap on this Neo4j-backed session).
"""

import pytest

from graqle.core.graph import Graqle
from graqle.core.node import CogniNode


def _graph(node_ids):
    g = Graqle()
    for nid in node_ids:
        # label = bare symbol/module name, mirroring how real graphs are built
        # (labels are NEVER filenames — that was the root cause of the bug).
        label = nid.split("::", 1)[-1] if "::" in nid else nid.rsplit("/", 1)[-1]
        g.add_node(
            CogniNode(
                id=nid,
                label=label,
                entity_type="Function" if "::" in nid else "PythonModule",
                description=label,
            )
        )
    return g


class TestDirectFileLookupMatchesNodeIdPath:
    def test_named_file_activates_its_nodes(self):
        g = _graph([
            "studio_backend/dashboard/read_api.py",
            "studio_backend/dashboard/read_api.py::get_proof",
            "studio_backend/dashboard/read_api.py::require_role",
            "graqle/studio/routes/dashboard.py::dashboard",
        ])
        hits = g._direct_file_lookup("explain read_api.py")
        assert hits is not None
        assert "studio_backend/dashboard/read_api.py::get_proof" in hits
        # Unrelated dashboard.py node must NOT be activated.
        assert "graqle/studio/routes/dashboard.py::dashboard" not in hits

    def test_full_path_in_query_activates(self):
        g = _graph([
            "studio_backend/dashboard/read_api.py::get_proof",
            "studio_backend/dashboard/read_api.py::get_usage",
        ])
        hits = g._direct_file_lookup(
            "what does studio_backend/dashboard/read_api.py do"
        )
        assert hits is not None
        assert "studio_backend/dashboard/read_api.py::get_proof" in hits


class TestDirectFileLookupNoFalseFire:
    def test_english_word_matching_a_basename_does_not_fire(self):
        # 'gate' is a real bare token of gate.py, but the query is English prose,
        # not a file reference. Old code false-fired; the fix returns None.
        g = _graph([
            "graqle/intelligence/gate.py::list",
            "graqle/intelligence/gate.py::get_impact",
        ])
        assert g._direct_file_lookup("how does the role gate access work") is None

    def test_api_substring_inside_read_api_does_not_match_api_py(self):
        # 'api.py' must NOT match inside the word 'read_api' (word-boundary guard).
        g = _graph([
            "graqle/studio/routes/api.py::studio_chat",
            "studio_backend/dashboard/read_api.py::get_proof",
        ])
        hits = g._direct_file_lookup("how does read_api handle tenants")
        # 'read_api' (no extension) is prose here -> no filename token -> None.
        assert hits is None

    def test_pure_semantic_query_returns_none(self):
        g = _graph([
            "studio_backend/dashboard/read_api.py::get_proof",
        ])
        assert g._direct_file_lookup(
            "how do we stop one tenant reading another tenant's data"
        ) is None


class TestDirectFileLookupCommonBasenameGuard:
    def test_bare_common_basename_does_not_explode(self):
        # Many __init__.py across packages. A bare '__init__.py' query must NOT
        # seed all of them.
        ids = [f"pkg{i}/__init__.py::x" for i in range(40)]
        g = _graph(ids)
        hits = g._direct_file_lookup("what is in __init__.py")
        assert hits is None

    def test_path_scoped_common_basename_matches_only_that_package(self):
        ids = [f"pkg{i}/__init__.py::x" for i in range(40)]
        ids.append("studio_backend/metering/__init__.py")
        g = _graph(ids)
        hits = g._direct_file_lookup(
            "what is in studio_backend/metering/__init__.py"
        )
        assert hits is not None
        assert "studio_backend/metering/__init__.py" in hits
        # Must not have pulled in the 40 unrelated __init__.py nodes.
        assert all("pkg" not in h or "metering" in h for h in hits)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
