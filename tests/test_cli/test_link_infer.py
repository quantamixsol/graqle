"""Tests for graq link infer — cross-project edge inference (v0.29.10).

Covers:
- Basic inference lifecycle (run, save, dry-run, missing file)
- Strategy selection (--strategy api/env/name/all)
- Name similarity noise reduction (2+ shared tokens, stoplist, caps)
- Integration: merge → infer → verify saved edges
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from graqle.cli.commands.link import (
    link_app,
    _infer_name_similarity_edges,
    _infer_api_edges,
    _infer_env_var_edges,
    _NAME_SIMILARITY_STOPLIST,
)

runner = CliRunner()


def _make_node(nid: str, label: str, ntype: str = "Function", **extra) -> dict:
    """Helper to create a graph node dict."""
    node = {"id": nid, "label": label, "type": ntype, "entity_type": ntype, "properties": {}}
    node.update(extra)
    return node


@pytest.fixture
def cross_project_graph(tmp_path):
    """Merged graph with frontend/backend projects for inference testing."""
    graph = {
        "directed": True,
        "multigraph": False,
        "graph": {"merged_from": ["frontend", "backend"]},
        "nodes": [
            # Frontend nodes — share "onboarding" + "state" tokens with backend
            _make_node("frontend/useOnboardingState", "useOnboardingState", "Function"),
            _make_node("frontend/OnboardingPage", "OnboardingPage", "Function"),
            # Backend nodes — share "onboarding" + "state" tokens with frontend
            _make_node("backend/onboarding_state_service", "onboarding_state_service", "PythonModule"),
            _make_node("backend/OnboardingStateManager", "OnboardingStateManager", "Class"),
            # API endpoint (for API pattern inference)
            _make_node(
                "backend/api_onboarding_state", "/api/onboarding/state",
                "APIEndpoint",
            ),
            # Frontend node that references the API
            _make_node(
                "frontend/fetchOnboarding", "fetchOnboarding", "Function",
                description="Calls fetch('/api/onboarding/state') to load state",
            ),
            # Shared env vars
            _make_node("frontend/DATABASE_URL", "DATABASE_URL", "EnvVar"),
            _make_node("backend/DATABASE_URL", "DATABASE_URL", "EnvVar"),
        ],
        "links": [],
    }
    path = tmp_path / "merged.json"
    path.write_text(json.dumps(graph, indent=2))
    return path


@pytest.fixture
def single_token_graph(tmp_path):
    """Graph where nodes share only 1 token — should produce 0 name-similarity edges."""
    graph = {
        "directed": True, "multigraph": False,
        "graph": {"merged_from": ["alpha", "beta"]},
        "nodes": [
            # "payment" is the only shared token (4+ chars, not in stoplist)
            _make_node("alpha/PaymentProcessor", "PaymentProcessor", "Class"),
            _make_node("beta/PaymentGateway", "PaymentGateway", "Class"),
        ],
        "links": [],
    }
    path = tmp_path / "single_token.json"
    path.write_text(json.dumps(graph, indent=2))
    return path


@pytest.fixture
def two_token_graph(tmp_path):
    """Graph where nodes share 2+ tokens — should produce name-similarity edges."""
    graph = {
        "directed": True, "multigraph": False,
        "graph": {"merged_from": ["alpha", "beta"]},
        "nodes": [
            # Share "payment" + "invoice" tokens
            _make_node("alpha/PaymentInvoiceHandler", "PaymentInvoiceHandler", "Class"),
            _make_node("beta/InvoicePaymentService", "InvoicePaymentService", "Class"),
        ],
        "links": [],
    }
    path = tmp_path / "two_token.json"
    path.write_text(json.dumps(graph, indent=2))
    return path


# ---------------------------------------------------------------------------
# Phase 1: Basic Inference
# ---------------------------------------------------------------------------


class TestLinkInferBasic:
    def test_infer_runs_without_error(self, cross_project_graph):
        result = runner.invoke(link_app, ["infer", str(cross_project_graph)])
        assert result.exit_code == 0
        assert "Inferring cross-project edges" in result.output

    def test_infer_missing_file(self):
        result = runner.invoke(link_app, ["infer", "/no/such/file.json"])
        assert result.exit_code != 0

    def test_infer_dry_run(self, cross_project_graph):
        before = cross_project_graph.read_text()
        result = runner.invoke(link_app, ["infer", str(cross_project_graph), "--dry-run"])
        assert result.exit_code == 0
        assert "Dry run" in result.output
        after = cross_project_graph.read_text()
        assert before == after  # File unchanged

    def test_infer_saves_edges(self, cross_project_graph):
        data_before = json.loads(cross_project_graph.read_text())
        links_before = len(data_before.get("links", []))

        result = runner.invoke(link_app, ["infer", str(cross_project_graph)])
        assert result.exit_code == 0
        assert "Saved to" in result.output

        data_after = json.loads(cross_project_graph.read_text())
        links_after = len(data_after.get("links", []))
        # Should have more edges (at least env var edges)
        assert links_after > links_before


# ---------------------------------------------------------------------------
# Phase 3: Strategy Selection
# ---------------------------------------------------------------------------


class TestLinkInferStrategy:
    def test_strategy_api_only(self, cross_project_graph):
        result = runner.invoke(link_app, [
            "infer", str(cross_project_graph), "--strategy", "api", "--dry-run",
        ])
        assert result.exit_code == 0
        assert "Strategies: api" in result.output
        # Env and name should be 0
        assert "Shared env var edges: 0" in result.output
        assert "Name similarity edges: 0" in result.output

    def test_strategy_env_only(self, cross_project_graph):
        result = runner.invoke(link_app, [
            "infer", str(cross_project_graph), "--strategy", "env", "--dry-run",
        ])
        assert result.exit_code == 0
        assert "Strategies: env" in result.output
        assert "API endpoint edges: 0" in result.output
        assert "Name similarity edges: 0" in result.output

    def test_strategy_name_only(self, cross_project_graph):
        result = runner.invoke(link_app, [
            "infer", str(cross_project_graph), "--strategy", "name", "--dry-run",
        ])
        assert result.exit_code == 0
        assert "Strategies: name" in result.output
        assert "API endpoint edges: 0" in result.output
        assert "Shared env var edges: 0" in result.output

    def test_strategy_comma_separated(self, cross_project_graph):
        result = runner.invoke(link_app, [
            "infer", str(cross_project_graph), "--strategy", "api,env", "--dry-run",
        ])
        assert result.exit_code == 0
        assert "Name similarity edges: 0" in result.output

    def test_strategy_all_default(self, cross_project_graph):
        result = runner.invoke(link_app, [
            "infer", str(cross_project_graph), "--dry-run",
        ])
        assert result.exit_code == 0
        # Default should run all strategies
        assert "Strategies: api, env, name" in result.output


# ---------------------------------------------------------------------------
# Phase 2: Name Similarity Noise Reduction
# ---------------------------------------------------------------------------


class TestNameSimilarityNoise:
    def test_single_shared_token_no_edge(self, single_token_graph):
        """Nodes sharing only 1 token should NOT get a name-similarity edge."""
        data = json.loads(single_token_graph.read_text())
        edges = _infer_name_similarity_edges(data["nodes"], data["links"])
        # "payment" is the only shared token — requires 2+, so 0 edges
        assert len(edges) == 0

    def test_two_shared_tokens_creates_edge(self, two_token_graph):
        """Nodes sharing 2+ tokens should get an edge."""
        data = json.loads(two_token_graph.read_text())
        edges = _infer_name_similarity_edges(data["nodes"], data["links"])
        # "payment" + "invoice" = 2 shared tokens → edge created
        assert len(edges) >= 1
        edge = edges[0]
        assert edge["relationship"] == "RELATED_TO"
        assert edge["properties"]["inferred"] is True
        assert "payment" in edge["properties"]["shared_tokens"]
        assert "invoice" in edge["properties"]["shared_tokens"]

    def test_stoplist_filters_common_words(self, tmp_path):
        """Nodes whose only shared non-stop tokens are in the stoplist get no edges."""
        graph = {
            "directed": True, "multigraph": False,
            "graph": {"merged_from": ["x", "y"]},
            "nodes": [
                # Only shared tokens: "handler", "state" — both in stoplist
                _make_node("x/ErrorHandlerState", "ErrorHandlerState", "Class"),
                _make_node("y/StateHandlerBase", "StateHandlerBase", "Class"),
            ],
            "links": [],
        }
        edges = _infer_name_similarity_edges(graph["nodes"], graph["links"])
        assert len(edges) == 0

    def test_edge_cap_per_token(self, tmp_path):
        """Many nodes sharing tokens should be capped (max 3 per side = max 9 per token)."""
        nodes = []
        # 10 nodes in project "a" and 10 in "b" all share "invoice" + "receipt"
        for i in range(10):
            nodes.append(_make_node(f"a/InvoiceReceiptWorker{i}", f"InvoiceReceiptWorker{i}", "Class"))
            nodes.append(_make_node(f"b/ReceiptInvoiceProcessor{i}", f"ReceiptInvoiceProcessor{i}", "Class"))

        edges = _infer_name_similarity_edges(nodes, [])
        # Cap is 3 per side → max 9 pairs per project-pair, but only pairs with 2+ tokens qualify
        # With 10 nodes per project, only first 3 from each side participate → max 9
        assert len(edges) <= 9


# ---------------------------------------------------------------------------
# Integration: Merge → Infer → Verify
# ---------------------------------------------------------------------------


class TestLinkInferIntegration:
    def test_merge_then_infer_end_to_end(self, tmp_path):
        """Full chain: create 2 project KGs, merge, infer, verify saved edges."""
        # Project A: frontend with fetch call
        g_a = {
            "directed": True, "multigraph": False, "graph": {},
            "nodes": [
                _make_node("fetchPaymentInvoice", "fetchPaymentInvoice", "Function",
                           description="Calls fetch('/api/payment/invoice')"),
                _make_node("STRIPE_KEY", "STRIPE_KEY", "EnvVar"),
            ],
            "links": [],
        }
        # Project B: backend with API endpoint + same env var
        g_b = {
            "directed": True, "multigraph": False, "graph": {},
            "nodes": [
                _make_node("/api/payment/invoice", "/api/payment/invoice", "APIEndpoint"),
                _make_node("PaymentInvoiceService", "PaymentInvoiceService", "Class"),
                _make_node("STRIPE_KEY", "STRIPE_KEY", "EnvVar"),
            ],
            "links": [],
        }

        pa = tmp_path / "proj_a"
        pa.mkdir()
        (pa / "graqle.json").write_text(json.dumps(g_a))

        pb = tmp_path / "proj_b"
        pb.mkdir()
        (pb / "graqle.json").write_text(json.dumps(g_b))

        merged_path = tmp_path / "merged.json"

        # Step 1: Merge
        r1 = runner.invoke(link_app, [
            "merge", str(pa / "graqle.json"), str(pb / "graqle.json"),
            "--output", str(merged_path),
        ])
        assert r1.exit_code == 0

        # Step 2: Infer
        r2 = runner.invoke(link_app, ["infer", str(merged_path)])
        assert r2.exit_code == 0
        assert "Saved to" in r2.output

        # Step 3: Verify
        final = json.loads(merged_path.read_text())
        links = final["links"]

        # Should have at least 1 env var edge (STRIPE_KEY shared)
        env_edges = [l for l in links if l.get("relationship") == "SHARES_ENV"]
        assert len(env_edges) >= 1

        # All inferred edges should have properties.inferred = True
        inferred = [l for l in links if l.get("properties", {}).get("inferred")]
        assert len(inferred) >= 1


# ---------------------------------------------------------------------------
# Stoplist sanity check
# ---------------------------------------------------------------------------


class TestStoplist:
    def test_stoplist_is_comprehensive(self):
        """Verify the stoplist contains the expected common tokens."""
        assert "handler" in _NAME_SIMILARITY_STOPLIST
        assert "store" in _NAME_SIMILARITY_STOPLIST
        assert "state" in _NAME_SIMILARITY_STOPLIST
        assert "context" in _NAME_SIMILARITY_STOPLIST
        assert "utils" in _NAME_SIMILARITY_STOPLIST
        assert "default" in _NAME_SIMILARITY_STOPLIST

    def test_stoplist_does_not_contain_domain_words(self):
        """Domain-specific words should NOT be in the stoplist."""
        assert "onboarding" not in _NAME_SIMILARITY_STOPLIST
        assert "payment" not in _NAME_SIMILARITY_STOPLIST
        assert "invoice" not in _NAME_SIMILARITY_STOPLIST
        assert "stripe" not in _NAME_SIMILARITY_STOPLIST
