"""Tests for R10 R9 federated activation configuration."""

from __future__ import annotations

import json
from pathlib import Path

from graqle.alignment.r9_config import (
    FederatedActivationConfig,
    _load_penalties,
    configure_r9_from_alignment,
)
from graqle.alignment.types import AlignmentReport


def _make_report(mean_cosine: float) -> AlignmentReport:
    return AlignmentReport(
        pairs=[], mean_cosine=mean_cosine, median_cosine=mean_cosine,
        std_cosine=0.0,
    )


class TestLoadPenalties:
    def test_missing_file_returns_defaults(self, tmp_path: Path):
        penalties = _load_penalties(tmp_path / "nonexistent.json")
        assert penalties["green"] == 1.0
        assert penalties["red"] == 0.0

    def test_valid_file_loads_values(self, tmp_path: Path):
        path = tmp_path / "penalties.json"
        path.write_text(json.dumps({"green": 1.0, "blue": 0.95, "yellow": 0.80}))
        penalties = _load_penalties(path)
        assert penalties["blue"] == 0.95
        assert penalties["yellow"] == 0.80

    def test_corrupt_file_falls_back(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text("NOT JSON")
        penalties = _load_penalties(path)
        assert penalties == {"green": 1.0, "blue": 1.0, "yellow": 1.0, "red": 0.0, "gray": 0.0}


class TestConfigureR9:
    def test_green_no_penalty(self):
        config = configure_r9_from_alignment(_make_report(0.90))
        assert config.unaligned_penalty == 1.0
        assert config.cross_kg_enabled is True
        assert len(config.warnings) == 0

    def test_blue_uses_loaded_penalty(self, tmp_path: Path):
        path = tmp_path / "penalties.json"
        path.write_text(json.dumps({"blue": 0.88}))
        config = configure_r9_from_alignment(_make_report(0.75), penalties_path=path)
        assert config.unaligned_penalty == 0.88
        assert config.cross_kg_enabled is True

    def test_yellow_uses_loaded_penalty(self, tmp_path: Path):
        path = tmp_path / "penalties.json"
        path.write_text(json.dumps({"yellow": 0.65}))
        config = configure_r9_from_alignment(_make_report(0.60), penalties_path=path)
        assert config.unaligned_penalty == 0.65
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

    def test_updates_existing_config(self):
        existing = FederatedActivationConfig(unaligned_penalty=0.5)
        config = configure_r9_from_alignment(_make_report(0.90), existing)
        assert config.unaligned_penalty == 1.0
        assert config is existing

    def test_default_penalties_without_config_file(self):
        """Without private config, defaults are safe (no proprietary values exposed)."""
        config = configure_r9_from_alignment(
            _make_report(0.75),
            penalties_path=Path("/nonexistent/path/penalties.json"),
        )
        # Default blue penalty is 1.0 (safe fallback)
        assert config.unaligned_penalty == 1.0
