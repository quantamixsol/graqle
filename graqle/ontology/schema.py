"""Graqle Ontology Schema — SHACL-like shape validation for KG node types.

Defines a formal ontology with shape constraints for all node types found in
markdown knowledge graph files (.gcc/departments/, .gcc/project-kg.md,
tasks/lessons-distilled.md, etc.).

Each shape declares:
  - required / optional properties with expected types
  - allowed values for enum-like fields
  - expected outgoing edge types (source_type -> edge_type -> target_type)
  - cardinality constraints

The validate_graph() function checks an entire graph (in networkx
node_link_data format) against the shapes and returns violations.

Extensible: users can register custom shapes via register_node_shape()
and register_edge_shape().
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Shape Definitions
# ---------------------------------------------------------------------------

@dataclass
class PropertyConstraint:
    """Constraint on a single property."""
    name: str
    required: bool = False
    prop_type: str = "str"  # str, int, float, bool, list, dict
    allowed_values: list[str] | None = None
    min_value: float | None = None
    max_value: float | None = None
    pattern: str | None = None  # regex pattern for string values


@dataclass
class EdgeConstraint:
    """Constraint on an edge from this node type."""
    edge_type: str
    target_types: list[str]
    min_count: int = 0
    max_count: int | None = None  # None = unlimited


@dataclass
class NodeShape:
    """SHACL-like shape definition for a node type."""
    node_type: str
    description: str = ""
    properties: list[PropertyConstraint] = field(default_factory=list)
    expected_edges: list[EdgeConstraint] = field(default_factory=list)
    allow_extra_properties: bool = True

    @property
    def required_properties(self) -> list[str]:
        return [p.name for p in self.properties if p.required]

    @property
    def optional_properties(self) -> list[str]:
        return [p.name for p in self.properties if not p.required]


@dataclass
class EdgeShape:
    """Shape definition for an edge type."""
    edge_type: str
    description: str = ""
    valid_source_types: list[str] = field(default_factory=list)
    valid_target_types: list[str] = field(default_factory=list)
    allow_any_source: bool = False
    allow_any_target: bool = False


@dataclass
class Violation:
    """A single validation violation."""
    node_id: str
    node_type: str
    severity: str  # ERROR, WARNING, INFO
    message: str
    property_name: str | None = None
    edge_type: str | None = None


@dataclass
class ValidationReport:
    """Result of validating a graph against the ontology."""
    violations: list[Violation] = field(default_factory=list)
    nodes_checked: int = 0
    edges_checked: int = 0
    nodes_valid: int = 0
    edges_valid: int = 0

    @property
    def is_valid(self) -> bool:
        return not any(v.severity == "ERROR" for v in self.violations)

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "ERROR")

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "WARNING")

    def summary(self) -> str:
        lines = [
            f"Nodes: {self.nodes_checked} checked, {self.nodes_valid} valid",
            f"Edges: {self.edges_checked} checked, {self.edges_valid} valid",
            f"Violations: {self.error_count} errors, {self.warning_count} warnings",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Node Shape Registry
# ---------------------------------------------------------------------------

def _prop(name: str, required: bool = False, prop_type: str = "str",
          allowed_values: list[str] | None = None, **kw: Any) -> PropertyConstraint:
    return PropertyConstraint(
        name=name, required=required, prop_type=prop_type,
        allowed_values=allowed_values, **kw,
    )


def _edge(edge_type: str, targets: list[str],
          min_count: int = 0, max_count: int | None = None) -> EdgeConstraint:
    return EdgeConstraint(
        edge_type=edge_type, target_types=targets,
        min_count=min_count, max_count=max_count,
    )


# -- All 28+ node shapes ---------------------------------------------------

NODE_SHAPES: dict[str, NodeShape] = {}


def _register(shape: NodeShape) -> None:
    NODE_SHAPES[shape.node_type] = shape


# SERVICE — Lambda functions, microservices
_register(NodeShape(
    node_type="SERVICE",
    description="A backend service (Lambda function, microservice, API)",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("handler"),
        _prop("timeout"),
        _prop("memory_mb"),
        _prop("function_url"),
        _prop("runtime"),
        _prop("critical_params", prop_type="list"),
    ],
    expected_edges=[
        _edge("REQUIRES", ["ENVVAR"]),
        _edge("CALLS", ["SERVICE"]),
        _edge("CONTAINS", ["MODULE"]),
        _edge("IMPORTS", ["MODULE"]),
    ],
))

# LESSON — distilled operational lessons
_register(NodeShape(
    node_type="LESSON",
    description="An operational lesson learned from production experience",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("severity", required=True, allowed_values=["CRITICAL", "HIGH", "MEDIUM", "LOW"]),
        _prop("domain", required=True),
        _prop("hit_count", prop_type="int"),
        _prop("source_adr"),
        _prop("added_date"),
    ],
    expected_edges=[
        _edge("APPLIES_TO", ["SERVICE", "MODULE", "FRONTEND_COMPONENT", "INFRA"]),
    ],
))

# MISTAKE — documented production mistakes
_register(NodeShape(
    node_type="MISTAKE",
    description="A documented production mistake with root cause and fix",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("component", required=True),
        _prop("root_cause", required=True),
        _prop("severity"),
        _prop("fix"),
        _prop("status"),
        _prop("date"),
    ],
    expected_edges=[
        _edge("OCCURRED_IN", ["SERVICE", "MODULE", "FRONTEND_COMPONENT", "INFRA"]),
    ],
))

# SAFETY — safety boundary rules
_register(NodeShape(
    node_type="SAFETY",
    description="A safety boundary or operational constraint",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("rule", required=True),
    ],
    expected_edges=[
        _edge("CONSTRAINS", ["SERVICE", "MODULE", "FRONTEND_COMPONENT", "INFRA", "DOMAIN"]),
    ],
))

# ENVVAR — environment variables
_register(NodeShape(
    node_type="ENVVAR",
    description="An environment variable required by services",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("required_by", prop_type="list"),
    ],
    expected_edges=[
        _edge("REQUIRED_BY", ["SERVICE"]),
    ],
))

# ADR — architecture decision records
_register(NodeShape(
    node_type="ADR",
    description="Architecture Decision Record",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("number"),
        _prop("status", allowed_values=["ACCEPTED", "SUPERSEDED", "DEPRECATED", "PROPOSED"]),
        _prop("date"),
    ],
    expected_edges=[
        _edge("GOVERNS", ["SERVICE", "MODULE", "FRONTEND_COMPONENT"]),
    ],
))

# PATENT — intellectual property filings
_register(NodeShape(
    node_type="PATENT",
    description="Patent filing or application",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("application_number"),
        _prop("filing_date"),
        _prop("status"),
        _prop("claims_count", prop_type="int"),
        _prop("office"),
    ],
    expected_edges=[
        _edge("COVERS", ["MOAT_MODULE", "INNOVATION"]),
        _edge("FILED_BY", ["IP_ASSET"]),
    ],
))

# PUBLICATION — papers, preprints, submissions
_register(NodeShape(
    node_type="PUBLICATION",
    description="Academic publication or preprint submission",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("venue"),
        _prop("status"),
        _prop("doi"),
        _prop("deadline"),
        _prop("version"),
        _prop("file_path"),
    ],
    expected_edges=[
        _edge("SUBMITTED_TO", ["PUBLICATION"]),
        _edge("REFERENCES", ["PAPER"]),
    ],
))

# PAPER — research paper versions
_register(NodeShape(
    node_type="PAPER",
    description="A specific version of a research paper",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("version"),
        _prop("file_path"),
        _prop("status", allowed_values=["CURRENT", "SUPERSEDED", "DRAFT", "COMPLETE"]),
    ],
    expected_edges=[
        _edge("SUPERSEDES", ["PAPER"]),
        _edge("PUBLISHED_AT", ["PUBLICATION"]),
    ],
))

# PACKAGE — SDK / software packages
_register(NodeShape(
    node_type="PACKAGE",
    description="Software package or SDK",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("version"),
        _prop("pypi_url"),
        _prop("github_url"),
        _prop("source_path"),
        _prop("license"),
    ],
    expected_edges=[
        _edge("CONTAINS", ["MODULE"]),
        _edge("DEPENDS_ON", ["PACKAGE"]),
    ],
))

# DOMAIN — DNS domains
_register(NodeShape(
    node_type="DOMAIN",
    description="DNS domain or subdomain",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("purpose"),
        _prop("hosting"),
    ],
    expected_edges=[
        _edge("HOSTED_BY", ["INFRA"]),
    ],
))

# AWS_RESOURCE — cloud infrastructure resources
_register(NodeShape(
    node_type="AWS_RESOURCE",
    description="AWS cloud resource (S3, DynamoDB, Cognito, etc.)",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("resource_type"),
        _prop("endpoint"),
        _prop("region"),
    ],
    expected_edges=[
        _edge("USED_BY", ["SERVICE"]),
    ],
))

# MODULE — code modules, shared libraries
_register(NodeShape(
    node_type="MODULE",
    description="Code module or shared library",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("file_path"),
        _prop("key_functions", prop_type="list"),
    ],
    expected_edges=[
        _edge("IMPORTED_BY", ["SERVICE", "MODULE"]),
    ],
))

# FRONTEND_COMPONENT — UI components and pages
_register(NodeShape(
    node_type="FRONTEND_COMPONENT",
    description="Frontend component, page, or hook",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("component_type"),
        _prop("file_path"),
    ],
    expected_edges=[
        _edge("USES", ["SERVICE", "MODULE"]),
    ],
))

# MOAT_MODULE — innovation/research modules
_register(NodeShape(
    node_type="MOAT_MODULE",
    description="Innovation module from the academic moat strategy",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("location"),
        _prop("status"),
        _prop("patent_claims"),
    ],
    expected_edges=[
        _edge("COVERED_BY", ["PATENT"]),
    ],
))

# IP_ASSET — intellectual property assets
_register(NodeShape(
    node_type="IP_ASSET",
    description="Intellectual property asset (trade secret, open-source, patent)",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("protection_type"),
        _prop("status"),
        _prop("license"),
    ],
    expected_edges=[
        _edge("PROTECTED_BY", ["PATENT"]),
    ],
))

# COMPETITOR — competitive analysis entries
_register(NodeShape(
    node_type="COMPETITOR",
    description="Competitor product or system",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("arxiv_id"),
        _prop("comparison", prop_type="dict"),
    ],
    expected_edges=[
        _edge("COMPETES_WITH", ["PACKAGE", "MOAT_MODULE"]),
    ],
))

# BENCHMARK — evaluation benchmarks
_register(NodeShape(
    node_type="BENCHMARK",
    description="Evaluation benchmark or test suite",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("file_path"),
        _prop("question_count", prop_type="int"),
        _prop("status"),
    ],
    expected_edges=[
        _edge("EVALUATES", ["PACKAGE", "MOAT_MODULE"]),
    ],
))

# BRAND_ASSET — brand identity elements
_register(NodeShape(
    node_type="BRAND_ASSET",
    description="Brand identity element (name, tagline, voice)",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("asset_type"),
        _prop("value"),
    ],
))

# PERSONA — customer personas
_register(NodeShape(
    node_type="PERSONA",
    description="Customer persona for marketing/sales",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("priority"),
        _prop("needs"),
    ],
    expected_edges=[
        _edge("TARGETS", ["CHANNEL"]),
    ],
))

# CHANNEL — marketing/distribution channels
_register(NodeShape(
    node_type="CHANNEL",
    description="Marketing or distribution channel",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("role"),
        _prop("frequency"),
        _prop("status"),
    ],
))

# CAMPAIGN — marketing campaigns
_register(NodeShape(
    node_type="CAMPAIGN",
    description="Marketing campaign or content initiative",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("status"),
        _prop("target_audience"),
    ],
    expected_edges=[
        _edge("RUNS_ON", ["CHANNEL"]),
    ],
))

# OPEN_ISSUE — tracked issues
_register(NodeShape(
    node_type="OPEN_ISSUE",
    description="Tracked open issue or bug",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("priority"),
        _prop("component"),
        _prop("proposed_fix"),
        _prop("status", allowed_values=["OPEN", "CLOSED", "IN_PROGRESS"]),
    ],
    expected_edges=[
        _edge("BLOCKS", ["SERVICE", "MODULE", "FRONTEND_COMPONENT"]),
    ],
))

# NEO4J_SCHEMA — Neo4j label/index definitions
_register(NodeShape(
    node_type="NEO4J_SCHEMA",
    description="Neo4j graph schema (labels, indexes, constraints)",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("subgraph"),
        _prop("queried_by"),
        _prop("isolation"),
    ],
))

# STRIPE_PRODUCT — billing products
_register(NodeShape(
    node_type="STRIPE_PRODUCT",
    description="Stripe billing product or price",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("product_id"),
        _prop("monthly_price_id"),
        _prop("yearly_price_id"),
        _prop("tier"),
    ],
))

# TEST_SUITE — test suites
_register(NodeShape(
    node_type="TEST_SUITE",
    description="Automated test suite",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("count"),
        _prop("status"),
        _prop("runner"),
    ],
    expected_edges=[
        _edge("TESTS", ["SERVICE", "MODULE", "PACKAGE"]),
    ],
))

# INNOVATION — innovations or key technical contributions
_register(NodeShape(
    node_type="INNOVATION",
    description="Key technical innovation or contribution",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("description"),
    ],
    expected_edges=[
        _edge("PART_OF", ["PACKAGE", "MOAT_MODULE"]),
    ],
))

# INFRA — infrastructure nodes
_register(NodeShape(
    node_type="INFRA",
    description="Infrastructure component (database, storage, compute)",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("infra_type"),
        _prop("endpoint"),
        _prop("region"),
    ],
    expected_edges=[
        _edge("USED_BY", ["SERVICE"]),
    ],
))

# PIPELINE_STEP — processing pipeline steps
_register(NodeShape(
    node_type="PIPELINE_STEP",
    description="A step in a processing pipeline",
    properties=[
        _prop("id", required=True),
        _prop("label", required=True),
        _prop("description"),
    ],
    expected_edges=[
        _edge("FLOWS_TO", ["PIPELINE_STEP"]),
        _edge("EXECUTED_BY", ["SERVICE"]),
    ],
))


# ---------------------------------------------------------------------------
# Edge Shape Registry
# ---------------------------------------------------------------------------

EDGE_SHAPES: dict[str, EdgeShape] = {}


def _register_edge(shape: EdgeShape) -> None:
    EDGE_SHAPES[shape.edge_type] = shape


_register_edge(EdgeShape("REQUIRES", "Service requires an environment variable",
                          valid_source_types=["SERVICE"], valid_target_types=["ENVVAR"]))
_register_edge(EdgeShape("CALLS", "Service invokes another service",
                          valid_source_types=["SERVICE"], valid_target_types=["SERVICE"]))
_register_edge(EdgeShape("CONTAINS", "Container contains a child",
                          allow_any_source=True, allow_any_target=True))
_register_edge(EdgeShape("IMPORTS", "Module imports another module",
                          valid_source_types=["SERVICE", "MODULE"], valid_target_types=["MODULE"]))
_register_edge(EdgeShape("APPLIES_TO", "Lesson/safety applies to a component",
                          valid_source_types=["LESSON", "SAFETY"],
                          valid_target_types=["SERVICE", "MODULE", "FRONTEND_COMPONENT", "INFRA"]))
_register_edge(EdgeShape("OCCURRED_IN", "Mistake occurred in a component",
                          valid_source_types=["MISTAKE"],
                          valid_target_types=["SERVICE", "MODULE", "FRONTEND_COMPONENT", "INFRA"]))
_register_edge(EdgeShape("CONSTRAINS", "Safety rule constrains a component",
                          valid_source_types=["SAFETY"],
                          valid_target_types=["SERVICE", "MODULE", "FRONTEND_COMPONENT", "INFRA", "DOMAIN"]))
_register_edge(EdgeShape("GOVERNS", "ADR governs a component",
                          valid_source_types=["ADR"],
                          valid_target_types=["SERVICE", "MODULE", "FRONTEND_COMPONENT"]))
_register_edge(EdgeShape("COVERS", "Patent covers innovation/module",
                          valid_source_types=["PATENT"], valid_target_types=["MOAT_MODULE", "INNOVATION"]))
_register_edge(EdgeShape("COVERED_BY", "Module is covered by patent",
                          valid_source_types=["MOAT_MODULE"], valid_target_types=["PATENT"]))
_register_edge(EdgeShape("DEPENDS_ON", "Component depends on another",
                          allow_any_source=True, allow_any_target=True))
_register_edge(EdgeShape("HOSTED_BY", "Domain hosted by infrastructure",
                          valid_source_types=["DOMAIN"], valid_target_types=["INFRA", "AWS_RESOURCE"]))
_register_edge(EdgeShape("USED_BY", "Resource used by a service",
                          valid_source_types=["INFRA", "AWS_RESOURCE"], valid_target_types=["SERVICE"]))
_register_edge(EdgeShape("BLOCKS", "Issue blocks a component",
                          valid_source_types=["OPEN_ISSUE"],
                          valid_target_types=["SERVICE", "MODULE", "FRONTEND_COMPONENT"]))
_register_edge(EdgeShape("TESTS", "Test suite tests a component",
                          valid_source_types=["TEST_SUITE"],
                          valid_target_types=["SERVICE", "MODULE", "PACKAGE"]))
_register_edge(EdgeShape("EVALUATES", "Benchmark evaluates a package/module",
                          valid_source_types=["BENCHMARK"], valid_target_types=["PACKAGE", "MOAT_MODULE"]))
_register_edge(EdgeShape("FLOWS_TO", "Pipeline step flows to another",
                          valid_source_types=["PIPELINE_STEP", "SERVICE"],
                          valid_target_types=["PIPELINE_STEP", "SERVICE"]))
_register_edge(EdgeShape("SUBMITTED_TO", "Publication submitted to venue",
                          valid_source_types=["PUBLICATION"], valid_target_types=["PUBLICATION"]))
_register_edge(EdgeShape("PUBLISHED_AT", "Paper published at venue",
                          valid_source_types=["PAPER"], valid_target_types=["PUBLICATION"]))
_register_edge(EdgeShape("SUPERSEDES", "Paper supersedes older version",
                          valid_source_types=["PAPER"], valid_target_types=["PAPER"]))
_register_edge(EdgeShape("RUNS_ON", "Campaign runs on channel",
                          valid_source_types=["CAMPAIGN"], valid_target_types=["CHANNEL"]))
_register_edge(EdgeShape("TARGETS", "Persona targeted by channel",
                          valid_source_types=["PERSONA"], valid_target_types=["CHANNEL"]))
_register_edge(EdgeShape("PROTECTED_BY", "IP asset protected by patent",
                          valid_source_types=["IP_ASSET"], valid_target_types=["PATENT"]))
_register_edge(EdgeShape("REQUIRED_BY", "EnvVar required by service",
                          valid_source_types=["ENVVAR"], valid_target_types=["SERVICE"]))
_register_edge(EdgeShape("IMPORTED_BY", "Module imported by service/module",
                          valid_source_types=["MODULE"], valid_target_types=["SERVICE", "MODULE"]))
_register_edge(EdgeShape("PART_OF", "Innovation is part of a package/module",
                          valid_source_types=["INNOVATION"], valid_target_types=["PACKAGE", "MOAT_MODULE"]))
_register_edge(EdgeShape("EXECUTED_BY", "Pipeline step executed by a service",
                          valid_source_types=["PIPELINE_STEP"], valid_target_types=["SERVICE"]))
_register_edge(EdgeShape("COMPETES_WITH", "Competitor competes with product",
                          valid_source_types=["COMPETITOR"], valid_target_types=["PACKAGE", "MOAT_MODULE"]))
_register_edge(EdgeShape("REFERENCES", "Publication references paper",
                          valid_source_types=["PUBLICATION"], valid_target_types=["PAPER"]))
_register_edge(EdgeShape("FILED_BY", "Patent filed by IP asset owner",
                          valid_source_types=["PATENT"], valid_target_types=["IP_ASSET"]))
_register_edge(EdgeShape("USES", "Frontend uses a service/module",
                          valid_source_types=["FRONTEND_COMPONENT"],
                          valid_target_types=["SERVICE", "MODULE"]))


# ---------------------------------------------------------------------------
# Extensibility API
# ---------------------------------------------------------------------------

def register_node_shape(shape: NodeShape) -> None:
    """Register a custom node shape (or override an existing one)."""
    NODE_SHAPES[shape.node_type] = shape


def register_edge_shape(shape: EdgeShape) -> None:
    """Register a custom edge shape (or override an existing one)."""
    EDGE_SHAPES[shape.edge_type] = shape


def get_node_shape(node_type: str) -> NodeShape | None:
    """Look up a node shape by type name."""
    return NODE_SHAPES.get(node_type)


def get_all_node_types() -> list[str]:
    """Return all registered node type names."""
    return sorted(NODE_SHAPES.keys())


def get_all_edge_types() -> list[str]:
    """Return all registered edge type names."""
    return sorted(EDGE_SHAPES.keys())


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_property(node_id: str, node_type: str,
                       constraint: PropertyConstraint,
                       value: Any) -> list[Violation]:
    """Validate a single property value against its constraint."""
    violations: list[Violation] = []

    if value is None:
        if constraint.required:
            violations.append(Violation(
                node_id=node_id, node_type=node_type, severity="ERROR",
                message=f"Required property '{constraint.name}' is missing",
                property_name=constraint.name,
            ))
        return violations

    # Type check
    type_map = {
        "str": str, "int": int, "float": (int, float),
        "bool": bool, "list": list, "dict": dict,
    }
    expected = type_map.get(constraint.prop_type, str)
    if not isinstance(value, expected):
        violations.append(Violation(
            node_id=node_id, node_type=node_type, severity="WARNING",
            message=(f"Property '{constraint.name}' expected type "
                     f"'{constraint.prop_type}', got '{type(value).__name__}'"),
            property_name=constraint.name,
        ))

    # Allowed values
    if constraint.allowed_values and isinstance(value, str):
        if value not in constraint.allowed_values:
            violations.append(Violation(
                node_id=node_id, node_type=node_type, severity="WARNING",
                message=(f"Property '{constraint.name}' value '{value}' "
                         f"not in allowed: {constraint.allowed_values}"),
                property_name=constraint.name,
            ))

    # Pattern
    if constraint.pattern and isinstance(value, str):
        if not re.match(constraint.pattern, value):
            violations.append(Violation(
                node_id=node_id, node_type=node_type, severity="WARNING",
                message=(f"Property '{constraint.name}' value '{value}' "
                         f"does not match pattern '{constraint.pattern}'"),
                property_name=constraint.name,
            ))

    # Range checks
    if constraint.min_value is not None and isinstance(value, (int, float)):
        if value < constraint.min_value:
            violations.append(Violation(
                node_id=node_id, node_type=node_type, severity="WARNING",
                message=(f"Property '{constraint.name}' value {value} "
                         f"below minimum {constraint.min_value}"),
                property_name=constraint.name,
            ))

    if constraint.max_value is not None and isinstance(value, (int, float)):
        if value > constraint.max_value:
            violations.append(Violation(
                node_id=node_id, node_type=node_type, severity="WARNING",
                message=(f"Property '{constraint.name}' value {value} "
                         f"above maximum {constraint.max_value}"),
                property_name=constraint.name,
            ))

    return violations


def validate_graph(graph_data: dict[str, Any]) -> ValidationReport:
    """Validate a graph (in networkx node_link_data format) against the ontology.

    Parameters
    ----------
    graph_data : dict
        A dict with 'nodes' (list of dicts with 'id', 'type', ...) and
        'links' (list of dicts with 'source', 'target', 'relationship').

    Returns
    -------
    ValidationReport
        Report with all violations found.
    """
    report = ValidationReport()

    nodes = graph_data.get("nodes", [])
    links = graph_data.get("links", [])

    # Build node lookup
    node_lookup: dict[str, dict[str, Any]] = {}
    for node in nodes:
        node_id = node.get("id", "")
        node_lookup[node_id] = node

    # Validate nodes
    for node in nodes:
        report.nodes_checked += 1
        node_id = node.get("id", "<unknown>")
        node_type = node.get("type", "")

        if not node_type:
            report.violations.append(Violation(
                node_id=node_id, node_type="", severity="WARNING",
                message="Node has no 'type' property",
            ))
            continue

        shape = NODE_SHAPES.get(node_type)
        if shape is None:
            report.violations.append(Violation(
                node_id=node_id, node_type=node_type, severity="INFO",
                message=f"No shape defined for node type '{node_type}'",
            ))
            report.nodes_valid += 1  # Unknown types are not errors
            continue

        node_valid = True
        for prop_constraint in shape.properties:
            value = node.get(prop_constraint.name)
            prop_violations = _validate_property(
                node_id, node_type, prop_constraint, value,
            )
            if any(v.severity == "ERROR" for v in prop_violations):
                node_valid = False
            report.violations.extend(prop_violations)

        if node_valid:
            report.nodes_valid += 1

    # Validate edges
    for link in links:
        report.edges_checked += 1
        source = link.get("source", "")
        target = link.get("target", "")
        rel = link.get("relationship", "")

        if not rel:
            report.violations.append(Violation(
                node_id=source, node_type="", severity="WARNING",
                message=f"Edge {source} -> {target} has no relationship type",
                edge_type="",
            ))
            continue

        # Check source and target exist
        if source not in node_lookup:
            report.violations.append(Violation(
                node_id=source, node_type="", severity="WARNING",
                message=f"Edge source '{source}' not found in nodes",
                edge_type=rel,
            ))

        if target not in node_lookup:
            report.violations.append(Violation(
                node_id=target, node_type="", severity="WARNING",
                message=f"Edge target '{target}' not found in nodes",
                edge_type=rel,
            ))

        # Check edge shape
        edge_shape = EDGE_SHAPES.get(rel)
        if edge_shape is None:
            report.violations.append(Violation(
                node_id=source, node_type="", severity="INFO",
                message=f"No shape defined for edge type '{rel}'",
                edge_type=rel,
            ))
            report.edges_valid += 1
            continue

        edge_valid = True

        # Validate source type
        source_type = node_lookup.get(source, {}).get("type", "")
        if (not edge_shape.allow_any_source
                and source_type
                and edge_shape.valid_source_types
                and source_type not in edge_shape.valid_source_types):
            report.violations.append(Violation(
                node_id=source, node_type=source_type, severity="WARNING",
                message=(f"Edge '{rel}' source type '{source_type}' "
                         f"not in valid sources: {edge_shape.valid_source_types}"),
                edge_type=rel,
            ))
            edge_valid = False

        # Validate target type
        target_type = node_lookup.get(target, {}).get("type", "")
        if (not edge_shape.allow_any_target
                and target_type
                and edge_shape.valid_target_types
                and target_type not in edge_shape.valid_target_types):
            report.violations.append(Violation(
                node_id=source, node_type=source_type, severity="WARNING",
                message=(f"Edge '{rel}' target type '{target_type}' "
                         f"not in valid targets: {edge_shape.valid_target_types}"),
                edge_type=rel,
            ))
            edge_valid = False

        if edge_valid:
            report.edges_valid += 1

    return report
