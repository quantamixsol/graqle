"""Tests for graqle.scanner.linker — auto-linking pipeline."""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_linker
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, pytest, linker
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import pytest

from graqle.scanner.linker import (
    AutoLinker,
    LinkingResult,
    ProposedEdge,
    _normalise,
    _token_overlap_score,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def code_nodes() -> list[dict]:
    """Representative set of code nodes."""
    return [
        {"id": "auth_service.py", "label": "AuthService", "entity_type": "MODULE", "description": "Handles JWT authentication"},
        {"id": "src/payments/handler.py", "label": "PaymentHandler", "entity_type": "MODULE", "description": "Payment processing"},
        {"id": "validate_token", "label": "validate_token", "entity_type": "FUNCTION", "description": "Validates JWT tokens"},
        {"id": "UserModel", "label": "UserModel", "entity_type": "CLASS", "description": "User database model"},
        {"id": "config.yaml", "label": "config.yaml", "entity_type": "FILE", "description": "Application configuration"},
        {"id": "db_connection", "label": "DatabaseConnection", "entity_type": "SERVICE", "description": "PostgreSQL connection pool"},
    ]


@pytest.fixture
def doc_nodes_with_refs() -> list[dict]:
    """Document nodes that reference code entities."""
    return [
        {
            "id": "doc::arch.md",
            "label": "Architecture Guide",
            "entity_type": "DOCUMENT",
            "description": "The auth_service.py module handles all JWT authentication. The validate_token function is called on every request.",
        },
        {
            "id": "sec::arch.md::Payments",
            "label": "Payments",
            "entity_type": "SECTION",
            "description": "Payment processing is handled by src/payments/handler.py which connects to the db_connection service.",
        },
    ]


@pytest.fixture
def doc_nodes_fuzzy() -> list[dict]:
    """Document nodes with fuzzy references (not exact matches)."""
    return [
        {
            "id": "doc::design.md",
            "label": "Design Doc",
            "entity_type": "DOCUMENT",
            "description": "The authentication service validates tokens using JWT. Users are stored in a database model.",
        },
    ]


@pytest.fixture
def doc_nodes_no_refs() -> list[dict]:
    """Document nodes with no code references."""
    return [
        {
            "id": "doc::license.md",
            "label": "License",
            "entity_type": "DOCUMENT",
            "description": "MIT License. Copyright 2026.",
        },
    ]


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


class TestNormalise:
    def test_camel_case(self) -> None:
        tokens = _normalise("AuthService")
        assert "auth" in tokens
        assert "service" in tokens

    def test_snake_case(self) -> None:
        tokens = _normalise("auth_service")
        assert "auth" in tokens
        assert "service" in tokens

    def test_path(self) -> None:
        tokens = _normalise("src/payments/handler.py")
        assert "payments" in tokens
        assert "handler" in tokens
        assert "handler.py" in tokens

    def test_short_tokens_filtered(self) -> None:
        tokens = _normalise("a")
        # Single char should be excluded
        assert "a" not in tokens

    def test_kebab_case(self) -> None:
        tokens = _normalise("my-component")
        assert "my" in tokens
        assert "component" in tokens


class TestTokenOverlap:
    def test_identical_sets(self) -> None:
        s = {"auth", "service"}
        assert _token_overlap_score(s, s) == 1.0

    def test_partial_overlap(self) -> None:
        a = {"auth", "service"}
        b = {"auth", "handler"}
        score = _token_overlap_score(a, b)
        assert 0.0 < score < 1.0

    def test_no_overlap(self) -> None:
        a = {"auth", "service"}
        b = {"payment", "handler"}
        assert _token_overlap_score(a, b) == 0.0

    def test_empty_set(self) -> None:
        assert _token_overlap_score(set(), {"a"}) == 0.0
        assert _token_overlap_score({"a"}, set()) == 0.0


# ---------------------------------------------------------------------------
# Exact matching
# ---------------------------------------------------------------------------


class TestExactMatch:
    def test_finds_verbatim_id(self, code_nodes: list, doc_nodes_with_refs: list) -> None:
        linker = AutoLinker(exact=True, fuzzy=False)
        result = linker.link(doc_nodes_with_refs, code_nodes)
        exact_edges = [e for e in result.accepted if e.method == "exact"]
        target_ids = {e.target_id for e in exact_edges}
        assert "auth_service.py" in target_ids
        assert "validate_token" in target_ids

    def test_finds_path_reference(self, code_nodes: list, doc_nodes_with_refs: list) -> None:
        linker = AutoLinker(exact=True, fuzzy=False)
        result = linker.link(doc_nodes_with_refs, code_nodes)
        exact_edges = [e for e in result.accepted if e.method == "exact"]
        target_ids = {e.target_id for e in exact_edges}
        assert "src/payments/handler.py" in target_ids

    def test_no_false_positives(self, code_nodes: list, doc_nodes_no_refs: list) -> None:
        linker = AutoLinker(exact=True, fuzzy=False)
        result = linker.link(doc_nodes_no_refs, code_nodes)
        assert len(result.accepted) == 0

    def test_exact_edge_confidence_is_1(self, code_nodes: list, doc_nodes_with_refs: list) -> None:
        linker = AutoLinker(exact=True, fuzzy=False)
        result = linker.link(doc_nodes_with_refs, code_nodes)
        for edge in result.accepted:
            assert edge.confidence == 1.0

    def test_short_ids_ignored(self) -> None:
        """IDs shorter than 3 chars should be ignored to prevent false matches."""
        linker = AutoLinker(exact=True, fuzzy=False)
        code = [{"id": "db", "label": "DB", "entity_type": "SERVICE"}]
        docs = [{"id": "doc::x.md", "label": "X", "entity_type": "DOCUMENT",
                 "description": "The db service handles everything."}]
        result = linker.link(docs, code)
        assert len(result.accepted) == 0


# ---------------------------------------------------------------------------
# Fuzzy matching
# ---------------------------------------------------------------------------


class TestFuzzyMatch:
    def test_fuzzy_finds_related(self, code_nodes: list, doc_nodes_fuzzy: list) -> None:
        linker = AutoLinker(exact=False, fuzzy=True, fuzzy_threshold=0.3)
        result = linker.link(doc_nodes_fuzzy, code_nodes)
        fuzzy_edges = [e for e in result.accepted if e.method == "fuzzy"]
        # Should find some fuzzy matches (auth/token related)
        assert len(fuzzy_edges) > 0

    def test_fuzzy_respects_threshold(self, code_nodes: list, doc_nodes_fuzzy: list) -> None:
        # Very high threshold should reject weak matches
        linker = AutoLinker(exact=False, fuzzy=True, fuzzy_threshold=0.99)
        result = linker.link(doc_nodes_fuzzy, code_nodes)
        fuzzy_accepted = [e for e in result.accepted if e.method == "fuzzy"]
        # Should have very few or no accepted fuzzy edges
        assert len(fuzzy_accepted) <= 1

    def test_fuzzy_confidence_range(self, code_nodes: list, doc_nodes_fuzzy: list) -> None:
        linker = AutoLinker(exact=False, fuzzy=True, fuzzy_threshold=0.3)
        result = linker.link(doc_nodes_fuzzy, code_nodes)
        for edge in result.proposed:
            if edge.method == "fuzzy":
                assert 0.0 <= edge.confidence <= 1.0


# ---------------------------------------------------------------------------
# Combined pipeline
# ---------------------------------------------------------------------------


class TestCombinedPipeline:
    def test_exact_plus_fuzzy(self, code_nodes: list, doc_nodes_with_refs: list) -> None:
        linker = AutoLinker(exact=True, fuzzy=True)
        result = linker.link(doc_nodes_with_refs, code_nodes)
        assert len(result.accepted) > 0
        methods = {e.method for e in result.accepted}
        assert "exact" in methods

    def test_deduplication(self, code_nodes: list, doc_nodes_with_refs: list) -> None:
        """Same (source, target) from exact and fuzzy should keep highest confidence."""
        linker = AutoLinker(exact=True, fuzzy=True, fuzzy_threshold=0.3)
        result = linker.link(doc_nodes_with_refs, code_nodes)
        # Check no duplicate (source, target) pairs
        pairs = [(e.source_id, e.target_id) for e in result.accepted]
        assert len(pairs) == len(set(pairs))

    def test_both_disabled(self, code_nodes: list, doc_nodes_with_refs: list) -> None:
        linker = AutoLinker(exact=False, fuzzy=False)
        result = linker.link(doc_nodes_with_refs, code_nodes)
        assert len(result.proposed) == 0

    def test_empty_doc_nodes(self, code_nodes: list) -> None:
        linker = AutoLinker()
        result = linker.link([], code_nodes)
        assert len(result.proposed) == 0

    def test_empty_code_nodes(self, doc_nodes_with_refs: list) -> None:
        linker = AutoLinker()
        result = linker.link(doc_nodes_with_refs, [])
        assert len(result.proposed) == 0


# ---------------------------------------------------------------------------
# Per-doc edge limit
# ---------------------------------------------------------------------------


class TestEdgeLimits:
    def test_max_edges_per_doc(self) -> None:
        # Create many code nodes
        code = [{"id": f"node_{i}", "label": f"node_{i}", "entity_type": "MODULE"} for i in range(100)]
        # Doc that mentions all of them
        text = " ".join(f"node_{i}" for i in range(100))
        docs = [{"id": "doc::x.md", "label": "X", "entity_type": "DOCUMENT", "description": text}]

        linker = AutoLinker(exact=True, fuzzy=False, max_edges_per_doc=5)
        result = linker.link(docs, code)
        # Should not exceed the limit
        assert len(result.accepted) <= 5


# ---------------------------------------------------------------------------
# doc_texts parameter
# ---------------------------------------------------------------------------


class TestDocTexts:
    def test_doc_texts_override(self, code_nodes: list) -> None:
        """When doc_texts is provided, it should be used instead of description."""
        docs = [{"id": "doc::x.md", "label": "X", "entity_type": "DOCUMENT",
                 "description": "Nothing relevant here"}]
        doc_texts = {"doc::x.md": "The auth_service.py module handles authentication."}

        linker = AutoLinker(exact=True, fuzzy=False)
        result = linker.link(docs, code_nodes, doc_texts=doc_texts)
        assert any(e.target_id == "auth_service.py" for e in result.accepted)


# ---------------------------------------------------------------------------
# LinkingResult / ProposedEdge
# ---------------------------------------------------------------------------


class TestDataStructures:
    def test_proposed_edge_fields(self) -> None:
        edge = ProposedEdge(
            source_id="doc::x",
            target_id="auth.py",
            relation="REFERENCED_IN",
            confidence=0.95,
            method="exact",
            evidence="Found verbatim",
        )
        assert edge.source_id == "doc::x"
        assert edge.confidence == 0.95

    def test_linking_result_stats(self) -> None:
        r = LinkingResult()
        r.stats["exact"] = 3
        r.stats["fuzzy"] = 2
        assert r.stats["exact"] == 3

    def test_relation_inference(self, code_nodes: list, doc_nodes_with_refs: list) -> None:
        """Edges should have valid relationship types."""
        linker = AutoLinker(exact=True, fuzzy=False)
        result = linker.link(doc_nodes_with_refs, code_nodes)
        for edge in result.accepted:
            assert edge.relation in (
                "REFERENCED_IN", "DESCRIBES", "DECIDED_BY",
                "CONSTRAINED_BY", "IMPLEMENTS", "SECTION_OF",
                "OWNED_BY", "SUPERSEDES", "DEPENDS_ON_DOC",
            )
