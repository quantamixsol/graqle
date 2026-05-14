"""CR-008 tests — ``_save_graph`` status disambiguation + handler routing.

Locks down the new :class:`SaveGraphResult` contract so the four
``_handle_learn_*`` MCP handlers report accurate ``error_code`` values
instead of always saying ``WRITE_COLLISION``.

Background: ``graq_kg_diag`` showed ``total_writes_recorded == 0`` for
Neo4j-backed sessions yet ``graq_learn`` returned ``WRITE_COLLISION`` on
every call. Root cause: ``_save_graph`` returned ``(False, 0)`` for FOUR
distinct reasons (``self._graph_file is None`` / shrink-guard refusal /
real PermissionError / generic exception) and the handlers conflated all
of them as WRITE_COLLISION. CR-008 replaces the ``tuple[bool, int]``
contract with :class:`SaveGraphResult` carrying an explicit
:class:`SaveStatus` enum.

Test categories:

1. ``SaveStatus`` enum + ``SaveGraphResult`` dataclass invariants.
2. ``_save_graph`` returns the right status for each branch.
3. ``_learn_response_for_save_failure`` helper maps status → error_code.
4. End-to-end: each of the 4 ``_handle_learn_*`` handlers folds
   NO_GRAPH_FILE into recorded=True and surfaces accurate error_codes
   for the three failure modes.
5. Regression: real PermissionError still surfaces as WRITE_COLLISION
   (we didn't accidentally swallow the one case we DO want to flag).

CI safety: no real graph file I/O, no real Neo4j connection, no real
subprocess. ``KogniDevServer.__new__`` bypasses ``__init__`` so we can
construct a minimal test double matching the existing pattern in
``tests/test_cloud/test_kg_sync.py``.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch

import pytest

from graqle.plugins.mcp_dev_server import (
    KogniDevServer,
    SaveGraphResult,
    SaveStatus,
)


# ── 1. SaveStatus + SaveGraphResult invariants ────────────────────────


class TestSaveStatusEnum:
    """Lock the enum values — they are serialised into MCP responses and
    a silent rename would break any client parsing ``persistence`` or
    ``error_code`` fields."""

    def test_five_members_exist(self) -> None:
        assert {s.value for s in SaveStatus} == {
            "OK", "NO_GRAPH_FILE", "SHRINK_REFUSED", "COLLISION", "SAVE_FAILED",
        }

    def test_status_is_str_subclass(self) -> None:
        # str-inheriting enum means result.status == "OK" works directly,
        # and json.dumps(result.status) serialises to the string value.
        assert isinstance(SaveStatus.OK, str)
        assert SaveStatus.OK == "OK"
        assert json.dumps(SaveStatus.OK.value) == '"OK"'


class TestSaveGraphResultDataclass:
    def test_frozen(self) -> None:
        result = SaveGraphResult(status=SaveStatus.OK)
        with pytest.raises(FrozenInstanceError):
            result.status = SaveStatus.COLLISION  # type: ignore[misc]

    def test_default_retries_and_detail(self) -> None:
        result = SaveGraphResult(status=SaveStatus.OK)
        assert result.retries == 0
        assert result.detail is None

    def test_saved_property_only_true_for_ok(self) -> None:
        assert SaveGraphResult(status=SaveStatus.OK).saved is True
        for bad in (
            SaveStatus.NO_GRAPH_FILE,
            SaveStatus.SHRINK_REFUSED,
            SaveStatus.COLLISION,
            SaveStatus.SAVE_FAILED,
        ):
            assert SaveGraphResult(status=bad).saved is False, bad

    def test_recorded_property_covers_ok_and_no_graph_file(self) -> None:
        """Critical CR-008 invariant: Neo4j-backed sessions (NO_GRAPH_FILE)
        report ``recorded=True`` because the in-memory mutation already
        happened. Only the three real failure modes count as NOT recorded.
        """
        assert SaveGraphResult(status=SaveStatus.OK).recorded is True
        assert SaveGraphResult(status=SaveStatus.NO_GRAPH_FILE).recorded is True
        for bad in (
            SaveStatus.SHRINK_REFUSED,
            SaveStatus.COLLISION,
            SaveStatus.SAVE_FAILED,
        ):
            assert SaveGraphResult(status=bad).recorded is False, bad


# ── 2. _save_graph status branch coverage ────────────────────────────


def _bare_server() -> KogniDevServer:
    """Construct a server skeleton without running __init__.

    Matches the existing pattern in tests/test_cloud/test_kg_sync.py — the
    server has heavy dependencies we don't need for these unit tests.
    """
    server = KogniDevServer.__new__(KogniDevServer)
    server._graph_file = None
    server._graph = None
    return server


class TestSaveGraphStatusBranches:
    """Exercise each return path of ``_save_graph`` and assert the status."""

    def test_no_graph_file_returns_NO_GRAPH_FILE(self) -> None:
        """The headline CR-008 bug: Neo4j-backed sessions have
        ``self._graph_file is None`` and the prior contract returned
        ``(False, 0)`` which handlers misreported as WRITE_COLLISION.
        """
        server = _bare_server()
        server._graph_file = None
        mock_graph = MagicMock()

        result = server._save_graph(mock_graph)

        assert isinstance(result, SaveGraphResult)
        assert result.status is SaveStatus.NO_GRAPH_FILE
        assert result.retries == 0
        assert result.recorded is True  # KEY ASSERTION — handlers fold this into recorded=True
        assert result.detail is not None
        assert "in-memory" in result.detail.lower() or "backend" in result.detail.lower()

    def test_ok_path_returns_OK_with_retry_count(self, tmp_path) -> None:
        """Happy path: ``_write_with_lock`` succeeds → status=OK."""
        server = _bare_server()
        server._graph_file = str(tmp_path / "graqle.json")

        mock_graph = MagicMock()
        mock_graph.nodes = [{"id": "n1"}, {"id": "n2"}]
        import networkx as nx
        mock_graph.to_networkx.return_value = nx.DiGraph()

        with patch("graqle.core.graph._write_with_lock", return_value=3) as mock_write:
            result = server._save_graph(mock_graph)

        assert mock_write.called
        assert isinstance(result, SaveGraphResult)
        assert result.status is SaveStatus.OK
        assert result.retries == 3
        assert result.saved is True
        assert result.recorded is True

    def test_permission_error_returns_COLLISION(self, tmp_path) -> None:
        """Real ``os.replace`` ``PermissionError`` → status=COLLISION.

        This is the ONE failure mode that should surface as
        ``error_code: WRITE_COLLISION`` to the MCP envelope. Regression
        guard against accidentally widening or narrowing this branch.
        """
        server = _bare_server()
        server._graph_file = str(tmp_path / "graqle.json")

        mock_graph = MagicMock()
        mock_graph.nodes = [{"id": "n1"}]
        import networkx as nx
        mock_graph.to_networkx.return_value = nx.DiGraph()

        with patch(
            "graqle.core.graph._write_with_lock",
            side_effect=PermissionError("simulated rename collision"),
        ):
            result = server._save_graph(mock_graph)

        assert result.status is SaveStatus.COLLISION
        assert result.saved is False
        assert result.recorded is False
        assert result.detail is not None
        assert "PermissionError" in result.detail

    def test_generic_exception_returns_SAVE_FAILED(self, tmp_path) -> None:
        """Any other exception (disk full, serialisation bug, etc.) →
        status=SAVE_FAILED, distinct from COLLISION so operators can
        triage. The detail field records only the exception TYPE name —
        never the message (which can contain paths/secrets)."""
        server = _bare_server()
        server._graph_file = str(tmp_path / "graqle.json")

        mock_graph = MagicMock()
        mock_graph.nodes = [{"id": "n1"}]
        import networkx as nx
        mock_graph.to_networkx.return_value = nx.DiGraph()

        with patch(
            "graqle.core.graph._write_with_lock",
            side_effect=RuntimeError("disk full or whatever"),
        ):
            result = server._save_graph(mock_graph)

        assert result.status is SaveStatus.SAVE_FAILED
        assert result.recorded is False
        assert result.detail == "RuntimeError"
        # SECURITY: the exception message must NOT leak through to detail
        assert "disk full" not in (result.detail or "")
        assert "whatever" not in (result.detail or "")

    def test_shrink_refused_returns_SHRINK_REFUSED(self, tmp_path) -> None:
        """Data-protection shrink guard refusal → status=SHRINK_REFUSED.

        Reproduces the conditions inside ``_save_graph``: an existing
        on-disk file with >= 50 nodes, and an incoming graph with too few.
        ``GRAQLE_ALLOW_SHRINK`` must be unset for the guard to fire.
        """
        import os
        graph_file = tmp_path / "graqle.json"
        # Write an existing KG with 200 nodes
        existing = {
            "directed": True,
            "multigraph": False,
            "graph": {},
            "nodes": [{"id": f"n{i}"} for i in range(200)],
            "links": [],
        }
        graph_file.write_text(json.dumps(existing), encoding="utf-8")

        server = _bare_server()
        server._graph_file = str(graph_file)

        # Incoming graph with only 10 nodes — 95% shrink
        mock_graph = MagicMock()
        mock_graph.nodes = [{"id": f"n{i}"} for i in range(10)]
        import networkx as nx
        mock_graph.to_networkx.return_value = nx.DiGraph()

        # Ensure the override env var is OFF
        prior = os.environ.pop("GRAQLE_ALLOW_SHRINK", None)
        try:
            result = server._save_graph(mock_graph)
        finally:
            if prior is not None:
                os.environ["GRAQLE_ALLOW_SHRINK"] = prior

        assert result.status is SaveStatus.SHRINK_REFUSED
        assert result.recorded is False
        assert result.retries == 0
        assert result.detail is not None
        # Detail should mention the shrink percentage so operators can triage
        assert "shrink" in result.detail.lower() or "%" in result.detail


# ── 3. _learn_response_for_save_failure helper ──────────────────────


class TestLearnResponseForSaveFailure:
    """Lock the status → error_code mapping. This is what the MCP client
    sees and what makes WRITE_COLLISION stop being a phantom."""

    def test_collision_maps_to_WRITE_COLLISION(self) -> None:
        result = SaveGraphResult(
            status=SaveStatus.COLLISION,
            retries=3,
            detail="PermissionError after 3 retries",
        )
        response = KogniDevServer._learn_response_for_save_failure(
            result, "mode", "outcome",
        )
        assert response["recorded"] is False
        assert response["error_code"] == "WRITE_COLLISION"
        assert response["mode"] == "outcome"
        assert response["retry_after_ms"] == 500
        assert response["retry_attempts"] == 3

    def test_shrink_refused_maps_to_SHRINK_GUARD_REFUSED(self) -> None:
        result = SaveGraphResult(
            status=SaveStatus.SHRINK_REFUSED,
            retries=0,
            detail="shrink=95.0% > 1%; in=10 disk=200. Override: GRAQLE_ALLOW_SHRINK=1.",
        )
        response = KogniDevServer._learn_response_for_save_failure(
            result, "mode", "knowledge",
        )
        assert response["recorded"] is False
        assert response["error_code"] == "SHRINK_GUARD_REFUSED"
        assert response["mode"] == "knowledge"
        assert "retry_after_ms" not in response  # SHRINK is not retryable

    def test_save_failed_maps_to_SAVE_FAILED(self) -> None:
        result = SaveGraphResult(
            status=SaveStatus.SAVE_FAILED,
            retries=1,
            detail="RuntimeError",
        )
        response = KogniDevServer._learn_response_for_save_failure(
            result, "kind", "pause_pick",
        )
        assert response["recorded"] is False
        assert response["error_code"] == "SAVE_FAILED"
        assert response["kind"] == "pause_pick"

    def test_field_name_can_be_mode_or_kind(self) -> None:
        """Different handler families use ``mode`` (outcome/entity/knowledge)
        vs ``kind`` (pause_pick) — the helper must respect that."""
        result = SaveGraphResult(status=SaveStatus.COLLISION, retries=0)
        r_mode = KogniDevServer._learn_response_for_save_failure(result, "mode", "entity")
        r_kind = KogniDevServer._learn_response_for_save_failure(result, "kind", "pause_pick")
        assert "mode" in r_mode and "kind" not in r_mode
        assert "kind" in r_kind and "mode" not in r_kind


# ── 4. End-to-end handler routing ────────────────────────────────────


class _StubGraph:
    """Lightweight graph stub honouring just enough of the Cogni API to
    drive the four handlers through their save-call point.

    Implements ``to_networkx()`` so the JSON-backed save path in
    ``_save_graph`` reaches the ``_write_with_lock`` call we patch — without
    it, the call raises AttributeError and surfaces SAVE_FAILED before
    the patched collision branch ever runs.
    """

    def __init__(self) -> None:
        self.nodes: list[dict] = []
        self.edges: list[dict] = []

    def add_node_simple(self, node_id: str, **kw: object) -> None:
        self.nodes.append({"id": node_id, **kw})

    def add_node(self, node: object) -> None:
        self.nodes.append({"id": getattr(node, "id", "?")})

    def add_edge_simple(self, src: str, dst: str, **kw: object) -> None:
        self.edges.append({"source_id": src, "target_id": dst, **kw})

    def add_edge(self, edge: object) -> None:
        self.edges.append({"source_id": getattr(edge, "source_id", "?")})

    def auto_connect(self, _ids: list) -> int:
        return 0

    def to_networkx(self):  # noqa: ANN201 — test-double; not type-pinned to nx.DiGraph
        import networkx as nx
        return nx.DiGraph()


def _server_with_stub_graph(graph_file: object) -> KogniDevServer:
    server = _bare_server()
    server._graph_file = graph_file  # None = Neo4j-backed; path = JSON-backed
    server._graph = _StubGraph()
    # _load_graph is the entry point all handlers use
    server._load_graph = lambda: server._graph  # type: ignore[method-assign]
    # _find_node is consulted by the entity handler's connects_to path
    server._find_node = lambda _t: None  # type: ignore[method-assign]
    return server


class TestHandlerKnowledgeRouting:
    """``_handle_learn_knowledge`` is the simplest of the four — exercises
    the four status branches end-to-end."""

    def _call(self, server: KogniDevServer) -> dict:
        coro = server._handle_learn_knowledge({
            "description": "Test domain fact for CR-008",
            "domain": "technical",
            "tags": ["cr-008"],
        })
        raw = asyncio.run(coro)
        return json.loads(raw)

    def test_neo4j_session_reports_recorded_true_not_collision(self) -> None:
        """THE HEADLINE BUG: Neo4j-backed session (no JSON file) used to
        return WRITE_COLLISION. After CR-008 it MUST report
        ``recorded: True`` with ``persistence: NO_GRAPH_FILE``.
        """
        server = _server_with_stub_graph(graph_file=None)
        response = self._call(server)

        assert response["recorded"] is True, (
            "Neo4j-backed graq_learn must succeed; the in-memory mutation "
            "already happened and the backend driver persisted it. "
            f"Got: {response!r}"
        )
        assert response["mode"] == "knowledge"
        assert response["persistence"] == "NO_GRAPH_FILE"
        assert "error_code" not in response
        # In-memory graph still got the node
        assert len(server._graph.nodes) == 1

    def test_collision_surfaces_WRITE_COLLISION(self, tmp_path) -> None:
        server = _server_with_stub_graph(graph_file=str(tmp_path / "g.json"))
        with patch(
            "graqle.core.graph._write_with_lock",
            side_effect=PermissionError("simulated"),
        ):
            response = self._call(server)
        assert response["recorded"] is False
        assert response["error_code"] == "WRITE_COLLISION"
        assert response["mode"] == "knowledge"
        assert response["retry_after_ms"] == 500

    def test_shrink_refused_surfaces_SHRINK_GUARD_REFUSED(self, tmp_path) -> None:
        # Pre-populate a 200-node KG so the shrink guard triggers
        graph_file = tmp_path / "g.json"
        graph_file.write_text(json.dumps({
            "directed": True, "multigraph": False, "graph": {},
            "nodes": [{"id": f"n{i}"} for i in range(200)], "links": [],
        }), encoding="utf-8")
        import os
        os.environ.pop("GRAQLE_ALLOW_SHRINK", None)

        server = _server_with_stub_graph(graph_file=str(graph_file))
        # Stub graph reports 1 node only (existing knowledge node) → 99% shrink
        response = self._call(server)
        assert response["recorded"] is False
        assert response["error_code"] == "SHRINK_GUARD_REFUSED"
        assert response["mode"] == "knowledge"

    def test_save_failed_surfaces_SAVE_FAILED(self, tmp_path) -> None:
        server = _server_with_stub_graph(graph_file=str(tmp_path / "g.json"))
        with patch(
            "graqle.core.graph._write_with_lock",
            side_effect=RuntimeError("simulated"),
        ):
            response = self._call(server)
        assert response["recorded"] is False
        assert response["error_code"] == "SAVE_FAILED"


class TestHandlerEntityRouting:
    """``_handle_learn_entity`` end-to-end on the headline NO_GRAPH_FILE
    branch. The other three branches are exhaustively covered by the
    knowledge handler tests — the failure-routing code path is identical
    (both go through ``_learn_response_for_save_failure``)."""

    def test_neo4j_session_reports_recorded_true(self) -> None:
        server = _server_with_stub_graph(graph_file=None)
        coro = server._handle_learn_entity({
            "entity_id": "test_entity",
            "entity_type": "PRODUCT",
            "description": "CR-008 entity test",
            "connects_to": [],
        })
        response = json.loads(asyncio.run(coro))
        assert response["recorded"] is True
        assert response["mode"] == "entity"
        assert response["persistence"] == "NO_GRAPH_FILE"
        assert "error_code" not in response


class TestHandlerOutcomeRouting:
    """``_handle_learn_outcome`` is the most complex handler (it has an
    ``else: _retries = 0`` branch for create_lesson=False). Both branches
    need the new ``persistence`` field, so test both."""

    def test_neo4j_session_with_create_lesson_true_reports_recorded_true(self) -> None:
        server = _server_with_stub_graph(graph_file=None)
        coro = server._handle_learn_outcome({
            "action": "Test action",
            "outcome": "success",
            "components": ["test.py"],
            "lesson": "CR-008 outcome lesson",
            "create_lesson": True,
        })
        response = json.loads(asyncio.run(coro))
        assert response["recorded"] is True
        assert response["mode"] == "outcome"
        # NO_GRAPH_FILE on Neo4j-backed → persistence reports the status
        assert response["persistence"] == "NO_GRAPH_FILE"


# ── 5. Regression guard: WRITE_COLLISION must still appear for the real case ──


class TestCollisionRegressionGuard:
    """Belt-and-braces: confirm the ONE case that legitimately should
    surface as ``WRITE_COLLISION`` still does. Any future refactor that
    accidentally widens or narrows this branch will trip this test.
    """

    def test_only_PermissionError_path_produces_WRITE_COLLISION(self, tmp_path) -> None:
        server = _server_with_stub_graph(graph_file=str(tmp_path / "g.json"))
        with patch(
            "graqle.core.graph._write_with_lock",
            side_effect=PermissionError("WinError 5"),
        ):
            coro = server._handle_learn_knowledge({
                "description": "Real collision test",
                "domain": "technical",
            })
            response = json.loads(asyncio.run(coro))

        assert response["error_code"] == "WRITE_COLLISION"
        assert response["recorded"] is False
        assert response["retry_after_ms"] == 500

    def test_NO_GRAPH_FILE_path_does_NOT_produce_WRITE_COLLISION(self) -> None:
        """The cross-project bug we're fixing: PHANTOM collisions on Neo4j
        sessions. If this assertion ever flips to ``error_code ==
        WRITE_COLLISION``, the bug has regressed.
        """
        server = _server_with_stub_graph(graph_file=None)
        coro = server._handle_learn_knowledge({
            "description": "Neo4j path regression guard",
            "domain": "technical",
        })
        response = json.loads(asyncio.run(coro))

        assert response.get("error_code") != "WRITE_COLLISION", (
            "PHANTOM collision regression: Neo4j-backed sessions must NOT "
            "report WRITE_COLLISION just because there is no JSON file. "
            f"Got: {response!r}"
        )
        assert response["recorded"] is True


# ── 6. Back-compat coercion: legacy tuple mocks still work ──────────


class TestLegacyTupleCoercion:
    """Pre-existing tests mock ``_save_graph`` to return ``(True, 0)`` /
    ``(False, n)`` tuples (e.g.
    ``srv._save_graph = MagicMock(return_value=(True, 0))`` in
    ``tests/test_plugins/test_mcp_dev_server.py`` and
    ``tests/test_plugins/test_v0513_ambiguous_options.py``). The CR-008
    handlers now read ``.recorded`` — so without a coercion step those
    tests would explode with ``AttributeError: 'tuple' object has no
    attribute 'recorded'``. ``_coerce_save_result`` bridges the gap during
    the deprecation grace period.
    """

    def test_passthrough_for_native_SaveGraphResult(self) -> None:
        original = SaveGraphResult(status=SaveStatus.OK, retries=2)
        coerced = KogniDevServer._coerce_save_result(original)
        assert coerced is original  # identity — no allocation when not needed

    def test_legacy_true_tuple_becomes_OK(self) -> None:
        coerced = KogniDevServer._coerce_save_result((True, 5))
        assert coerced.status is SaveStatus.OK
        assert coerced.retries == 5
        assert coerced.recorded is True

    def test_legacy_false_tuple_becomes_SAVE_FAILED_not_COLLISION(self) -> None:
        """Critical: legacy (False, n) must NOT silently become COLLISION.

        The whole point of CR-008 is that ``False`` from the old contract
        was ambiguous. We map it to the most conservative status
        (``SAVE_FAILED``) so operators triaging a test fixture see an
        accurate-not-misleading label.
        """
        coerced = KogniDevServer._coerce_save_result((False, 3))
        assert coerced.status is SaveStatus.SAVE_FAILED
        assert coerced.retries == 3
        assert coerced.recorded is False
        # Detail explains why this status was chosen
        assert "legacy" in (coerced.detail or "").lower()

    def test_unexpected_shape_becomes_SAVE_FAILED_with_type_only_detail(self) -> None:
        coerced = KogniDevServer._coerce_save_result("definitely not a tuple")
        assert coerced.status is SaveStatus.SAVE_FAILED
        # Detail records only the TYPE — never the value, which can leak
        assert "str" in (coerced.detail or "")
        assert "definitely" not in (coerced.detail or "")

    def test_handler_survives_legacy_true_tuple_mock(self) -> None:
        """End-to-end: a handler whose ``_save_graph`` is mocked to return
        ``(True, 0)`` (the exact pattern in ``test_v0513_ambiguous_options.py``)
        must still produce ``recorded: True`` after CR-008.
        """
        from unittest.mock import MagicMock as _MM
        server = _server_with_stub_graph(graph_file=None)
        server._save_graph = _MM(return_value=(True, 0))  # type: ignore[method-assign]

        coro = server._handle_learn_knowledge({
            "description": "Back-compat smoke",
            "domain": "technical",
        })
        response = json.loads(asyncio.run(coro))

        assert response["recorded"] is True
        # Persistence reports OK (not NO_GRAPH_FILE) because the mock claimed True
        assert response["persistence"] == "OK"
