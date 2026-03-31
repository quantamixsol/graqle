"""Tests for R10 five-tier alignment classification."""

from __future__ import annotations

from graqle.alignment.tiers import ALIGNMENT_TIERS, classify_alignment_tier


class TestTierClassification:
    def test_green(self):
        assert classify_alignment_tier(0.90) == "GREEN"
        assert classify_alignment_tier(0.85) == "GREEN"
        assert classify_alignment_tier(1.0) == "GREEN"

    def test_blue(self):
        assert classify_alignment_tier(0.75) == "BLUE"
        assert classify_alignment_tier(0.70) == "BLUE"

    def test_yellow(self):
        assert classify_alignment_tier(0.60) == "YELLOW"
        assert classify_alignment_tier(0.55) == "YELLOW"

    def test_red(self):
        assert classify_alignment_tier(0.50) == "RED"
        assert classify_alignment_tier(0.40) == "RED"

    def test_gray(self):
        assert classify_alignment_tier(0.30) == "GRAY"
        assert classify_alignment_tier(0.0) == "GRAY"

    def test_negative_falls_to_gray(self):
        assert classify_alignment_tier(-0.1) == "GRAY"

    def test_all_tiers_defined(self):
        assert set(ALIGNMENT_TIERS.keys()) == {"GREEN", "BLUE", "YELLOW", "RED", "GRAY"}

    def test_each_tier_has_required_fields(self):
        for tier_name, tier_info in ALIGNMENT_TIERS.items():
            assert "range" in tier_info, f"{tier_name} missing 'range'"
            assert "label" in tier_info, f"{tier_name} missing 'label'"
            assert "action" in tier_info, f"{tier_name} missing 'action'"
            assert "description" in tier_info, f"{tier_name} missing 'description'"

    def test_boundary_values(self):
        # Exact boundaries
        assert classify_alignment_tier(0.85) == "GREEN"
        assert classify_alignment_tier(0.70) == "BLUE"
        assert classify_alignment_tier(0.55) == "YELLOW"
        assert classify_alignment_tier(0.40) == "RED"
