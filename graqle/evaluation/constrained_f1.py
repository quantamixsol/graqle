"""Constrained F1 Evaluation — governance-aware precision/recall.

Standard F1 treats all tokens equally. Constrained F1 penalizes:
- Out-of-scope claims (false positives with governance cost)
- Missing in-scope coverage (false negatives with compliance cost)
- Cross-framework misattribution (wrong source cited)

This produces a governance-adjusted F1 that reflects regulatory accuracy,
not just textual overlap.

Usage:
    evaluator = ConstrainedF1Evaluator(constraints=shacl_constraints)
    result = evaluator.evaluate(
        prediction="The AI Act prohibits social scoring...",
        reference="Article 5(1)(c) prohibits social scoring systems...",
        entity_type="PROHIBITED_PRACTICE",
    )
    print(result.constrained_f1)  # 0.82 (penalized for missing article citation)
"""

# ── graqle:intelligence ──
# module: graqle.evaluation.constrained_f1
# risk: LOW (impact radius: 1 modules)
# consumers: __init__
# dependencies: __future__, logging, re, dataclasses, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("graqle.evaluation.constrained_f1")


@dataclass
class ConstrainedF1Result:
    """Result of a Constrained F1 evaluation."""

    # Standard metrics
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0

    # Governance penalties
    scope_penalty: float = 0.0          # Penalty for out-of-scope claims
    attribution_penalty: float = 0.0    # Penalty for misattributed sources
    coverage_penalty: float = 0.0       # Penalty for missing in-scope topics

    # Final constrained score
    constrained_f1: float = 0.0

    # Detailed breakdown
    in_scope_hits: int = 0
    out_of_scope_hits: int = 0
    missing_coverage: list[str] = field(default_factory=list)
    misattributions: list[str] = field(default_factory=list)
    reasoning_rule_violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "constrained_f1": round(self.constrained_f1, 4),
            "scope_penalty": round(self.scope_penalty, 4),
            "attribution_penalty": round(self.attribution_penalty, 4),
            "coverage_penalty": round(self.coverage_penalty, 4),
            "in_scope_hits": self.in_scope_hits,
            "out_of_scope_hits": self.out_of_scope_hits,
            "missing_coverage": self.missing_coverage,
            "misattributions": self.misattributions,
            "reasoning_rule_violations": self.reasoning_rule_violations,
        }


@dataclass
class BatchEvalResult:
    """Result of evaluating multiple predictions."""

    results: list[ConstrainedF1Result] = field(default_factory=list)

    @property
    def avg_f1(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.f1 for r in self.results) / len(self.results)

    @property
    def avg_constrained_f1(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.constrained_f1 for r in self.results) / len(self.results)

    @property
    def governance_gap(self) -> float:
        """Gap between standard F1 and constrained F1 (higher = more governance issues)."""
        return self.avg_f1 - self.avg_constrained_f1

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            f"Batch Evaluation: {len(self.results)} samples",
            f"  Avg F1:              {self.avg_f1:.4f}",
            f"  Avg Constrained F1:  {self.avg_constrained_f1:.4f}",
            f"  Governance Gap:      {self.governance_gap:.4f}",
        ]
        return "\n".join(lines)


