"""R10 R9 Integration — configure federated activation from alignment."""

# ── graqle:intelligence ──
# module: graqle.alignment.r9_config
# risk: LOW (impact radius: 1 module)
# consumers: R9 federated activation (future)
# dependencies: graqle.alignment.types
# constraints: penalty values are design parameters, not proprietary calibration
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

from graqle.alignment.types import AlignmentReport

logger = logging.getLogger("graqle.alignment.r9_config")


@dataclass
class FederatedActivationConfig:
    """Configuration for R9 federated cross-KG activation."""

    unaligned_penalty: float = 1.0
    cross_kg_enabled: bool = False
    warnings: List[str] = field(default_factory=list)
    alignment_metadata: Dict[str, Any] = field(default_factory=dict)


def configure_r9_from_alignment(
    alignment_report: AlignmentReport,
    federated_config: FederatedActivationConfig | None = None,
) -> FederatedActivationConfig:
    """Set R9 federated activation parameters based on measured alignment.

    The key parameter is ``unaligned_penalty``: a multiplicative factor
    applied to cross-KG activation scores before merging.

    Parameters
    ----------
    alignment_report:
        AlignmentReport from ``measure_alignment()``.
    federated_config:
        Existing config to update. Creates new one if None.

    Returns
    -------
    Updated FederatedActivationConfig.
    """
    if federated_config is None:
        federated_config = FederatedActivationConfig()

    mean_cos = alignment_report.mean_cosine

    if mean_cos >= 0.85:
        # GREEN — no penalty, scores directly comparable
        federated_config.unaligned_penalty = 1.0
        federated_config.cross_kg_enabled = True
    elif mean_cos >= 0.70:
        # BLUE — slight discount for cross-KG scores
        federated_config.unaligned_penalty = 0.90
        federated_config.cross_kg_enabled = True
    elif mean_cos >= 0.55:
        # YELLOW — significant discount
        federated_config.unaligned_penalty = 0.70
        federated_config.cross_kg_enabled = True
        federated_config.warnings.append(
            "YELLOW alignment: cross-KG scores discounted by 30%. "
            "Run R10 correction to improve."
        )
    else:
        # RED / GRAY — federation blocked
        federated_config.unaligned_penalty = 0.0
        federated_config.cross_kg_enabled = False
        federated_config.warnings.append(
            f"RED/GRAY alignment (mean_cosine={mean_cos:.3f}): "
            "federation BLOCKED. Apply R10 correction first."
        )

    # Store alignment metadata for R9 auditing
    federated_config.alignment_metadata = {
        "mean_cosine": alignment_report.mean_cosine,
        "median_cosine": alignment_report.median_cosine,
        "tier_distribution": alignment_report.tier_distribution,
        "correction_applied": alignment_report.correction_applied,
        "measurement_timestamp": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        "R9 config: penalty=%.2f, enabled=%s, mean_cosine=%.3f",
        federated_config.unaligned_penalty,
        federated_config.cross_kg_enabled,
        mean_cos,
    )

    return federated_config
