"""R22 SGCV — SHACL Governance Completeness Validator.

Converts GovernedTrace objects to RDF and validates them against shapes.ttl
using pyshacl. Returns ShaclValidationResult with conforms + violation details.

Determinism guarantee: same trace + same shapes.ttl → same conforms value.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rdflib import RDF, Graph, Literal, Namespace, URIRef
from rdflib.namespace import XSD

from graqle.governance.trace_schema import GovernedTrace

_GQ = Namespace("https://graqle.io/governance/shapes#")
_DEFAULT_SHAPES = Path(__file__).parent / "shapes.ttl"


@dataclass
class ViolationDetail:
    """A single SHACL constraint violation."""

    shape: str
    path: str
    message: str
    value: Any = None


@dataclass
class ShaclValidationResult:
    """Result of SHACL validation against governance shapes."""

    conforms: bool
    violations: list[ViolationDetail] = field(default_factory=list)
    shape_set_version: str = "1.0.0"
    validated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "conforms": self.conforms,
            "violations": [
                {
                    "shape": v.shape,
                    "path": v.path,
                    "message": v.message,
                    "value": str(v.value) if v.value is not None else None,
                }
                for v in self.violations
            ],
            "shape_set_version": self.shape_set_version,
            "validated_at": self.validated_at,
        }


class ShaclValidator:
    """Validates GovernedTrace objects against SHACL shapes.

    Loads shapes.ttl once at init time. Thread-safe for concurrent reads
    (shapes graph is never mutated after load).
    """

    def __init__(self, shapes_path: Path | None = None) -> None:
        self._shapes_path = shapes_path or _DEFAULT_SHAPES
        self._shapes_graph = Graph()
        self._shapes_graph.parse(str(self._shapes_path), format="turtle")
        self._shapes_hash = _sha256_file(self._shapes_path)

    @property
    def shapes_file_hash(self) -> str:
        return self._shapes_hash

    def validate(self, trace: GovernedTrace) -> ShaclValidationResult:
        """Validate a GovernedTrace against governance shapes."""
        data_graph = _trace_to_rdf(trace)
        return self.validate_graph(data_graph)

    def validate_graph(self, data_graph: Graph) -> ShaclValidationResult:
        """Low-level entry point: validate an already-built RDF graph."""
        import pyshacl  # deferred — caller must have [api] extras

        conforms, results_graph, _ = pyshacl.validate(
            data_graph,
            shacl_graph=self._shapes_graph,
            inference="none",
            abort_on_first=False,
            allow_infos=False,
            allow_warnings=False,
            meta_shacl=False,
            js=False,
            debug=False,
        )

        violations = _extract_violations(results_graph)
        return ShaclValidationResult(
            conforms=bool(conforms),
            violations=violations,
            shape_set_version=_get_shape_set_version(self._shapes_graph),
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _trace_to_rdf(trace: GovernedTrace) -> Graph:
    """Convert GovernedTrace to an RDF graph for SHACL validation."""
    g = Graph()
    g.bind("gq", _GQ)

    trace_uri = URIRef(f"urn:graqle:trace:{trace.id}")
    g.add((trace_uri, RDF.type, _GQ.GovernedTrace))

    # Core trace fields
    g.add((trace_uri, _GQ.toolName, Literal(trace.tool_name, datatype=XSD.string)))
    g.add((trace_uri, _GQ.clearanceLevel, Literal(trace.clearance_level.value, datatype=XSD.string)))
    g.add((trace_uri, _GQ.confidence, Literal(trace.confidence, datatype=XSD.double)))
    g.add((trace_uri, _GQ.outcome, Literal(trace.outcome.value, datatype=XSD.string)))

    # Gate decisions
    for i, gd in enumerate(trace.governance_decisions):
        gd_uri = URIRef(f"urn:graqle:gate:{trace.id}:{i}")
        g.add((gd_uri, RDF.type, _GQ.GateDecision))
        g.add((gd_uri, _GQ.gateId, Literal(gd.gate_id, datatype=XSD.string)))
        g.add((gd_uri, _GQ.gateType, Literal(gd.gate_type.value, datatype=XSD.string)))
        g.add((gd_uri, _GQ.decision, Literal(gd.decision.value, datatype=XSD.string)))
        g.add((trace_uri, _GQ.hasGateStep, gd_uri))

    # Tool calls as step nodes (typed by tool name)
    _STEP_TYPE_MAP = {
        "graq_inspect": _GQ.InspectStep,
        "graq_preflight": _GQ.PreflightStep,
        "graq_reason": _GQ.ReasonStep,
        "graq_review": _GQ.ReviewStep,
        "graq_learn": _GQ.LearnStep,
    }
    for i, tc in enumerate(trace.tool_calls):
        step_type = _STEP_TYPE_MAP.get(tc.tool)
        if step_type is None:
            continue
        step_uri = URIRef(f"urn:graqle:step:{trace.id}:{i}")
        g.add((step_uri, RDF.type, step_type))
        g.add((step_uri, _GQ.toolCallName, Literal(tc.tool, datatype=XSD.string)))
        g.add((trace_uri, _GQ.hasGateStep, step_uri))

        # Tool-specific fields from result_summary
        summary = tc.result_summary or ""
        if step_type == _GQ.InspectStep:
            status = "PASS" if "error" not in summary.lower() else "FAIL"
            g.add((step_uri, _GQ.stepStatus, Literal(status, datatype=XSD.string)))

        elif step_type == _GQ.PreflightStep:
            safety_score = _parse_float_from_summary(summary, "safety_score", 1.0)
            decision = "BLOCK" if "BLOCK" in summary.upper() else "PASS"
            g.add((step_uri, _GQ.safetyScore, Literal(safety_score, datatype=XSD.double)))
            g.add((step_uri, _GQ.decision, Literal(decision, datatype=XSD.string)))

        elif step_type == _GQ.ReasonStep:
            answer_confidence = _parse_float_from_summary(summary, "answer_confidence", 0.5)
            g.add((step_uri, _GQ.answerConfidence, Literal(answer_confidence, datatype=XSD.double)))

        elif step_type == _GQ.ReviewStep:
            approved = "BLOCK" not in summary.upper() and "BLOCKER" not in summary.upper()
            g.add((step_uri, _GQ.approved, Literal(approved, datatype=XSD.boolean)))

        elif step_type == _GQ.LearnStep:
            outcome_str = summary[:200] if summary else "recorded"
            g.add((step_uri, _GQ.learnOutcome, Literal(outcome_str, datatype=XSD.string)))

    return g


def _parse_float_from_summary(summary: str, key: str, default: float) -> float:
    """Extract a float value from a result_summary string."""
    import re
    pattern = rf"{re.escape(key)}[^\d]*([0-9]+(?:\.[0-9]+)?)"
    m = re.search(pattern, summary, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return default


def _extract_violations(results_graph: Graph) -> list[ViolationDetail]:
    """Extract violation details from pyshacl results graph."""
    _SH = Namespace("http://www.w3.org/ns/shacl#")
    violations = []

    for result in results_graph.subjects(_SH.resultSeverity, _SH.Violation):
        shape = str(results_graph.value(result, _SH.sourceShape) or "")
        path = str(results_graph.value(result, _SH.resultPath) or "")
        message = str(results_graph.value(result, _SH.resultMessage) or "")
        value = results_graph.value(result, _SH.value)
        violations.append(ViolationDetail(
            shape=shape, path=path, message=message, value=value
        ))

    return violations


def _get_shape_set_version(shapes_graph: Graph) -> str:
    """Extract shapeSetVersion triple from the shapes graph."""
    for _, _, v in shapes_graph.triples((_GQ.ShapeSetMetadata, _GQ.shapeSetVersion, None)):
        return str(v)
    return "unknown"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
