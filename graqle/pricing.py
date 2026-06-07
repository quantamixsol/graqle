# V-AUTH-SAVINGS-NATIVE-001: new file via native Write (S-010).
"""Single source of truth for LLM token pricing and cost-savings math.

WHY THIS EXISTS
---------------
The dashboard's "Cost Saved" figure is a key marketing claim, so it must be an
AUTHENTIC, defensible number — real tokens valued at the REAL per-model price, not
a hardcoded flat rate. Before this module there were THREE conflicting hardcoded
rates in the codebase ($3/1M in the live dashboard partial, $15/1M in two others)
and the cost was model-agnostic. This module replaces all of them with one dated,
per-model price table and one cost function.

PRICING IS SOURCED AND DATED
----------------------------
``MODEL_PRICING`` lists published Anthropic per-million-token prices with an
``as_of`` date. When prices change, update the table and the date — never edit a
rate inline anywhere else. ``cost_for_tokens`` and ``cost_saved`` look prices up
here. A model id not in the table falls back to ``DEFAULT_MODEL`` pricing (logged),
so an unknown model degrades to a documented assumption rather than a wrong number.

The dashboard should surface the model + ``PRICING_AS_OF`` so the figure is
auditable ("$X saved, valued at <model> input pricing as of <date>").
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("graqle.pricing")

# Date the prices below were last verified against Anthropic's published pricing.
# Bump this whenever MODEL_PRICING changes.
PRICING_AS_OF = "2026-05-26"


@dataclass(frozen=True)
class ModelPrice:
    """Published price for one model, in USD per 1,000,000 tokens."""

    input_per_1m: float
    output_per_1m: float

    @property
    def input_per_token(self) -> float:
        return self.input_per_1m / 1_000_000.0

    @property
    def output_per_token(self) -> float:
        return self.output_per_1m / 1_000_000.0


# Published Anthropic pricing, $/1M tokens (input, output). Verified PRICING_AS_OF.
# Keys are EXACT model ids (the same strings passed to the API). Keep this list as
# the ONLY place rates live.
MODEL_PRICING: dict[str, ModelPrice] = {
    # Opus 4.x — $5 in / $25 out per 1M
    "claude-opus-4-8": ModelPrice(5.00, 25.00),
    "claude-opus-4-7": ModelPrice(5.00, 25.00),
    "claude-opus-4-6": ModelPrice(5.00, 25.00),
    "claude-opus-4-5": ModelPrice(5.00, 25.00),
    # Sonnet 4.x — $3 in / $15 out per 1M
    "claude-sonnet-4-6": ModelPrice(3.00, 15.00),
    "claude-sonnet-4-5": ModelPrice(3.00, 15.00),
    # Haiku 4.x — $1 in / $5 out per 1M
    "claude-haiku-4-5": ModelPrice(1.00, 5.00),
}

# When the model behind a saving is unknown, value it at this model's price. We
# pick the DEFAULT MODEL Graqle reasons with (Sonnet) so the headline number is
# conservative and defensible rather than inflated.
DEFAULT_MODEL = "claude-sonnet-4-6"


def _normalise_model(model: str | None) -> str:
    """Map a possibly-suffixed/blank model id to a key in MODEL_PRICING.

    Accepts exact ids, an empty/None value (→ DEFAULT_MODEL), and tolerates a
    trailing date/speed suffix (e.g. ``claude-haiku-4-5-20251001`` or
    ``claude-opus-4-6-fast``) by longest-prefix match against known ids.
    """
    if not model or not isinstance(model, str):
        return DEFAULT_MODEL
    m = model.strip()
    if m in MODEL_PRICING:
        return m
    # Longest known id that is a prefix of the supplied id wins (handles date /
    # `-fast` suffixes without guessing a price for a truly unknown family).
    candidates = [k for k in MODEL_PRICING if m.startswith(k)]
    if candidates:
        return max(candidates, key=len)
    logger.info("pricing: unknown model %r, valuing at %s", model, DEFAULT_MODEL)
    return DEFAULT_MODEL


def price_for(model: str | None) -> ModelPrice:
    """Return the :class:`ModelPrice` for a model id (DEFAULT_MODEL if unknown)."""
    return MODEL_PRICING[_normalise_model(model)]


def cost_for_tokens(
    model: str | None,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> float:
    """USD cost of ``input_tokens``/``output_tokens`` at ``model``'s real price."""
    p = price_for(model)
    return (max(input_tokens, 0) * p.input_per_token) + (
        max(output_tokens, 0) * p.output_per_token
    )


def cost_saved(tokens_saved: int, model: str | None = None) -> float:
    """USD value of ``tokens_saved`` context tokens at ``model``'s INPUT price.

    Tokens saved are tokens NOT sent to the model as input (the graph returned a
    focused context instead of a naive full load), so they are valued at the
    *input* rate — never the output rate. ``model`` defaults to DEFAULT_MODEL.
    This is the one function the dashboard / CLI / reports must call.
    """
    return max(tokens_saved, 0) * price_for(model).input_per_token


def pricing_basis(model: str | None = None) -> dict[str, object]:
    """A small dict for the UI to render the basis of a cost figure honestly."""
    key = _normalise_model(model)
    p = MODEL_PRICING[key]
    return {
        "model": key,
        "input_per_1m": p.input_per_1m,
        "output_per_1m": p.output_per_1m,
        "as_of": PRICING_AS_OF,
    }


__all__ = [
    "PRICING_AS_OF",
    "DEFAULT_MODEL",
    "MODEL_PRICING",
    "ModelPrice",
    "price_for",
    "cost_for_tokens",
    "cost_saved",
    "pricing_basis",
]
