"""GraQle configuration system — Pydantic settings + YAML loading."""

# ── graqle:intelligence ──
# module: graqle.config.settings
# risk: HIGH (impact radius: 12 modules)
# consumers: sdk_self_audit, governance_example, benchmark_runner, run_multigov_v2, run_multigov_v3 +7 more
# dependencies: __future__, logging, os, pathlib, typing +2 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger("graqle.config")


class ModelConfig(BaseModel):
    """Model backend configuration."""

    backend: str = "local"
    model: str = "Qwen/Qwen2.5-0.5B-Instruct"
    quantization: str = "none"
    device: str = "auto"
    max_concurrent_adapters: int = 16
    api_key: str | None = None
    region: str | None = None  # AWS region (e.g. us-east-1, eu-west-1). Only used by Bedrock backend.
    host: str | None = None  # Ollama/vLLM host URL. Only used by local backends.
    endpoint: str | None = None  # Custom endpoint URL. Used by custom/self-hosted providers.


class GraphConfig(BaseModel):
    """Graph connector configuration."""

    connector: str = "networkx"
    path: str | None = None  # JSON graph file path (default: graqle.json)
    uri: str | None = None
    username: str | None = None
    password: str | None = None
    database: str | None = None
    # Neo4j vector search settings
    vector_index_name: str = "cogni_chunk_embedding_index"
    embedding_dimension: int = 1024
    embedding_model: str = "amazon.titan-embed-text-v2:0"


class EmbeddingsConfig(BaseModel):
    """Embedding engine configuration.

    Controls which embedding backend is used for chunk scoring,
    activation, and semantic search. Users should choose the best
    embedding model available to maximize reasoning quality.

    Backends:
        - "local": sentence-transformers (free, local, 384-dim default)
        - "bedrock": Amazon Bedrock Titan V2 (production, 1024-dim)
        - "simple": hash-based fallback (zero deps, 128-dim, lowest quality)
    """

    backend: str = "local"  # "local", "bedrock", "simple"
    model: str = "sentence-transformers/all-MiniLM-L6-v2"
    region: str | None = None  # AWS region for Bedrock
    dimension: int = 0  # 0 = auto (384 for local, 1024 for bedrock, 128 for simple)


class ActivationConfig(BaseModel):
    """Subgraph activation configuration."""

    strategy: str = "chunk"  # "chunk" (default), "pcst" (legacy), "full", "top_k"
    max_nodes: int = 50
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_engine: str = ""  # deprecated — use top-level embeddings section
    pcst_pruning: str = "strong"
    prize_scaling: float = 1.0
    cost_scaling: float = 1.0
    skill_aware: bool = True  # Boost nodes whose skills match query keywords


class SkillConfig(BaseModel):
    """Skill assignment configuration."""

    mode: str = "auto"  # "auto" (type-first + semantic fallback), "type_only", "semantic", "hybrid"
    max_per_node: int = 5
    domains: list[str] = []  # Empty = auto-discover all registered domains
    use_titan: bool = True  # Prefer Titan V2 for semantic matching


class OrchestrationConfig(BaseModel):
    """Message passing orchestration configuration."""

    max_rounds: int = 5
    min_rounds: int = 2
    convergence_threshold: float = 0.95
    aggregation: str = "weighted_synthesis"
    async_mode: bool = False
    confidence_threshold: float = 0.8


class ObserverConfig(BaseModel):
    """MasterObserver configuration.

    v0.12: Observer is enabled by default. It runs at zero cost
    (rule-based, no LLM calls) and provides valuable transparency.
    Disable explicitly with ``enabled: false`` if you want to suppress.
    """

    enabled: bool = True
    report_per_round: bool = False
    detect_conflicts: bool = True
    detect_patterns: bool = True
    detect_anomalies: bool = True
    use_llm_analysis: bool = False
    backend: str | None = None  # named model profile for observer


class CostConfig(BaseModel):
    """Cost control configuration."""

    budget_per_query: float = 0.15  # $0.15 — sufficient for 50 nodes on multi-repo graphs
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


class RoutingRuleConfig(BaseModel):
    """A single task-to-provider routing rule."""

    task: str
    provider: str
    model: str | None = None
    reason: str = ""
    region: str | None = None
    profile: str | None = None

    @model_validator(mode="after")
    def require_bedrock_fields(self) -> "RoutingRuleConfig":
        """Bedrock routing rules must specify region and profile.

        FB-006: without these fields, Bedrock routing silently routes to the
        wrong AWS account with no error. Fail at config load time, not at
        runtime when it's too late to catch.
        """
        if self.provider == "bedrock":
            if not self.region:
                raise ValueError(
                    f"Bedrock routing rule for task '{self.task}' requires 'region'. "
                    "Set the AWS region (e.g. 'eu-central-1')."
                )
            if not self.profile:
                raise ValueError(
                    f"Bedrock routing rule for task '{self.task}' requires 'profile'. "
                    "Set the AWS profile name (e.g. 'default')."
                )
        return self


