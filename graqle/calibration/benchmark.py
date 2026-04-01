"""Benchmark loader and correctness evaluator for GraQle calibration.

Loads YAML benchmark files containing calibration questions and provides
multi-strategy answer matching for automated scoring.
"""

# ── graqle:intelligence ──
# module: graqle.calibration.benchmark
# risk: MEDIUM (impact radius: 3 modules)
# consumers: calibration_runner, benchmark_runner, calibration CLI
# dependencies: __future__, dataclasses, logging, pathlib, re, typing, yaml
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.calibration.benchmark")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkQuestion:
    """A single calibration benchmark question with expected answer metadata."""

    id: str
    question: str
    expected_answer: str
    canonical_variants: list[str] = field(default_factory=list)
    expected_tool: str = "graq_reason"
    answer_type: str = "free_text"  # categorical | numeric | boolean | free_text
    difficulty: str = "medium"  # easy | medium | hard
    domain: str = ""
    expected_band: int = 4  # 1-7
    cross_kg: bool = False
    source: str = ""
    notes: str = ""
    is_answerable: bool = True


@dataclass
class CalibrationBenchmark:
    """A complete calibration benchmark suite loaded from YAML."""

    schema_version: str
    benchmark_name: str
    questions: list[BenchmarkQuestion] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    created: str = ""
    author: str = ""


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------

_VALID_ANSWER_TYPES = frozenset({"categorical", "numeric", "boolean", "free_text"})
_VALID_DIFFICULTIES = frozenset({"easy", "medium", "hard"})


def load_benchmark(path: str) -> CalibrationBenchmark:
    """Load a calibration benchmark from a YAML file.

    Validates the schema structure and returns a typed
    ``CalibrationBenchmark`` instance.

    Parameters
    ----------
    path:
        Filesystem path to the YAML benchmark file.

    Returns
    -------
    CalibrationBenchmark
        Parsed and validated benchmark.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    ValueError
        If required fields are missing or the schema is invalid.
    """
    import yaml  # lazy — yaml only needed at load time

    filepath = Path(path)
    if not filepath.exists():
        raise FileNotFoundError(f"Benchmark file not found: {filepath}")

    with open(filepath, "r", encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)

    if not isinstance(raw, dict):
        raise ValueError(
            f"Benchmark YAML must be a mapping, got {type(raw).__name__}"
        )

    # Validate required top-level keys
    for key in ("schema_version", "benchmark_name", "questions"):
        if key not in raw:
            raise ValueError(f"Missing required top-level key: '{key}'")

    raw_questions = raw["questions"]
    if not isinstance(raw_questions, list):
        raise ValueError("'questions' must be a list")

    questions: list[BenchmarkQuestion] = []
    for idx, q in enumerate(raw_questions):
        if not isinstance(q, dict):
            raise ValueError(f"Question at index {idx} must be a mapping")

        for req in ("id", "question", "expected_answer"):
            if req not in q:
                raise ValueError(
                    f"Question at index {idx} missing required field: '{req}'"
                )

        answer_type = str(q.get("answer_type", "free_text"))
        if answer_type not in _VALID_ANSWER_TYPES:
            raise ValueError(
                f"Question '{q['id']}': invalid answer_type '{answer_type}', "
                f"expected one of {sorted(_VALID_ANSWER_TYPES)}"
            )

        difficulty = str(q.get("difficulty", "medium"))
        if difficulty not in _VALID_DIFFICULTIES:
            raise ValueError(
                f"Question '{q['id']}': invalid difficulty '{difficulty}', "
                f"expected one of {sorted(_VALID_DIFFICULTIES)}"
            )

        band = int(q.get("expected_band", 4))
        if not 1 <= band <= 7:
            raise ValueError(
                f"Question '{q['id']}': expected_band must be 1-7, got {band}"
            )

        questions.append(
            BenchmarkQuestion(
                id=str(q["id"]),
                question=str(q["question"]),
                expected_answer=str(q["expected_answer"]),
                canonical_variants=[str(v) for v in q.get("canonical_variants", [])],
                expected_tool=str(q.get("expected_tool", "graq_reason")),
                answer_type=answer_type,
                difficulty=difficulty,
                domain=str(q.get("domain", "")),
                expected_band=band,
                cross_kg=bool(q.get("cross_kg", False)),
                source=str(q.get("source", "")),
                notes=str(q.get("notes", "")),
                is_answerable=bool(q.get("is_answerable", True)),
            )
        )

    benchmark = CalibrationBenchmark(
        schema_version=str(raw["schema_version"]),
        benchmark_name=str(raw["benchmark_name"]),
        questions=questions,
        domains=[str(d) for d in raw.get("domains", [])],
        created=str(raw.get("created", "")),
        author=str(raw.get("author", "")),
    )

    logger.info(
        "Loaded benchmark '%s' (v%s): %d questions, %d domains",
        benchmark.benchmark_name,
        benchmark.schema_version,
        len(benchmark.questions),
        len(benchmark.domains),
    )
    return benchmark


