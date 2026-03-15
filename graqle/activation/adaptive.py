"""AdaptiveActivation — dynamically adjusts Kmax based on query complexity.

Queries are scored on 4 complexity dimensions:
1. Token count (longer queries = more complex)
2. Entity count (more entities mentioned = broader scope)
3. Conjunction density (AND/OR/cross-ref signals)
4. Question depth (multi-hop indicators: "how does X affect Y", "compare")

The complexity score maps to Kmax via a configurable tier system:
- Simple (score < 0.15): Kmax = min_nodes (e.g., 4)
- Moderate (0.15-0.35): Kmax = mid_nodes (e.g., 8)
- Complex (0.35-0.55): Kmax = max_nodes (e.g., 12)
- Expert (score > 0.55): Kmax = expert_nodes (e.g., 16)
"""

# ── graqle:intelligence ──
# module: graqle.activation.adaptive
# risk: LOW (impact radius: 2 modules)
# consumers: __init__, test_adaptive
# dependencies: __future__, logging, re, dataclasses, pcst
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from graqle.activation.pcst import PCSTActivation

logger = logging.getLogger("graqle.activation.adaptive")


# Multi-hop / complexity indicator patterns
_MULTI_HOP_PATTERNS = [
    r"\bhow\s+does\s+\w+\s+(?:affect|impact|interact|relate|work|connect)\b",
    r"\bhow\s+do\s+\w+\s+(?:affect|impact|interact|relate|work|connect)\b",
    r"\bcompare\s+and\s+contrast\b",
    r"\bwhat\s+are\s+the\s+(?:combined|joint|dual|total)\b",
    r"\bboth\s+\w+\s+and\s+\w+\b",
    r"\bacross\s+(?:multiple|different|several)\b",
    r"\binter-?\w*\s+(?:domain|framework|regulation|service)\b",
    r"\bsupply\s+chain\b",
    r"\bend-to-end\b",
    r"\bcomprehensive\b",
    # Dev-specific multi-hop
    r"\bwhat\s+(?:depends|calls|imports|uses)\b",
    r"\bwhere\s+is\s+\w+\s+(?:used|called|imported|defined)\b",
    r"\bwhat\s+happens\s+when\b",
    r"\btrace\s+(?:the|through)\b",
    r"\bimpact\s+(?:of|analysis)\b",
    r"\brelationship\s+between\b",
    r"\bwhat\s+(?:files|components|services|modules)\b",
    r"\bexplain\s+(?:how|the|this)\b",
]

# Entity/framework markers (EU regulatory domain + general dev)
_ENTITY_MARKERS = [
    r"\bAI\s+Act\b", r"\bGDPR\b", r"\bDORA\b", r"\bNIS2?\b",
    r"\bPSD[23]?\b", r"\bCRR\b", r"\bCRD\b", r"\bMiCA\b",
    r"\beIDAS\b", r"\bMDR\b", r"\bIVDR\b",
    # General regulatory/compliance
    r"\bregulation\b", r"\bdirective\b", r"\bframework\b",
    r"\bstandard\b", r"\bcompliance\b",
    # Dev-specific entities (files, services, components)
    r"\bservice\b", r"\bcomponent\b", r"\bmodule\b", r"\bfunction\b",
    r"\bendpoint\b", r"\broute\b", r"\bhandler\b", r"\bmiddleware\b",
    r"\bdatabase\b", r"\bschema\b", r"\bAPI\b", r"\bauth\b",
    r"\bconfig\b", r"\btest\b", r"\bdeploy\b", r"\bpipeline\b",
    r"\b\w+\.\w{2,4}\b",  # filename patterns like "auth.ts", "api.py"
]

# Conjunction / cross-reference signals
_CONJUNCTION_PATTERNS = [
    r"\band\b", r"\bor\b", r"\bwhile\b", r"\bwhereas\b",
    r"\bin\s+addition\b", r"\balong\s+with\b", r"\bcombined\s+with\b",
    r"\binteract(?:s|ion)?\s+with\b", r"\boverlap\b",
    r"\bbetween\b", r"\bwith\b", r"\bthrough\b",
]


@dataclass
class ComplexityProfile:
    """Result of query complexity analysis."""
    token_score: float = 0.0      # 0-1: normalized token count
    entity_score: float = 0.0     # 0-1: entity density
    conjunction_score: float = 0.0 # 0-1: cross-reference density
    depth_score: float = 0.0      # 0-1: multi-hop indicator count

    @property
    def composite(self) -> float:
        """Weighted composite complexity score."""
        return (
            0.15 * self.token_score
            + 0.30 * self.entity_score
            + 0.20 * self.conjunction_score
            + 0.35 * self.depth_score
        )

    @property
    def tier(self) -> str:
        """Map composite score to tier.

        v0.12.1: Thresholds lowered based on real-world testing.
        Typical dev queries ("how does auth work?") scored 0.07-0.14
        with old thresholds, always landing in "simple". New thresholds
        ensure moderate/complex tiers actually trigger for real queries.
        """
        s = self.composite
        if s < 0.15:
            return "simple"
        elif s < 0.35:
            return "moderate"
        elif s < 0.55:
            return "complex"
        return "expert"


