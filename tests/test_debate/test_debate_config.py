"""Tests for R15 P0 debate configuration, dataclasses, and cost lookups.

Covers:
  1. DebateTurn dataclass instantiation and defaults
  2. DebateTrace dataclass instantiation and defaults
  3. DebateConfig default values
  4. DebateConfig YAML override via GraqleConfig
  5. GraqleConfig panelist validation (error cases)
  6. GraqleConfig panelist validation (success + warning)
  7. OpenAI GPT-5.4 cost lookups
  8. OpenAI unknown model fallback
"""

from __future__ import annotations

import logging
from datetime import datetime

import pytest

from graqle.backends.api import OpenAIBackend
from graqle.config.settings import DebateConfig, GraqleConfig, NamedModelConfig
from graqle.core.types import DebateTrace, DebateTurn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_turn(panelist: str = "gpt-5.4") -> DebateTurn:
    return DebateTurn(
        round_number=1,
        panelist=panelist,
        position="propose",
        argument="Test argument.",
        evidence_refs=["ref-1"],
        confidence=0.8,
        cost_usd=0.01,
        latency_ms=120.0,
    )


def _models_dict(*names: str) -> dict[str, dict]:
    """Build a models dict for GraqleConfig validation."""
    return {n: {"backend": "openai", "model": n} for n in names}


# ---------------------------------------------------------------------------
# 1. DebateTurn dataclass
# ---------------------------------------------------------------------------


class TestDebateTurn:
    """DebateTurn instantiation and field defaults."""

    def test_instantiation_all_fields(self):
        turn = _make_turn("analyst-a")
        assert turn.panelist == "analyst-a"
        assert turn.position == "propose"
        assert turn.argument == "Test argument."
        assert turn.confidence == 0.8
        assert turn.evidence_refs == ["ref-1"]
        assert turn.round_number == 1
        assert turn.cost_usd == 0.01
        assert turn.latency_ms == 120.0

    def test_timestamp_default_is_datetime(self):
        turn = _make_turn()
        assert isinstance(turn.timestamp, datetime)

    def test_evidence_refs_is_list(self):
        turn = _make_turn()
        assert isinstance(turn.evidence_refs, list)


# ---------------------------------------------------------------------------
# 2. DebateTrace dataclass
# ---------------------------------------------------------------------------


class TestDebateTrace:
    """DebateTrace instantiation and defaults."""

    def test_instantiation(self):
        trace = DebateTrace(
            query="What is the root cause?",
            turns=[_make_turn("p1"), _make_turn("p2")],
            synthesis="The root cause is X.",
            final_confidence=0.9,
            total_cost_usd=0.05,
            total_latency_ms=500.0,
            consensus_reached=True,
            rounds_completed=2,
            panelist_names=["p1", "p2"],
        )
        assert trace.panelist_names == ["p1", "p2"]
        assert len(trace.turns) == 2

    def test_metadata_defaults_to_empty_dict(self):
        trace = DebateTrace(
            query="q",
            turns=[],
            synthesis="s",
            final_confidence=0.5,
            total_cost_usd=0.0,
            total_latency_ms=0.0,
            consensus_reached=False,
            rounds_completed=0,
            panelist_names=[],
        )
        assert isinstance(trace.metadata, dict)
        assert trace.metadata == {}

    def test_panelist_names_is_list(self):
        trace = DebateTrace(
            query="q",
            turns=[],
            synthesis="s",
            final_confidence=0.5,
            total_cost_usd=0.0,
            total_latency_ms=0.0,
            consensus_reached=False,
            rounds_completed=0,
            panelist_names=["a", "b", "c"],
        )
        assert isinstance(trace.panelist_names, list)
        assert len(trace.panelist_names) == 3

    def test_turns_is_list_of_debate_turn(self):
        t1, t2 = _make_turn("p1"), _make_turn("p2")
        trace = DebateTrace(
            query="q",
            turns=[t1, t2],
            synthesis="s",
            final_confidence=0.5,
            total_cost_usd=0.0,
            total_latency_ms=0.0,
            consensus_reached=False,
            rounds_completed=1,
            panelist_names=["p1", "p2"],
        )
        assert all(isinstance(t, DebateTurn) for t in trace.turns)


# ---------------------------------------------------------------------------
# 3. DebateConfig defaults
# ---------------------------------------------------------------------------


