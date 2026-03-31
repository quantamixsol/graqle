"""R10 Correction Selection Pipeline — escalation chain."""

# ── graqle:intelligence ──
# module: graqle.alignment.pipeline
# risk: MEDIUM (impact radius: 1 module)
# consumers: alignment CLI, MCP tools
# dependencies: graqle.alignment.*
# constraints: always apply lightest correction that achieves BLUE or better
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from typing import Any

from graqle.alignment.diagnostic import diagnose_misalignment
from graqle.alignment.embedding_store import EmbeddingStore
from graqle.alignment.measurement import measure_alignment
from graqle.alignment.types import AlignmentReport

logger = logging.getLogger("graqle.alignment.pipeline")

_BLUE_THRESHOLD = 0.70  # mean_cosine >= this means BLUE or GREEN


def correct_alignment(
    report: AlignmentReport,
    graph: Any,
    embedding_store: EmbeddingStore,
    embedding_model: Any = None,
) -> AlignmentReport:
    """Master correction pipeline: diagnose -> select -> apply -> verify.

    Always applies the lightest correction that achieves BLUE or better.
    Escalation chain: procrustes -> augmentation -> dual_encoder.
    """
    # Already aligned — no correction needed
    if report.mean_cosine >= _BLUE_THRESHOLD:
        report.diagnosis = "aligned"
        report.correction_applied = "none"
        logger.info(
            "Alignment already BLUE or better (mean=%.3f)", report.mean_cosine,
        )
        return report

    # Diagnose
    diagnosis = diagnose_misalignment(report.pairs)
    report.diagnosis = diagnosis.diagnosis
    logger.info(
        "Diagnosis: %s (confidence=%.2f, recommended=%s)",
        diagnosis.diagnosis,
        diagnosis.confidence,
        diagnosis.recommended_correction,
    )

    correction_order = []
    if diagnosis.recommended_correction == "procrustes":
        correction_order = ["procrustes", "augmentation", "dual_encoder"]
    elif diagnosis.recommended_correction == "augmentation":
        correction_order = ["augmentation", "dual_encoder"]
    elif diagnosis.recommended_correction == "dual_encoder":
        correction_order = ["dual_encoder"]
    else:
        correction_order = ["procrustes", "augmentation", "dual_encoder"]

    for correction in correction_order:
        logger.info("Attempting correction: %s", correction)

        try:
            if correction == "procrustes":
                from graqle.alignment.procrustes import apply_procrustes_correction
                _R, post_report = apply_procrustes_correction(
                    report.pairs, embedding_store, graph,
                )
            elif correction == "augmentation":
                from graqle.alignment.augmentation import apply_description_augmentation
                post_report = apply_description_augmentation(
                    report.pairs, graph, embedding_store, embedding_model,
                )
            elif correction == "dual_encoder":
                from graqle.alignment.dual_encoder import apply_dual_encoder_correction
                post_report = apply_dual_encoder_correction(
                    report.pairs, graph, embedding_store,
                )
            else:
                continue

            if post_report.mean_cosine >= _BLUE_THRESHOLD:
                logger.info(
                    "Correction %s achieved BLUE (mean=%.3f)",
                    correction, post_report.mean_cosine,
                )
                return post_report

            logger.info(
                "Correction %s insufficient (mean=%.3f < %.2f), escalating",
                correction, post_report.mean_cosine, _BLUE_THRESHOLD,
            )
        except ImportError as exc:
            logger.warning(
                "Correction %s unavailable: %s — escalating", correction, exc,
            )
        except Exception as exc:
            logger.error(
                "Correction %s failed: %s — escalating", correction, exc,
            )

    # All corrections attempted — return best result
    logger.warning("All corrections attempted, alignment may still be below BLUE")
    return measure_alignment(graph, embedding_store)
