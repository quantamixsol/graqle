"""Tests for R10 R9 federated activation configuration."""

from __future__ import annotations

from graqle.alignment.r9_config import (
    FederatedActivationConfig,
    configure_r9_from_alignment,
)
from graqle.alignment.types import AlignmentReport


def _make_report(mean_cosine: float) -> AlignmentReport:
    return AlignmentReport(
        pairs=[], mean_cosine=mean_cosine, median_cosine=mean_cosine,
        std_cosine=0.0,
    )


class TestConfigureR9:
    def test_green_no_penalty(self):
        config = configure_r9_from_alignment(_make_report(0.90))
        assert config.unaligned_penalty == 1.0
        assert config.cross_kg_enabled is True
        assert len(config.warnings) == 0

    def test_blue_slight_discount(self):
        config = configure_r9_from_alignment(_make_report(0.75))
        assert config.unaligned_penalty == 0.90
        assert config.cross_kg_enabled is True

    def test_yellow_significant_discount(self):
        config = configure_r9_from_alignment(_make_report(0.60))
        assert config.unaligned_penalty == 0.70
        assert config.cross_kg_enabled is True
        assert len(config.warnings) == 1
        assert "YELLOW" in config.warnings[0]

    def test_red_federation_blocked(self):
        config = configure_r9_from_alignment(_make_report(0.45))
        assert config.unaligned_penalty == 0.0
        assert config.cross_kg_enabled is False
        assert len(config.warnings) == 1
        assert "BLOCKED" in config.warnings[0]

    def test_gray_federation_blocked(self):
        config = configure_r9_from_alignment(_make_report(0.20))
        assert config.unaligned_penalty == 0.0
        assert config.cross_kg_enabled is False

    def test_metadata_stored(self):
        config = configure_r9_from_alignment(_make_report(0.85))
        assert "mean_cosine" in config.alignment_metadata
        assert "measurement_timestamp" in config.alignment_metadata
        assert config.alignment_metadata["mean_cosine"] == 0.85

    def test_updates_existing_config(self):
        existing = FederatedActivationConfig(unaligned_penalty=0.5)
        config = configure_r9_from_alignment(_make_report(0.90), existing)
        assert config.unaligned_penalty == 1.0
        assert config is existing  # same object updated

    def test_boundary_085_is_green(self):
        config = configure_r9_from_alignment(_make_report(0.85))
        assert config.unaligned_penalty == 1.0

    def test_boundary_070_is_blue(self):
        config = configure_r9_from_alignment(_make_report(0.70))
        assert config.unaligned_penalty == 0.90
