"""Tests for ConvergenceDetector."""

# ── graqle:intelligence ──
# module: tests.test_orchestration.test_convergence
# risk: LOW (impact radius: 0 modules)
# dependencies: message, convergence
# constraints: none
# ── /graqle:intelligence ──

from graqle.core.message import Message
from graqle.orchestration.convergence import ConvergenceDetector


def _make_msg(node_id: str, content: str, confidence: float = 0.5) -> Message:
    return Message(
        source_node_id=node_id,
        target_node_id="__broadcast__",
        round=0,
        content=content,
        confidence=confidence,
    )


def test_never_converge_before_min_rounds():
    detector = ConvergenceDetector(max_rounds=10, min_rounds=3)
    msgs = [_make_msg("n1", "test", 0.99)]
    assert not detector.check(1, msgs, None)
    assert not detector.check(2, msgs, None)


def test_always_converge_at_max_rounds():
    detector = ConvergenceDetector(max_rounds=3, min_rounds=1)
    msgs = [_make_msg("n1", "test", 0.1)]
    assert detector.check(3, msgs, None)


def test_converge_on_high_confidence():
    detector = ConvergenceDetector(
        max_rounds=10, min_rounds=2, confidence_threshold=0.8
    )
    msgs = [_make_msg("n1", "test", 0.9), _make_msg("n2", "test2", 0.85)]
    assert detector.check(2, msgs, None)


def test_converge_on_similarity():
    detector = ConvergenceDetector(
        max_rounds=10, min_rounds=2, similarity_threshold=0.8
    )
    prev = [_make_msg("n1", "the answer is regulation conflict")]
    curr = [_make_msg("n1", "the answer is regulation conflict clearly")]
    assert detector.check(2, curr, prev)


def test_reset():
    detector = ConvergenceDetector()
    detector._round = 5
    detector.reset()
    assert detector._round == 0
