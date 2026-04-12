"""OnlineLearner — R6 Component 2: adaptive weight updater for intent routing.

Learns from user corrections to improve keyword-rule and KG-signal weighting
over time.  Cold-start safe: falls back to pure rule scores until enough
corrections accumulate.
"""

# ── graqle:intelligence ──
# module: graqle.intent.online_learner
# risk: HIGH (impact radius: intent routing pipeline)
# consumers: intent_classifier, tool_router, checkpoint_manager
# dependencies: graqle.intent.types, collections, json, logging, math
# constraints: internal-pattern-B (all hyperparameters as constructor kwargs)
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from graqle.intent.types import CorrectionRecord, LearnerCheckpoint, ToolPrediction

logger = logging.getLogger("graqle.intent.online_learner")


class OnlineLearner:
    """Adaptive weight updater that blends keyword-rule scores with KG
    node-type signals, learning from user corrections.

    All hyperparameters are constructor kwargs (internal-pattern-B compliance — no
    class-level constants).
    """

    def __init__(
        self,
        *,
        learning_rate: float = 0.05,
        min_corrections: int = 10,
        weight_floor: float = 0.01,
        weight_ceiling: float = 5.0,
        decay_factor: float = 0.999,
        kg_blend_max: float = 0.6,
        kg_blend_denominator: float = 200.0,
        known_rules: Optional[List[str]] = None,
    ) -> None:
        # Hyperparameters (instance-level, NOT class constants — internal-pattern-B)
        self.learning_rate = learning_rate
        self.min_corrections = min_corrections
        self.weight_floor = weight_floor
        self.weight_ceiling = weight_ceiling
        self.decay_factor = decay_factor
        self.kg_blend_max = kg_blend_max
        self.kg_blend_denominator = kg_blend_denominator

        # State
        self.rule_weights: Dict[str, float] = {
            name: 1.0 for name in (known_rules or [])
        }
        self.node_type_weights: Dict[Tuple[str, str], float] = defaultdict(float)
        self.correction_count: int = 0
        self.weight_version: int = 0

    # ------------------------------------------------------------------
    # Core update
    # ------------------------------------------------------------------

    def update(self, correction: CorrectionRecord) -> None:
        """Apply a single correction to rule and node-type weights."""
        self.correction_count += 1
        self.weight_version += 1

        is_wrong = correction.predicted_tool != correction.corrected_tool

        # ── Rule weight updates ──────────────────────────────────────
        for rule_name in correction.keyword_rules_matched:
            current = self.rule_weights.get(rule_name, 1.0)
            if is_wrong:
                # Multiplicative penalty, floored
                updated = current * (1.0 - self.learning_rate)
                self.rule_weights[rule_name] = max(updated, self.weight_floor)
            else:
                # Additive reward, capped
                updated = current + self.learning_rate
                self.rule_weights[rule_name] = min(updated, self.weight_ceiling)

        # ── KG node_type × tool weight updates ───────────────────────
        for node_type in set(correction.activated_node_types):
            correct_key = (node_type, correction.corrected_tool)
            self.node_type_weights[correct_key] += self.learning_rate

            if is_wrong:
                wrong_key = (node_type, correction.predicted_tool)
                updated = self.node_type_weights[wrong_key] - self.learning_rate
                self.node_type_weights[wrong_key] = max(updated, 0.0)

        # ── Global decay on all node_type_weights ────────────────────
        for key in list(self.node_type_weights):
            self.node_type_weights[key] *= self.decay_factor

        logger.debug(
            "OnlineLearner update #%d (v%d): is_wrong=%s, rules_matched=%d, "
            "node_types=%d",
            self.correction_count,
            self.weight_version,
            is_wrong,
            len(correction.keyword_rules_matched),
            len(set(correction.activated_node_types)),
        )

    # ------------------------------------------------------------------
    # Scoring & classification
    # ------------------------------------------------------------------

    def score_tool(
        self,
        matched_rules: List[Tuple[str, str]],
        activated_node_types: List[str],
        tool: str,
    ) -> float:
        """Score a single tool given matched rules and activated node types.

        Parameters
        ----------
        matched_rules:
            List of ``(rule_name, target_tool)`` pairs from keyword matching.
        activated_node_types:
            KG node types activated by the current query.
        tool:
            The candidate tool to score.
        """
        rule_score = sum(
            self.rule_weights.get(name, 1.0)
            for name, target in matched_rules
            if target == tool
        )

        # Cold-start guard: pure rule signal until enough corrections
        if self.correction_count < self.min_corrections:
            return rule_score

        kg_score = sum(
            self.node_type_weights.get((nt, tool), 0.0) for nt in activated_node_types
        )

        # Blend caps at kg_blend_max KG influence
        kg_blend = min(self.kg_blend_max, self.correction_count / self.kg_blend_denominator)
        return (1.0 - kg_blend) * rule_score + kg_blend * kg_score

    def classify(
        self,
        matched_rules: List[Tuple[str, str]],
        activated_node_types: List[str],
        known_tools: List[str],
    ) -> ToolPrediction:
        """Classify the best tool from candidates via softmax over scores."""
        if not known_tools:
            raise ValueError("known_tools must be non-empty")

        scores: Dict[str, float] = {
            tool: self.score_tool(matched_rules, activated_node_types, tool)
            for tool in known_tools
        }

        probabilities = self._softmax(scores)

        best_tool = max(probabilities, key=probabilities.__getitem__)
        best_prob = probabilities[best_tool]
        method = "learned" if self.is_ready() else "rules_only"

        return ToolPrediction(
            tool=best_tool,
            confidence=best_prob,
            method=method,
            weight_version=self.weight_version,
        )

    def is_ready(self) -> bool:
        """Return ``True`` once enough corrections have been observed."""
        return self.correction_count >= self.min_corrections

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def checkpoint(self, path: str = "learner_weights.json") -> None:
        """Serialize current learner state to a JSON file."""
        serialized_nt_weights: Dict[str, float] = {
            f"{nt}|{tool}": weight
            for (nt, tool), weight in self.node_type_weights.items()
        }

        data = LearnerCheckpoint(
            rule_weights=dict(self.rule_weights),
            node_type_weights=serialized_nt_weights,
            correction_count=self.correction_count,
            weight_version=self.weight_version,
        )

        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data.to_dict(), fh, indent=2)

        logger.info(
            "Checkpoint saved to %s (version=%d)", path, self.weight_version
        )

    @classmethod
    def from_checkpoint(
        cls, path: str = "learner_weights.json", **kwargs: object
    ) -> OnlineLearner:
        """Restore an :class:`OnlineLearner` from a JSON checkpoint.

        Parameters
        ----------
        path:
            Path to the JSON checkpoint file.
        **kwargs:
            Hyperparameter overrides forwarded to the constructor.
        """
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)

        instance = cls(**kwargs)
        instance.rule_weights = raw.get("rule_weights", {})
        instance.correction_count = raw.get("correction_count", 0)
        instance.weight_version = raw.get("weight_version", 0)

        # Parse "node_type|tool" pipe-separated keys back to tuples
        # (no eval — security constraint)
        nt_raw: Dict[str, float] = raw.get("node_type_weights", {})
        restored: Dict[Tuple[str, str], float] = defaultdict(float)
        for pipe_key, weight in nt_raw.items():
            parts = pipe_key.split("|", 1)
            if len(parts) == 2:
                restored[(parts[0], parts[1])] = weight
        instance.node_type_weights = restored

        logger.info(
            "Restored from %s: correction_count=%d, weight_version=%d, "
            "rules=%d, node_type_keys=%d",
            path,
            instance.correction_count,
            instance.weight_version,
            len(instance.rule_weights),
            len(instance.node_type_weights),
        )
        return instance

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _softmax(scores: Dict[str, float]) -> Dict[str, float]:
        """Standard softmax with numerical stability (subtract max)."""
        if not scores:
            return {}
        max_score = max(scores.values())
        exp_scores = {k: math.exp(v - max_score) for k, v in scores.items()}
        total = sum(exp_scores.values())
        if total == 0:
            # Uniform fallback
            n = len(scores)
            return {k: 1.0 / n for k in scores}
        return {k: v / total for k, v in exp_scores.items()}
