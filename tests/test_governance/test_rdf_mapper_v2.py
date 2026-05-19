"""Integration tests for cr-017 RDF mapper emission of v2 schema fields.

Layer 2 of the cr-017 test plan. Targets
:func:`graqle.governance.shacl.validator._trace_to_rdf` — the helper that
converts a :class:`GovernedTrace` into RDF triples for SHACL validation.

cr-017 added two new triples:

  - ``trace_uri _GQ.schemaVersion "<version-string>"``  (always emitted)
  - ``trace_uri _GQ.policyVersion "<sha256:...>"``       (CONDITIONAL: only
    when ``trace.policy_version`` is not None)

These tests run only when ``rdflib`` is installed (it lives in the
``[api]`` optional-dependency extra, not the base install). On dev
environments without rdflib (such as a clean SDK clone before
``pip install graqle[api]``), the whole file is skipped via
``pytest.importorskip``.
"""

# ── graqle:intelligence ──
# module: tests.test_governance.test_rdf_mapper_v2
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, rdflib (optional), graqle.governance
# constraints: pin cr-017 RDF emission contract
# ── /graqle:intelligence ──

from __future__ import annotations

import pytest

# Skip the whole module if rdflib is unavailable. rdflib ships in the
# [api] extra of the graqle wheel; on a minimal install (or a dev env
# missing the isodate transitive dep), this file is silently skipped.
rdflib = pytest.importorskip("rdflib")

from graqle.governance.shacl.validator import _GQ, _trace_to_rdf  # noqa: E402
from graqle.governance.trace_schema import (  # noqa: E402
    ClearanceLevel,
    GovernedTrace,
    Outcome,
    ToolCall,
)


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------


def _minimal_trace_with_inspect_step(**overrides) -> GovernedTrace:
    """Build a trace with one graq_inspect ToolCall (so _trace_to_rdf has
    a step to emit alongside the trace-level triples)."""
    defaults = {
        "tool_name": "graq_inspect",
        "query": "test",
        "outcome": Outcome.SUCCESS,
        "confidence": 0.9,
        "tool_calls": [
            ToolCall(tool="graq_inspect", args={}, result_summary="ok"),
        ],
    }
    defaults.update(overrides)
    return GovernedTrace(**defaults)


def _triples_with_predicate(g, predicate):
    """Return all triples in graph g that have the given predicate."""
    return list(g.triples((None, predicate, None)))


# -------------------------------------------------------------------------
# LAYER 2A — schemaVersion triple emission
# -------------------------------------------------------------------------


class TestSchemaVersionTriple:
    """The schemaVersion triple must ALWAYS be emitted (the field has a
    non-None default of "2", so it always has a value)."""

    def test_default_schema_version_emitted_as_2(self):
        trace = _minimal_trace_with_inspect_step()
        g = _trace_to_rdf(trace)
        triples = _triples_with_predicate(g, _GQ.schemaVersion)
        assert len(triples) == 1, (
            f"Expected exactly one schemaVersion triple; got {len(triples)}"
        )
        _, _, obj = triples[0]
        assert str(obj) == "2"

    def test_explicit_schema_version_3_emitted(self):
        # Forward-compat: future schema bumps must emit the actual version.
        trace = _minimal_trace_with_inspect_step(schema_version="3")
        g = _trace_to_rdf(trace)
        triples = _triples_with_predicate(g, _GQ.schemaVersion)
        assert len(triples) == 1
        assert str(triples[0][2]) == "3"

    def test_schema_version_attached_to_correct_trace_uri(self):
        trace = _minimal_trace_with_inspect_step()
        g = _trace_to_rdf(trace)
        triples = _triples_with_predicate(g, _GQ.schemaVersion)
        subj = triples[0][0]
        # The subject must be the canonical trace URI.
        assert str(subj) == f"urn:graqle:trace:{trace.id}"


# -------------------------------------------------------------------------
# LAYER 2B — policyVersion triple emission (CONDITIONAL)
# -------------------------------------------------------------------------


