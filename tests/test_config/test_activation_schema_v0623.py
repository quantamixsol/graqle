"""Tests for v0.62.3 ActivationConfig schema split (TC_01..TC_16).

Covers:
- Pure new schema (ranking + max_nodes)
- Legacy `strategy:` -> `ranking:` promotion via Pydantic model_validator
- Legacy `top_k:` -> `max_nodes:` promotion
- Conflict resolution when both old + new fields are set
- Validation errors for invalid values
- DeprecationWarning structure (single consolidated warning per config load)

SPEC: .gsm/decisions/SPEC-v0623-activation-schema.md §3.1
"""

from __future__ import annotations

import warnings

import pytest

from graqle.config.settings import (
    STRATEGY_TO_RANKING,
    VALID_RANKINGS,
    ActivationConfig,
    GraqleConfig,
)


# ─── TC_01-TC_03: pure new schema (no warnings) ────────────────────────────


def test_TC_01_new_schema_default():
    """Default ActivationConfig: ranking=semantic, max_nodes=50, no warnings."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = ActivationConfig()
    assert cfg.ranking == "semantic"
    assert cfg.max_nodes == 50
    assert cfg.strategy is None
    assert cfg.top_k is None
    deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deprecation_warnings == [], f"Unexpected DeprecationWarnings: {deprecation_warnings}"


def test_TC_02_new_schema_explicit():
    """Explicit new fields: ranking=degree, max_nodes=20, no warnings."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = ActivationConfig(ranking="degree", max_nodes=20)
    assert cfg.ranking == "degree"
    assert cfg.max_nodes == 20
    deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deprecation_warnings == []


def test_TC_03_legacy_strategy_chunk_no_warning():
    """strategy='chunk' (the old default) maps to ranking=semantic WITHOUT warning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = ActivationConfig(strategy="chunk")
    assert cfg.ranking == "semantic"
    deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    # chunk was the old default — using it explicitly should NOT trigger a warning
    assert deprecation_warnings == [], (
        f"strategy='chunk' should not warn (was the default); got: "
        f"{[str(w.message) for w in deprecation_warnings]}"
    )


# ─── TC_04-TC_07: legacy strategy values that DO warn ──────────────────────


def test_TC_04_legacy_strategy_top_k_warns():
    """strategy='top_k' -> ranking='degree' + DeprecationWarning fires."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = ActivationConfig(strategy="top_k")
    assert cfg.ranking == "degree"
    deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deprecation_warnings) >= 1
    msgs = [str(w.message) for w in deprecation_warnings]
    assert any("GRAQLE_LEGACY_ACTIVATION_SCHEMA" in m for m in msgs), (
        f"Expected consolidated migration warning; got: {msgs}"
    )


def test_TC_05_legacy_strategy_full_warns():
    """strategy='full' -> ranking='none' + warning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = ActivationConfig(strategy="full")
    assert cfg.ranking == "none"
    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deps) >= 1


def test_TC_06_legacy_strategy_pcst_warns():
    """strategy='pcst' -> ranking='semantic' (pcst is a semantic variant) + warning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = ActivationConfig(strategy="pcst")
    assert cfg.ranking == "semantic"
    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deps) >= 1


def test_TC_07_legacy_strategy_manual_warns():
    """strategy='manual' -> ranking='none' + warning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = ActivationConfig(strategy="manual")
    assert cfg.ranking == "none"
    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deps) >= 1


# ─── TC_08-TC_09: legacy top_k + conflict cases ────────────────────────────


def test_TC_08_legacy_top_k_alias_warns():
    """top_k=100 -> max_nodes=100 + warning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = ActivationConfig(top_k=100)
    assert cfg.max_nodes == 100
    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deps) >= 1


def test_TC_09_both_old_and_new_new_wins_with_conflict_warning():
    """strategy=top_k + ranking=semantic: new wins, both warnings fire."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = ActivationConfig(strategy="top_k", ranking="semantic")
    assert cfg.ranking == "semantic"  # new wins
    msgs = [str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)]
    assert any("GRAQLE_ACTIVATION_CONFLICT" in m for m in msgs), (
        f"Expected conflict warning; got: {msgs}"
    )


# ─── TC_10-TC_11: yaml round-trip ──────────────────────────────────────────


def test_TC_10_yaml_roundtrip_legacy(tmp_path):
    """from_yaml with old schema parses + both warnings fire."""
    yaml_text = """
