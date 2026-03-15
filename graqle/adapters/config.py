"""AdapterConfig — LoRA adapter configuration."""

# ── graqle:intelligence ──
# module: graqle.adapters.config
# risk: LOW (impact radius: 7 modules)
# consumers: hub, loader, registry, __init__, test_adapter_config +2 more
# dependencies: __future__, dataclasses
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AdapterConfig:
    """Configuration for a LoRA adapter.

    LoRA adapters are small (~4MB) parameter patches that specialize
    the base model for a specific domain. A GDPR adapter makes the
    base model an expert on GDPR. They hot-swap on top of one shared
    base model.
    """

    # Identity
    adapter_id: str = ""
    name: str = ""
    domain: str = "custom"
    version: str = "v1"

    # LoRA hyperparameters
    rank: int = 16
    alpha: int = 32
    dropout: float = 0.05
    target_modules: list[str] = field(
        default_factory=lambda: ["q_proj", "v_proj"]
    )

    # Training
    base_model: str = "Qwen/Qwen2.5-0.5B-Instruct"
    learning_rate: float = 2e-4
    epochs: int = 3
    batch_size: int = 4
    max_seq_length: int = 2048

    # Metadata
    description: str = ""
    tags: list[str] = field(default_factory=list)
    size_mb: float = 0.0  # computed after training

    @property
    def full_id(self) -> str:
        """Full adapter identifier: domain/name_version."""
        return f"{self.domain}/{self.name}_{self.version}"

    def to_peft_config(self) -> dict:
        """Convert to PEFT LoraConfig kwargs."""
        return {
            "r": self.rank,
            "lora_alpha": self.alpha,
            "lora_dropout": self.dropout,
            "target_modules": self.target_modules,
            "task_type": "CAUSAL_LM",
        }
