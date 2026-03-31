"""Three-tier diagnostic protocol for embedding misalignment (R10)."""

# ── graqle:intelligence ──
# module: graqle.alignment.diagnostic
# risk: MEDIUM (impact radius: 3 modules)
# consumers: alignment pipeline, correction strategies
# dependencies: numpy, graqle.alignment.types, sklearn (optional)
# constraints: sklearn optional — numpy SVD fallback provided
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from typing import List

import numpy as np

from graqle.alignment.types import AlignmentPair, DiagnosisResult

logger = logging.getLogger("graqle.alignment.diagnostic")

try:
    from sklearn.decomposition import PCA as _SklearnPCA

    _HAS_SKLEARN = True
except ImportError:  # pragma: no cover
    _HAS_SKLEARN = False

_SHIFT_RATIO_THRESHOLD = 2.0
_DRIFT_VARIANCE_THRESHOLD = 0.70


def _pca_explained_variance(X: np.ndarray, n_components: int) -> np.ndarray:
    """Compute explained-variance ratio via numpy SVD fallback."""
    X_centered = X - X.mean(axis=0)
    _U, S, _Vt = np.linalg.svd(X_centered, full_matrices=False)
    variance = S ** 2
    total = variance.sum()
    if total == 0:
        return np.zeros(n_components)
    return (variance / total)[:n_components]


def diagnose_misalignment(
    pairs: List[AlignmentPair],
    min_pairs: int = 10,
) -> DiagnosisResult:
    """Run three-tier diagnostic on TS/PY alignment pairs.

    Tier 1 — Systematic shift (Procrustes-correctable).
    Tier 2 — Domain drift (augmentation-correctable).
    Tier 3 — Random noise fallback (dual-encoder recommended).
    """
    # ── Guard: insufficient data ──────────────────────────────────
    if len(pairs) < min_pairs:
        logger.warning(
            "Insufficient alignment pairs (%d < %d)", len(pairs), min_pairs,
        )
        return DiagnosisResult(
            diagnosis="insufficient_data",
            confidence=0.0,
            evidence={
                "pairs_available": len(pairs),
                "min_required": min_pairs,
            },
            recommended_correction="none",
        )

    ts_embeddings = np.array([p.ts_embedding for p in pairs])
    py_embeddings = np.array([p.py_embedding for p in pairs])

    # ── TEST 1: Systematic Shift ──────────────────────────────────
    diff_vectors = ts_embeddings - py_embeddings
    centroid = np.mean(diff_vectors, axis=0)
    centroid_magnitude = float(np.linalg.norm(centroid))
    centered_diffs = diff_vectors - centroid
    shift_variance = float(np.mean(np.linalg.norm(centered_diffs, axis=1)))
    shift_ratio = centroid_magnitude / (shift_variance + 1e-8)

    if shift_ratio > _SHIFT_RATIO_THRESHOLD:
        logger.info("Diagnosed systematic_shift (ratio=%.3f)", shift_ratio)
        return DiagnosisResult(
            diagnosis="systematic_shift",
            confidence=min(1.0, shift_ratio / 5.0),
            evidence={
                "centroid_magnitude": centroid_magnitude,
                "shift_variance": shift_variance,
                "shift_ratio": float(shift_ratio),
                "interpretation": (
                    "Embedding spaces are offset by a consistent vector; "
                    "Procrustes alignment can correct this."
                ),
            },
            recommended_correction="procrustes",
        )

    # ── TEST 2: Domain Drift ──────────────────────────────────────
    n_components = min(3, len(pairs))

    if _HAS_SKLEARN:
        pca = _SklearnPCA(n_components=n_components)
        pca.fit(diff_vectors)
        explained_variance_ratio = pca.explained_variance_ratio_
    else:
        explained_variance_ratio = _pca_explained_variance(
            diff_vectors, n_components,
        )

    top3_variance = float(np.sum(explained_variance_ratio[:3]))
    component_variances = [float(v) for v in explained_variance_ratio[:3]]

    if top3_variance > _DRIFT_VARIANCE_THRESHOLD:
        logger.info("Diagnosed domain_drift (top-3 variance=%.3f)", top3_variance)
        return DiagnosisResult(
            diagnosis="domain_drift",
            confidence=min(1.0, top3_variance),
            evidence={
                "top_3_explained_variance": top3_variance,
                "component_variances": component_variances,
                "interpretation": (
                    "Misalignment is concentrated in a few principal directions, "
                    "indicating domain-specific drift correctable via augmentation."
                ),
            },
            recommended_correction="augmentation",
        )

    # ── TEST 3: Random Noise (fallback) ───────────────────────────
    logger.info(
        "Diagnosed random_noise (shift=%.3f, drift=%.3f)", shift_ratio, top3_variance,
    )
    return DiagnosisResult(
        diagnosis="random_noise",
        confidence=0.7,
        evidence={
            "shift_ratio": float(shift_ratio),
            "top_3_explained_variance": top3_variance,
            "interpretation": (
                "No systematic pattern detected; misalignment appears stochastic. "
                "A dual-encoder architecture is recommended."
            ),
        },
        recommended_correction="dual_encoder",
    )
