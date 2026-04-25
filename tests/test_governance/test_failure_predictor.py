"""Tests for R19 Causal Governance Failure Chain Predictor (ADR-202).

Covers: failure_features.py, failure_predictor.py, near_miss_store.py.
Acceptance criteria: AC-1 through AC-7.
"""

import asyncio
import json
import tempfile
from datetime import datetime, timezone

import pytest

from graqle.governance.failure_features import (
    GovernanceFailureFeatures,
    extract_features,
    _safe_entropy,
    _percentile,
)
from graqle.governance.failure_predictor import (
    CausalChainDAG,
    CausalChainPrediction,
    CausalEdge,
    CausalNode,
    FailurePredictionResult,
    predict_governance_failures,
    _sigmoid,
    _build_candidate_chains,
)
from graqle.governance.near_miss_store import NearMissRecord, NearMissStore


# ═══════════════════════════════════════════════════════════════════
# failure_features.py tests
# ═══════════════════════════════════════════════════════════════════


class TestFeatureExtraction:
    """Feature vector extraction from topology and traces."""

    def test_empty_inputs(self):
        features = extract_features()
        assert features.feature_version == "r19.1"
        assert features.gate.total_decisions == 0
        assert features.trace_window.sample_count == 0

    def test_topology_only(self):
        edges = [
            {"source": "A", "target": "B", "relation": "COMPLIES_WITH"},
            {"source": "B", "target": "C", "relation": "GOVERNS"},
            {"source": "A", "target": "C", "relation": "AMENDS"},
        ]
        features = extract_features(topology_edges=edges)
        assert features.topology.node_count == 3
        assert features.topology.edge_count == 3
        assert features.decision_patterns.complies_with_count == 1
        assert features.decision_patterns.amends_count == 1
        assert features.decision_patterns.governs_count == 1
        assert features.decision_patterns.decision_entropy > 0

    def test_traces_gate_metrics(self):
        traces = [
            {"governance_decisions": [{"decision": "PASS"}], "outcome": "SUCCESS",
             "clearance_level": "INTERNAL", "latency_ms": 100, "tool_name": "graq_reason",
             "human_override": False, "timestamp": "2026-04-10T10:00:00+00:00"},
            {"governance_decisions": [{"decision": "BLOCK"}], "outcome": "BLOCKED",
             "clearance_level": "CONFIDENTIAL", "latency_ms": 200, "tool_name": "graq_write",
             "human_override": False, "timestamp": "2026-04-10T10:01:00+00:00"},
            {"governance_decisions": [{"decision": "WARN"}], "outcome": "SUCCESS",
             "clearance_level": "PUBLIC", "latency_ms": 50, "tool_name": "graq_context",
             "human_override": True, "timestamp": "2026-04-10T10:02:00+00:00"},
        ]
        features = extract_features(traces=traces)
        assert features.gate.total_decisions == 3
        assert abs(features.gate.pass_ratio - 1/3) < 0.01
        assert abs(features.gate.block_ratio - 1/3) < 0.01
        assert abs(features.gate.warn_ratio - 1/3) < 0.01
        assert abs(features.gate.override_rate - 1/3) < 0.01

    def test_traces_tool_metrics(self):
        traces = [
            {"governance_decisions": [], "outcome": "SUCCESS", "clearance_level": "INTERNAL",
             "latency_ms": 100, "tool_name": "graq_reason", "human_override": False,
             "timestamp": "2026-04-10T10:00:00+00:00"},
            {"governance_decisions": [], "outcome": "FAILURE", "clearance_level": "INTERNAL",
             "latency_ms": 5000, "tool_name": "graq_generate", "human_override": False,
             "timestamp": "2026-04-10T10:01:00+00:00"},
        ]
        features = extract_features(traces=traces)
        assert features.tool.total_calls == 2
        assert features.tool.failure_rate == 0.5
        assert features.tool.distinct_tools == 2

    def test_traces_latency_metrics(self):
        # Need enough data points for stdev-based anomaly detection
        traces = []
        for i in range(10):
            traces.append({"governance_decisions": [], "outcome": "SUCCESS",
                          "clearance_level": "INTERNAL", "latency_ms": 100 + i,
                          "tool_name": "t", "human_override": False,
                          "timestamp": f"2026-04-10T10:{i:02d}:00+00:00"})
        # Add a clear outlier
        traces.append({"governance_decisions": [], "outcome": "SUCCESS",
                       "clearance_level": "INTERNAL", "latency_ms": 50000,
                       "tool_name": "t", "human_override": False,
                       "timestamp": "2026-04-10T10:10:00+00:00"})
        features = extract_features(traces=traces)
        assert features.latency.max_ms == 50000
        assert features.latency.p50_ms > 0
        assert features.latency.anomaly_count >= 1

    def test_clearance_metrics(self):
        traces = [
            {"governance_decisions": [], "outcome": "SUCCESS", "clearance_level": "PUBLIC",
             "latency_ms": 100, "tool_name": "t", "human_override": False,
             "timestamp": "2026-04-10T10:00:00+00:00"},
            {"governance_decisions": [], "outcome": "SUCCESS", "clearance_level": "RESTRICTED",
             "latency_ms": 100, "tool_name": "t", "human_override": False,
             "timestamp": "2026-04-10T10:01:00+00:00"},
        ]
        features = extract_features(traces=traces)
        assert features.clearance.distinct_levels_used == 2
        assert features.clearance.escalation_gap_max == 3  # PUBLIC(0) to RESTRICTED(3)


