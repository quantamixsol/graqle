"""Tests for graqle.governance.layer_status (ADR-RT-003 LS-1..LS-6, §8.3).

All tests inject a temporary transition_dir so the §8.3 audit sidecar never
touches the real ~/.graqle store. No live Neo4j, no network.
"""

from __future__ import annotations

import json

import pytest

from graqle.governance.layer_status import (
    LAYER_IDS,
    LayerDependencyError,
    LayerMonotonicityViolation,
    LayerState,
    LayerStatusRegistry,
    configure_default_registry,
    dependencies_of,
    flip_to_monotonic_on_atomic,
    get_default_registry,
    get_layer_state,
    history,
    record_first_write,
    request_enabled,
    validate_layer_config,
)
from graqle.governance.layer_status.dependency_graph import LAYER_DEPENDENCIES

L5 = "l5_cryptographic_tamper_evidence"
L3 = "l3_governed_trace"
L2 = "l2_reasoning_loop"
L1 = "l1_kg_substrate"


@pytest.fixture
def prod_registry(tmp_path):
    return LayerStatusRegistry(environment="production", transition_dir=tmp_path)


@pytest.fixture
def dev_registry(tmp_path):
    return LayerStatusRegistry(environment="development", transition_dir=tmp_path)


# ---- LS-3 dependency graph -------------------------------------------------


class TestDependencyGraph:
    def test_layer_ids_and_edges_match_spec(self):
        assert LAYER_IDS[0] == L1 and LAYER_IDS[-1] == L5
        assert LAYER_DEPENDENCIES[L1] == ()
        assert LAYER_DEPENDENCIES[L2] == (L1,)
        assert LAYER_DEPENDENCIES[L3] == (L1, L2)
        # L5 requires L1+L2+L3 but NOT L4 (recommended, not hard-required)
        assert "l4_pct_integration" not in LAYER_DEPENDENCIES[L5]
        assert set(LAYER_DEPENDENCIES[L5]) == {L1, L2, L3}

    def test_dependencies_of(self):
        assert dependencies_of(L1) == ()
        assert dependencies_of(L3) == (L1, L2)

    def test_dependencies_of_unknown_raises(self):
        with pytest.raises(KeyError):
            dependencies_of("l9_nope")

    def test_all_enabled_is_valid(self):
        validate_layer_config({lid: True for lid in LAYER_IDS})

    def test_disabled_dependency_refused_names_lowest_missing(self):
        cfg = {lid: True for lid in LAYER_IDS}
        cfg[L2] = False
        with pytest.raises(LayerDependencyError) as ei:
            validate_layer_config(cfg)
        # L3 is the first enabled layer with a disabled dep; L2 is the missing dep.
        assert ei.value.layer_id == L3
        assert ei.value.missing_dependency == L2

    def test_disabling_a_leaf_with_no_dependents_is_valid(self):
        cfg = {lid: True for lid in LAYER_IDS}
        cfg[L5] = False  # nothing depends on L5
        validate_layer_config(cfg)

    def test_missing_key_raises_keyerror(self):
        with pytest.raises(KeyError):
            validate_layer_config({L1: True})


# ---- LS-2 / LS-4 monotonic-on (production) ---------------------------------


class TestMonotonicOnProduction:
    def test_default_l5_disabled(self, prod_registry):
        st = prod_registry.get_layer_state(L5)
        assert isinstance(st, LayerState)
        assert st.enabled is False
        assert st.monotonic_on is False
        assert st.first_record_at_iso is None

    def test_first_write_flips_monotonic_on(self, prod_registry):
        prod_registry.request_enabled(L5, True)
        st = prod_registry.record_first_write(L5)
        assert st.monotonic_on is True
        assert st.first_record_at_iso is not None

    def test_first_write_idempotent(self, prod_registry):
        prod_registry.record_first_write(L5)
        first_iso = prod_registry.get_layer_state(L5).first_record_at_iso
        prod_registry.record_first_write(L5)
        assert prod_registry.get_layer_state(L5).first_record_at_iso == first_iso
        # only ONE monotonic_on transition recorded
        events = [h["event"] for h in prod_registry.history(L5)]
        assert events.count("monotonic_on") == 1

    def test_disable_after_monotonic_on_raises(self, prod_registry):
        prod_registry.record_first_write(L5)
        with pytest.raises(LayerMonotonicityViolation) as ei:
            prod_registry.request_enabled(L5, False)
        assert ei.value.layer_id == L5

    def test_disable_refusal_is_audited_before_raise(self, prod_registry):
        prod_registry.record_first_write(L5)
        with pytest.raises(LayerMonotonicityViolation):
            prod_registry.request_enabled(L5, False)
        events = [h["event"] for h in prod_registry.history(L5)]
        assert "disable_refused" in events

    def test_enable_is_always_allowed(self, prod_registry):
        st = prod_registry.request_enabled(L5, True)
        assert st.enabled is True
        # enabling again is a no-op (no duplicate 'enabled' transition)
        prod_registry.request_enabled(L5, True)
        events = [h["event"] for h in prod_registry.history(L5)]
        assert events.count("enabled") == 1

    def test_disable_before_monotonic_on_is_allowed(self, prod_registry):
        prod_registry.request_enabled(L3, True)
        st = prod_registry.request_enabled(L3, False)
        assert st.enabled is False
        events = [h["event"] for h in prod_registry.history(L3)]
        assert "disabled" in events

    def test_disable_when_already_disabled_no_transition(self, prod_registry):
        # L5 starts disabled; a redundant disable adds no transition.
        prod_registry.request_enabled(L5, False)
        assert prod_registry.history(L5) == []

    def test_unknown_environment_treated_as_production(self, tmp_path):
        reg = LayerStatusRegistry(environment="staging", transition_dir=tmp_path)
        assert reg.is_production is True
        reg.record_first_write(L5)
        with pytest.raises(LayerMonotonicityViolation):
            reg.request_enabled(L5, False)

    def test_custom_enabled_map(self, tmp_path):
        reg = LayerStatusRegistry(
            environment="production",
            enabled={lid: True for lid in LAYER_IDS},
            transition_dir=tmp_path,
        )
        assert reg.get_layer_state(L5).enabled is True

    def test_get_state_returns_copy(self, prod_registry):
        st = prod_registry.get_layer_state(L5)
        st.enabled = True  # mutate the copy
        assert prod_registry.get_layer_state(L5).enabled is False  # registry unchanged

    def test_get_state_unknown_layer_raises(self, prod_registry):
        with pytest.raises(KeyError) as ei:
            prod_registry.get_layer_state("l9_nope")
        # actionable message names the valid ids
        assert "l9_nope" in str(ei.value)
        assert "l1_kg_substrate" in str(ei.value)

    def test_request_enabled_unknown_layer_raises(self, prod_registry):
        with pytest.raises(KeyError):
            prod_registry.request_enabled("l9_nope", True)

    def test_record_first_write_unknown_layer_raises(self, prod_registry):
        with pytest.raises(KeyError):
            prod_registry.record_first_write("l9_nope")


