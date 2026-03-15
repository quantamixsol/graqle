"""Tests for server Pydantic request/response models."""

# ── graqle:intelligence ──
# module: tests.test_server.test_models
# risk: LOW (impact radius: 0 modules)
# dependencies: models
# constraints: none
# ── /graqle:intelligence ──

from graqle.server.models import (
    BatchReasonRequest,
    ReasonRequest,
)


def test_reason_request_strategy_defaults_to_none():
    """Bug 24: strategy should default to None (reads from config), not 'pcst'."""
    req = ReasonRequest(query="test query")
    assert req.strategy is None, (
        f"ReasonRequest.strategy defaults to {req.strategy!r} — "
        f"should be None so graph.areason() reads from config"
    )


def test_batch_reason_request_strategy_defaults_to_none():
    """Bug 24: BatchReasonRequest.strategy should also default to None."""
    req = BatchReasonRequest(queries=["q1", "q2"])
    assert req.strategy is None, (
        f"BatchReasonRequest.strategy defaults to {req.strategy!r} — "
        f"should be None so graph.areason() reads from config"
    )


def test_reason_request_explicit_strategy_preserved():
    """Explicit strategy in request body should be preserved."""
    req = ReasonRequest(query="test", strategy="chunk")
    assert req.strategy == "chunk"

    req2 = ReasonRequest(query="test", strategy="pcst")
    assert req2.strategy == "pcst"