class TestFeatureVector:
    """Feature vector serialization."""

    def test_vector_size(self):
        features = GovernanceFailureFeatures()
        vec = features.to_vector()
        assert len(vec) == 25  # VECTOR_SIZE defined in failure_features.py

    def test_feature_names_match_vector(self):
        names = GovernanceFailureFeatures.feature_names()
        vec = GovernanceFailureFeatures().to_vector()
        assert len(names) == len(vec)

    def test_vector_all_numeric(self):
        features = extract_features(
            topology_edges=[{"source": "A", "target": "B", "relation": "GOVERNS"}],
            traces=[{"governance_decisions": [{"decision": "PASS"}], "outcome": "SUCCESS",
                     "clearance_level": "INTERNAL", "latency_ms": 100, "tool_name": "t",
                     "human_override": False, "timestamp": "2026-04-10T10:00:00+00:00"}],
        )
        vec = features.to_vector()
        assert all(isinstance(v, float) for v in vec)


class TestHelpers:
    """Helper function tests."""

    def test_safe_entropy_uniform(self):
        # 3 equal counts: entropy = log2(3) ~ 1.585
        e = _safe_entropy([10, 10, 10])
        assert abs(e - 1.585) < 0.01

    def test_safe_entropy_zero(self):
        assert _safe_entropy([]) == 0.0
        assert _safe_entropy([0, 0, 0]) == 0.0

    def test_percentile_basic(self):
        assert _percentile([1, 2, 3, 4, 5], 50) == 3
        assert _percentile([], 50) == 0.0


# ═══════════════════════════════════════════════════════════════════
# failure_predictor.py tests
# ═══════════════════════════════════════════════════════════════════


class TestSigmoid:
    """Sigmoid activation function."""

    def test_zero_input(self):
        assert abs(_sigmoid(0) - 0.5) < 0.001

    def test_large_positive(self):
        assert _sigmoid(10) > 0.99

    def test_large_negative(self):
        assert _sigmoid(-10) < 0.01

    def test_numerically_stable(self):
        # Should not overflow
        assert _sigmoid(1000) == 1.0
        assert _sigmoid(-1000) == 0.0


class TestCausalChainDAG:
    """Causal chain DAG model."""

    def test_basic_creation(self):
        chain = CausalChainDAG(
            chain=["a", "b", "c"],
            nodes=[
                CausalNode(id="a", label="Node A", kind="gate"),
                CausalNode(id="b", label="Node B", kind="tool"),
                CausalNode(id="c", label="Node C", kind="gate"),
            ],
            edges=[
                CausalEdge(source="a", target="b", relation="causes"),
                CausalEdge(source="b", target="c", relation="triggers"),
            ],
            probability=0.85,
            root_cause="a",
            leaf_failure="c",
        )
        assert len(chain.nodes) == 3
        assert len(chain.edges) == 2
        assert chain.root_cause == "a"

    def test_serialization(self):
        chain = CausalChainDAG(chain=["x"], probability=0.5)
        d = chain.model_dump(mode="json")
        assert "chain" in d
        assert "probability" in d
        json.dumps(d, default=str)  # Should not raise