# ---- LS-2 development (free toggle) ----------------------------------------


class TestDevelopmentEnvironment:
    def test_is_not_production(self, dev_registry):
        assert dev_registry.is_production is False

    def test_record_first_write_does_not_flip(self, dev_registry):
        dev_registry.record_first_write(L5)
        assert dev_registry.get_layer_state(L5).monotonic_on is False

    def test_disable_freely_allowed(self, dev_registry):
        dev_registry.request_enabled(L3, True)
        dev_registry.record_first_write(L3)
        st = dev_registry.request_enabled(L3, False)  # would raise in prod
        assert st.enabled is False


# ---- LS-5 history -----------------------------------------------------------


class TestHistory:
    def test_history_all_layers_when_no_filter(self, prod_registry):
        prod_registry.record_first_write(L5)
        prod_registry.request_enabled(L3, True)
        prod_registry.request_enabled(L3, False)
        all_events = prod_registry.history()
        layers = {h["layer_id"] for h in all_events}
        assert L5 in layers and L3 in layers

    def test_history_filtered_by_layer(self, prod_registry):
        prod_registry.record_first_write(L5)
        prod_registry.request_enabled(L3, True)
        l5_only = prod_registry.history(L5)
        assert all(h["layer_id"] == L5 for h in l5_only)

    def test_history_entries_have_expected_shape(self, prod_registry):
        prod_registry.record_first_write(L5)
        entry = prod_registry.history(L5)[0]
        assert set(entry) == {"layer_id", "event", "at_iso", "environment", "detail"}
        assert entry["environment"] == "production"


# ---- LS-4 §8.3 transition sidecar (recursion prevention) -------------------


class TestTransitionSidecar:
    def test_sidecar_records_flagged_internal_transition(self, tmp_path):
        reg = LayerStatusRegistry(environment="production", transition_dir=tmp_path)
        reg.record_first_write(L5)
        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1
        recs = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]
        assert recs
        assert all(r["_internal_transition"] is True for r in recs)
        assert recs[0]["layer_id"] == L5
        assert recs[0]["event"] == "monotonic_on"

    def test_sidecar_captures_refused_disable(self, tmp_path):
        reg = LayerStatusRegistry(environment="production", transition_dir=tmp_path)
        reg.record_first_write(L5)
        with pytest.raises(LayerMonotonicityViolation):
            reg.request_enabled(L5, False)
        files = list(tmp_path.glob("*.jsonl"))
        recs = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]
        events = [r["event"] for r in recs]
        assert "disable_refused" in events


# ---- module-level default-registry API -------------------------------------


class TestModuleLevelApi:
    def test_default_registry_lazily_created_and_cached(self):
        r1 = get_default_registry()
        r2 = get_default_registry()
        assert r1 is r2

    def test_configure_default_registry(self, tmp_path):
        custom = LayerStatusRegistry(environment="development", transition_dir=tmp_path)
        configure_default_registry(custom)
        try:
            assert get_default_registry() is custom
            # module-level helpers route through it
            record_first_write(L5)
            assert get_layer_state(L5).monotonic_on is False  # dev: no flip
            # L5 starts disabled, so enabling it records a real 'enabled' transition
            request_enabled(L5, True)
            assert any(h["layer_id"] == L5 and h["event"] == "enabled" for h in history())
        finally:
            # reset the module singleton so other tests are unaffected
            import graqle.governance.layer_status as ls_mod

            ls_mod._default_registry = None

    def test_flip_to_monotonic_on_atomic(self, tmp_path):
        custom = LayerStatusRegistry(environment="production", transition_dir=tmp_path)
        configure_default_registry(custom)
        try:
            st = flip_to_monotonic_on_atomic(L5, first_record_id="rec-1")
            assert st.monotonic_on is True
            # idempotent
            st2 = flip_to_monotonic_on_atomic(L5, first_record_id="rec-2")
            assert st2.monotonic_on is True
            assert custom.history(L5).__len__() == 1  # only one flip recorded
        finally:
            import graqle.governance.layer_status as ls_mod

            ls_mod._default_registry = None

    def test_flip_atomic_without_first_record_id(self, tmp_path):
        custom = LayerStatusRegistry(environment="production", transition_dir=tmp_path)
        configure_default_registry(custom)
        try:
            st = flip_to_monotonic_on_atomic(L5)
            assert st.monotonic_on is True
        finally:
            import graqle.governance.layer_status as ls_mod

            ls_mod._default_registry = None
