"""Tests for region-agnostic backend configuration."""

# ── graqle:intelligence ──
# module: tests.test_config.test_region_agnostic
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, os, mock, pytest
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import os
from unittest.mock import patch


class TestRegionConfig:
    def test_model_config_has_region_field(self):
        """ModelConfig should have an optional region field."""
        from graqle.config.settings import ModelConfig
        cfg = ModelConfig()
        assert cfg.region is None

    def test_model_config_accepts_region(self):
        """ModelConfig should accept region in constructor."""
        from graqle.config.settings import ModelConfig
        cfg = ModelConfig(region="us-west-2")
        assert cfg.region == "us-west-2"

    def test_model_config_has_host_field(self):
        """ModelConfig should have an optional host field."""
        from graqle.config.settings import ModelConfig
        cfg = ModelConfig()
        assert cfg.host is None

    def test_graqle_config_region_from_yaml(self, tmp_path):
        """Region should be loadable from graqle.yaml."""
        yaml_file = tmp_path / "graqle.yaml"
        yaml_file.write_text(
            "model:\n  backend: bedrock\n  model: anthropic.claude-haiku-4-5-20251001-v1:0\n  region: eu-north-1\n",
            encoding="utf-8",
        )
        from graqle.config.settings import GraqleConfig
        cfg = GraqleConfig.from_yaml(str(yaml_file))
        assert cfg.model.region == "eu-north-1"

    def test_bedrock_backend_no_default_region(self):
        """BedrockBackend should not hardcode eu-central-1."""
        from graqle.backends.api import BedrockBackend
        # With explicit region
        b = BedrockBackend(region="ap-southeast-1")
        assert b._region == "ap-southeast-1"

    def test_bedrock_backend_env_fallback(self):
        """BedrockBackend should fall back to AWS_DEFAULT_REGION env var."""
        from graqle.backends.api import BedrockBackend
        with patch.dict(os.environ, {"AWS_DEFAULT_REGION": "eu-west-1"}, clear=False):
            b = BedrockBackend(region=None)
            assert b._region == "eu-west-1"

    def test_bedrock_backend_ultimate_fallback(self):
        """BedrockBackend should use us-east-1 as ultimate fallback."""
        from graqle.backends.api import BedrockBackend
        with patch.dict(os.environ, {}, clear=True):
            # Remove all AWS region env vars
            env = {k: v for k, v in os.environ.items() if "REGION" not in k}
            with patch.dict(os.environ, env, clear=True):
                b = BedrockBackend(region=None)
                assert b._region == "us-east-1"