class TestPredictGovernanceFailures:
    """AC-1: Produces ranked failure-chain predictions."""

    def _make_traces(self, n=20, block_ratio=0.3):
        traces = []
        for i in range(n):
            decision = "BLOCK" if i < n * block_ratio else "PASS"
            traces.append({
                "governance_decisions": [{"decision": decision}],
                "outcome": "BLOCKED" if decision == "BLOCK" else "SUCCESS",
                "clearance_level": "INTERNAL",
                "latency_ms": 100 + i * 10,
                "tool_name": f"graq_tool_{i % 5}",
                "human_override": i % 10 == 0,
                "timestamp": f"2026-04-10T10:{i:02d}:00+00:00",
            })
        return traces

    def test_produces_ranked_predictions(self):
        """AC-1: Output contains ordered list of (chain, probability)."""
        result = predict_governance_failures(traces=self._make_traces(50))
        assert isinstance(result, FailurePredictionResult)
        assert len(result.predictions) > 0
        # Verify ranking
        for i in range(1, len(result.predictions)):
            assert result.predictions[i].probability <= result.predictions[i-1].probability
            assert result.predictions[i].rank == i + 1

    def test_causal_edges_present(self):
        """AC-2: Each chain has source->target with causal label."""
        result = predict_governance_failures(traces=self._make_traces(50))
        for pred in result.predictions:
            if len(pred.chain.nodes) > 1:
                assert len(pred.chain.edges) > 0
                for edge in pred.chain.edges:
                    assert edge.source
                    assert edge.target
                    assert edge.relation

    def test_backward_compatible(self):
        """AC-7: Default mode works without causal_chain parameter."""
        result = predict_governance_failures(traces=self._make_traces(20))
        assert isinstance(result, FailurePredictionResult)

    def test_empty_traces(self):
        result = predict_governance_failures(traces=[])
        assert result.trace_count == 0
        assert result.confidence == 0.0

    def test_topology_enhances_predictions(self):
        edges = [
            {"source": "CG-01", "target": "CG-02", "relation": "GOVERNS"},
            {"source": "CG-02", "target": "CG-03", "relation": "COMPLIES_WITH"},
        ]
        result = predict_governance_failures(
            topology_edges=edges,
            traces=self._make_traces(30),
        )
        assert result.features_used is not None
        assert result.features_used.topology.edge_count == 2

    def test_high_block_rate_triggers_chain(self):
        """High block rate should produce a failure chain prediction."""
        traces = self._make_traces(30, block_ratio=0.5)
        result = predict_governance_failures(traces=traces, threshold=0.1)
        chain_ids = []
        for p in result.predictions:
            chain_ids.extend(p.chain.chain)
        assert "high_block_rate" in chain_ids

    def test_threshold_filters_predictions(self):
        result_low = predict_governance_failures(
            traces=self._make_traces(30), threshold=0.0)
        result_high = predict_governance_failures(
            traces=self._make_traces(30), threshold=0.99)
        assert len(result_low.predictions) >= len(result_high.predictions)


# ═══════════════════════════════════════════════════════════════════
# near_miss_store.py tests
# ═══════════════════════════════════════════════════════════════════


class TestNearMissStore:
    """Near-miss corpus management."""

    def _make_record(self, chain="test_chain"):
        return NearMissRecord(
            chain_summary=chain,
            predicted_probability=0.85,
            prevented_by="gate_block",
            root_cause="high_block_rate",
        )

    def test_record_creates_file(self):
        """AC-6: Near-miss recorded."""
        async def _test():
            d = tempfile.mkdtemp()
            store = NearMissStore(store_dir=d)
            await store.record(self._make_record())
            assert store.count == 1
            records = store.read_near_misses()
            assert len(records) == 1
            assert records[0]["chain_summary"] == "test_chain"

        asyncio.run(_test())

    def test_corpus_growth_monotonic(self):
        async def _test():
            d = tempfile.mkdtemp()
            store = NearMissStore(store_dir=d)
            sizes = []
            for i in range(5):
                await store.record(self._make_record(f"chain_{i}"))
                sizes.append(store.corpus_size())
            for i in range(1, len(sizes)):
                assert sizes[i] >= sizes[i-1]

        asyncio.run(_test())

    def test_record_fields(self):
        async def _test():
            d = tempfile.mkdtemp()
            store = NearMissStore(store_dir=d)
            await store.record(self._make_record())
            records = store.read_near_misses()
            r = records[0]
            assert r["outcome"] == "prevented"
            assert r["prevented_by"] == "gate_block"
            assert r["predicted_probability"] == 0.85

        asyncio.run(_test())

    def test_empty_date(self):
        d = tempfile.mkdtemp()
        store = NearMissStore(store_dir=d)
        assert store.read_near_misses(date="1999-01-01") == []

    def test_valid_jsonl(self):
        async def _test():
            d = tempfile.mkdtemp()
            store = NearMissStore(store_dir=d)
            for i in range(3):
                await store.record(self._make_record(f"chain_{i}"))
            from pathlib import Path
            files = list(Path(d).glob("*.jsonl"))
            assert len(files) == 1
            with open(files[0]) as f:
                for line in f:
                    data = json.loads(line)
                    assert "id" in data
                    assert "chain_summary" in data

        asyncio.run(_test())
