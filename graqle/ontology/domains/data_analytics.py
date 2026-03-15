"""Data & Analytics domain — skills for metrics, ML pipelines, data quality.

15 skills organized by analytics function:
- Data Quality (4)
- Metrics & KPIs (4)
- ML & AI (4)
- Visualization & Reporting (3)
"""

# ── graqle:intelligence ──
# module: graqle.ontology.domains.data_analytics
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, typing, skill_resolver
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from typing import TYPE_CHECKING

from graqle.ontology.skill_resolver import Skill

if TYPE_CHECKING:
    from graqle.ontology.domain_registry import DomainRegistry


DATA_ANALYTICS_CLASS_HIERARCHY: dict[str, str] = {
    "DataAnalytics": "Thing",
    "DATASET": "DataAnalytics",
    "DATA_PIPELINE": "DataAnalytics",
    "ETL_JOB": "DATA_PIPELINE",
    "STREAM": "DATA_PIPELINE",
    "ML_MODEL": "DataAnalytics",
    "ML_EXPERIMENT": "DataAnalytics",
    "FEATURE": "DataAnalytics",
    "FEATURE_STORE": "DataAnalytics",
    "DASHBOARD": "DataAnalytics",
    "KPI": "DataAnalytics",
    "DATA_SOURCE": "DataAnalytics",
    "DATA_WAREHOUSE": "DATA_SOURCE",
    "DATA_LAKE": "DATA_SOURCE",
}

DATA_ANALYTICS_ENTITY_SHAPES: dict[str, dict] = {
    "DATASET": {"required": ["name"], "optional": ["schema", "row_count", "freshness", "quality_score"]},
    "ML_MODEL": {"required": ["name", "type"], "optional": ["accuracy", "framework", "version", "features"]},
    "KPI": {"required": ["name", "value"], "optional": ["target", "period", "trend", "owner"]},
    "DATA_PIPELINE": {"required": ["name"], "optional": ["schedule", "source", "destination", "sla"]},
}

DATA_ANALYTICS_RELATIONSHIP_SHAPES: dict[str, dict] = {
    "FEEDS_INTO": {"domain": {"DATA_SOURCE", "DATASET", "DATA_PIPELINE"}, "range": {"DATA_PIPELINE", "ML_MODEL", "DASHBOARD"}},
    "PRODUCES": {"domain": {"DATA_PIPELINE", "ETL_JOB"}, "range": {"DATASET", "FEATURE"}},
    "TRAINS_ON": {"domain": {"ML_MODEL"}, "range": {"DATASET", "FEATURE_STORE"}},
    "MEASURES": {"domain": {"KPI"}, "range": {"DataAnalytics"}},
    "VISUALIZES": {"domain": {"DASHBOARD"}, "range": {"DATASET", "KPI", "ML_MODEL"}},
}

DATA_ANALYTICS_SKILL_MAP: dict[str, list[str]] = {
    "DataAnalytics": ["data_quality_check", "metric_interpretation"],
    "DATASET": ["data_quality_check", "schema_evolution_check", "data_profiling", "freshness_check"],
    "DATA_PIPELINE": ["pipeline_health_check", "sla_monitoring", "data_lineage_trace"],
    "ETL_JOB": ["pipeline_health_check", "transformation_review"],
    "ML_MODEL": ["model_evaluation", "bias_detection", "feature_importance", "model_drift_check"],
    "ML_EXPERIMENT": ["experiment_analysis", "model_evaluation"],
    "FEATURE": ["feature_importance", "feature_quality"],
    "FEATURE_STORE": ["feature_quality", "freshness_check"],
    "DASHBOARD": ["dashboard_design_review", "metric_interpretation"],
    "KPI": ["metric_interpretation", "trend_detection", "anomaly_detection"],
    "DATA_SOURCE": ["data_lineage_trace", "freshness_check"],
}

