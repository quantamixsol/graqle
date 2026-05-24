"""LS-7 monotonic-on compare-and-set atomicity proof (ADR-RT-003 §8.2 / §10.2).

PR-6 made the monotonic-on flip race-free *within* one process (the registry's
RLock). PR-6.5 proves it: under heavy thread contention the flip happens exactly
once per layer, and adds the cross-process write-once persistence
(:meth:`Neo4jConnector.persist_monotonic_on`, a COALESCE CAS) plus the proof that
exactly one concurrent writer wins it.

The headline AC is :meth:`TestMonotonicOnConcurrencyProof.test_50x200x10_zero_duplicate_flips`
— 50 threads × 200 iterations × 10 runs asserting ZERO duplicate flips. No live
Neo4j: the persisted CAS is exercised against an in-memory fake driver that
reproduces COALESCE write-once semantics, so the whole proof runs in CI.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from graqle.governance.layer_status import (
    LAYER_IDS,
    LayerStatusRegistry,
)

L5 = "l5_cryptographic_tamper_evidence"
L3 = "l3_governed_trace"


# ---------------------------------------------------------------------------
# In-process LS-7 proof: the registry lock guarantees a single flip per layer.
# ---------------------------------------------------------------------------


class TestMonotonicOnConcurrencyProof:
    def _run_contended_flip(
        self, registry: LayerStatusRegistry, layer_id: str, *, threads: int, iterations: int
    ) -> None:
        """Hammer ``record_first_write(layer_id)`` from many threads at once.

        A barrier releases all threads together to maximise the chance of a
        genuine interleave on the flip, then each thread re-attempts the write
        ``iterations`` times (every attempt after the first must be an idempotent
        no-op).
        """
        barrier = threading.Barrier(threads)
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                barrier.wait()
                for _ in range(iterations):
                    registry.record_first_write(layer_id)
            except BaseException as exc:  # noqa: BLE001 - surface any thread error
                errors.append(exc)

        workers = [threading.Thread(target=worker) for _ in range(threads)]
        for t in workers:
            t.start()
        for t in workers:
            t.join()
        assert not errors, f"worker thread(s) raised: {errors!r}"

    @pytest.mark.parametrize("run", range(10))
    def test_50x200x10_zero_duplicate_flips(self, tmp_path, run):
        """50 threads × 200 iterations, 10 runs: exactly one flip per layer.

        This is the LS-7 proof. Across all the contending writers there must be
        exactly ONE ``monotonic_on`` transition recorded for the layer — a second
        would mean two writers both believed they performed the first write
        (a double flip), the precise failure the lock + COALESCE rule out.
        """
        registry = LayerStatusRegistry(environment="production", transition_dir=tmp_path / str(run))
        self._run_contended_flip(registry, L5, threads=50, iterations=200)

        state = registry.get_layer_state(L5)
        assert state.monotonic_on is True
        assert state.first_record_at_iso is not None

        monotonic_events = [h for h in registry.history(L5) if h["event"] == "monotonic_on"]
        assert len(monotonic_events) == 1, (
            f"run {run}: expected exactly 1 monotonic_on transition, "
            f"got {len(monotonic_events)}"
        )

    def test_concurrent_flips_on_independent_layers(self, tmp_path):
        """Two layers flipped concurrently each get exactly one transition.

        Guards against a shared-state bug where contention on one layer could
        corrupt another (e.g. a single mis-scoped flag).
        """
        registry = LayerStatusRegistry(environment="production", transition_dir=tmp_path)

        def flip(layer_id: str) -> None:
            self._run_contended_flip(registry, layer_id, threads=20, iterations=50)

        a = threading.Thread(target=flip, args=(L5,))
        b = threading.Thread(target=flip, args=(L3,))
        a.start(), b.start()
        a.join(), b.join()

        for lid in (L5, L3):
            events = [h for h in registry.history(lid) if h["event"] == "monotonic_on"]
            assert len(events) == 1


# ---------------------------------------------------------------------------
# persist_fn wiring: the registry drives the CAS exactly once, under the lock.
# ---------------------------------------------------------------------------


class TestRegistryPersistFnWiring:
    def test_persist_fn_called_once_on_flip(self, tmp_path):
        calls: list[tuple[str, str, str | None]] = []

        def persist_fn(layer_id, iso, rid):
            calls.append((layer_id, iso, rid))
            return True  # this process won the cross-process CAS

        reg = LayerStatusRegistry(
            environment="production", transition_dir=tmp_path, persist_fn=persist_fn
        )
        reg.record_first_write(L5, first_record_id="rec-1")
        # idempotent re-write must NOT call persist_fn again
        reg.record_first_write(L5, first_record_id="rec-2")

        assert len(calls) == 1
        layer_id, iso, rid = calls[0]
        assert layer_id == L5
        assert rid == "rec-1"
        assert iso  # the flip timestamp was forwarded

    def test_cas_won_recorded_in_audit_detail(self, tmp_path):
        reg = LayerStatusRegistry(
            environment="production",
            transition_dir=tmp_path,
            persist_fn=lambda *_: True,
        )
        reg.record_first_write(L5, first_record_id="rec-1")
        flip = next(h for h in reg.history(L5) if h["event"] == "monotonic_on")
        assert flip["detail"]["cas_won"] is True
        assert flip["detail"]["first_record_id"] == "rec-1"

    def test_cas_lost_still_flips_locally(self, tmp_path):
        """A process that loses the cross-process CAS still enforces LS-2 locally.

        ``persist_fn`` returning False means another process won the durable
        flip; this process must still reflect monotonic_on locally so a later
        disable in *this* process is refused.
        """
        reg = LayerStatusRegistry(
            environment="production",
            transition_dir=tmp_path,
            persist_fn=lambda *_: False,
        )
        st = reg.record_first_write(L5, first_record_id="rec-1")
        assert st.monotonic_on is True
        flip = next(h for h in reg.history(L5) if h["event"] == "monotonic_on")
        assert flip["detail"]["cas_won"] is False

    def test_persist_fn_failure_propagates(self, tmp_path):
        """A persist failure surfaces — a flip with no durable record isn't silent.

        The in-memory state is left flipped (LS-6 forbids clearing it), but the
        exception is not swallowed.
        """

        def boom(*_):
            raise RuntimeError("neo4j down")

        reg = LayerStatusRegistry(
            environment="production", transition_dir=tmp_path, persist_fn=boom
        )
        with pytest.raises(RuntimeError, match="neo4j down"):
            reg.record_first_write(L5, first_record_id="rec-1")

    def test_no_persist_fn_is_byte_identical_to_pr6(self, tmp_path):
        """With persist_fn=None the flip records no cas_won — PR-6 behaviour."""
        reg = LayerStatusRegistry(environment="production", transition_dir=tmp_path)
        reg.record_first_write(L5)
        flip = next(h for h in reg.history(L5) if h["event"] == "monotonic_on")
        assert "cas_won" not in flip["detail"]

    def test_dev_environment_never_drives_persist_fn(self, tmp_path):
        """In development the flip is a state no-op, so the CAS is never driven."""
        calls = []
        reg = LayerStatusRegistry(
            environment="development",
            transition_dir=tmp_path,
            persist_fn=lambda *a: calls.append(a) or True,
        )
        reg.record_first_write(L5, first_record_id="rec-1")
        assert calls == []


# ---------------------------------------------------------------------------
# Neo4jConnector.persist_monotonic_on: COALESCE write-once CAS Cypher.
# ---------------------------------------------------------------------------


class _CoalesceTx:
    """A fake tx that reproduces COALESCE write-once semantics over a shared store.

    ``store`` maps layer_id -> properties dict. ``run`` executes exactly the one
    statement persist_monotonic_on emits: it returns the PRE-state ``was_on`` and
    applies COALESCE (keep-first) to monotonic_on / first_record_at_iso /
    first_record_id. A lock serialises the read-modify-write so concurrent fake
    writers see linearised COALESCE — exactly what a single Neo4j tx guarantees.
    """

    def __init__(self, store, lock):
        self._store = store
        self._lock = lock

    def run(self, cypher, **params):
        assert "COALESCE" in cypher  # §8.2 decision #7: COALESCE, never ON CREATE/ON MATCH
        assert "ON CREATE" not in cypher and "ON MATCH" not in cypher
        lid = params["layer_id"]
        with self._lock:
            props = self._store.setdefault(lid, {})
            was_on = bool(props.get("monotonic_on", False))
            props["monotonic_on"] = props.get("monotonic_on", True)
            props["first_record_at_iso"] = props.get(
                "first_record_at_iso", params["first_record_at_iso"]
            )
            props["first_record_id"] = props.get("first_record_id", params["first_record_id"])
        result = MagicMock()
        result.single.return_value = {"was_on": was_on}
        return result


class _CoalesceSession:
    def __init__(self, store, lock):
        self._store = store
        self._lock = lock

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute_write(self, fn):
        return fn(_CoalesceTx(self._store, self._lock))


class _CoalesceDriver:
    def __init__(self):
        self.store: dict[str, dict] = {}
        self.lock = threading.Lock()

    def session(self, database=None):
        return _CoalesceSession(self.store, self.lock)


def _connector_with_coalesce_driver():
    with patch.dict("sys.modules", {"neo4j": MagicMock()}):
        from graqle.connectors.neo4j import Neo4jConnector

        connector = Neo4jConnector()
        connector._driver = _CoalesceDriver()
        return connector


class TestPersistMonotonicOnCypher:
    def test_returns_true_on_first_flip_false_after(self):
        connector = _connector_with_coalesce_driver()
        assert connector.persist_monotonic_on(L5, "2026-06-14T11:23:45Z", "rec-1") is True
        # second call: already flipped -> idempotent no-op, returns False
        assert connector.persist_monotonic_on(L5, "2026-07-01T00:00:00Z", "rec-2") is False

    def test_first_record_fields_pinned_write_once(self):
        connector = _connector_with_coalesce_driver()
        connector.persist_monotonic_on(L5, "2026-06-14T11:23:45Z", "rec-1")
        connector.persist_monotonic_on(L5, "2026-07-01T00:00:00Z", "rec-2")
        props = connector._driver.store[L5]
        assert props["first_record_at_iso"] == "2026-06-14T11:23:45Z"  # winner pinned
        assert props["first_record_id"] == "rec-1"

    def test_none_first_record_id_allowed(self):
        connector = _connector_with_coalesce_driver()
        assert connector.persist_monotonic_on(L5, "2026-06-14T11:23:45Z", None) is True
        assert connector._driver.store[L5]["first_record_id"] is None

    def test_preexisting_node_without_flag_is_first_writer(self):
        """A :LayerStatus node that pre-exists but is NOT yet monotonic-on flips once.

        This is the exact scenario decision #7 rejects ON CREATE/ON MATCH for: the
        node already exists (e.g. an earlier *enable* transition created it), so an
        ON CREATE clause would never fire and an ON MATCH clause could rewrite the
        first-record fields on every subsequent call. With COALESCE, the first
        writer to find monotonic_on still null performs the flip (returns True) and
        pins the provenance; a later call is a no-op (returns False).
        """
        connector = _connector_with_coalesce_driver()
        # Simulate a node created earlier (enable transition) with NO monotonic_on.
        connector._driver.store[L5] = {"enabled": True}
        assert connector.persist_monotonic_on(L5, "2026-06-14T11:23:45Z", "rec-1") is True
        assert connector._driver.store[L5]["monotonic_on"] is True
        assert connector._driver.store[L5]["first_record_at_iso"] == "2026-06-14T11:23:45Z"
        # subsequent call must NOT rewrite (the ON MATCH hazard) — write-once holds
        assert connector.persist_monotonic_on(L5, "2099-01-01T00:00:00Z", "rec-2") is False
        assert connector._driver.store[L5]["first_record_at_iso"] == "2026-06-14T11:23:45Z"

    @pytest.mark.parametrize("bad", ["", None, 123])
    def test_empty_or_nonstring_layer_id_raises(self, bad):
        connector = _connector_with_coalesce_driver()
        with pytest.raises(ValueError):
            connector.persist_monotonic_on(bad, "2026-06-14T11:23:45Z", "rec-1")

    def test_independent_layers_flip_independently(self):
        connector = _connector_with_coalesce_driver()
        assert connector.persist_monotonic_on(L5, "2026-06-14T11:23:45Z", "a") is True
        assert connector.persist_monotonic_on(L3, "2026-06-14T11:23:45Z", "b") is True
        assert set(connector._driver.store) == {L5, L3}

    def test_concurrent_writers_exactly_one_winner(self):
        """LS-7 across processes (simulated): only ONE writer gets True per layer.

        Many threads call persist_monotonic_on for the same layer at once against
        the COALESCE fake driver; exactly one must observe the pre-state as
        not-yet-flipped and return True.
        """
        connector = _connector_with_coalesce_driver()
        winners: list[bool] = []
        winners_lock = threading.Lock()
        barrier = threading.Barrier(50)

        def worker():
            barrier.wait()
            won = connector.persist_monotonic_on(L5, "2026-06-14T11:23:45Z", "rec")
            with winners_lock:
                winners.append(won)

        threads = [threading.Thread(target=worker) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert winners.count(True) == 1
        assert winners.count(False) == 49

    def test_all_layers_can_persist(self):
        connector = _connector_with_coalesce_driver()
        for lid in LAYER_IDS:
            assert connector.persist_monotonic_on(lid, "2026-06-14T11:23:45Z", "r") is True


# ---------------------------------------------------------------------------
# End-to-end: registry wired to the real connector method over the fake driver.
# ---------------------------------------------------------------------------


class TestRegistryDrivesConnectorCAS:
    def test_registry_flip_drives_coalesce_cas_once(self, tmp_path):
        connector = _connector_with_coalesce_driver()
        reg = LayerStatusRegistry(
            environment="production",
            transition_dir=tmp_path,
            persist_fn=connector.persist_monotonic_on,
        )
        reg.record_first_write(L5, first_record_id="rec-1")
        reg.record_first_write(L5, first_record_id="rec-2")  # idempotent

        # persisted exactly once with the winning provenance
        assert connector._driver.store[L5]["monotonic_on"] is True
        assert connector._driver.store[L5]["first_record_id"] == "rec-1"
        flip = next(h for h in reg.history(L5) if h["event"] == "monotonic_on")
        assert flip["detail"]["cas_won"] is True
