"""CR-004 PR-004a tests — :class:`GraphHealth` dataclass bounds validation.

The dataclass itself does no I/O — these tests cover the
``__post_init__`` bounds checks only. The probe behaviour is covered by
``tests/test_activation/test_graph_health_probe.py``.

CI safety: only normal imports, no ``importlib.util.module_from_spec``.
"""

from __future__ import annotations

import pytest

from graqle.core.graph_health import GraphHealth


def _healthy_kwargs(**overrides: object) -> dict[str, object]:
    """Baseline valid keyword args; tests pass overrides to flip one field."""
    base: dict[str, object] = {
        "node_count": 100,
        "edge_count": 250,
        "chunks_unembedded": 0,
        "percent_stale": 0.0,
        "activation_mode": "semantic",
        "degraded": False,
        "reason": None,
    }
    base.update(overrides)
    return base


# ─── Happy path ─────────────────────────────────────────────────────────────


def test_healthy_construction_succeeds() -> None:
    """A minimal valid GraphHealth constructs without raising."""
    gh = GraphHealth(**_healthy_kwargs())  # type: ignore[arg-type]
    assert gh.node_count == 100
    assert gh.edge_count == 250
    assert gh.degraded is False
    assert gh.reason is None
    assert gh.schema_version == "1"


def test_degraded_with_reason_succeeds() -> None:
    """Degraded snapshot with a short reason string constructs cleanly."""
    gh = GraphHealth(  # type: ignore[arg-type]
        **_healthy_kwargs(
            degraded=True,
            reason="graph has 100 nodes but 0 edges",
            edge_count=0,
        )
    )
    assert gh.degraded is True
    assert gh.reason == "graph has 100 nodes but 0 edges"


# ─── Bounds: negative counts ────────────────────────────────────────────────


def test_negative_node_count_rejected() -> None:
    with pytest.raises(ValueError, match=r"node_count must be >= 0"):
        GraphHealth(**_healthy_kwargs(node_count=-1))  # type: ignore[arg-type]


def test_negative_edge_count_rejected() -> None:
    with pytest.raises(ValueError, match=r"edge_count must be >= 0"):
        GraphHealth(**_healthy_kwargs(edge_count=-5))  # type: ignore[arg-type]


def test_negative_chunks_unembedded_rejected() -> None:
    with pytest.raises(ValueError, match=r"chunks_unembedded must be >= 0"):
        GraphHealth(**_healthy_kwargs(chunks_unembedded=-1))  # type: ignore[arg-type]


# ─── Bounds: percent_stale in [0, 1] ────────────────────────────────────────


@pytest.mark.parametrize("bad_value", [-0.001, 1.0001, -1.0, 2.0, float("nan")])
def test_percent_stale_out_of_range_rejected(bad_value: float) -> None:
    with pytest.raises(ValueError, match=r"percent_stale must be in"):
        GraphHealth(**_healthy_kwargs(percent_stale=bad_value))  # type: ignore[arg-type]


@pytest.mark.parametrize("ok_value", [0.0, 0.5, 1.0])
def test_percent_stale_in_range_accepted(ok_value: float) -> None:
    gh = GraphHealth(**_healthy_kwargs(percent_stale=ok_value))  # type: ignore[arg-type]
    assert gh.percent_stale == ok_value


# ─── Bounds: reason length cap ──────────────────────────────────────────────


def test_reason_200_chars_accepted() -> None:
    """Exactly 200 chars is the cap and must be accepted."""
    s = "x" * 200
    gh = GraphHealth(  # type: ignore[arg-type]
        **_healthy_kwargs(reason=s, degraded=True)
    )
    assert gh.reason == s


def test_reason_201_chars_rejected() -> None:
    """One char over the cap raises."""
    s = "x" * 201
    with pytest.raises(ValueError, match=r"reason too long \(201 chars\)"):
        GraphHealth(**_healthy_kwargs(reason=s, degraded=True))  # type: ignore[arg-type]


def test_reason_none_always_accepted() -> None:
    """None is the canonical no-diagnostic value and is independent of len cap."""
    gh = GraphHealth(**_healthy_kwargs(reason=None))  # type: ignore[arg-type]
    assert gh.reason is None


# ─── Frozen semantics ───────────────────────────────────────────────────────


def test_frozen_assignment_raises() -> None:
    """Dataclass is frozen — direct attribute assignment raises."""
    gh = GraphHealth(**_healthy_kwargs())  # type: ignore[arg-type]
    with pytest.raises(Exception):
        gh.node_count = 999  # type: ignore[misc]
