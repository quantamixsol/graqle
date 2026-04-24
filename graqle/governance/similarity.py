# ------------------------------------------------------------------
# PATENT NOTICE -- Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Applications EP26162901.8, EP26166054.2, EP26167849.4 (composite),
# owned by Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: support@quantamixsolutions.com
# ------------------------------------------------------------------

"""Project Similarity for Cross-Org Transfer (R21 ADR-204).

Computes sim(A, B) = alpha*sim_domain + beta*sim_stack + gamma*sim_governance
where:
- sim_domain: industry/domain tag overlap
- sim_stack: technology stack tag overlap
- sim_governance: governance configuration overlap
- alpha + beta + gamma = 1.0

Defaults: alpha=0.35, beta=0.30, gamma=0.35

This similarity module is SEPARATE from graqle/activation/chunk_scorer.py
cosine_similarity — that is for embedding similarity. This is for
project-level compliance matching.

TS-2 Gate: Similarity weights are learned from transfer outcomes (core IP).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from graqle.governance.pattern_abstractor import AbstractPattern, SimilarityProfile

# Default weights — learned from transfer outcomes in production
DEFAULT_ALPHA = 0.35  # domain weight
DEFAULT_BETA = 0.30   # stack weight
DEFAULT_GAMMA = 0.35  # governance weight

# Minimum similarity required to allow a transfer
DEFAULT_TRANSFER_THRESHOLD = 0.6


class SimilarityWeights(BaseModel):
    """Weights for the three-dimensional similarity score."""

    model_config = ConfigDict(extra="forbid")

    alpha: float = Field(ge=0.0, le=1.0, default=DEFAULT_ALPHA)
    beta: float = Field(ge=0.0, le=1.0, default=DEFAULT_BETA)
    gamma: float = Field(ge=0.0, le=1.0, default=DEFAULT_GAMMA)

    def validate_sum(self) -> bool:
        """Verify weights sum to ~1.0."""
        total = self.alpha + self.beta + self.gamma
        return abs(total - 1.0) < 0.001


class SimilarityScore(BaseModel):
    """Full similarity breakdown between two projects."""

    model_config = ConfigDict(extra="forbid")

    total: float = Field(ge=0.0, le=1.0)
    domain: float = Field(ge=0.0, le=1.0)
    stack: float = Field(ge=0.0, le=1.0)
    governance: float = Field(ge=0.0, le=1.0)
    weights: SimilarityWeights
    meets_threshold: bool
    threshold: float


def jaccard(set_a: set[str], set_b: set[str]) -> float:
    """Jaccard similarity between two sets: |A ∩ B| / |A ∪ B|."""
    if not set_a and not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def domain_similarity(tags_a: list[str], tags_b: list[str]) -> float:
    """Compute domain tag overlap via Jaccard."""
    return jaccard(set(tags_a), set(tags_b))


def stack_similarity(tags_a: list[str], tags_b: list[str]) -> float:
    """Compute stack tag overlap via Jaccard."""
    return jaccard(set(tags_a), set(tags_b))


def governance_similarity(
    gov_tags_a: list[str],
    gov_tags_b: list[str],
    pattern_a: AbstractPattern | None = None,
    pattern_b: AbstractPattern | None = None,
) -> float:
    """Compute governance overlap.

    Combines:
    - governance tag Jaccard (50%)
    - gate_type sequence overlap (25%, if patterns provided)
    - clearance level overlap (25%, if patterns provided)
    """
    tag_sim = jaccard(set(gov_tags_a), set(gov_tags_b))

    if pattern_a is None or pattern_b is None:
        return tag_sim

    # Gate type overlap
    gates_a = set(step.gate_type for step in pattern_a.gate_sequence)
    gates_b = set(step.gate_type for step in pattern_b.gate_sequence)
    gate_sim = jaccard(gates_a, gates_b)

    # Clearance level overlap
    clearances_a = set(step.clearance_before for step in pattern_a.gate_sequence)
    clearances_b = set(step.clearance_before for step in pattern_b.gate_sequence)
    clearance_sim = jaccard(clearances_a, clearances_b)

    return 0.5 * tag_sim + 0.25 * gate_sim + 0.25 * clearance_sim


def compute_similarity(
    pattern_a: AbstractPattern,
    pattern_b: AbstractPattern,
    weights: SimilarityWeights | None = None,
    threshold: float = DEFAULT_TRANSFER_THRESHOLD,
) -> SimilarityScore:
    """Compute full similarity between two abstract patterns.

    Parameters
    ----------
    pattern_a, pattern_b:
        Abstract patterns from two different organizations.
    weights:
        Override default weights (must sum to 1.0).
    threshold:
        Minimum total similarity for transfer eligibility.

    Returns
    -------
    SimilarityScore with per-dimension breakdown and threshold check.

    Raises
    ------
    ValueError: if weights do not sum to 1.0.
    """
    if weights is None:
        weights = SimilarityWeights()
    elif not weights.validate_sum():
        raise ValueError(
            f"Weights must sum to 1.0, got {weights.alpha + weights.beta + weights.gamma}"
        )

    domain = domain_similarity(pattern_a.domain_tags, pattern_b.domain_tags)
    stack = stack_similarity(pattern_a.stack_tags, pattern_b.stack_tags)
    governance = governance_similarity(
        pattern_a.governance_tags,
        pattern_b.governance_tags,
        pattern_a=pattern_a,
        pattern_b=pattern_b,
    )

    total = weights.alpha * domain + weights.beta * stack + weights.gamma * governance

    return SimilarityScore(
        total=total,
        domain=domain,
        stack=stack,
        governance=governance,
        weights=weights,
        meets_threshold=total >= threshold,
        threshold=threshold,
    )


def build_similarity_profile(
    pattern: AbstractPattern,
    against: list[AbstractPattern],
    weights: SimilarityWeights | None = None,
) -> SimilarityProfile:
    """Compute average similarity profile of a pattern against a corpus.

    Used to populate SimilarityProfile on an abstract pattern at creation time.
    """
    if not against:
        return SimilarityProfile()

    domain_scores = []
    stack_scores = []
    gov_scores = []
    for other in against:
        score = compute_similarity(pattern, other, weights=weights)
        domain_scores.append(score.domain)
        stack_scores.append(score.stack)
        gov_scores.append(score.governance)

    return SimilarityProfile(
        domain=sum(domain_scores) / len(domain_scores),
        stack=sum(stack_scores) / len(stack_scores),
        governance=sum(gov_scores) / len(gov_scores),
    )
