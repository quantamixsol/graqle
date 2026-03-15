"""Tests for natural language query router."""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_nl_router
# risk: LOW (impact radius: 0 modules)
# dependencies: nl_router
# constraints: none
# ── /graqle:intelligence ──

from graqle.scanner.nl_router import route_query, is_natural_language, RouteResult


class TestRouteQuery:

    def test_impact_what_depends(self):
        result = route_query("what depends on auth?")
        assert result.tool == "impact"

    def test_impact_safe_to_change(self):
        result = route_query("is it safe to change payment.py?")
        assert result.tool == "impact"

    def test_impact_what_breaks(self):
        result = route_query("what breaks if I modify the database schema?")
        assert result.tool == "impact"

    def test_preflight_before_deploy(self):
        result = route_query("before I deploy, what should I check?")
        assert result.tool == "preflight"

    def test_preflight_safety_check(self):
        result = route_query("safety check for the auth refactor")
        assert result.tool == "preflight"

    def test_lessons_what_went_wrong(self):
        result = route_query("what went wrong last time?")
        assert result.tool == "lessons"

    def test_lessons_past_mistakes(self):
        result = route_query("past mistakes with the deployment pipeline")
        assert result.tool == "lessons"

    def test_context_explain(self):
        result = route_query("explain the auth system")
        assert result.tool == "context"

    def test_context_what_is(self):
        result = route_query("what is the payment module?")
        assert result.tool == "context"

    def test_context_who_owns(self):
        result = route_query("who owns the payments module?")
        assert result.tool == "context"

    def test_inspect_stats(self):
        result = route_query("show me graph stats")
        assert result.tool == "inspect"

    def test_inspect_how_many(self):
        result = route_query("how many nodes are there?")
        assert result.tool == "inspect"

    def test_complex_falls_to_reason(self):
        result = route_query("given the auth constraints from ADR-003, how should we redesign the token flow to support multi-tenant?")
        assert result.tool == "reason"

    def test_confidence_range(self):
        result = route_query("what depends on auth?")
        assert 0.0 <= result.confidence <= 1.0

    def test_returns_original_query(self):
        q = "explain the auth system"
        result = route_query(q)
        assert result.query == q


class TestIsNaturalLanguage:

    def test_question(self):
        assert is_natural_language("what is the auth module?") is True

    def test_single_word(self):
        assert is_natural_language("auth") is False

    def test_entity_name(self):
        assert is_natural_language("auth_service") is False

    def test_two_words_not_nl(self):
        assert is_natural_language("auth service") is False

    def test_how_question(self):
        assert is_natural_language("how does the payment system work?") is True

    def test_question_mark(self):
        assert is_natural_language("tell me about auth?") is True
