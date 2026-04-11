"""CG-REASON-02 (v0.47.1) regression tests for BaseBackend serialization.

These tests cover the four scenarios identified in the pre-implementation
graq_review of the fix:

  1. copy.deepcopy(backend) after the lazy ``_client`` is populated
  2. pickle round-trip preserves durable config and drops transient handles
  3. ADR-151 simulation: deepcopying a node that holds an activated backend
  4. Concurrent shared-backend scenario: two deepcopies from one source are
     isolated and the source is untouched

Plus a smoke test that the real OpenAIBackend (constructor only, no network
call) survives deepcopy when its ``_client`` slot has been populated with a
placeholder that holds a threading.RLock.
"""

# ── graqle:intelligence ──
# module: tests.test_backends.test_base_serialization
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, copy, pickle, threading, graqle.backends.base
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import copy
import os
import pickle
import threading

import pytest

from graqle.backends.base import (
    BaseBackend,
    GenerateResult,
    _TRANSIENT_BACKEND_ATTRS,
)


class _RLockHolder:
    """Stand-in for httpx/AsyncOpenAI client tree — holds an RLock.

    Without the BaseBackend serialization fix, copy.deepcopy on a backend
    that has one of these as ``_client`` raises
    ``TypeError: cannot pickle '_thread.RLock' object``.
    """

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.connection_count = 0


class _FakeBackend(BaseBackend):
    """Minimal concrete backend for serialization tests.

    Mirrors the OpenAIBackend pattern: durable config in ``__init__``,
    lazy ``_client`` populated on first ``_get_client()`` call.
    """

    def __init__(self, model: str = "fake-model") -> None:
        self.model = model
        self.max_retries = 3
        self.total_input_tokens = 0
        self.total_cost_usd = 0.0
        self._client = None
        self._init_count = 0

    def _get_client(self) -> _RLockHolder:
        if self._client is None:
            self._client = _RLockHolder()
            self._init_count += 1
        return self._client

    async def generate(self, prompt: str, **kw):  # type: ignore[override]
        client = self._get_client()
        client.connection_count += 1
        return GenerateResult(text="ok", model=self.model)

    @property
    def name(self) -> str:
        return f"fake:{self.model}"

    @property
    def cost_per_1k_tokens(self) -> float:
        return 0.0


class _DualClientBackend(_FakeBackend):
    """Module-level subclass with multiple transient handles (pickle-able)."""

    def __init__(self) -> None:
        super().__init__()
        self._async_client = _RLockHolder()
        self._session = _RLockHolder()
        self._lock = threading.RLock()



# ── 1. deepcopy after lazy client init ────────────────────────────────


def test_deepcopy_after_lazy_client_init() -> None:
    backend = _FakeBackend()
    backend._get_client()  # populate the troublesome client
    assert backend._client is not None

    # Without the fix this raises TypeError(cannot pickle _thread.RLock)
    clone = copy.deepcopy(backend)

    assert clone._client is None, "deepcopy should drop transient _client"
    assert clone.model == backend.model, "durable config must survive"
    assert clone.max_retries == backend.max_retries
    assert backend._client is not None, "source must be untouched"


# ── 2. pickle round-trip ──────────────────────────────────────────────


def test_pickle_round_trip_preserves_durable_state() -> None:
    backend = _FakeBackend(model="rtt-model")
    backend.total_input_tokens = 12345
    backend._get_client()  # populate transient handle

    blob = pickle.dumps(backend)
    restored = pickle.loads(blob)

    assert restored.model == "rtt-model"
    assert restored.max_retries == 3
    assert restored.total_input_tokens == 12345
    assert restored._client is None, "transient slot must be reset to None"


def test_pickle_does_not_mutate_source() -> None:
    backend = _FakeBackend()
    backend._get_client()
    original_client = backend._client
    pickle.dumps(backend)
    assert backend._client is original_client, "pickle must not mutate source"


# ── 3. ADR-151 snapshot simulation ────────────────────────────────────