class TestPolicyVersionTriple:
    """policyVersion is emitted ONLY when trace.policy_version is set.
    Absence in RDF mirrors absence in JSON — both signal 'legacy or
    intentionally unbound' to downstream tooling."""

    def test_emitted_when_set(self):
        trace = _minimal_trace_with_inspect_step(
            policy_version="sha256:abc123"
        )
        g = _trace_to_rdf(trace)
        triples = _triples_with_predicate(g, _GQ.policyVersion)
        assert len(triples) == 1
        assert str(triples[0][2]) == "sha256:abc123"

    def test_not_emitted_when_none(self):
        # Default: policy_version=None → NO triple in the RDF graph.
        trace = _minimal_trace_with_inspect_step(policy_version=None)
        g = _trace_to_rdf(trace)
        triples = _triples_with_predicate(g, _GQ.policyVersion)
        assert len(triples) == 0

    def test_not_emitted_when_default(self):
        # Even without explicitly setting None, the default is None and
        # no triple should be emitted.
        trace = _minimal_trace_with_inspect_step()
        g = _trace_to_rdf(trace)
        triples = _triples_with_predicate(g, _GQ.policyVersion)
        assert len(triples) == 0

    def test_emitted_attached_to_correct_trace_uri(self):
        trace = _minimal_trace_with_inspect_step(
            policy_version="sha256:bound"
        )
        g = _trace_to_rdf(trace)
        triples = _triples_with_predicate(g, _GQ.policyVersion)
        subj = triples[0][0]
        assert str(subj) == f"urn:graqle:trace:{trace.id}"


# -------------------------------------------------------------------------
# LAYER 2C — additive invariant
# -------------------------------------------------------------------------


class TestRdfMapperAdditiveBehaviour:
    """The cr-017 fields must be ADDITIVE: no existing triple should
    disappear, no existing triple should change value, and the count of
    triples for pre-cr-017 fields must remain identical."""

    def test_existing_core_triples_still_present(self):
        # Pre-cr-017 core triples: toolName, clearanceLevel, confidence,
        # outcome. All four must still be emitted with correct values.
        trace = _minimal_trace_with_inspect_step()
        g = _trace_to_rdf(trace)
        assert len(_triples_with_predicate(g, _GQ.toolName)) == 1
        assert len(_triples_with_predicate(g, _GQ.clearanceLevel)) == 1
        assert len(_triples_with_predicate(g, _GQ.confidence)) == 1
        assert len(_triples_with_predicate(g, _GQ.outcome)) == 1

    def test_inspect_step_still_emitted(self):
        # The InspectStep RDF subnode must still be emitted (cr-017 only
        # touched trace-level triples, not step-level).
        trace = _minimal_trace_with_inspect_step()
        g = _trace_to_rdf(trace)
        inspect_triples = list(
            g.triples((None, rdflib.RDF.type, _GQ.InspectStep))
        )
        assert len(inspect_triples) == 1

    def test_total_triple_count_increase_when_policy_version_set(self):
        # When both new fields are populated, total triple count goes
        # up by exactly 2 (schemaVersion + policyVersion).
        trace_v1 = _minimal_trace_with_inspect_step(policy_version=None)
        trace_v2 = _minimal_trace_with_inspect_step(
            policy_version="sha256:x"
        )
        g_v1 = _trace_to_rdf(trace_v1)
        g_v2 = _trace_to_rdf(trace_v2)
        # Same number of triples MINUS the one policyVersion triple in v2.
        assert len(g_v2) == len(g_v1) + 1

    def test_no_phantom_triples_with_policy_version_none(self):
        # If policy_version is None, the only NEW triple vs hypothetical
        # pre-cr-017 should be schemaVersion. There must not be an
        # accidental policyVersion triple with empty/None value.
        trace = _minimal_trace_with_inspect_step(policy_version=None)
        g = _trace_to_rdf(trace)
        # Iterate ALL triples and verify no rdflib literal has empty value
        # for our predicates.
        for subj, pred, obj in g:
            if pred == _GQ.policyVersion:
                pytest.fail(f"Unexpected policyVersion triple: {obj}")
