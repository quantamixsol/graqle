"""Tests for benchmark scoring functions and governance metrics."""

# ── graqle:intelligence ──
# module: tests.test_benchmarks.test_metrics
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, benchmark_runner
# constraints: none
# ── /graqle:intelligence ──


from graqle.benchmarks.benchmark_runner import (
    BenchmarkRunner,
    BenchmarkSummary,
    QuestionResult,
    _normalize_answer,
    exact_match,
    f1_score,
)

# ── Normalization ──

class TestNormalizeAnswer:
    def test_lowercase(self):
        assert _normalize_answer("Hello World") == "hello world"

    def test_strip_articles(self):
        assert _normalize_answer("the quick brown fox") == "quick brown fox"

    def test_strip_punctuation(self):
        assert _normalize_answer("hello, world!") == "hello world"

    def test_collapse_whitespace(self):
        assert _normalize_answer("  hello   world  ") == "hello world"


# ── Exact Match ──

class TestExactMatch:
    def test_identical(self):
        assert exact_match("Paris", "Paris") == 1.0

    def test_case_insensitive(self):
        assert exact_match("paris", "PARIS") == 1.0

    def test_article_stripping(self):
        assert exact_match("The Eiffel Tower", "Eiffel Tower") == 1.0

    def test_no_match(self):
        assert exact_match("London", "Paris") == 0.0


# ── Token F1 ──

class TestF1Score:
    def test_perfect(self):
        assert f1_score("hello world", "hello world") == 1.0

    def test_partial_overlap(self):
        score = f1_score("hello world foo", "hello world bar")
        assert 0.5 < score < 1.0

    def test_no_overlap(self):
        assert f1_score("abc", "xyz") == 0.0

    def test_empty_gold(self):
        assert f1_score("", "") == 1.0

    def test_empty_pred(self):
        assert f1_score("", "gold answer") == 0.0


# ── Keyword F1 / Recall ──

class TestKeywordF1:
    def test_all_found(self):
        score = BenchmarkRunner._keyword_f1(
            "Article 5 imposes a penalty of EUR 35 million", ["article 5", "penalty"]
        )
        assert score == 1.0

    def test_none_found(self):
        score = BenchmarkRunner._keyword_f1("irrelevant text", ["article 5", "penalty"])
        assert score == 0.0

    def test_partial(self):
        score = BenchmarkRunner._keyword_f1(
            "Article 5 applies here", ["article 5", "penalty"]
        )
        assert score == 0.5

    def test_empty_keywords(self):
        assert BenchmarkRunner._keyword_f1("anything", []) == 0.0

    def test_keyword_recall_alias(self):
        r1 = BenchmarkRunner._keyword_f1("Article 5", ["article 5", "penalty"])
        r2 = BenchmarkRunner._keyword_recall("Article 5", ["article 5", "penalty"])
        assert r1 == r2


# ── QuestionResult governance fields ──

class TestQuestionResultGovernance:
    def test_default_governance_fields(self):
        qr = QuestionResult(
            question_id="Q1",
            question="test",
            gold_answer="answer",
            predicted_answer="pred",
            exact_match=0.0,
            f1=0.5,
            latency_ms=100.0,
            cost_usd=0.0,
            total_tokens=50,
            convergence_rounds=2,
            active_nodes=3,
            method="graqle-pcst",
        )
        assert qr.shacl_pass == 0
        assert qr.shacl_fail == 0
        assert qr.constraint_propagations == 0
        assert qr.observer_redirects == 0
        assert qr.ontology_route_filtered == 0

    def test_governance_fields_set(self):
        qr = QuestionResult(
            question_id="Q1",
            question="test",
            gold_answer="answer",
            predicted_answer="pred",
            exact_match=0.0,
            f1=0.5,
            latency_ms=100.0,
            cost_usd=0.0,
            total_tokens=50,
            convergence_rounds=2,
            active_nodes=3,
            method="graqle-pcst",
            shacl_pass=5,
            shacl_fail=1,
            constraint_propagations=3,
            observer_redirects=2,
            ontology_route_filtered=4,
        )
        assert qr.shacl_pass == 5
        assert qr.shacl_fail == 1
        assert qr.constraint_propagations == 3

    def test_to_dict_includes_governance(self):
        qr = QuestionResult(
            question_id="Q1",
            question="test",
            gold_answer="answer",
            predicted_answer="pred",
            exact_match=0.0,
            f1=0.5,
            latency_ms=100.0,
            cost_usd=0.0,
            total_tokens=50,
            convergence_rounds=2,
            active_nodes=3,
            method="graqle-pcst",
            shacl_pass=5,
        )
        d = qr.to_dict()
        assert "shacl_pass" in d
        assert d["shacl_pass"] == 5


# ── BenchmarkSummary governance fields ──

class TestBenchmarkSummaryGovernance:
    def test_default_governance_totals(self):
        s = BenchmarkSummary(
            method="graqle-pcst",
            dataset="MultiGov-30",
            n_questions=10,
            avg_em=0.3,
            avg_f1=0.5,
            avg_latency_ms=500.0,
            avg_cost_usd=0.001,
            avg_tokens=100.0,
            avg_rounds=2.0,
            avg_nodes=4.0,
            total_cost_usd=0.01,
            total_latency_s=5.0,
        )
        assert s.total_shacl_pass == 0
        assert s.total_shacl_fail == 0
        assert s.total_constraint_propagations == 0

    def test_governance_totals_set(self):
        s = BenchmarkSummary(
            method="graqle-pcst",
            dataset="MultiGov-30",
            n_questions=10,
            avg_em=0.3,
            avg_f1=0.5,
            avg_latency_ms=500.0,
            avg_cost_usd=0.001,
            avg_tokens=100.0,
            avg_rounds=2.0,
            avg_nodes=4.0,
            total_cost_usd=0.01,
            total_latency_s=5.0,
            total_shacl_pass=20,
            total_shacl_fail=3,
            total_constraint_propagations=8,
            total_observer_redirects=5,
            total_ontology_route_filtered=12,
        )
        assert s.total_shacl_pass == 20
        assert s.total_ontology_route_filtered == 12