class _NodeLike:
    """Stand-in for graqle.core.node.CogniNode — holds a backend ref."""

    def __init__(self, label: str, backend: BaseBackend | None = None) -> None:
        self.label = label
        self.properties: dict = {"chunks": []}
        self.description = "test node"
        self.backend = backend


def test_adr151_node_snapshot_with_activated_backend() -> None:
    """Reproduces graqle/core/graph.py:1520 deepcopy of an activated node."""
    backend = _FakeBackend()
    backend._get_client()
    node = _NodeLike("hub-node", backend=backend)

    # The exact pattern from areason() line 1520:
    snapshot = copy.deepcopy(node)

    assert snapshot.backend is not None, "backend ref preserved"
    assert snapshot.backend._client is None, "snapshot client is reset"
    assert backend._client is not None, "source backend client untouched"
    assert snapshot.label == "hub-node"


# ── 4. Concurrent shared-backend isolation ────────────────────────────


def test_two_snapshots_share_no_state() -> None:
    """Two reasoning rounds deepcopying nodes from the same backend ref."""
    shared = _FakeBackend()
    shared._get_client()

    node_a = _NodeLike("a", backend=shared)
    node_b = _NodeLike("b", backend=shared)

    snap_a = copy.deepcopy(node_a)
    snap_b = copy.deepcopy(node_b)

    assert snap_a.backend is not snap_b.backend, "snapshots must be isolated"
    assert snap_a.backend._client is None
    assert snap_b.backend._client is None
    assert shared._client is not None, "source backend untouched by either"


# ── 5. Real OpenAIBackend smoke test (constructor only, no network) ───


def test_openai_backend_deepcopy_safe_with_rlock_in_client_slot() -> None:
    """The real OpenAIBackend must inherit the fix from BaseBackend."""
    from graqle.backends.api import OpenAIBackend

    os.environ.setdefault("OPENAI_API_KEY", "placeholder-for-test")
    backend = OpenAIBackend(model="gpt-4o-mini")
    # Inject a stand-in that holds a real RLock — this is the failure mode
    # that crashes deepcopy without the fix.
    backend._client = _RLockHolder()

    clone = copy.deepcopy(backend)
    assert clone._client is None
    assert clone._model == "gpt-4o-mini"
    assert backend._client is not None


# ── 6. _TRANSIENT_BACKEND_ATTRS contract ──────────────────────────────


def test_transient_attrs_contract_includes_known_handles() -> None:
    expected = {"_client", "_async_client", "_session",
                "_executor", "_loop", "_lock"}
    assert expected.issubset(_TRANSIENT_BACKEND_ATTRS), (
        "the documented transient set must include all standard handles"
    )


def test_subclass_specific_transient_attr_can_be_added() -> None:
    """Subclasses with extra handles can override __getstate__."""

    class _ExtendedBackend(_FakeBackend):
        def __init__(self) -> None:
            super().__init__()
            self._extra_executor = _RLockHolder()

        def __getstate__(self) -> dict:
            state = super().__getstate__()
            state.pop("_extra_executor", None)
            return state

    b = _ExtendedBackend()
    clone = copy.deepcopy(b)
    assert not hasattr(clone, "_extra_executor")


# ── 7. __setstate__ resets every entry in _TRANSIENT_BACKEND_ATTRS ────


def test_setstate_resets_all_transient_handles_consistently() -> None:
    """A backend with multiple transient handles must come out consistent.

    Per the post-implementation graq_review feedback: __setstate__ used
    to only reset _client. With multiple transient slots (e.g. an async
    backend that holds both _client and _async_client), the unpickled
    instance must have ALL of them set to None.
    """
    b = _DualClientBackend()
    restored = pickle.loads(pickle.dumps(b))

    # Every transient attribute must be present and None on the restored copy
    for attr in ("_client", "_async_client", "_session", "_lock"):
        assert hasattr(restored, attr), f"missing transient attr: {attr}"
        assert getattr(restored, attr) is None, f"{attr} not reset to None"
    # Source untouched
    assert b._async_client is not None and b._lock is not None
