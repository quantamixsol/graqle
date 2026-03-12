"""CogniGraph configuration system — Pydantic settings + YAML loading."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    """Model backend configuration."""

    backend: str = "local"
    model: str = "Qwen/Qwen2.5-0.5B-Instruct"
    quantization: str = "none"
    device: str = "auto"
    max_concurrent_adapters: int = 16
    api_key: str | None = None


class GraphConfig(BaseModel):
    """Graph connector configuration."""

    connector: str = "networkx"
    uri: str | None = None
    username: str | None = None
    password: str | None = None
    database: str | None = None
    # Neo4j vector search settings
    vector_index_name: str = "cogni_chunk_embedding_index"
    embedding_dimension: int = 1024
    embedding_model: str = "amazon.titan-embed-text-v2:0"


class ActivationConfig(BaseModel):
    """Subgraph activation configuration."""

    strategy: str = "chunk"  # "chunk" (default), "pcst" (legacy), "full", "top_k"
    max_nodes: int = 50
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    pcst_pruning: str = "strong"
    prize_scaling: float = 1.0
    cost_scaling: float = 1.0


class OrchestrationConfig(BaseModel):
    """Message passing orchestration configuration."""

    max_rounds: int = 5
    min_rounds: int = 2
    convergence_threshold: float = 0.95
    aggregation: str = "weighted_synthesis"
    async_mode: bool = False
    confidence_threshold: float = 0.8


class ObserverConfig(BaseModel):
    """MasterObserver configuration."""

    enabled: bool = False
    report_per_round: bool = False
    detect_conflicts: bool = True
    detect_patterns: bool = True
    detect_anomalies: bool = True
    use_llm_analysis: bool = False
    backend: str | None = None  # named model profile for observer


class CostConfig(BaseModel):
    """Cost control configuration."""

    budget_per_query: float = 0.10  # $0.10 — sufficient for ChunkScorer with 20 nodes
    prefer_local: bool = True
    fallback_to_api: bool = True

    # Dynamic budget ceiling (v0.10.3)
    # After budget is hit, each subsequent round has P(continue) = base * decay^k
    # where k = rounds since budget was first exceeded.
    # This allows convergence without hard cutoff while preventing runaway cost.
    dynamic_ceiling: bool = True
    continuation_base_prob: float = 0.85  # P(continue) on the first round over budget
    continuation_decay: float = 0.6  # multiplicative decay per additional round
    hard_ceiling_multiplier: float = 3.0  # absolute max: never exceed N * budget


class ReformulatorConfig(BaseModel):
    """Query reformulation configuration (ADR-104).

    Controls whether and how queries are enhanced before PCST activation.

    Modes:
        - "auto": Detect AI tool environment and use context if available,
                  otherwise fall back to LLM mode if a backend is set.
        - "ai_tool": Force AI tool mode (expect context from Claude Code etc.)
        - "llm": Use a backend model call to reformulate (standalone usage)
        - "off": Disable reformulation entirely (raw query pass-through)
    """

    enabled: bool = True
    mode: str = "auto"  # "auto", "ai_tool", "llm", "off"
    llm_backend: str | None = None  # named model profile for LLM reformulation
    graph_summary: str = ""  # brief KG description to help LLM mode


class LoggingConfig(BaseModel):
    """Logging and tracing configuration."""

    level: str = "INFO"
    trace_messages: bool = True
    trace_dir: str = "./traces"


class NamedModelConfig(BaseModel):
    """Named model profile for node-to-model mapping."""

    backend: str
    model: str
    quantization: str = "none"
    api_key: str | None = None


class CogniGraphConfig(BaseModel):
    """Root configuration for a CogniGraph instance."""

    model: ModelConfig = Field(default_factory=ModelConfig)
    graph: GraphConfig = Field(default_factory=GraphConfig)
    activation: ActivationConfig = Field(default_factory=ActivationConfig)
    orchestration: OrchestrationConfig = Field(default_factory=OrchestrationConfig)
    observer: ObserverConfig = Field(default_factory=ObserverConfig)
    cost: CostConfig = Field(default_factory=CostConfig)
    reformulator: ReformulatorConfig = Field(default_factory=ReformulatorConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    domain: str = "custom"
    models: dict[str, NamedModelConfig] = Field(default_factory=dict)
    node_models: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str | Path) -> CogniGraphConfig:
        """Load configuration from a YAML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        # Interpolate environment variables
        raw = _interpolate_env(raw)
        return cls.model_validate(raw)

    @classmethod
    def default(cls) -> CogniGraphConfig:
        """Return default configuration."""
        return cls()


def _interpolate_env(obj: Any) -> Any:
    """Recursively interpolate ${ENV_VAR} patterns in config values."""
    if isinstance(obj, str):
        if obj.startswith("${") and obj.endswith("}"):
            var_name = obj[2:-1]
            return os.environ.get(var_name, obj)
        return obj
    elif isinstance(obj, dict):
        return {k: _interpolate_env(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_interpolate_env(item) for item in obj]
    return obj
