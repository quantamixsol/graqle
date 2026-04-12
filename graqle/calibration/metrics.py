"""Calibration metrics for GraQle confidence scoring (R11 .

Numpy-only implementations of standard calibration metrics:
- Expected Calibration Error (ECE)
- Maximum Calibration Error (MCE)
- Brier Score

No scipy or sklearn dependencies.
"""

# ── graqle:intelligence ──
# module: graqle.calibration.metrics
# risk: LOW (impact radius: 3 modules)
# consumers: calibration_pipeline, benchmark_runner
# dependencies: __future__, numpy
# constraints: numpy-only — no scipy, no sklearn
# ── /graqle:intelligence ──

from __future__ import annotations

import numpy as np


def _validate_inputs(
    confidences: np.ndarray,
    correctness: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Validate and normalize calibration inputs.

    Raises ValueError on empty input, size mismatch, or out-of-range values.
    """
    confidences = np.asarray(confidences, dtype=np.float64).ravel()
    correctness = np.asarray(correctness, dtype=np.float64).ravel()

    if confidences.size == 0:
        raise ValueError("confidences array is empty")
    if confidences.size != correctness.size:
        raise ValueError(
            f"Shape mismatch: confidences={confidences.size}, "
            f"correctness={correctness.size}"
        )
    if np.any((confidences < 0.0) | (confidences > 1.0)):
        raise ValueError(
            "confidences must be in [0, 1]; "
            f"got range [{confidences.min():.4f}, {confidences.max():.4f}]"
        )
    return confidences, correctness


def compute_ece(
    confidences: np.ndarray,
    correctness: np.ndarray,
    n_bins: int = 10,
) -> tuple[float, dict]:
    """Compute Expected Calibration Error with reliability diagram data.

    Uses equal-width bins over [0, 1].

    Parameters
    ----------
    confidences : np.ndarray
        Predicted confidence scores in [0, 1].
    correctness : np.ndarray
        Binary correctness labels (1 = correct, 0 = incorrect).
    n_bins : int
        Number of equal-width bins (default 10).

    Returns
    -------
    tuple[float, dict]
        ``(ece_value, reliability_diagram)`` where *reliability_diagram*
        maps ``bin_center -> (accuracy, mean_confidence, count)``.
    """
    confidences, correctness = _validate_inputs(confidences, correctness)

    if n_bins < 1:
        raise ValueError(f"n_bins must be >= 1, got {n_bins}")

    n_samples = confidences.size
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    reliability: dict[float, tuple[float, float, int]] = {}
    ece = 0.0

    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        bin_center = round((lo + hi) / 2.0, 4)

        # Last bin is inclusive on the right edge to capture confidence == 1.0
        if i < n_bins - 1:
            mask = (confidences >= lo) & (confidences < hi)
        else:
            mask = (confidences >= lo) & (confidences <= hi)

        count = int(mask.sum())
        if count == 0:
            continue

        bin_acc = float(correctness[mask].mean())
        bin_conf = float(confidences[mask].mean())
        reliability[bin_center] = (bin_acc, bin_conf, count)
        ece += (count / n_samples) * abs(bin_acc - bin_conf)

    return float(ece), reliability


def compute_mce(
    confidences: np.ndarray,
    correctness: np.ndarray,
    n_bins: int = 10,
) -> float:
    """Compute Maximum Calibration Error — worst-case bin gap.

    Parameters
    ----------
    confidences : np.ndarray
        Predicted confidence scores in [0, 1].
    correctness : np.ndarray
        Binary correctness labels (1 = correct, 0 = incorrect).
    n_bins : int
        Number of equal-width bins (default 10).

    Returns
    -------
    float
        Maximum |accuracy - confidence| across all non-empty bins.
    """
    _, reliability = compute_ece(confidences, correctness, n_bins=n_bins)

    if not reliability:
        return 0.0

    return float(max(abs(acc - conf) for acc, conf, _ in reliability.values()))


def compute_brier_score(
    confidences: np.ndarray,
    correctness: np.ndarray,
) -> float:
    """Compute Brier Score — mean squared error between confidence and correctness.

    Parameters
    ----------
    confidences : np.ndarray
        Predicted confidence scores in [0, 1].
    correctness : np.ndarray
        Binary correctness labels (1 = correct, 0 = incorrect).

    Returns
    -------
    float
        Mean squared difference. Lower is better; 0.0 for empty input.
    """
    confidences, correctness = _validate_inputs(confidences, correctness)

    return float(np.mean((confidences - correctness) ** 2))
