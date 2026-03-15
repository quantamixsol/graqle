"""SHACL Validation Gate — validates node reasoning outputs.

Every node output passes through the SHACL gate before propagation.
Invalid reasoning is rejected with structured feedback for retry.
Based on the Licensing Oracle pattern (arXiv:2511.06073): AP=1.0, zero false answers.
"""

# ── graqle:intelligence ──
# module: graqle.ontology.shacl_gate
# risk: MEDIUM (impact radius: 8 modules)
# consumers: run_multigov_v3, ontology_generator, __init__, governance_v3, test_governance_v3 +3 more
# dependencies: __future__, logging, re, dataclasses, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("graqle.ontology.shacl_gate")


@dataclass
class ValidationResult:
    """Result of SHACL gate validation on a node output."""

    valid: bool = True
    violations: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    score: float = 1.0  # 0.0 = completely invalid, 1.0 = fully valid

    def add_violation(self, msg: str) -> None:
        self.valid = False
        self.violations.append(msg)

    def add_suggestion(self, msg: str) -> None:
        self.suggestions.append(msg)

    def to_feedback(self) -> str:
        """Format as feedback string for node retry prompt."""
        parts = []
        if self.violations:
            parts.append("VIOLATIONS (must fix):")
            for v in self.violations:
                parts.append(f"  - {v}")
        if self.suggestions:
            parts.append("SUGGESTIONS (should fix):")
            for s in self.suggestions:
                parts.append(f"  - {s}")
        return "\n".join(parts)


class SHACLGate:
    """Validates node reasoning outputs against entity-type-specific shapes.

    Output shapes define what a valid node output looks like:
    - must_reference: fields that MUST appear in the output
    - must_include_if_relevant: fields to include when the query touches them
    - max_length_words: maximum output length
    - forbidden_patterns: phrases that indicate evasion or hallucination
    - required_patterns: regex patterns that must match (e.g., article citations)
    """

    def __init__(self, output_shapes: Dict[str, Dict[str, Any]] | None = None) -> None:
        self._shapes: Dict[str, Dict[str, Any]] = output_shapes or {}
        self._stats = {"passes": 0, "failures": 0, "retries": 0}

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    def register_shapes(self, shapes: Dict[str, Dict[str, Any]]) -> None:
        """Register or update output shapes for entity types."""
        self._shapes.update(shapes)

    def validate(
        self,
        entity_type: str,
        output_text: str,
        query: str = "",
    ) -> ValidationResult:
        """Validate a node's reasoning output against its entity-type shape.

        Args:
            entity_type: The node's entity type (e.g., GOV_ENFORCEMENT)
            output_text: The node's reasoning output text
            query: The original query (for relevance checks)

        Returns:
            ValidationResult with validity, violations, and suggestions
        """
        result = ValidationResult()
        shape = self._shapes.get(entity_type)

        if not shape:
            # No shape defined — pass through (backward compatible)
            self._stats["passes"] += 1
            return result

        # Check forbidden patterns
        forbidden = shape.get("forbidden_patterns", [])
        output_lower = output_text.lower()
        for pattern in forbidden:
            if pattern.lower() in output_lower:
                result.add_violation(
                    f"Contains forbidden pattern: '{pattern}'. "
                    f"Provide specific domain knowledge instead."
                )

        # Check max length
        max_words = shape.get("max_length_words")
        if max_words:
            word_count = len(output_text.split())
            if word_count > max_words:
                result.add_violation(
                    f"Output too long: {word_count} words (max {max_words}). "
                    f"Be more concise and focused."
                )
                result.score *= 0.7

        # Check must_reference fields
        must_ref = shape.get("must_reference", [])
        for ref_field in must_ref:
            # Check if any form of the reference appears
            ref_patterns = _field_to_patterns(ref_field)
            found = any(p.lower() in output_lower for p in ref_patterns)
            if not found:
                result.add_violation(
                    f"Must reference '{ref_field}' but it's missing. "
                    f"Include specific {ref_field} information."
                )
                result.score *= 0.5

        # Check must_include_if_relevant
        conditional = shape.get("must_include_if_relevant", [])
        query_lower = query.lower() if query else ""
        for field_name in conditional:
            # Only check if the query mentions something related
            if _is_field_relevant(field_name, query_lower):
                ref_patterns = _field_to_patterns(field_name)
                found = any(p.lower() in output_lower for p in ref_patterns)
                if not found:
                    result.add_suggestion(
                        f"Query mentions '{field_name}'-related content but "
                        f"output doesn't address it. Consider including."
                    )
                    result.score *= 0.9

        # Check required_patterns (regex)
        required_patterns = shape.get("required_patterns", [])
        for pat in required_patterns:
            if not re.search(pat, output_text, re.IGNORECASE):
                result.add_violation(
                    f"Missing required pattern: {pat}"
                )
                result.score *= 0.6

        # Check minimum substance
        min_words = shape.get("min_length_words", 10)
        if len(output_text.split()) < min_words:
            result.add_violation(
                f"Output too short: {len(output_text.split())} words "
                f"(min {min_words}). Provide substantive analysis."
            )

        # Update stats
        if result.valid:
            self._stats["passes"] += 1
        else:
            self._stats["failures"] += 1

        return result

    def reset_stats(self) -> None:
        self._stats = {"passes": 0, "failures": 0, "retries": 0}

    def record_retry(self) -> None:
        self._stats["retries"] += 1


def _field_to_patterns(field_name: str) -> List[str]:
    """Convert a field name to search patterns.

    For compound fields like 'penalty_amount_or_percentage', also generates
    individual significant word patterns to allow flexible matching.
    """
    patterns = [field_name]
    # Handle common field name formats
    if "_" in field_name:
        spaced = field_name.replace("_", " ")
        patterns.append(spaced)
        # Also add individual significant words (skip connectors)
        skip_words = {"or", "and", "of", "the", "a", "an", "in", "for", "if"}
        words = [w for w in field_name.split("_") if w.lower() not in skip_words and len(w) > 2]
        patterns.extend(words)
    # Handle camelCase
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", field_name)
    if spaced != field_name:
        patterns.append(spaced.lower())
    return patterns


def _is_field_relevant(field_name: str, query_lower: str) -> bool:
    """Check if a field is relevant to the query."""
    relevance_map = {
        "penalty": ["penalty", "fine", "sanction", "enforcement", "punish"],
        "timeline": ["when", "deadline", "timeline", "date", "by when", "effective"],
        "obligation_type": ["must", "shall", "required", "obligation", "mandatory"],
        "penalty_amount_or_percentage": ["how much", "penalty", "fine", "amount", "%"],
        "enforcement_authority": ["who enforce", "authority", "regulator", "body"],
        "enforcement_type": ["type of", "kind of", "enforcement", "action"],
        "article_number": ["article", "art.", "section", "provision"],
    }
    keywords = relevance_map.get(field_name, [field_name.replace("_", " ")])
    return any(kw in query_lower for kw in keywords)
