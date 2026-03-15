"""Semantic SHACL Gate — OWL-aware governance validation for node reasoning.

Replaces the format-based SHACLGate with semantic validation that uses
the node's position in the OWL hierarchy to enforce governance constraints.

Three validation layers:
1. Framework Fidelity — node output must cite its own framework correctly
2. Scope Boundary — node must stay within its ontological domain
3. Cross-Reference Integrity — cross-framework citations must be explicit

Design principle: "Skills = HOW to reason. Constraints = WHERE to reason."
"""

# ── graqle:intelligence ──
# module: graqle.ontology.semantic_shacl_gate
# risk: MEDIUM (impact radius: 7 modules)
# consumers: run_multigov_v3, ontology_generator, __init__, governance_v3, test_governance_v3 +2 more
# dependencies: __future__, logging, re, dataclasses, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("graqle.ontology.semantic_shacl_gate")


@dataclass
class SemanticViolation:
    """A semantic governance violation with context."""

    layer: str  # "framework_fidelity", "scope_boundary", "cross_reference"
    severity: str  # "hard" (must fix) or "soft" (suggestion)
    message: str
    expected: str = ""
    found: str = ""


@dataclass
class SemanticValidationResult:
    """Result of semantic SHACL validation on a node output."""

    valid: bool = True
    violations: List[SemanticViolation] = field(default_factory=list)
    score: float = 1.0
    # Governance accuracy sub-scores (0.0 to 1.0)
    framework_fidelity_score: float = 1.0
    scope_adherence_score: float = 1.0
    cross_reference_score: float = 1.0

    def add_violation(self, v: SemanticViolation) -> None:
        self.violations.append(v)
        if v.severity == "hard":
            self.valid = False
            self.score *= 0.5
        else:
            self.score *= 0.85

    def to_feedback(self) -> str:
        """Format as feedback for node retry prompt."""
        parts = []
        hard = [v for v in self.violations if v.severity == "hard"]
        soft = [v for v in self.violations if v.severity == "soft"]
        if hard:
            parts.append("GOVERNANCE VIOLATIONS (must fix):")
            for v in hard:
                parts.append(f"  [{v.layer}] {v.message}")
                if v.expected:
                    parts.append(f"    Expected: {v.expected}")
                if v.found:
                    parts.append(f"    Found: {v.found}")
        if soft:
            parts.append("GOVERNANCE SUGGESTIONS:")
            for v in soft:
                parts.append(f"  [{v.layer}] {v.message}")
        return "\n".join(parts)

    @property
    def governance_accuracy(self) -> float:
        """Combined governance accuracy score."""
        return (
            self.framework_fidelity_score * 0.4
            + self.scope_adherence_score * 0.4
            + self.cross_reference_score * 0.2
        )


@dataclass
class SemanticConstraint:
    """A semantic constraint for a node type, derived from OWL + document analysis.

    This replaces the old format-based output shapes. Instead of
    'max_length_words: 150', we have 'reasoning_rules' that encode
    what the node MUST and MUST NOT claim.
    """

    entity_type: str
    framework: str = ""  # Which framework this entity belongs to (e.g., "EU AI Act")

    # Layer 1: Framework Fidelity
    own_framework_markers: List[str] = field(default_factory=list)
    # Keywords/phrases that identify THIS framework (e.g., ["EU AI Act", "AI Act", "Regulation 2024/1689"])
    other_framework_markers: Dict[str, List[str]] = field(default_factory=dict)
    # Other frameworks' markers — if found, must be flagged as cross-reference
    # e.g., {"GDPR": ["GDPR", "Regulation 2016/679", "data protection"], ...}

    # Layer 2: Scope Boundary
    in_scope_topics: List[str] = field(default_factory=list)
    # Topics this node IS authorized to speak about
    out_of_scope_topics: List[str] = field(default_factory=list)
    # Topics this node must NOT claim as its own (belong to other nodes)
    scope_description: str = ""
    # Human-readable scope description

    # Layer 3: Reasoning Rules (semantic, not format)
    reasoning_rules: List[str] = field(default_factory=list)
    # Deep semantic rules: "Prohibited practices have NO risk tier — they are BANNED"
    # These are injected into the node prompt AND checked during validation.

    # Layer 4: Cross-Reference Rules
    cross_reference_rules: Dict[str, str] = field(default_factory=dict)
    # How to reference other frameworks:
    # {"GDPR": "If mentioning GDPR, state it as 'Related: under GDPR Art. X...'"}

    # Relationship-derived constraints (from OWL)
    valid_relationships: List[str] = field(default_factory=list)
    # e.g., ["DEPENDS_ON → GDPR Art. 5", "MAPS_TO → AI Act Art. 14"]


