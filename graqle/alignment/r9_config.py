"""R10 R9 Integration — configure federated activation from alignment."""

# ── graqle:intelligence ──
# module: graqle.alignment.r9_config
# risk: LOW (impact radius: 1 module)
# consumers: R9 federated activation (future)
# dependencies: graqle.alignment.types
# constraints: TS-2 — penalty values externalized to .graqle/r9_penalties.json (gitignored)
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from graqle.alignment.types import AlignmentReport

logger = logging.getLogger("graqle.alignment.r9_config")


# ---------------------------------------------------------------------------
# Penalty configuration — loaded from private gitignored config
# ---------------------------------------------------------------------------

# Default penalties are safe fallbacks for open-source users.
# Production values are loaded from .graqle/r9_penalties.json (gitignored).
_DEFAULT_PENALTIES = {
    "green": 1.0,   # no penalty — publicly safe default
    "blue": 1.0,    # safe default — overridden by private config
    "yellow": 1.0,  # safe default — overridden by private config
    "red": 0.0,     # blocked — safe default
    "gray": 0.0,    # blocked — safe default
}


def _load_penalties(path: Path | None = None) -> Dict[str, float]:
    """Load R9 penalty values from private config.

    Falls back to safe defaults if the file doesn't exist.
    """
    if path is None:
        path = Path(".graqle/r9_penalties.json")

    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            logger.info("Loaded R9 penalties from %s", path)
            return {
                "green": float(data.get("green", _DEFAULT_PENALTIES["green"])),
                "blue": float(data.get("blue", _DEFAULT_PENALTIES["blue"])),
                "yellow": float(data.get("yellow", _DEFAULT_PENALTIES["yellow"])),
                "red": float(data.get("red", _DEFAULT_PENALTIES["red"])),
                "gray": float(data.get("gray", _DEFAULT_PENALTIES["gray"])),
            }
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning("Invalid R9 penalties file %s: %s — using defaults", path, exc)

    return _DEFAULT_PENALTIES.copy()


def load_federation_config(path: Path | None = None) -> Dict[str, Any]:
    """Load R9 federation tuning values from private config.

    Falls back to safe defaults if the file doesn't exist.
    Production values are in .graqle/r9_federation.json (gitignored).
    """
    if path is None:
        path = Path(".graqle/r9_federation.json")

    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            logger.info("Loaded R9 federation config from %s", path)
            return data
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning("Invalid R9 federation config %s: %s — using defaults", path, exc)

    return {}


def apply_federation_config(
    config: "FederatedActivationConfig",
    path: Path | None = None,
) -> "FederatedActivationConfig":
    """Apply private federation tuning values to config.

    Overwrites safe defaults with production values from .graqle/r9_federation.json.
    """
    data = load_federation_config(path)
    if not data:
        return config

    if "dedup_threshold" in data:
        config.dedup_threshold = float(data["dedup_threshold"])
    if "min_kg_quorum" in data:
        config.min_kg_quorum = int(data["min_kg_quorum"])
    if "min_diversity_ratio" in data:
        config.min_diversity_ratio = float(data["min_diversity_ratio"])
    if "ema_alpha" in data:
        config.ema_alpha = float(data["ema_alpha"])
    if "disagreement_discount" in data:
        config.disagreement_discount = float(data["disagreement_discount"])

    return config


@dataclass
class FederatedActivationConfig:
    """Configuration for R9 federated cross-KG activation.

    R10 fields: unaligned_penalty, cross_kg_enabled, warnings, alignment_metadata.
    R9 fields: top_k_per_kg, timeout_ms, min_kg_quorum, dedup_threshold,
    authority_weights, diversity_enforcement, min_diversity_ratio,
    conflict_detection, rrf_k, ema_alpha, disagreement_discount.

    All tuning values are config fields with safe defaults (TS-2 compliant).
    Production values loaded from .graqle/r9_penalties.json.
    """

    # ── R10 fields (alignment penalty) ──
    unaligned_penalty: float = 1.0
    cross_kg_enabled: bool = False
    warnings: List[str] = field(default_factory=list)
    alignment_metadata: Dict[str, Any] = field(default_factory=dict)

    # ── R9 fields (federation) ──
    # Safe defaults for open-source users. Production values loaded
    # from .graqle/r9_federation.json (gitignored) via load_federation_config().
    top_k_per_kg: int = 10
    timeout_ms: int = 5000
    min_kg_quorum: int = 1          # safe default — overridden by private config
    dedup_threshold: float = 1.0    # safe default (no dedup) — overridden by private config
    authority_weights: Dict[str, float] = field(default_factory=dict)
    diversity_enforcement: bool = True
    min_diversity_ratio: float = 0.0  # safe default (no enforcement) — overridden by private config
    conflict_detection: bool = True
    rrf_k: int = 60                 # published constant (Cormack et al. 2009) — NOT proprietary
    ema_alpha: float = 0.5          # safe default — overridden by private config
    disagreement_discount: float = 1.0  # safe default (no discount) — overridden by private config


def configure_r9_from_alignment(
    alignment_report: AlignmentReport,
    federated_config: FederatedActivationConfig | None = None,
    penalties_path: Path | None = None,
) -> FederatedActivationConfig:
    """Set R9 federated activation parameters based on measured alignment.

    Penalty values are loaded from ``.graqle/r9_penalties.json`` (gitignored)
    to comply with TS-2 trade secret governance. Safe defaults are used when
    the file is absent.

    Parameters
    ----------
    alignment_report:
        AlignmentReport from ``measure_alignment()``.
    federated_config:
        Existing config to update. Creates new one if None.
    penalties_path:
        Override path for penalties JSON (for testing).
    """
    if federated_config is None:
        federated_config = FederatedActivationConfig()

    penalties = _load_penalties(penalties_path)
    mean_cos = alignment_report.mean_cosine

    if mean_cos >= 0.85:
        # GREEN — no penalty, scores directly comparable
        federated_config.unaligned_penalty = penalties["green"]
        federated_config.cross_kg_enabled = True
    elif mean_cos >= 0.70:
        # BLUE — slight discount for cross-KG scores
        federated_config.unaligned_penalty = penalties["blue"]
        federated_config.cross_kg_enabled = True
    elif mean_cos >= 0.55:
        # YELLOW — significant discount
        federated_config.unaligned_penalty = penalties["yellow"]
        federated_config.cross_kg_enabled = True
        federated_config.warnings.append(
            "YELLOW alignment: cross-KG scores discounted. "
            "Run R10 correction to improve."
        )
    else:
        # RED / GRAY — federation blocked
        federated_config.unaligned_penalty = penalties.get(
            "red" if mean_cos >= 0.40 else "gray", 0.0,
        )
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
