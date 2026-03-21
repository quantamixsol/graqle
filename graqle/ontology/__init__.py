"""GraQle Ontology Module — Governance-Constrained Reasoning.

Provides OWL-like class hierarchy, SHACL validation gates, constraint
propagation, ontology-based message routing, and skill resolution.
Domain-agnostic: any domain registers via the DomainRegistry API.
"""

# ── graqle:intelligence ──
# module: graqle.ontology.__init__
# risk: LOW (impact radius: 0 modules)
# dependencies: upper, domain_registry, shacl_gate, constraint_graph, router +5 more
# constraints: none
# ── /graqle:intelligence ──

try:
    from graqle.ontology.constraint_graph import ConstraintGraph
except ImportError:
    ConstraintGraph = None  # type: ignore[assignment,misc]

from graqle.ontology.domain_registry import DomainOntology, DomainRegistry
from graqle.ontology.markdown_parser import (
    EdgeInferenceEngine,
    ExtractedEdge,
    ExtractedEntity,
    MarkdownKGParser,
    ParseResult,
    extract_tables,
    parse_and_infer,
    parse_markdown_kg,
)
from graqle.ontology.ontology_generator import OntologyGenerator
from graqle.ontology.router import OntologyRouter
from graqle.ontology.schema import (
    EDGE_SHAPES,
    NODE_SHAPES,
    EdgeConstraint,
    EdgeShape,
    NodeShape,
    PropertyConstraint,
    ValidationReport,
    Violation,
    get_all_edge_types,
    get_all_node_types,
    get_node_shape,
    register_edge_shape,
    register_node_shape,
    validate_graph,
)
try:
    from graqle.ontology.semantic_shacl_gate import (
        SemanticConstraint,
        SemanticSHACLGate,
        SemanticValidationResult,
        SemanticViolation,
        build_semantic_constraints_from_kg,
    )
except ImportError:
    SemanticConstraint = SemanticSHACLGate = SemanticValidationResult = None  # type: ignore[assignment,misc]
    SemanticViolation = build_semantic_constraints_from_kg = None  # type: ignore[assignment,misc]
from graqle.ontology.shacl_gate import SHACLGate, ValidationResult
from graqle.ontology.skill_resolver import Skill, SkillResolver
from graqle.ontology.upper import UpperOntology

__all__ = [
    "UpperOntology",
    "DomainRegistry",
    "DomainOntology",
    "SHACLGate",
    "ValidationResult",
    "ConstraintGraph",
    "OntologyRouter",
    "SkillResolver",
    "Skill",
    # Semantic governance (v3)
    "SemanticSHACLGate",
    "SemanticConstraint",
    "SemanticValidationResult",
    "SemanticViolation",
    "build_semantic_constraints_from_kg",
    "OntologyGenerator",
    # Ontology schema (SHACL-like validation)
    "NODE_SHAPES",
    "EDGE_SHAPES",
    "NodeShape",
    "EdgeShape",
    "PropertyConstraint",
    "EdgeConstraint",
    "Violation",
    "ValidationReport",
    "validate_graph",
    "register_node_shape",
    "register_edge_shape",
    "get_node_shape",
    "get_all_node_types",
    "get_all_edge_types",
    # Markdown KG parser
    "MarkdownKGParser",
    "ExtractedEntity",
    "ExtractedEdge",
    "ParseResult",
    "EdgeInferenceEngine",
    "parse_markdown_kg",
    "parse_and_infer",
    "extract_tables",
]
