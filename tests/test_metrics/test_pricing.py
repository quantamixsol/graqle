# V-AUTH-SAVINGS-NATIVE-002: new test file via native Write (S-010).
"""Tests for graqle.pricing — the authentic cost-savings source of truth."""

from __future__ import annotations

import pytest

from graqle import pricing


def test_known_model_prices_match_published_rates():
    assert pricing.price_for("claude-opus-4-8").input_per_1m == 5.00
    assert pricing.price_for("claude-opus-4-8").output_per_1m == 25.00
    assert pricing.price_for("claude-sonnet-4-6").input_per_1m == 3.00
    assert pricing.price_for("claude-sonnet-4-6").output_per_1m == 15.00
    assert pricing.price_for("claude-haiku-4-5").input_per_1m == 1.00
    assert pricing.price_for("claude-haiku-4-5").output_per_1m == 5.00


def test_per_token_derives_from_per_million():
    p = pricing.price_for("claude-opus-4-8")
    assert p.input_per_token == pytest.approx(5.00 / 1_000_000)
    assert p.output_per_token == pytest.approx(25.00 / 1_000_000)


def test_unknown_model_falls_back_to_default_not_error():
    # An unknown family must NOT raise and must value at DEFAULT_MODEL (Sonnet).
    p = pricing.price_for("some-future-model-x")
    assert p.input_per_1m == pricing.price_for(pricing.DEFAULT_MODEL).input_per_1m


def test_none_and_blank_model_use_default():
    assert pricing.price_for(None).input_per_1m == pricing.price_for(pricing.DEFAULT_MODEL).input_per_1m
    assert pricing.price_for("").input_per_1m == pricing.price_for(pricing.DEFAULT_MODEL).input_per_1m


def test_date_and_speed_suffixes_match_by_prefix():
    # Real ids sometimes carry a date or speed suffix — value them correctly.
    assert pricing.price_for("claude-haiku-4-5-20251001").input_per_1m == 1.00
    assert pricing.price_for("claude-opus-4-6-fast").input_per_1m == 5.00


def test_cost_saved_uses_input_price_of_the_real_model():
    # 88.2M input tokens saved, valued at each model's INPUT rate.
    saved = 88_200_000
    assert pricing.cost_saved(saved, "claude-sonnet-4-6") == pytest.approx(264.60, abs=0.01)
    assert pricing.cost_saved(saved, "claude-opus-4-8") == pytest.approx(441.00, abs=0.01)
    assert pricing.cost_saved(saved, "claude-haiku-4-5") == pytest.approx(88.20, abs=0.01)


def test_cost_saved_default_model_is_sonnet():
    saved = 1_000_000
    assert pricing.cost_saved(saved) == pytest.approx(3.00, abs=1e-6)


def test_cost_saved_never_negative():
    assert pricing.cost_saved(-5, "claude-opus-4-8") == 0.0


def test_cost_for_tokens_input_and_output():
    # 1M input + 1M output on Opus = $5 + $25.
    assert pricing.cost_for_tokens("claude-opus-4-8", 1_000_000, 1_000_000) == pytest.approx(30.00)
    # negatives clamp to 0
    assert pricing.cost_for_tokens("claude-opus-4-8", -10, -10) == 0.0


def test_pricing_basis_is_renderable_and_dated():
    basis = pricing.pricing_basis("claude-opus-4-8")
    assert basis["model"] == "claude-opus-4-8"
    assert basis["input_per_1m"] == 5.00
    assert basis["output_per_1m"] == 25.00
    assert basis["as_of"] == pricing.PRICING_AS_OF


def test_pricing_as_of_is_set():
    assert isinstance(pricing.PRICING_AS_OF, str) and pricing.PRICING_AS_OF


# ---- engine wiring: authentic per-model cost in the summary ----

def test_summary_exposes_authentic_cost_saved(tmp_path):
    from graqle.metrics.engine import MetricsEngine

    eng = MetricsEngine(metrics_dir=tmp_path)
    eng.tokens_saved = 88_200_000

    # default (no model recorded) → Sonnet rate
    s = eng.get_summary()
    assert s["cost_saved_usd"] == pytest.approx(264.60, abs=0.01)
    assert s["cost_basis"]["model"] == pricing.DEFAULT_MODEL
    assert s["cost_model"] is None

    # record the real model → cost reflects it
    eng.set_cost_model("claude-opus-4-8")
    s2 = eng.get_summary()
    assert s2["cost_saved_usd"] == pytest.approx(441.00, abs=0.01)
    assert s2["cost_basis"]["model"] == "claude-opus-4-8"
    assert s2["cost_model"] == "claude-opus-4-8"


def test_set_cost_model_ignores_blank(tmp_path):
    from graqle.metrics.engine import MetricsEngine

    eng = MetricsEngine(metrics_dir=tmp_path)
    eng.set_cost_model("claude-opus-4-8")
    eng.set_cost_model("")     # ignored
    eng.set_cost_model(None)   # ignored
    eng.set_cost_model("   ")  # ignored
    assert eng._cost_model == "claude-opus-4-8"


def test_roi_report_shows_model_basis_not_hardcoded_rate(tmp_path):
    from graqle.metrics.engine import MetricsEngine

    eng = MetricsEngine(metrics_dir=tmp_path)
    eng.tokens_saved = 10_000_000
    eng.set_cost_model("claude-opus-4-8")
    report = eng.get_roi_report()
    assert "claude-opus-4-8 input" in report
    assert pricing.PRICING_AS_OF in report
    assert "$0.015" not in report  # the old hardcoded rate must be gone
