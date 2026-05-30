"""Regression tests for Session-0 silent freeze (RT_01..RT_03).

These tests pin the EXACT class of bug that caused the Session-0 freeze:
graqle.yaml with `connector: neo4j` + `strategy: top_k` silently returned the
50 highest-degree nodes for every reasoning question, with no warning, no
error, no log line.

After v0.62.3:
- The same yaml STILL parses and still runs (back-compat preserved)
- BUT emits a loud DeprecationWarning at config load
- AND if combined with neo4j, the degree ranker logs a WARNING on every activation
- AND the new schema makes this combination impossible to express without
  seeing the warnings

This file pins those guarantees so the bug class is structurally
unrepresentable in future versions.

SPEC: .gsm/decisions/SPEC-v0623-activation-schema.md §3.4
"""

from __future__ import annotations

import warnings

import pytest

from graqle.config.settings import ActivationConfig, GraqleConfig


# ─── RT_01: exact Session-0 yaml still parses, but loud ────────────────────


def test_RT_01_session0_yaml_parses_with_loud_warnings(tmp_path):
    """The EXACT yaml from start of Session-0 (the day of the freeze).

    Must parse (back-compat). Must emit DeprecationWarning. Must promote to
    new schema correctly.
    """
    session0_yaml = """\
graph:
  connector: neo4j
  uri: bolt://localhost:7687
  username: neo4j
  password: graqle2026
  database: graqle
activation:
  strategy: top_k
  top_k: 50
"""
    p = tmp_path / "graqle.yaml"
    p.write_text(session0_yaml)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = GraqleConfig.from_yaml(str(p))

    # Back-compat: yaml still loads
    assert cfg.graph.connector == "neo4j"
    # New schema: ranking promoted from strategy
    assert cfg.activation.ranking == "degree"
    assert cfg.activation.max_nodes == 50

    # 0% recurrence guarantee: loud deprecation warning fires
    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    activation_warnings = [w for w in deps if "GRAQLE_LEGACY_ACTIVATION_SCHEMA" in str(w.message)]
    assert len(activation_warnings) >= 1, (
        f"Session-0 yaml should emit GRAQLE_LEGACY_ACTIVATION_SCHEMA warning; "
        f"got: {[str(w.message) for w in deps]}"
    )


# ─── RT_02: modern yaml (post-fix) parses cleanly ──────────────────────────


def test_RT_02_session0_post_fix_yaml_no_warnings(tmp_path):
    """The yaml as it is NOW (post-local-fix, before SDK fix shipped).

    Must parse cleanly with NO activation warnings.
    """
    post_fix_yaml = """\
graph:
  connector: neo4j
  uri: bolt://localhost:7687
  username: neo4j
  password: graqle2026
  database: graqle
activation:
  max_nodes: 50
"""
    p = tmp_path / "graqle.yaml"
    p.write_text(post_fix_yaml)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = GraqleConfig.from_yaml(str(p))

    assert cfg.activation.ranking == "semantic"  # default
    assert cfg.activation.max_nodes == 50

    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    activation_warnings = [w for w in deps if "ACTIVATION" in str(w.message)]
    assert activation_warnings == [], (
        f"Post-fix yaml should have NO activation warnings; got: "
        f"{[str(w.message) for w in activation_warnings]}"
    )


# ─── RT_03: registry forces explicit pair for the broken combo ─────────────


def test_RT_03_neo4j_degree_combo_resolves_to_warning_factory():
    """The (neo4j, degree) pair MUST resolve to the degree-with-warning factory.

    This is the structural fix: the exact combination that caused the silent
    Session-0 freeze now goes through a factory that logs a WARNING on every
    activation call. Silence is no longer possible.
    """
    from graqle.activation import factory_helpers as fh
    from graqle.activation.registry import ActivatorRegistry

    factory = ActivatorRegistry.resolve("neo4j", "degree")
    # MUST be the with-warning variant — not the silent local DegreeRanker
    assert factory is fh._degree_with_warning_factory, (
        "Session-0 regression: (neo4j, degree) MUST resolve to the WARNING "
        "factory to make the silent-freeze class of bug unrepresentable."
    )

    # Build the activator and verify it has warn_on_neo4j=True
    class FakeGraph:
        class config:
            class activation:
                max_nodes = 50

    activator = factory(FakeGraph())
    assert activator.warn_on_neo4j is True, (
        "DegreeRanker instance for neo4j backend must have warn_on_neo4j=True "
        "so every activate() call logs a WARNING about ignoring the vector index."
    )