class RoutingConfig(BaseModel):
    """Task-based model routing configuration.

    Users define rules that map task types (context, reason, preflight,
    impact, lessons, learn, code, docs) to specific providers and models.
    The router never auto-assigns — all rules are explicit opt-in.

    Example YAML::

        routing:
          default_provider: groq
          default_model: llama-3.3-70b-versatile
          rules:
            - task: reason
              provider: anthropic
              model: claude-sonnet-4-6
              reason: "Reasoning needs strong multi-step logic"
            - task: context
              provider: groq
              model: llama-3.1-8b-instant
              reason: "Context lookups are simple — use fast model"
    """

    default_provider: str | None = None
    default_model: str | None = None
    rules: list[RoutingRuleConfig] = Field(default_factory=list)


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


class RedactionConfig(BaseModel):
    """Privacy redaction configuration for document scanning."""

    enabled: bool = True
    patterns: list[str] = Field(default_factory=list)
    redact_api_keys: bool = True
    redact_passwords: bool = True
    redact_tokens: bool = True


class LinkingConfig(BaseModel):
    """Auto-linking configuration for document-to-code connections."""

    exact: bool = True
    fuzzy: bool = True
    semantic: bool = False
    llm_assisted: bool = False
    semantic_threshold: float = 0.70
    fuzzy_threshold: float = 0.60
    llm_max_docs: int = 20
    max_edges_per_doc: int = 50


class DocScanConfig(BaseModel):
    """Document scanning configuration."""

    enabled: bool = True
    background: bool = True
    extensions: list[str] = Field(
        default_factory=lambda: [".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt"]
    )
    exclude_extensions: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    scan_dirs: list[str] = Field(default_factory=lambda: ["."])
    max_file_size_mb: float = 50.0
    chunk_max_chars: int = 1500
    chunk_overlap_chars: int = 100
    chunk_min_chars: int = 100
    linking: LinkingConfig = Field(default_factory=LinkingConfig)
    redaction: RedactionConfig = Field(default_factory=RedactionConfig)
    incremental: bool = True
    max_nodes: int = 0
    max_files: int = 0


class JSONScanConfig(BaseModel):
    """JSON file scanning configuration."""

    enabled: bool = True
    auto_detect: bool = True
    max_file_size_mb: float = 10.0
    exclude_patterns: list[str] = Field(
        default_factory=lambda: [
            "package-lock.json", "yarn.lock", "*.min.json",
            "node_modules/", ".git/", "__pycache__/", "dist/", ".next/",
        ]
    )
    categories: dict[str, bool] = Field(
        default_factory=lambda: {
            "DEPENDENCY_MANIFEST": True,
            "API_SPEC": True,
            "TOOL_CONFIG": True,
            "APP_CONFIG": True,
            "INFRA_CONFIG": True,
            "SCHEMA_FILE": True,
            "DATA_FILE": False,
        }
    )


class RuntimeSourceConfig(BaseModel):
    """A single runtime log source configuration."""

    type: str = "cloudwatch"  # "cloudwatch", "azure_monitor", "cloud_logging", "docker", "file"
    log_group: str = ""  # CloudWatch log group name
    log_path: str = ""  # Local file path
    region: str = ""  # Cloud region override
    scan_hours: float = 6  # How far back to look
    scan_interval: int = 300  # Scan interval in seconds
    service: str = ""  # Service name filter
    workspace_id: str = ""  # Azure Log Analytics workspace ID
    project_id: str = ""  # GCP project ID
    error_patterns: list[dict[str, str]] = Field(default_factory=list)


class RuntimeConfig(BaseModel):
    """Runtime observability configuration.

    Configures live log/metric fetching from cloud providers or local sources.
    Auto-detects the environment if provider is "auto".
    """

    enabled: bool = False  # Opt-in — must be explicitly enabled
    provider: str = "auto"  # "auto", "aws", "azure", "gcp", "local"
    sources: list[RuntimeSourceConfig] = Field(default_factory=list)
    auto_ingest: bool = False  # Auto-ingest runtime events into KG on graq grow
    max_events: int = 100  # Max events per fetch
    default_hours: float = 6  # Default lookback window