# ---------------------------------------------------------------------------
# Multi-strategy correctness evaluator
# ---------------------------------------------------------------------------

_NUMERIC_RE = re.compile(r"-?\d+(?:\.\d+)?")
_BOOL_TRUE = frozenset({"true", "yes", "1", "correct", "right", "affirmative"})
_BOOL_FALSE = frozenset({"false", "no", "0", "incorrect", "wrong", "negative"})


def evaluate_correctness(
    actual: str,
    expected: str,
    canonical_variants: list[str] | None = None,
    answer_type: str = "free_text",
) -> float:
    """Score *actual* against *expected* using type-aware multi-strategy matching.

    Strategies applied in order:

    1. Exact match (case-insensitive, stripped) -> 1.0
    2. Canonical variant match -> 1.0
    3. Type-specific: categorical substring, numeric extraction with
       tolerance, boolean normalisation, free-text keyword overlap.

    Returns a score in ``[0.0, 1.0]``.
    """
    if canonical_variants is None:
        canonical_variants = []

    if not actual or not expected:
        return 0.0

    actual_norm = actual.strip().lower()
    expected_norm = expected.strip().lower()

    # 1. Exact match
    if actual_norm == expected_norm:
        return 1.0

    # 2. Canonical variant match
    for variant in canonical_variants:
        if actual_norm == variant.strip().lower():
            return 1.0

    # 3. Type-specific strategies
    if answer_type == "categorical":
        if expected_norm in actual_norm or actual_norm in expected_norm:
            return 1.0
        for variant in canonical_variants:
            v = variant.strip().lower()
            if v in actual_norm or actual_norm in v:
                return 1.0
        return 0.0

    if answer_type == "numeric":
        actual_nums = _NUMERIC_RE.findall(actual_norm)
        expected_nums = _NUMERIC_RE.findall(expected_norm)
        if actual_nums and expected_nums:
            try:
                a_val = float(actual_nums[0])
                e_val = float(expected_nums[0])
                if e_val == 0.0:
                    return 1.0 if abs(a_val) < 1e-9 else 0.0
                rel_error = abs(a_val - e_val) / max(abs(e_val), 1e-9)
                return max(0.0, 1.0 - rel_error)
            except (ValueError, ZeroDivisionError):
                pass
        return 0.0

    if answer_type == "boolean":
        a_bool = actual_norm in _BOOL_TRUE
        e_bool = expected_norm in _BOOL_TRUE
        a_known = actual_norm in (_BOOL_TRUE | _BOOL_FALSE)
        if a_known:
            return 1.0 if a_bool == e_bool else 0.0
        return 0.0

    # free_text — keyword overlap
    expected_tokens = set(expected_norm.split())
    actual_tokens = set(actual_norm.split())
    if not expected_tokens:
        return 1.0 if not actual_tokens else 0.0
    overlap = expected_tokens & actual_tokens
    return len(overlap) / len(expected_tokens)