DATA_ANALYTICS_SKILLS: dict[str, Skill] = {
    # -- Data Quality --
    "data_quality_check": Skill(
        name="data_quality_check",
        description="Check data quality: completeness, accuracy, consistency",
        handler_prompt=(
            "Assess data quality on 6 dimensions: completeness, accuracy, consistency, "
            "timeliness, uniqueness, validity. Flag violations with examples."
        ),
    ),
    "schema_evolution_check": Skill(
        name="schema_evolution_check",
        description="Check schema changes for compatibility",
        handler_prompt="Review schema changes: backwards compatibility, nullable additions, type changes, migration plan.",
    ),
    "data_profiling": Skill(
        name="data_profiling",
        description="Profile data distributions and statistics",
        handler_prompt="Profile: distributions, null rates, cardinality, outliers, correlations. Flag anomalies.",
    ),
    "freshness_check": Skill(
        name="freshness_check",
        description="Check data freshness and staleness",
        handler_prompt="Check last update time vs SLA. Flag stale data. Identify pipeline delays.",
    ),
    # -- Metrics & KPIs --
    "metric_interpretation": Skill(
        name="metric_interpretation",
        description="Interpret metrics in business context",
        handler_prompt="Interpret the metric: what does this value mean? Is it good/bad? What benchmark applies? Trend?",
    ),
    "trend_detection": Skill(
        name="trend_detection",
        description="Detect trends and patterns in data",
        handler_prompt="Identify: direction, acceleration, seasonality, inflection points. Statistical significance.",
    ),
    "anomaly_detection": Skill(
        name="anomaly_detection",
        description="Detect anomalies and outliers in data",
        handler_prompt="Flag: statistical outliers (>2sigma), sudden changes, pattern breaks. Root cause hypothesis.",
    ),
    "data_lineage_trace": Skill(
        name="data_lineage_trace",
        description="Trace data lineage from source to consumption",
        handler_prompt="Map lineage: source -> transformations -> destinations. Identify: quality gates, latency, dependencies.",
    ),
    # -- ML & AI --
    "model_evaluation": Skill(
        name="model_evaluation",
        description="Evaluate ML model performance and fitness",
        handler_prompt=(
            "Evaluate: accuracy/precision/recall/F1, confusion matrix, overfitting indicators, "
            "training vs validation gap, feature leakage."
        ),
    ),
    "bias_detection": Skill(
        name="bias_detection",
        description="Detect bias in ML models and training data",
        handler_prompt="Check: class imbalance, protected attribute correlation, disparate impact, fairness metrics.",
    ),
    "feature_importance": Skill(
        name="feature_importance",
        description="Analyze feature importance and impact",
        handler_prompt="Rank features by importance. Identify: redundant features, leaky features, engineering opportunities.",
    ),
    "model_drift_check": Skill(
        name="model_drift_check",
        description="Check for model and data drift",
        handler_prompt="Check: prediction drift, feature distribution drift, concept drift. Recommend retraining threshold.",
    ),
    # -- Visualization & Reporting --
    "dashboard_design_review": Skill(
        name="dashboard_design_review",
        description="Review dashboard design and effectiveness",
        handler_prompt="Review: metric selection, visual hierarchy, drill-down paths, update frequency, audience fit.",
    ),
    "pipeline_health_check": Skill(
        name="pipeline_health_check",
        description="Check data pipeline health and reliability",
        handler_prompt="Check: success rate, latency, error patterns, data volume trends, resource utilization.",
    ),
    "transformation_review": Skill(
        name="transformation_review",
        description="Review data transformation logic",
        handler_prompt="Review: transformation correctness, edge cases, null handling, type casting, aggregation logic.",
    ),
}


def register_data_analytics_domain(registry: DomainRegistry) -> None:
    """Register the data analytics domain with a DomainRegistry."""
    registry.register_domain(
        name="data_analytics",
        class_hierarchy=DATA_ANALYTICS_CLASS_HIERARCHY,
        entity_shapes=DATA_ANALYTICS_ENTITY_SHAPES,
        relationship_shapes=DATA_ANALYTICS_RELATIONSHIP_SHAPES,
        skill_map=DATA_ANALYTICS_SKILL_MAP,
    )