class SemanticSHACLGate:
    """Semantic governance validation using OWL context.

    Instead of checking format (word count, regex patterns), this gate checks:
    1. Does the node speak about its OWN framework?
    2. Does the node stay within its ontological SCOPE?
    3. Are cross-framework references properly attributed?

    The OWL hierarchy defines WHAT you are.
    The SHACL constraints enforce HOW you must reason.
    """

    def __init__(
        self,
        constraints: Dict[str, SemanticConstraint] | None = None,
        strict_mode: bool = False,
    ) -> None:
        self._constraints: Dict[str, SemanticConstraint] = constraints or {}
        self._strict_mode = strict_mode
        self._stats = {
            "passes": 0,
            "failures": 0,
            "retries": 0,
            "framework_violations": 0,
            "scope_violations": 0,
            "crossref_violations": 0,
        }

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    def register_constraint(self, constraint: SemanticConstraint) -> None:
        """Register a semantic constraint for an entity type."""
        self._constraints[constraint.entity_type] = constraint

    def register_constraints(self, constraints: Dict[str, SemanticConstraint]) -> None:
        """Register multiple semantic constraints."""
        self._constraints.update(constraints)

    def validate(
        self,
        entity_type: str,
        output_text: str,
        query: str = "",
        node_context: Dict[str, Any] | None = None,
    ) -> SemanticValidationResult:
        """Validate a node's reasoning output against semantic governance constraints.

        Args:
            entity_type: The node's entity type (e.g., GOV_REQUIREMENT)
            output_text: The node's reasoning output
            query: The original user query
            node_context: Additional context (framework, label, relationships)

        Returns:
            SemanticValidationResult with governance accuracy scores
        """
        result = SemanticValidationResult()
        constraint = self._constraints.get(entity_type)

        if not constraint:
            # No semantic constraint — pass through
            self._stats["passes"] += 1
            return result

        output_lower = output_text.lower()
        node_ctx = node_context or {}

        # Layer 1: Framework Fidelity
        self._check_framework_fidelity(constraint, output_lower, result, node_ctx)

        # Layer 2: Scope Boundary
        self._check_scope_boundary(constraint, output_lower, query, result)

        # Layer 3: Cross-Reference Integrity
        self._check_cross_references(constraint, output_lower, result)

        # Update stats
        if result.valid:
            self._stats["passes"] += 1
        else:
            self._stats["failures"] += 1

        return result

    def _check_framework_fidelity(
        self,
        constraint: SemanticConstraint,
        output_lower: str,
        result: SemanticValidationResult,
        node_context: Dict[str, Any],
    ) -> None:
        """Layer 1: Does the output cite the correct framework?

        A GDPR node should cite GDPR, not claim AI Act provisions as its own.
        """
        if not constraint.own_framework_markers:
            return

        # Check if own framework is mentioned
        own_mentioned = any(
            marker.lower() in output_lower
            for marker in constraint.own_framework_markers
        )

        if not own_mentioned and len(output_lower.split()) > 20:
            # Substantive output that doesn't mention its own framework
            result.framework_fidelity_score *= 0.6
            result.add_violation(SemanticViolation(
                layer="framework_fidelity",
                severity="soft",
                message=f"Output doesn't reference own framework ({constraint.framework})",
                expected=f"Should cite: {', '.join(constraint.own_framework_markers[:3])}",
            ))

        # Check if OTHER frameworks are mentioned WITHOUT attribution
        for other_fw, markers in constraint.other_framework_markers.items():
            other_found = [m for m in markers if m.lower() in output_lower]
            if other_found:
                # Is it properly attributed as cross-reference?
                attribution_patterns = [
                    f"related.*{other_fw.lower()}",
                    f"under.*{other_fw.lower()}",
                    f"see also.*{other_fw.lower()}",
                    f"cf\\..*{other_fw.lower()}",
                    f"cross.?reference.*{other_fw.lower()}",
                    f"{other_fw.lower()}.*also",
                    f"maps.?to.*{other_fw.lower()}",
                    f"compare.*{other_fw.lower()}",
                ]
                properly_attributed = any(
                    re.search(pat, output_lower) for pat in attribution_patterns
                )

                if not properly_attributed:
                    # Node is claiming another framework's content as its own
                    self._stats["framework_violations"] += 1
                    result.framework_fidelity_score *= 0.5
                    result.add_violation(SemanticViolation(
                        layer="framework_fidelity",
                        severity="hard" if self._strict_mode else "soft",
                        message=(
                            f"Mentions {other_fw} ({', '.join(other_found[:2])}) "
                            f"without proper attribution. "
                            f"State it as a cross-reference, not your own provision."
                        ),
                        expected=f"'Related: under {other_fw}...' or 'See also: {other_fw}...'",
                        found=f"Direct mention of {other_fw} without attribution",
                    ))

    def _check_scope_boundary(
        self,
        constraint: SemanticConstraint,
        output_lower: str,
        query: str,
        result: SemanticValidationResult,
    ) -> None:
        """Layer 2: Does the output stay within its ontological scope?

        A 'prohibited practices' node should not answer about 'high-risk obligations'.
        """
        if not constraint.out_of_scope_topics:
            return

        for topic in constraint.out_of_scope_topics:
            topic_lower = topic.lower()
            # Check for substantial discussion of out-of-scope topic
            # (not just passing mention)
            topic_words = topic_lower.split()
            if len(topic_words) <= 2:
                # Short topic — check exact match
                if topic_lower in output_lower:
                    # Count occurrences to distinguish passing mention from substantial discussion
                    count = output_lower.count(topic_lower)
                    if count >= 2:
                        self._stats["scope_violations"] += 1
                        result.scope_adherence_score *= 0.7
                        result.add_violation(SemanticViolation(
                            layer="scope_boundary",
                            severity="soft",
                            message=(
                                f"Discusses out-of-scope topic '{topic}' ({count} mentions). "
                                f"Your scope: {constraint.scope_description}"
                            ),
                            expected=f"Stay within: {constraint.scope_description}",
                            found=f"Discussed: {topic}",
                        ))
            else:
                # Longer topic — check if key words appear together
                key_words = [w for w in topic_words if len(w) > 3]
                matches = sum(1 for w in key_words if w in output_lower)
                if matches >= len(key_words) * 0.7:
                    self._stats["scope_violations"] += 1
                    result.scope_adherence_score *= 0.7
                    result.add_violation(SemanticViolation(
                        layer="scope_boundary",
                        severity="soft",
                        message=(
                            f"Appears to discuss out-of-scope topic: '{topic}'. "
                            f"Your scope: {constraint.scope_description}"
                        ),
                    ))

        # Check reasoning rules violations
        for rule in constraint.reasoning_rules:
            # Extract negation rules (rules that say "do NOT" or "MUST NOT")
            negation_match = re.search(
                r"(?:do not|must not|never|don't|cannot)\s+(?:say|claim|state|mention|confuse|mix)\s+(.+)",
                rule,
                re.IGNORECASE,
            )
            if negation_match:
                forbidden_claim = negation_match.group(1).lower().strip().rstrip(".")
                # Check if the forbidden claim appears in output
                forbidden_words = [w for w in forbidden_claim.split() if len(w) > 3]
                if forbidden_words:
                    matches = sum(1 for w in forbidden_words if w in output_lower)
                    if matches >= len(forbidden_words) * 0.6:
                        result.scope_adherence_score *= 0.8
                        result.add_violation(SemanticViolation(
                            layer="scope_boundary",
                            severity="soft",
                            message=f"May violate reasoning rule: {rule}",
                        ))

    def _check_cross_references(
        self,
        constraint: SemanticConstraint,
        output_lower: str,
        result: SemanticValidationResult,
    ) -> None:
        """Layer 3: Are cross-framework references properly handled?

        If the output mentions another framework, it must follow the
        cross_reference_rules defined in the constraint.
        """
        if not constraint.cross_reference_rules:
            return

        for framework, rule in constraint.cross_reference_rules.items():
            fw_lower = framework.lower()
            if fw_lower in output_lower:
                # Framework is mentioned — check if rule guidance is followed
                # We can't perfectly validate free text, but we check for
                # attribution patterns that indicate proper cross-referencing
                attribution_indicators = [
                    "related", "see also", "compare", "maps to",
                    "under", "separately", "distinct", "different",
                    "cross-reference", "cf.", "in contrast",
                ]
                has_attribution = any(
                    indicator in output_lower for indicator in attribution_indicators
                )
                if not has_attribution:
                    self._stats["crossref_violations"] += 1
                    result.cross_reference_score *= 0.7
                    result.add_violation(SemanticViolation(
                        layer="cross_reference",
                        severity="soft",
                        message=f"Mentions {framework} without attribution context. Rule: {rule}",
                    ))

    def get_constraint_prompt(
        self, entity_type: str, node_label: str = ""
    ) -> str:
        """Generate a semantic constraint prompt for a node.

        This replaces the old format-based constraint_text with rich
        semantic governance context derived from OWL + SHACL.
        """
        constraint = self._constraints.get(entity_type)
        if not constraint:
            return ""

        parts = []

        # Framework identity
        if constraint.framework:
            parts.append(f"FRAMEWORK: You belong to {constraint.framework}.")

        # Scope boundary
        if constraint.scope_description:
            parts.append(f"SCOPE: {constraint.scope_description}")
        if constraint.in_scope_topics:
            topics = ", ".join(constraint.in_scope_topics[:5])
            parts.append(f"IN YOUR SCOPE: {topics}")
        if constraint.out_of_scope_topics:
            topics = ", ".join(constraint.out_of_scope_topics[:5])
            parts.append(f"NOT YOUR SCOPE (other nodes handle these): {topics}")

        # Reasoning rules
        if constraint.reasoning_rules:
            parts.append("REASONING RULES:")
            for rule in constraint.reasoning_rules:
                parts.append(f"  - {rule}")

        # Cross-reference rules
        if constraint.cross_reference_rules:
            parts.append("CROSS-REFERENCE RULES:")
            for fw, rule in constraint.cross_reference_rules.items():
                parts.append(f"  - {fw}: {rule}")

        # Relationship-derived context
        if constraint.valid_relationships:
            parts.append("RELATED PROVISIONS:")
            for rel in constraint.valid_relationships[:5]:
                parts.append(f"  - {rel}")

        return "\n".join(parts)

    def record_retry(self) -> None:
        self._stats["retries"] += 1

    def reset_stats(self) -> None:
        self._stats = {
            "passes": 0,
            "failures": 0,
            "retries": 0,
            "framework_violations": 0,
            "scope_violations": 0,
            "crossref_violations": 0,
        }