@dataclass
class AdaptiveConfig:
    """Configuration for adaptive Kmax tiers."""
    simple_nodes: int = 4
    moderate_nodes: int = 8
    complex_nodes: int = 12
    expert_nodes: int = 16
    # PCST parameters
    prize_scaling: float = 1.0
    cost_scaling: float = 1.0
    pruning: str = "strong"
    # Complexity scoring
    token_low: int = 5     # tokens below this = simple
    token_high: int = 30   # tokens above this = max complexity

    def kmax_for_tier(self, tier: str) -> int:
        return {
            "simple": self.simple_nodes,
            "moderate": self.moderate_nodes,
            "complex": self.complex_nodes,
            "expert": self.expert_nodes,
        }.get(tier, self.moderate_nodes)


class QueryComplexityScorer:
    """Scores query complexity on 4 dimensions."""

    def __init__(self, config: AdaptiveConfig | None = None) -> None:
        self._config = config or AdaptiveConfig()
        # Pre-compile patterns
        self._multi_hop = [re.compile(p, re.IGNORECASE) for p in _MULTI_HOP_PATTERNS]
        self._entities = [re.compile(p, re.IGNORECASE) for p in _ENTITY_MARKERS]
        self._conjunctions = [re.compile(p, re.IGNORECASE) for p in _CONJUNCTION_PATTERNS]

    def score(self, query: str) -> ComplexityProfile:
        """Analyze query and return complexity profile."""
        tokens = query.split()
        n_tokens = len(tokens)

        # 1. Token score: normalize between low and high
        cfg = self._config
        token_score = min(1.0, max(0.0,
            (n_tokens - cfg.token_low) / max(1, cfg.token_high - cfg.token_low)
        ))

        # 2. Entity score: count distinct entity markers
        entity_hits = sum(1 for p in self._entities if p.search(query))
        entity_score = min(1.0, entity_hits / 3.0)  # 3+ entities = max

        # 3. Conjunction score: cross-reference density
        conj_hits = sum(1 for p in self._conjunctions if p.search(query))
        conjunction_score = min(1.0, conj_hits / 2.0)  # 2+ conjunctions = max

        # 4. Depth score: multi-hop pattern matches
        depth_hits = sum(1 for p in self._multi_hop if p.search(query))
        depth_score = min(1.0, depth_hits / 1.5)  # 2+ multi-hop = max

        return ComplexityProfile(
            token_score=round(token_score, 3),
            entity_score=round(entity_score, 3),
            conjunction_score=round(conjunction_score, 3),
            depth_score=round(depth_score, 3),
        )


class AdaptiveActivation:
    """PCST activation with adaptive Kmax based on query complexity.

    Wraps PCSTActivation and dynamically adjusts max_nodes per query:
    - Simple queries (single-entity, short) → fewer nodes (faster, cheaper)
    - Complex queries (multi-framework, cross-domain) → more nodes (thorough)

    Usage:
        activator = AdaptiveActivation()
        node_ids = activator.activate(graph, query)
        print(f"Selected {len(node_ids)} nodes (tier: {activator.last_profile.tier})")
    """

    def __init__(self, config: AdaptiveConfig | None = None) -> None:
        self._config = config or AdaptiveConfig()
        self._scorer = QueryComplexityScorer(self._config)
        self._last_profile: ComplexityProfile | None = None
        self._last_kmax: int = 0

    @property
    def last_profile(self) -> ComplexityProfile | None:
        """Last query's complexity profile (for inspection/logging)."""
        return self._last_profile

    @property
    def last_kmax(self) -> int:
        """Last Kmax used."""
        return self._last_kmax

    def analyze(self, query: str) -> tuple[ComplexityProfile, int]:
        """Analyze query complexity and determine Kmax without activating."""
        profile = self._scorer.score(query)
        kmax = self._config.kmax_for_tier(profile.tier)
        return profile, kmax

    def activate(self, graph, query: str) -> list[str]:
        """Activate subgraph with adaptive Kmax.

        Args:
            graph: Graqle instance
            query: The reasoning query

        Returns:
            List of activated node IDs
        """
        profile, kmax = self.analyze(query)
        self._last_profile = profile
        self._last_kmax = kmax

        logger.info(
            f"Adaptive activation: tier={profile.tier}, "
            f"kmax={kmax}, composite={profile.composite:.3f} "
            f"[tok={profile.token_score:.2f} ent={profile.entity_score:.2f} "
            f"conj={profile.conjunction_score:.2f} dep={profile.depth_score:.2f}]"
        )

        # Create PCST with adapted max_nodes
        pcst = PCSTActivation(
            max_nodes=kmax,
            prize_scaling=self._config.prize_scaling,
            cost_scaling=self._config.cost_scaling,
            pruning=self._config.pruning,
        )

        return pcst.activate(graph, query)
