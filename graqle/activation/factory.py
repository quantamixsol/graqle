"""pre-reason-activation design — Factory for the default production ActivationLayer.

Wires real providers (or falls back to no-op providers on any import
failure) and resolves the tier mode from env + config.

Public entry point:
    default_activation_layer(config=None, predict_fn=None) -> ActivationLayer

Behavior:
    - Always returns a usable ActivationLayer; never raises.
    - Tier mode: resolved via tier_gate.resolve_tier_mode.
    - Providers:
        * ChunkScoring: RealChunkScoringProvider (wraps ChunkScorer)
        * Safety:       RealSafetyGateProvider (wraps DRACEScorer)
        * Subgraph:     RealSubgraphActivationProvider (wraps predict_fn if given)
    - If any real provider fails to load, substitutes the matching Noop.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from graqle.activation.layer import ActivationLayer
from graqle.activation.tier_gate import resolve_tier_mode

logger = logging.getLogger("graqle.activation.factory")


def default_activation_layer(
    config: dict[str, Any] | None = None,
    predict_fn: Optional[Callable] = None,
) -> ActivationLayer:
    """Construct the production default ActivationLayer.

    Parameters
    ----------
    config:
        Optional parsed graqle.yaml content. Used for tier detection.
    predict_fn:
        Optional async callable for PSE subgraph prediction. If None,
        the subgraph provider returns empty activations (turn still runs).
    """
    # Resolve tier first
    tier_mode = resolve_tier_mode(config)

    # Load providers defensively — any failure falls back to Noop
    try:
        from graqle.activation.real_providers import RealChunkScoringProvider
        chunk_scorer = RealChunkScoringProvider()
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("falling back to noop chunk scorer: %s", type(exc).__name__)
        from graqle.activation.default_providers import NoopChunkScoringProvider
        chunk_scorer = NoopChunkScoringProvider()

    try:
        from graqle.activation.real_providers import RealSafetyGateProvider
        safety_gate = RealSafetyGateProvider()
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("falling back to noop safety gate: %s", type(exc).__name__)
        from graqle.activation.default_providers import NoopSafetyGateProvider
        safety_gate = NoopSafetyGateProvider()

    try:
        from graqle.activation.real_providers import RealSubgraphActivationProvider
        subgraph = RealSubgraphActivationProvider(predict_fn=predict_fn)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("falling back to noop subgraph activator: %s", type(exc).__name__)
        from graqle.activation.default_providers import NoopSubgraphActivationProvider
        subgraph = NoopSubgraphActivationProvider()

    return ActivationLayer(
        chunk_scorer=chunk_scorer,
        safety_gate=safety_gate,
        subgraph_activator=subgraph,
        tier_mode=tier_mode,
    )