def build_semantic_constraints_from_kg(
    kg_nodes: Dict[str, Any],
    framework_map: Dict[str, str] | None = None,
) -> Dict[str, SemanticConstraint]:
    """Build semantic constraints from KG node properties.

    This is the bridge between the KG structure and the SHACL gate.
    Each node's framework, scope, and relationships become constraints.

    Args:
        kg_nodes: Dict of node_id -> node data (from KG)
        framework_map: Optional mapping of node_id -> framework name

    Returns:
        Dict of entity_type -> SemanticConstraint
    """
    framework_map = framework_map or {}

    # Collect all frameworks for cross-reference detection
    all_frameworks: Dict[str, List[str]] = {}
    for nid, data in kg_nodes.items():
        fw = framework_map.get(nid, "")
        if not fw:
            fw = data.get("framework", data.get("label", "")).split(" -")[0].strip()
        if fw:
            markers = all_frameworks.setdefault(fw, [])
            if fw not in markers:
                markers.append(fw)

    # Build per-entity-type constraints
    type_constraints: Dict[str, SemanticConstraint] = {}

    # Group nodes by entity type
    nodes_by_type: Dict[str, List[Dict[str, Any]]] = {}
    for nid, data in kg_nodes.items():
        etype = data.get("entity_type", data.get("type", "Entity"))
        nodes_by_type.setdefault(etype, []).append(data)

    for etype, nodes in nodes_by_type.items():
        # Determine primary framework for this entity type
        frameworks = set()
        for n in nodes:
            fw = n.get("framework", "")
            if fw:
                frameworks.add(fw)

        primary_fw = list(frameworks)[0] if len(frameworks) == 1 else ""

        # Build scope from node descriptions
        in_scope = []
        for n in nodes:
            desc = n.get("description", "")
            if desc and len(desc) > 20:
                in_scope.append(desc[:100])

        # Other frameworks = cross-references
        other_markers = {}
        for fw, markers in all_frameworks.items():
            if fw != primary_fw:
                other_markers[fw] = markers

        constraint = SemanticConstraint(
            entity_type=etype,
            framework=primary_fw,
            own_framework_markers=all_frameworks.get(primary_fw, []),
            other_framework_markers=other_markers,
            in_scope_topics=in_scope[:5],
            scope_description=f"{etype} entities under {primary_fw}" if primary_fw else f"{etype} entities",
        )
        type_constraints[etype] = constraint

    return type_constraints
