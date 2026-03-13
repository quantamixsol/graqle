"""Tests for AdaptiveActivation — adaptive Kmax based on query complexity."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from graqle.activation.adaptive import (
    AdaptiveActivation,
    AdaptiveConfig,
    ComplexityProfile,
    QueryComplexityScorer,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def scorer() -> QueryComplexityScorer:
    return QueryComplexityScorer()


@pytest.fixture
def activator() -> AdaptiveActivation:
    return AdaptiveActivation()


# ---------------------------------------------------------------------------
# 1. Simple query → low Kmax
# ---------------------------------------------------------------------------

def test_simple_query_low_kmax(activator: AdaptiveActivation) -> None:
    query = "Hello"
    profile, kmax = activator.analyze(query)
    assert profile.tier == "simple"
    assert kmax == 4


# ---------------------------------------------------------------------------
# 2. Complex query → high Kmax
# ---------------------------------------------------------------------------

def test_complex_query_high_kmax(activator: AdaptiveActivation) -> None:
    query = (
        "How does the AI Act affect GDPR and DORA compliance frameworks "
        "across multiple regulatory domains while considering both NIS2 "
        "and MiCA requirements? Compare and contrast the combined impact "
        "of these overlapping directives on supply chain obligations "
        "in addition to eIDAS standards and PSD2 interoperability."
    )
    profile, kmax = activator.analyze(query)
    assert profile.tier in ("complex", "expert")
    assert kmax >= 12


# ---------------------------------------------------------------------------
# 3. Moderate query → mid Kmax
# ---------------------------------------------------------------------------

def test_moderate_query_mid_kmax(activator: AdaptiveActivation) -> None:
    # v0.12.1: use a genuinely moderate query (1-2 entities, short)
    query = "How does the auth service work?"
    profile, kmax = activator.analyze(query)
    assert profile.tier == "moderate"
    assert kmax == 8


# ---------------------------------------------------------------------------
# 4. Complexity profile — verify each dimension scores correctly
# ---------------------------------------------------------------------------

def test_complexity_profile_scores(scorer: QueryComplexityScorer) -> None:
    # Long query with multiple entities, conjunctions, and multi-hop patterns
    query = (
        "How does GDPR affect DORA and NIS2 compliance frameworks "
        "across multiple regulatory domains while considering "
        "both AI Act and MiCA requirements?"
    )
    profile = scorer.score(query)

    # Token score: query has ~20 tokens, should be above 0
    assert profile.token_score > 0.0

    # Entity score: GDPR, DORA, NIS2, AI Act, MiCA = 5 entities → capped at 1.0
    assert profile.entity_score >= 0.75

    # Conjunction score: "and", "while", "both...and" → multiple hits
    assert profile.conjunction_score > 0.0

    # Depth score: "how does X affect" + "across multiple" + "both X and Y"
    assert profile.depth_score > 0.0

    # Composite should be high
    assert profile.composite > 0.5


# ---------------------------------------------------------------------------
# 5. Custom config overrides
# ---------------------------------------------------------------------------

def test_custom_config() -> None:
    config = AdaptiveConfig(
        simple_nodes=2,
        moderate_nodes=6,
        complex_nodes=10,
        expert_nodes=20,
        token_low=5,
        token_high=30,
    )
    activator = AdaptiveActivation(config=config)

    # Simple query
    _, kmax_simple = activator.analyze("Hello")
    assert kmax_simple == 2

    # Complex query
    _, kmax_complex = activator.analyze(
        "How does GDPR affect DORA and NIS2 compliance across multiple "
        "regulatory frameworks while considering both AI Act and MiCA?"
    )
    assert kmax_complex >= 10


# ---------------------------------------------------------------------------
# 6. Tier classification — test all 4 tier boundaries
# ---------------------------------------------------------------------------

def test_tier_classification() -> None:
    # v0.12.1 thresholds: simple <0.15, moderate 0.15-0.35, complex 0.35-0.55, expert >=0.55

    # Simple: composite < 0.15
    p_simple = ComplexityProfile(
        token_score=0.0, entity_score=0.0,
        conjunction_score=0.0, depth_score=0.0,
    )
    assert p_simple.tier == "simple"
    assert p_simple.composite < 0.15

    # Moderate: 0.15 <= composite < 0.35
    p_moderate = ComplexityProfile(
        token_score=0.3, entity_score=0.3,
        conjunction_score=0.2, depth_score=0.2,
    )
    assert p_moderate.tier == "moderate"
    assert 0.15 <= p_moderate.composite < 0.35

    # Complex: 0.35 <= composite < 0.55
    p_complex = ComplexityProfile(
        token_score=0.6, entity_score=0.5,
        conjunction_score=0.5, depth_score=0.5,
    )
    assert p_complex.tier == "complex"
    assert 0.35 <= p_complex.composite < 0.55

    # Expert: composite >= 0.55
    p_expert = ComplexityProfile(
        token_score=1.0, entity_score=1.0,
        conjunction_score=1.0, depth_score=1.0,
    )
    assert p_expert.tier == "expert"
    assert p_expert.composite >= 0.55


# ---------------------------------------------------------------------------
# 7. activate() delegates to PCSTActivation with correct max_nodes
# ---------------------------------------------------------------------------

def test_activate_delegates_to_pcst(activator: AdaptiveActivation) -> None:
    mock_graph = MagicMock()
    expected_nodes = ["node_1", "node_2", "node_3"]

    with patch(
        "graqle.activation.adaptive.PCSTActivation"
    ) as MockPCST:
        mock_instance = MockPCST.return_value
        mock_instance.activate.return_value = expected_nodes

        query = "Hello"
        result = activator.activate(mock_graph, query)

    # Should have created PCSTActivation with kmax=4 (simple tier)
    MockPCST.assert_called_once()
    call_kwargs = MockPCST.call_args[1]
    assert call_kwargs["max_nodes"] == 4

    # Should have delegated activate call
    mock_instance.activate.assert_called_once_with(mock_graph, query)
    assert result == expected_nodes


# ---------------------------------------------------------------------------
# 8. last_profile and last_kmax are accessible after activate
# ---------------------------------------------------------------------------

def test_last_profile_stored(activator: AdaptiveActivation) -> None:
    # Before any call, last_profile is None
    assert activator.last_profile is None
    assert activator.last_kmax == 0

    mock_graph = MagicMock()

    with patch(
        "graqle.activation.adaptive.PCSTActivation"
    ) as MockPCST:
        mock_instance = MockPCST.return_value
        mock_instance.activate.return_value = ["n1", "n2"]

        activator.activate(mock_graph, "Hello")

    # After activate, last_profile and last_kmax should be set
    assert activator.last_profile is not None
    assert isinstance(activator.last_profile, ComplexityProfile)
    assert activator.last_profile.tier == "simple"
    assert activator.last_kmax == 4


# ---------------------------------------------------------------------------
# 9. v0.12.1: Real-world dev queries trigger non-simple tiers
# ---------------------------------------------------------------------------

def test_dev_queries_not_always_simple(scorer: QueryComplexityScorer) -> None:
    """Bug 5 regression: dev queries must trigger moderate+ tiers."""
    queries_and_expected_min_tier = [
        ("How does the auth service work?", "moderate"),
        ("What files depend on the database module?", "moderate"),
        ("Explain how the API endpoints interact with the auth middleware", "complex"),
    ]
    tier_order = {"simple": 0, "moderate": 1, "complex": 2, "expert": 3}

    for query, min_tier in queries_and_expected_min_tier:
        profile = scorer.score(query)
        assert tier_order[profile.tier] >= tier_order[min_tier], (
            f"Query '{query}' scored {profile.tier} (composite={profile.composite:.3f}), "
            f"expected at least {min_tier}"
        )


def test_simple_queries_stay_simple(scorer: QueryComplexityScorer) -> None:
    """Very short, single-concept queries should stay simple."""
    for query in ["Hello", "Hi there", "What?"]:
        profile = scorer.score(query)
        assert profile.tier == "simple", (
            f"'{query}' should be simple but got {profile.tier}"
        )


# ---------------------------------------------------------------------------
# 10. Init merge logic
# ---------------------------------------------------------------------------

def test_deep_merge() -> None:
    """_deep_merge preserves existing values and fills gaps."""
    from graqle.cli.commands.init import _deep_merge

    base = {"a": 1, "b": {"x": 10, "y": 20}, "c": 3}
    override = {"a": 99, "b": {"x": 99, "z": 30}, "d": 4}
    result = _deep_merge(base, override)

    assert result["a"] == 99       # override wins
    assert result["b"]["x"] == 99  # override wins (nested)
    assert result["b"]["y"] == 20  # base preserved (not in override)
    assert result["b"]["z"] == 30  # override adds new key
    assert result["c"] == 3        # base preserved
    assert result["d"] == 4        # override adds new key