class TestDebateConfigDefaults:
    """DebateConfig default field values per R15 spec."""

    def test_mode_default(self):
        assert DebateConfig().mode == "off"

    def test_panelists_default(self):
        assert DebateConfig().panelists == []

    def test_max_rounds_default(self):
        assert DebateConfig().max_rounds == 3

    def test_convergence_threshold_is_float(self):
        assert isinstance(DebateConfig().convergence_threshold, float)

    def test_cost_ceiling_usd_is_float(self):
        assert isinstance(DebateConfig().cost_ceiling_usd, float)

    def test_require_citation_default(self):
        assert DebateConfig().require_citation is True

    def test_ab_mode_default(self):
        assert DebateConfig().ab_mode is False

    def test_judge_profile_default(self):
        assert DebateConfig().judge_profile is None


# ---------------------------------------------------------------------------
# 4. DebateConfig YAML override via GraqleConfig
# ---------------------------------------------------------------------------


class TestDebateConfigYAMLOverride:
    """convergence_threshold and cost_ceiling_usd can be overridden."""

    def test_convergence_threshold_override(self):
        cfg = GraqleConfig.model_validate({
            "debate": {"convergence_threshold": 0.70},
        })
        assert cfg.debate.convergence_threshold == pytest.approx(0.70)

    def test_cost_ceiling_usd_override(self):
        cfg = GraqleConfig.model_validate({
            "debate": {"cost_ceiling_usd": 10.0},
        })
        assert cfg.debate.cost_ceiling_usd == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# 5. GraqleConfig panelist validation — error cases
# ---------------------------------------------------------------------------


class TestPanelistValidationErrors:
    """mode='debate' requires >=2 defined panelists; mode='off' skips."""

    def test_debate_mode_undefined_panelists_raises(self):
        with pytest.raises(ValueError, match="undefined model profiles"):
            GraqleConfig.model_validate({
                "debate": {"mode": "debate", "panelists": ["no-such", "also-no"]},
            })

    def test_debate_mode_one_panelist_raises(self):
        with pytest.raises(ValueError, match="at least 2 panelists"):
            GraqleConfig.model_validate({
                "debate": {"mode": "debate", "panelists": ["only-one"]},
                "models": _models_dict("only-one"),
            })

    def test_off_mode_skips_validation(self):
        cfg = GraqleConfig.model_validate({
            "debate": {"mode": "off", "panelists": []},
        })
        assert cfg.debate.mode == "off"


# ---------------------------------------------------------------------------
# 6. GraqleConfig panelist validation — success + warning
# ---------------------------------------------------------------------------


class TestPanelistValidationSuccess:
    """mode='debate' with 2-7 panelists passes; >7 logs warning."""

    def test_two_panelists_passes(self):
        cfg = GraqleConfig.model_validate({
            "debate": {"mode": "debate", "panelists": ["a", "b"]},
            "models": _models_dict("a", "b"),
        })
        assert len(cfg.debate.panelists) == 2

    def test_seven_panelists_passes(self):
        names = [f"p{i}" for i in range(7)]
        cfg = GraqleConfig.model_validate({
            "debate": {"mode": "debate", "panelists": names},
            "models": _models_dict(*names),
        })
        assert len(cfg.debate.panelists) == 7

    def test_more_than_seven_panelists_logs_warning(self, caplog):
        names = [f"p{i}" for i in range(8)]
        with caplog.at_level(logging.WARNING):
            cfg = GraqleConfig.model_validate({
                "debate": {"mode": "debate", "panelists": names},
                "models": _models_dict(*names),
            })
        assert len(cfg.debate.panelists) == 8
        assert any("panelist" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# 7. OpenAI GPT-5.4 cost lookups
# ---------------------------------------------------------------------------


class TestOpenAIGPT54Costs:
    """GPT-5.4 family cost-per-1k-token lookups."""

    @pytest.mark.parametrize("model,expected_cost", [
        ("gpt-5.4", 0.015),
        ("gpt-5.4-mini", 0.003),
        ("gpt-5.4-nano", 0.0006),
    ])
    def test_known_model_costs(self, model, expected_cost):
        backend = OpenAIBackend(model=model, api_key="test-key")
        assert backend.cost_per_1k_tokens == pytest.approx(expected_cost)


# ---------------------------------------------------------------------------
# 8. OpenAI unknown model fallback
# ---------------------------------------------------------------------------


class TestOpenAIUnknownModelFallback:
    """Unknown model returns 0.001 and logs a warning."""

    def test_unknown_model_returns_fallback(self):
        backend = OpenAIBackend(model="totally-unknown-xyz", api_key="test-key")
        assert backend.cost_per_1k_tokens == pytest.approx(0.001)

    def test_unknown_model_logs_warning(self, caplog):
        backend = OpenAIBackend(model="totally-unknown-xyz", api_key="test-key")
        with caplog.at_level(logging.WARNING):
            _ = backend.cost_per_1k_tokens
        assert any("unknown" in r.message.lower() for r in caplog.records)
