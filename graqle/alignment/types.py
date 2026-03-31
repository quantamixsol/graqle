"""R10 Embedding Space Alignment — data types."""

# ── graqle:intelligence ──
# module: graqle.alignment.types
# risk: LOW (impact radius: 3 modules)
# consumers: alignment.engine, alignment.tiers, alignment.diagnostics
# dependencies: __future__, dataclasses, typing, numpy
# constraints: no hardcoded thresholds — thresholds live in tiers.py
# ── /graqle:intelligence ──

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import numpy as np


# ---------------------------------------------------------------------------
# Module-level utilities
# ---------------------------------------------------------------------------


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors.

    Returns 0.0 if either vector has zero norm.
    """
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if not (norm_a > 0.0 and norm_b > 0.0):
        return 0.0
    return float(np.clip(np.dot(a, b) / (norm_a * norm_b), -1.0, 1.0))


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class AlignmentPair:
    """A single cross-language embedding alignment pair."""

    ts_node_id: str          # TypeScript node ID
    py_node_id: str          # Python node ID
    ts_embedding: np.ndarray  # 384-dim
    py_embedding: np.ndarray  # 384-dim
    tool_name: str           # e.g. "graq_reason"
    cosine_sim: float = 0.0
    tier: str = ""           # GREEN/BLUE/YELLOW/RED/GRAY


@dataclass
class AlignmentReport:
    """Aggregate alignment report across all pairs."""

    pairs: List[AlignmentPair]
    mean_cosine: float = 0.0
    median_cosine: float = 0.0
    std_cosine: float = 0.0
    tier_distribution: Dict[str, int] = field(default_factory=dict)
    diagnosis: str = ""       # "systematic_shift"|"domain_drift"|"random_noise"|"aligned"
    correction_applied: str = ""  # "none"|"procrustes"|"augmentation"|"dual_encoder"

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dictionary representation.

        Numpy arrays inside each :class:`AlignmentPair` are converted to
        plain Python lists so the result is safe for ``json.dumps``.
        """
        return {
            "pairs": [
                {
                    "ts_node_id": p.ts_node_id,
                    "py_node_id": p.py_node_id,
                    "ts_embedding": p.ts_embedding.tolist(),
                    "py_embedding": p.py_embedding.tolist(),
                    "tool_name": p.tool_name,
                    "cosine_sim": p.cosine_sim,
                    "tier": p.tier,
                }
                for p in self.pairs
            ],
            "mean_cosine": self.mean_cosine,
            "median_cosine": self.median_cosine,
            "std_cosine": self.std_cosine,
            "tier_distribution": dict(self.tier_distribution),
            "diagnosis": self.diagnosis,
            "correction_applied": self.correction_applied,
        }


@dataclass
class DiagnosisResult:
    """Result of a misalignment diagnosis analysis."""

    diagnosis: str              # "systematic_shift"|"domain_drift"|"random_noise"|"insufficient_data"
    confidence: float           # 0.0-1.0
    evidence: Dict[str, Any]    # test-specific evidence
    recommended_correction: str  # "procrustes"|"augmentation"|"dual_encoder"|"none"

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dictionary representation.

        Any numpy arrays or scalars nested inside *evidence* are
        recursively converted to native Python types.
        """
        return {
            "diagnosis": self.diagnosis,
            "confidence": self.confidence,
            "evidence": _serialize_evidence(self.evidence),
            "recommended_correction": self.recommended_correction,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _serialize_evidence(obj: Any) -> Any:
    """Recursively convert numpy types to JSON-safe Python primitives."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.complexfloating):
        return float(obj.real)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, dict):
        return {k: _serialize_evidence(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize_evidence(v) for v in obj]
    return obj
