"""A2 (ADR-220-A) tests: the reasoning context-dimension scope filter.

`_filter_nodes_by_dimension` narrows the activated node set to the user-selected
Studio dimension chip(s). Entity-type sets are grounded in the live KG type
distribution (APIEndpoint, DatabaseModel, Config/EnvVar, TestFile, PythonModule…).
The filter must: honour 'all'/absent as no-op, match by type OR path OR label, and
NEVER return an empty list (degrade to unscoped rather than starve reasoning).
"""

from __future__ import annotations

from types import SimpleNamespace

from graqle.studio.routes.api import _filter_nodes_by_dimension


class _FakeGraph:
    """A graph whose nodes carry id, entity_type, label, and optional path prop."""

    def __init__(self, nodes: dict[str, SimpleNamespace]):
        self.nodes = nodes


def _node(entity_type="Function", label="", path=None):
    props = {"path": path} if path else {}
    return SimpleNamespace(entity_type=entity_type, label=label, properties=props)


def _graph():
    return _FakeGraph({
        "pkg/api/users.py::list_users": _node("APIEndpoint", "list_users", "pkg/api/users.py"),
        "pkg/models/user.py::User": _node("DatabaseModel", "User", "pkg/models/user.py"),
        "tests/test_user.py::test_create": _node("TestFile", "test_create", "tests/test_user.py"),
        "pkg/settings.py::DEBUG": _node("Config", "DEBUG", "pkg/settings.py"),
        "pkg/core/graph.py": _node("PythonModule", "graph", "pkg/core/graph.py"),
        "pkg/auth/login.py::authenticate": _node("Function", "authenticate", "pkg/auth/login.py"),
        "pkg/util/math.py::add": _node("Function", "add", "pkg/util/math.py"),
    })


ALL_IDS = [
    "pkg/api/users.py::list_users",
    "pkg/models/user.py::User",
    "tests/test_user.py::test_create",
    "pkg/settings.py::DEBUG",
    "pkg/core/graph.py",
    "pkg/auth/login.py::authenticate",
    "pkg/util/math.py::add",
]


# ----------------------------- no-op cases --------------------------------- #

def test_none_dimensions_is_noop():
    assert _filter_nodes_by_dimension(_graph(), ALL_IDS, None) == ALL_IDS


def test_empty_list_is_noop():
    assert _filter_nodes_by_dimension(_graph(), ALL_IDS, []) == ALL_IDS


def test_all_dimension_is_noop():
    assert _filter_nodes_by_dimension(_graph(), ALL_IDS, ["all"]) == ALL_IDS
    assert _filter_nodes_by_dimension(_graph(), ALL_IDS, ["architecture", "all"]) == ALL_IDS


def test_unknown_dimension_is_noop():
    assert _filter_nodes_by_dimension(_graph(), ALL_IDS, ["nonsense"]) == ALL_IDS


def test_non_list_is_noop():
    assert _filter_nodes_by_dimension(_graph(), ALL_IDS, "security") == ALL_IDS


# ----------------------------- scoping cases ------------------------------- #

def test_api_dimension_selects_endpoint():
    out = _filter_nodes_by_dimension(_graph(), ALL_IDS, ["api"])
    assert "pkg/api/users.py::list_users" in out
    assert "pkg/util/math.py::add" not in out
    assert "pkg/models/user.py::User" not in out


def test_data_model_dimension_selects_databasemodel():
    out = _filter_nodes_by_dimension(_graph(), ALL_IDS, ["data-model"])
    assert out == ["pkg/models/user.py::User"]


def test_testing_dimension_selects_testfile():
    out = _filter_nodes_by_dimension(_graph(), ALL_IDS, ["testing"])
    assert "tests/test_user.py::test_create" in out
    assert "pkg/util/math.py::add" not in out


def test_config_dimension_selects_config():
    out = _filter_nodes_by_dimension(_graph(), ALL_IDS, ["config"])
    assert "pkg/settings.py::DEBUG" in out


def test_architecture_dimension_selects_module():
    out = _filter_nodes_by_dimension(_graph(), ALL_IDS, ["architecture"])
    assert "pkg/core/graph.py" in out


def test_security_dimension_is_heuristic_on_path_label():
    # No exclusive type — 'authenticate' in pkg/auth/login.py matches via path+label.
    out = _filter_nodes_by_dimension(_graph(), ALL_IDS, ["security"])
    assert "pkg/auth/login.py::authenticate" in out
    assert "pkg/util/math.py::add" not in out


def test_multiple_dimensions_union():
    out = _filter_nodes_by_dimension(_graph(), ALL_IDS, ["api", "testing"])
    assert "pkg/api/users.py::list_users" in out
    assert "tests/test_user.py::test_create" in out
    assert "pkg/util/math.py::add" not in out


# ----------------------------- never-empty guard --------------------------- #

def test_never_returns_empty_falls_back_to_unscoped():
    # A graph with only a generic util fn; 'data-model' matches nothing -> must
    # return the original list, not [].
    g = _FakeGraph({"pkg/util/math.py::add": _node("Function", "add", "pkg/util/math.py")})
    ids = ["pkg/util/math.py::add"]
    assert _filter_nodes_by_dimension(g, ids, ["data-model"]) == ids


def test_huge_dimension_list_does_not_crash():
    # Defence-in-depth: even if a large list reaches the helper (the route caps it
    # to 20), the helper must handle it without error. Unknown ids => no-op.
    out = _filter_nodes_by_dimension(_graph(), ALL_IDS, [f"junk{i}" for i in range(5000)])
    assert out == ALL_IDS


def test_non_string_elements_ignored():
    out = _filter_nodes_by_dimension(_graph(), ALL_IDS, [123, None, "api"])
    assert "pkg/api/users.py::list_users" in out
    assert "pkg/util/math.py::add" not in out


def test_missing_node_is_skipped_not_crash():
    g = _graph()
    ids = ALL_IDS + ["does/not/exist::ghost"]
    out = _filter_nodes_by_dimension(g, ids, ["api"])
    assert "does/not/exist::ghost" not in out
    assert "pkg/api/users.py::list_users" in out