class ConstrainedF1Evaluator:
    """Governance-aware F1 evaluator with semantic constraint penalties.

    Standard F1 measures token overlap. Constrained F1 adds three penalty
    layers that reflect governance accuracy:

    1. **Scope Penalty**: Claims about topics outside the entity's scope
       reduce precision (you said something you shouldn't have).
    2. **Attribution Penalty**: Citing the wrong framework for a claim
       reduces precision (you said something misleading).
    3. **Coverage Penalty**: Missing in-scope topics that appear in the
       reference reduces recall (you missed something important).

    .. note:: Requires Graqle Pro license (``constrained_f1`` feature).
    """

    def __init__(
        self,
        constraints: dict[str, Any] | None = None,
        scope_weight: float = 0.3,
        attribution_weight: float = 0.3,
        coverage_weight: float = 0.2,
        rule_weight: float = 0.2,
    ) -> None:
        self._constraints = constraints or {}
        self._scope_weight = scope_weight
        self._attribution_weight = attribution_weight
        self._coverage_weight = coverage_weight
        self._rule_weight = rule_weight

    def evaluate(
        self,
        prediction: str,
        reference: str,
        entity_type: str = "",
    ) -> ConstrainedF1Result:
        """Evaluate a single prediction against reference with governance constraints.

        Args:
            prediction: The model's output text
            reference: The ground truth / expected output
            entity_type: The entity type for constraint lookup

        Returns:
            ConstrainedF1Result with standard and governance-adjusted scores
        """
        result = ConstrainedF1Result()

        # Phase 1: Standard token-level F1
        pred_tokens = self._tokenize(prediction)
        ref_tokens = self._tokenize(reference)
        result.precision, result.recall, result.f1 = self._compute_f1(
            pred_tokens, ref_tokens
        )

        # Phase 2: Governance penalties (only if constraints exist for this type)
        constraint = self._constraints.get(entity_type)
        if constraint is not None:
            result.scope_penalty = self._compute_scope_penalty(
                prediction, constraint
            )
            result.attribution_penalty = self._compute_attribution_penalty(
                prediction, constraint
            )
            result.coverage_penalty = self._compute_coverage_penalty(
                prediction, reference, constraint, result
            )
            rule_penalty = self._compute_rule_violations(
                prediction, constraint, result
            )

            # Compute constrained F1
            total_penalty = (
                self._scope_weight * result.scope_penalty
                + self._attribution_weight * result.attribution_penalty
                + self._coverage_weight * result.coverage_penalty
                + self._rule_weight * rule_penalty
            )
            result.constrained_f1 = max(0.0, result.f1 * (1.0 - total_penalty))
        else:
            # No constraints — constrained F1 equals standard F1
            result.constrained_f1 = result.f1

        return result

    def evaluate_batch(
        self,
        predictions: list[str],
        references: list[str],
        entity_types: list[str] | None = None,
    ) -> BatchEvalResult:
        """Evaluate a batch of predictions."""
        if entity_types is None:
            entity_types = [""] * len(predictions)

        batch = BatchEvalResult()
        for pred, ref, etype in zip(predictions, references, entity_types):
            batch.results.append(self.evaluate(pred, ref, etype))
        return batch

    # -- Internal scoring methods -----------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Normalize and tokenize text for F1 computation."""
        text = text.lower().strip()
        # Remove punctuation except hyphens (preserve "Art. 5" as "art 5")
        text = re.sub(r"[^\w\s\-]", " ", text)
        tokens = set(text.split())
        # Remove stopwords
        stopwords = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "shall", "can",
            "of", "in", "to", "for", "with", "on", "at", "by", "from",
            "as", "into", "through", "during", "before", "after", "and",
            "but", "or", "not", "no", "this", "that", "these", "those",
            "it", "its", "they", "them", "their", "which", "what", "who",
        }
        return tokens - stopwords

    @staticmethod
    def _compute_f1(
        pred_tokens: set[str], ref_tokens: set[str]
    ) -> tuple[float, float, float]:
        """Compute precision, recall, F1 from token sets."""
        if not pred_tokens or not ref_tokens:
            return (0.0, 0.0, 0.0)

        common = pred_tokens & ref_tokens
        precision = len(common) / len(pred_tokens) if pred_tokens else 0.0
        recall = len(common) / len(ref_tokens) if ref_tokens else 0.0

        if precision + recall == 0:
            return (precision, recall, 0.0)

        f1 = 2 * precision * recall / (precision + recall)
        return (precision, recall, f1)

    def _compute_scope_penalty(
        self, prediction: str, constraint: Any
    ) -> float:
        """Penalty for discussing out-of-scope topics."""
        pred_lower = prediction.lower()
        out_of_scope = getattr(constraint, "out_of_scope_topics", [])
        if not out_of_scope:
            return 0.0

        hits = 0
        for topic in out_of_scope:
            if topic.lower() in pred_lower:
                hits += 1

        in_scope = getattr(constraint, "in_scope_topics", [])
        in_hits = sum(1 for t in in_scope if t.lower() in pred_lower)

        penalty = hits / max(len(out_of_scope), 1)
        return min(1.0, penalty)

    def _compute_attribution_penalty(
        self, prediction: str, constraint: Any
    ) -> float:
        """Penalty for misattributing claims to wrong frameworks."""
        pred_lower = prediction.lower()
        cross_ref_rules = getattr(constraint, "cross_reference_rules", {})
        own_markers = getattr(constraint, "own_framework_markers", [])

        if not cross_ref_rules:
            return 0.0

        misattributions = 0
        total_refs = 0

        for other_framework, rule in cross_ref_rules.items():
            # Check if the other framework is mentioned
            if other_framework.lower() in pred_lower:
                total_refs += 1
                # Check if it's properly attributed (mentioned as separate)
                proper_markers = ["separate", "distinct", "under", "regulation"]
                if not any(m in pred_lower for m in proper_markers):
                    misattributions += 1

        if total_refs == 0:
            return 0.0

        return misattributions / total_refs

    def _compute_coverage_penalty(
        self,
        prediction: str,
        reference: str,
        constraint: Any,
        result: ConstrainedF1Result,
    ) -> float:
        """Penalty for missing in-scope topics that are in the reference."""
        pred_lower = prediction.lower()
        ref_lower = reference.lower()
        in_scope = getattr(constraint, "in_scope_topics", [])

        if not in_scope:
            return 0.0

        missing = []
        covered = 0
        for topic in in_scope:
            topic_lower = topic.lower()
            # Topic is in reference but not in prediction
            if topic_lower in ref_lower:
                if topic_lower in pred_lower:
                    covered += 1
                    result.in_scope_hits += 1
                else:
                    missing.append(topic)

        result.missing_coverage = missing
        total_expected = covered + len(missing)
        if total_expected == 0:
            return 0.0

        return len(missing) / total_expected

    def _compute_rule_violations(
        self,
        prediction: str,
        constraint: Any,
        result: ConstrainedF1Result,
    ) -> float:
        """Check reasoning rules for semantic violations."""
        pred_lower = prediction.lower()
        rules = getattr(constraint, "reasoning_rules", [])

        if not rules:
            return 0.0

        violations = []
        for rule in rules:
            # Parse rules for contradiction signals
            # Rules like "Prohibited practices are BANNED, not 'high-risk'"
            negation_match = re.search(
                r"(?:not|never|cannot|must not)\s+['\"]?(\w+)", rule, re.IGNORECASE
            )
            assertion_match = re.search(
                r"(?:are|is|must be)\s+(\w+)", rule, re.IGNORECASE
            )

            if negation_match and assertion_match:
                wrong_term = negation_match.group(1).lower()
                right_term = assertion_match.group(1).lower()
                # If prediction uses the wrong term without the right term
                if wrong_term in pred_lower and right_term not in pred_lower:
                    violations.append(
                        f"Rule violated: used '{wrong_term}' "
                        f"instead of '{right_term}' — {rule[:80]}"
                    )

        result.reasoning_rule_violations = violations
        if not rules:
            return 0.0
        return len(violations) / len(rules)
