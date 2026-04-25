"""Tests for R23 GSEFT scaffold (ADR-206).

Covers:
- GSEFT_TRAINING_DEFERRED default (True) and env-injectable flip (B3)
- TrainerConfig hyperparameter env injection (B1)
- B4 guard: ValueError on zero batch_size / learning_rate when training enabled
- No Bedrock/boto3 imports in graqle.embeddings (B2)
"""
from __future__ import annotations

import importlib
import os
import sys

import pytest

from graqle.embeddings.governance_dataset import GovernanceDataset


# ---------------------------------------------------------------------------
# B3: GSEFT_TRAINING_DEFERRED env-injectable
# ---------------------------------------------------------------------------

class TestGseftDeferredFlag:
    def test_deferred_by_default(self):
        import graqle.embeddings.governance_dataset as gd
        assert gd.GSEFT_TRAINING_DEFERRED is True

    def test_env_flip_enables_training(self, monkeypatch):
        monkeypatch.setenv("GRAQLE_GSEFT_TRAINING_ENABLED", "1")
        import graqle.embeddings.governance_dataset as gd
        importlib.reload(gd)
        assert gd.GSEFT_TRAINING_DEFERRED is False
        # restore
        monkeypatch.delenv("GRAQLE_GSEFT_TRAINING_ENABLED", raising=False)
        importlib.reload(gd)

    def test_any_value_other_than_1_keeps_deferred(self, monkeypatch):
        for val in ("0", "false", "True", "yes", ""):
            monkeypatch.setenv("GRAQLE_GSEFT_TRAINING_ENABLED", val)
            import graqle.embeddings.governance_dataset as gd
            importlib.reload(gd)
            assert gd.GSEFT_TRAINING_DEFERRED is True
        importlib.reload(gd)


# ---------------------------------------------------------------------------
# B1: TrainerConfig hyperparameter env injection
# ---------------------------------------------------------------------------

class TestTrainerConfigEnvInjection:
    def test_defaults_are_zero_not_hardcoded(self):
        from graqle.embeddings.contrastive_trainer import TrainerConfig
        cfg = TrainerConfig()
        assert cfg.batch_size == 0
        assert cfg.learning_rate == 0.0

    def test_batch_size_from_env(self, monkeypatch):
        monkeypatch.setenv("GRAQLE_GSEFT_BATCH_SIZE", "64")
        from graqle.embeddings import contrastive_trainer as ct
        importlib.reload(ct)
        cfg = ct.TrainerConfig()
        assert cfg.batch_size == 64

    def test_learning_rate_from_env(self, monkeypatch):
        monkeypatch.setenv("GRAQLE_GSEFT_LEARNING_RATE", "0.0001")
        from graqle.embeddings import contrastive_trainer as ct
        importlib.reload(ct)
        cfg = ct.TrainerConfig()
        assert cfg.learning_rate == pytest.approx(0.0001)

    def test_explicit_values_override_env(self, monkeypatch):
        monkeypatch.setenv("GRAQLE_GSEFT_BATCH_SIZE", "32")
        from graqle.embeddings.contrastive_trainer import TrainerConfig
        cfg = TrainerConfig(batch_size=128, learning_rate=5e-5)
        assert cfg.batch_size == 128
        assert cfg.learning_rate == pytest.approx(5e-5)


# ---------------------------------------------------------------------------
# B4: ValueError guard on zero hyperparams when training is enabled
# ---------------------------------------------------------------------------

class TestB4ZeroHyperparamGuard:
    def _make_trainer(self, batch_size, learning_rate):
        from graqle.embeddings.contrastive_trainer import ContrastiveTrainer, TrainerConfig
        cfg = TrainerConfig(batch_size=batch_size, learning_rate=learning_rate)
        return ContrastiveTrainer(config=cfg)

    def _non_empty_dataset(self):
        from graqle.embeddings.governance_dataset import GovernanceTriplet
        return GovernanceDataset([GovernanceTriplet("a", "b", "c")])

    def test_raises_on_zero_batch_size_when_training_enabled(self, monkeypatch):
        monkeypatch.setenv("GRAQLE_GSEFT_TRAINING_ENABLED", "1")
        import graqle.embeddings.governance_dataset as gd
        importlib.reload(gd)
        # patch the module-level flag seen by contrastive_trainer
        import graqle.embeddings.contrastive_trainer as ct
        monkeypatch.setattr(ct, "GSEFT_TRAINING_DEFERRED", False)
        trainer = self._make_trainer(batch_size=0, learning_rate=1e-4)
        with pytest.raises(ValueError, match="batch_size"):
            trainer.train(self._non_empty_dataset())

    def test_raises_on_zero_learning_rate_when_training_enabled(self, monkeypatch):
        import graqle.embeddings.contrastive_trainer as ct
        monkeypatch.setattr(ct, "GSEFT_TRAINING_DEFERRED", False)
        trainer = self._make_trainer(batch_size=32, learning_rate=0.0)
        with pytest.raises(ValueError, match="learning_rate"):
            trainer.train(self._non_empty_dataset())

    def test_no_error_when_deferred(self):
        # When GSEFT_TRAINING_DEFERRED=True (default), guard is never reached
        from graqle.embeddings.contrastive_trainer import ContrastiveTrainer, TrainerConfig
        cfg = TrainerConfig(batch_size=0, learning_rate=0.0)
        trainer = ContrastiveTrainer(config=cfg)
        result = trainer.train(GovernanceDataset([]))
        assert result.trained is False
        assert "DEFERRED" in result.skipped_reason


# ---------------------------------------------------------------------------
# B2: No Bedrock/boto3 imports in graqle.embeddings
# ---------------------------------------------------------------------------

class TestB2NoBedrockImports:
    def test_embeddings_package_has_no_boto3(self):
        import graqle.embeddings
        import graqle.embeddings.model_registry
        import graqle.embeddings.governance_dataset
        import graqle.embeddings.contrastive_trainer
        import graqle.embeddings.governance_eval
        import ast
        for mod_name, mod in sys.modules.items():
            if mod_name.startswith("graqle.embeddings"):
                src = getattr(mod, "__file__", "") or ""
                if src and src.endswith(".py"):
                    tree = ast.parse(open(src, encoding="utf-8").read())
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.Import, ast.ImportFrom)):
                            names = (
                                [a.name for a in node.names]
                                if isinstance(node, ast.Import)
                                else ([node.module] if node.module else [])
                            )
                            for name in names:
                                assert "boto3" not in name, f"boto3 import in {src}"
                                assert "bedrock" not in name.lower(), f"bedrock import in {src}"