class ScanConfig(BaseModel):
    """Top-level scan configuration (code + docs + JSON)."""

    model_config = {"populate_by_name": True}

    exclude_patterns: list[str] = Field(default_factory=list)  # gitignore-style patterns for code scan
    docs: DocScanConfig = Field(default_factory=DocScanConfig)
    json_files: JSONScanConfig = Field(
        default_factory=JSONScanConfig,
        alias="json",
    )


class GraqleConfig(BaseModel):
    """Root configuration for a GraQle instance."""

    model: ModelConfig = Field(default_factory=ModelConfig)
    graph: GraphConfig = Field(default_factory=GraphConfig)
    activation: ActivationConfig = Field(default_factory=ActivationConfig)
    skills: SkillConfig = Field(default_factory=SkillConfig)
    orchestration: OrchestrationConfig = Field(default_factory=OrchestrationConfig)
    observer: ObserverConfig = Field(default_factory=ObserverConfig)
    cost: CostConfig = Field(default_factory=CostConfig)
    reformulator: ReformulatorConfig = Field(default_factory=ReformulatorConfig)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    scan: ScanConfig = Field(default_factory=ScanConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    domain: str = "custom"
    project_name: str = ""       # Human-readable project identity (settable in graqle.yaml)
    source_mode: str = "auto"    # "local", "cloud", "hybrid", "auto" (auto = detect at runtime)
    models: dict[str, NamedModelConfig] = Field(default_factory=dict)
    node_models: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str | Path) -> GraqleConfig:
        """Load configuration from a YAML file."""
        path = Path(path)
        if not path.exists():
            # Check for deprecated cognigraph.yaml
            if path.name == "graqle.yaml":
                legacy = path.parent / "cognigraph.yaml"
                if legacy.exists():
                    import warnings
                    warnings.warn(
                        "cognigraph.yaml is deprecated and will stop working in v0.26. "
                        "Rename to graqle.yaml: mv cognigraph.yaml graqle.yaml",
                        DeprecationWarning,
                        stacklevel=2,
                    )
                    path = legacy
                else:
                    raise FileNotFoundError(f"Config file not found: {path}")
            else:
                raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        if raw is None:
            raw = {}

        # Migrate v0.23.x schema: backend.provider/model -> model.backend/model
        raw = _migrate_old_schema(raw)

        # Interpolate environment variables
        raw = _interpolate_env(raw)
        return cls.model_validate(raw)

    @classmethod
    def default(cls) -> GraqleConfig:
        """Return default configuration."""
        return cls()


def _migrate_old_schema(raw: dict[str, Any]) -> dict[str, Any]:
    """Detect and migrate v0.23.x config schema to v0.24.0+ format.

    v0.23.x used:
        backend:
          provider: bedrock
          model: claude-sonnet-4-6
          region: eu-west-1

    v0.24.0+ uses:
        model:
          backend: bedrock
          model: claude-sonnet-4-6
          region: eu-west-1
    """
    if not isinstance(raw, dict):
        return raw

    old_backend = raw.get("backend")
    if not isinstance(old_backend, dict):
        return raw

    # Only migrate if "backend" has provider/model keys (old schema)
    # and "model" section doesn't already exist or is incomplete
    has_old_keys = "provider" in old_backend or "model" in old_backend
    if not has_old_keys:
        return raw

    model_section = raw.get("model", {})
    if not isinstance(model_section, dict):
        model_section = {}

    # Only migrate if model.backend isn't already explicitly set to a real value
    if model_section.get("backend") not in (None, "local"):
        return raw

    # Perform migration
    migrated: dict[str, Any] = {}
    if "provider" in old_backend:
        migrated["backend"] = old_backend["provider"]
    if "model" in old_backend:
        migrated["model"] = old_backend["model"]
    if "region" in old_backend:
        migrated["region"] = old_backend["region"]
    if "api_key" in old_backend:
        migrated["api_key"] = old_backend["api_key"]
    if "host" in old_backend:
        migrated["host"] = old_backend["host"]
    if "endpoint" in old_backend:
        migrated["endpoint"] = old_backend["endpoint"]

    # Merge: explicit model section wins over migrated values
    merged = {**migrated, **model_section}
    raw["model"] = merged

    # Remove old backend section so pydantic doesn't choke on it
    del raw["backend"]

    logger.warning(
        "DEPRECATED: Config uses v0.23.x schema (backend.provider: %s). "
        "Auto-migrated to v0.24.0 format (model.backend: %s). "
        "Update your config file — the old format will stop working in v0.26.",
        old_backend.get("provider", "?"),
        merged.get("backend", "?"),
    )

    return raw


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