graph:
  connector: networkx
activation:
  strategy: top_k
  top_k: 75
"""
    yaml_path = tmp_path / "graqle.yaml"
    yaml_path.write_text(yaml_text)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = GraqleConfig.from_yaml(str(yaml_path))
    assert cfg.activation.ranking == "degree"
    assert cfg.activation.max_nodes == 75
    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deps) >= 1


def test_TC_11_yaml_roundtrip_new_schema(tmp_path):
    """from_yaml with new schema parses cleanly, no warnings."""
    yaml_text = """
graph:
  connector: networkx
activation:
  ranking: semantic
  max_nodes: 100
"""
    yaml_path = tmp_path / "graqle.yaml"
    yaml_path.write_text(yaml_text)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = GraqleConfig.from_yaml(str(yaml_path))
    assert cfg.activation.ranking == "semantic"
    assert cfg.activation.max_nodes == 100
    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    activation_warnings = [w for w in deps if "ACTIVATION" in str(w.message)]
    assert activation_warnings == []


# ─── TC_12-TC_14: validation errors ────────────────────────────────────────


def test_TC_12_invalid_ranking_value():
    """ranking='garbage' raises ValueError listing valid values."""
    with pytest.raises(ValueError) as exc_info:
        ActivationConfig(ranking="garbage")
    msg = str(exc_info.value)
    assert "garbage" in msg
    # Error message should list valid values
    for valid in VALID_RANKINGS:
        assert valid in msg, f"Expected {valid!r} in error message; got: {msg}"


def test_TC_13_invalid_max_nodes_negative():
    """max_nodes=-1 raises ValidationError (Pydantic ge=1 constraint)."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ActivationConfig(max_nodes=-1)


def test_TC_13b_invalid_max_nodes_zero():
    """max_nodes=0 also raises (ge=1)."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ActivationConfig(max_nodes=0)


def test_TC_14_max_nodes_upper_no_hard_bound():
    """max_nodes=10000 passes (no hard upper bound — large multi-repo graphs)."""
    cfg = ActivationConfig(max_nodes=10000)
    assert cfg.max_nodes == 10000


# ─── TC_15: programmatic setter (benchmarks pattern) ───────────────────────


def test_TC_15_runtime_setter_strategy_promotes_to_ranking():
    """benchmarks do: config.activation.strategy = 'pcst' — must promote."""
    cfg = ActivationConfig()
    assert cfg.ranking == "semantic"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg.strategy = "pcst"  # mimics benchmarks/benchmark_runner.py:237
    # After assignment, validator should promote
    assert cfg.ranking == "semantic"  # pcst maps to semantic
    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deps) >= 1, "Setter-side validator should fire deprecation warning"


# ─── TC_16: strategy mapping table is internally consistent ────────────────


def test_TC_16_strategy_to_ranking_table_consistency():
    """Every value in STRATEGY_TO_RANKING maps to a VALID_RANKINGS member."""
    for legacy, new in STRATEGY_TO_RANKING.items():
        assert new in VALID_RANKINGS, (
            f"STRATEGY_TO_RANKING[{legacy!r}]={new!r} is not a valid ranking. "
            f"Valid: {sorted(VALID_RANKINGS)}"
        )


# ─── Bonus: unknown legacy strategy passes through with warning ─────────────


def test_TC_17_unknown_legacy_strategy_warns_and_defaults_semantic():
    """Unknown legacy strategy value (e.g. custom benchmark name) defaults to semantic + warns."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = ActivationConfig(strategy="custom_unknown_strategy")
    assert cfg.ranking == "semantic"
    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    msgs = [str(w.message) for w in deps]
    assert any("GRAQLE_UNKNOWN_STRATEGY" in m for m in msgs), (
        f"Expected unknown-strategy warning; got: {msgs}"
    )
