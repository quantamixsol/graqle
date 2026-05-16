"""Tests for graqle.compliance.eur_lex_guard (CR-010 PR-010f — CG-MKT-06)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from graqle.compliance.eur_lex_guard import (
    DEFAULT_BASELINE_PATH,
    DriftReport,
    EurLexHash,
    USER_AGENT,
    _EUR_LEX_URL_RE,
    check_drift,
    compute_url_hash,
    enumerate_eur_lex_urls,
    load_baseline,
    refresh_baseline,
    save_baseline,
)


# ---------------------------------------------------------------------------
# URL regex
# ---------------------------------------------------------------------------


class TestEurLexUrlRegex:
    def test_matches_bare_url(self):
        text = "See https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689 for the act."
        urls = [m.group(0) for m in _EUR_LEX_URL_RE.finditer(text)]
        assert len(urls) == 1
        assert "L_202401689" in urls[0]

    def test_matches_markdown_link(self):
        text = "Refer to [the act](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689)."
        urls = [m.group(0) for m in _EUR_LEX_URL_RE.finditer(text)]
        assert len(urls) == 1

    def test_rejects_http_downgrade(self):
        text = "http://eur-lex.europa.eu/legal-content/EN/TXT/?uri=X"
        urls = [m.group(0) for m in _EUR_LEX_URL_RE.finditer(text)]
        # https only — http should NOT match
        assert urls == []

    def test_rejects_other_domains(self):
        text = "https://example.com/eur-lex"
        urls = [m.group(0) for m in _EUR_LEX_URL_RE.finditer(text)]
        assert urls == []


# ---------------------------------------------------------------------------
# enumerate_eur_lex_urls
# ---------------------------------------------------------------------------


class TestEnumerateUrls:
    def test_finds_urls_in_markdown(self, tmp_path):
        (tmp_path / "a.md").write_text(
            "Authoritative: https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=A",
            encoding="utf-8",
        )
        (tmp_path / "b.md").write_text(
            "See [B](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=B).",
            encoding="utf-8",
        )
        urls = enumerate_eur_lex_urls([tmp_path])
        assert len(urls) == 2
        # Sorted
        assert urls == sorted(urls)

    def test_dedupes_across_files(self, tmp_path):
        url = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=A"
        (tmp_path / "a.md").write_text(f"See {url}", encoding="utf-8")
        (tmp_path / "b.md").write_text(f"Also {url}", encoding="utf-8")
        urls = enumerate_eur_lex_urls([tmp_path])
        assert urls == [url]

    def test_strips_trailing_punctuation(self, tmp_path):
        (tmp_path / "a.md").write_text(
            "Refer to https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=A.",
            encoding="utf-8",
        )
        urls = enumerate_eur_lex_urls([tmp_path])
        # Trailing period stripped
        assert urls[0].endswith("=A")

    def test_nonexistent_root_returns_empty(self, tmp_path):
        urls = enumerate_eur_lex_urls([tmp_path / "no-such-dir"])
        assert urls == []

    def test_recursive_glob(self, tmp_path):
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "nested.md").write_text(
            "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=N",
            encoding="utf-8",
        )
        urls = enumerate_eur_lex_urls([tmp_path])
        assert len(urls) == 1


# ---------------------------------------------------------------------------
# compute_url_hash
# ---------------------------------------------------------------------------


class TestComputeUrlHash:
    def test_returns_sha256_hex(self):
        result = compute_url_hash(b"hello")
        assert len(result) == 64
        int(result, 16)  # valid hex

    def test_deterministic(self):
        assert compute_url_hash(b"x") == compute_url_hash(b"x")

    def test_different_inputs_different_hashes(self):
        assert compute_url_hash(b"x") != compute_url_hash(b"y")


# ---------------------------------------------------------------------------
# Baseline I/O
# ---------------------------------------------------------------------------


class TestBaselineIO:
    def test_load_baseline_missing_returns_empty(self, tmp_path):
        result = load_baseline(tmp_path / "nonexistent.json")
        assert result == {}

    def test_save_and_load_round_trip(self, tmp_path):
        baseline_path = tmp_path / "baseline.json"
        entries = [
            EurLexHash(
                url="https://eur-lex.europa.eu/X",
                sha256="a" * 64,
                fetched_at_iso="2026-05-16T00:00:00Z",
                byte_size=100,
            ),
        ]
        save_baseline(entries, baseline_path)
        assert baseline_path.exists()
        loaded = load_baseline(baseline_path)
        assert "https://eur-lex.europa.eu/X" in loaded
        assert loaded["https://eur-lex.europa.eu/X"].sha256 == "a" * 64

    def test_load_baseline_invalid_json_raises(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        with pytest.raises(ValueError, match="not valid JSON"):
            load_baseline(bad)

    def test_save_creates_parent_dir(self, tmp_path):
        baseline_path = tmp_path / "nested" / "dir" / "baseline.json"
        save_baseline([], baseline_path)
        assert baseline_path.exists()


# ---------------------------------------------------------------------------
# Drift detection (offline mode)
# ---------------------------------------------------------------------------


class TestDriftDetectionOffline:
    """Offline mode: no network — verify the baseline/docs delta logic."""

    def test_no_baseline_yet(self, tmp_path):
        # docs have URLs, baseline missing → all "missing_from_baseline"
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.md").write_text(
            "https://eur-lex.europa.eu/A", encoding="utf-8"
        )
        baseline = tmp_path / "baseline.json"
        report = check_drift(
            search_roots=[docs],
            baseline_path=baseline,
            offline=True,
        )
        assert report.n_missing_from_baseline == 1
        assert report.n_missing_from_current == 0
        assert report.has_drift is True

    def test_url_removed_from_docs(self, tmp_path):
        # baseline has URL, docs don't → "missing_from_current"
        docs = tmp_path / "docs"
        docs.mkdir()
        baseline_path = tmp_path / "baseline.json"
        save_baseline(
            [EurLexHash("https://eur-lex.europa.eu/A", "a" * 64, "t", 0)],
            baseline_path,
        )
        report = check_drift(
            search_roots=[docs],
            baseline_path=baseline_path,
            offline=True,
        )
        assert report.n_missing_from_current == 1
        assert report.has_drift is True

    def test_perfect_match_offline_reports_no_drift_from_baseline(self, tmp_path):
        # Same URL in docs + baseline → no drift IN OFFLINE MODE (skip fetch)
        url = "https://eur-lex.europa.eu/A"
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.md").write_text(url, encoding="utf-8")
        baseline_path = tmp_path / "baseline.json"
        save_baseline(
            [EurLexHash(url, "a" * 64, "t", 0)],
            baseline_path,
        )
        report = check_drift(
            search_roots=[docs],
            baseline_path=baseline_path,
            offline=True,
        )
        # n_urls_checked is 0 in offline mode (no fetches)
        assert report.n_urls_checked == 0
        assert report.has_drift is False


# ---------------------------------------------------------------------------
# Drift detection (mocked fetch)
# ---------------------------------------------------------------------------


class TestDriftDetectionMocked:
    """Verify fetch-and-compare logic with the network call mocked out."""

    def test_drift_detected_when_hash_changes(self, tmp_path):
        url = "https://eur-lex.europa.eu/A"
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.md").write_text(url, encoding="utf-8")
        baseline_path = tmp_path / "baseline.json"
        save_baseline(
            [EurLexHash(url, sha256="a" * 64, fetched_at_iso="t", byte_size=0)],
            baseline_path,
        )
        # Mock the fetch to return content whose hash != baseline's "a"*64
        with patch(
            "graqle.compliance.eur_lex_guard._fetch_url",
            return_value=b"new content",
        ):
            report = check_drift(
                search_roots=[docs],
                baseline_path=baseline_path,
                offline=False,
            )
        assert report.n_drifted == 1
        assert url in report.drifted
        assert report.has_drift is True

    def test_no_drift_when_hash_matches(self, tmp_path):
        url = "https://eur-lex.europa.eu/A"
        content = b"stable content"
        expected_hash = compute_url_hash(content)
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.md").write_text(url, encoding="utf-8")
        baseline_path = tmp_path / "baseline.json"
        save_baseline(
            [EurLexHash(url, sha256=expected_hash, fetched_at_iso="t", byte_size=len(content))],
            baseline_path,
        )
        with patch(
            "graqle.compliance.eur_lex_guard._fetch_url",
            return_value=content,
        ):
            report = check_drift(
                search_roots=[docs],
                baseline_path=baseline_path,
                offline=False,
            )
        assert report.n_drifted == 0
        assert report.n_unchanged == 1
        assert report.has_drift is False

    def test_fetch_error_counted(self, tmp_path):
        url = "https://eur-lex.europa.eu/A"
        from urllib.error import URLError
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.md").write_text(url, encoding="utf-8")
        baseline_path = tmp_path / "baseline.json"
        save_baseline(
            [EurLexHash(url, "a" * 64, "t", 0)],
            baseline_path,
        )
        with patch(
            "graqle.compliance.eur_lex_guard._fetch_url",
            side_effect=URLError("network down"),
        ):
            report = check_drift(
                search_roots=[docs],
                baseline_path=baseline_path,
                offline=False,
            )
        assert report.n_fetch_errors == 1
        assert report.has_drift is True


# ---------------------------------------------------------------------------
# Refresh baseline
# ---------------------------------------------------------------------------


class TestRefreshBaseline:
    def test_offline_writes_empty_baseline(self, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.md").write_text(
            "https://eur-lex.europa.eu/A", encoding="utf-8"
        )
        baseline_path = tmp_path / "baseline.json"
        entries, errors = refresh_baseline(
            search_roots=[docs],
            baseline_path=baseline_path,
            offline=True,
        )
        assert entries == []
        assert errors == []
        assert baseline_path.exists()

    def test_online_fetches_and_writes(self, tmp_path):
        url = "https://eur-lex.europa.eu/A"
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.md").write_text(url, encoding="utf-8")
        baseline_path = tmp_path / "baseline.json"
        with patch(
            "graqle.compliance.eur_lex_guard._fetch_url",
            return_value=b"content",
        ):
            entries, errors = refresh_baseline(
                search_roots=[docs],
                baseline_path=baseline_path,
                offline=False,
            )
        assert len(entries) == 1
        assert entries[0].url == url
        assert errors == []

    def test_per_url_errors_dont_abort_refresh(self, tmp_path):
        from urllib.error import URLError
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.md").write_text(
            "https://eur-lex.europa.eu/A https://eur-lex.europa.eu/B",
            encoding="utf-8",
        )
        baseline_path = tmp_path / "baseline.json"
        # First URL fetches OK, second errors
        responses = [b"ok", URLError("timeout")]
        def _mock_fetch(url):
            r = responses.pop(0)
            if isinstance(r, BaseException):
                raise r
            return r
        with patch(
            "graqle.compliance.eur_lex_guard._fetch_url",
            side_effect=_mock_fetch,
        ):
            entries, errors = refresh_baseline(
                search_roots=[docs],
                baseline_path=baseline_path,
                offline=False,
            )
        assert len(entries) == 1
        assert len(errors) == 1


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_user_agent_identifies_graqle(self):
        assert "GraQle" in USER_AGENT
        assert "EUR-Lex-Guard" in USER_AGENT

    def test_default_baseline_path(self):
        assert ".graqle" in DEFAULT_BASELINE_PATH
        assert "baseline" in DEFAULT_BASELINE_PATH.lower()


class TestFetchUrlDefenseInDepth:
    """Sentinel pass 2 MAJOR — _fetch_url validates URL at entry."""

    def test_rejects_non_eur_lex_url(self):
        from graqle.compliance.eur_lex_guard import _fetch_url
        with pytest.raises(ValueError, match="canonical pattern"):
            _fetch_url("https://example.com/anything")

    def test_rejects_http_downgrade(self):
        from graqle.compliance.eur_lex_guard import _fetch_url
        with pytest.raises(ValueError, match="canonical pattern"):
            _fetch_url("http://eur-lex.europa.eu/something")

    def test_rejects_empty_url(self):
        from graqle.compliance.eur_lex_guard import _fetch_url
        with pytest.raises(ValueError, match="canonical pattern"):
            _fetch_url("")


class TestDriftReport:
    def test_has_drift_false_when_clean(self):
        r = DriftReport(
            n_urls_checked=5, n_unchanged=5, n_drifted=0,
            n_missing_from_baseline=0, n_missing_from_current=0,
            n_fetch_errors=0,
        )
        assert r.has_drift is False

    def test_has_drift_true_when_drifted(self):
        r = DriftReport(
            n_urls_checked=5, n_unchanged=4, n_drifted=1,
            n_missing_from_baseline=0, n_missing_from_current=0,
            n_fetch_errors=0,
        )
        assert r.has_drift is True

    def test_to_dict_converts_fetch_errors(self):
        r = DriftReport(
            n_urls_checked=1, n_unchanged=0, n_drifted=0,
            n_missing_from_baseline=0, n_missing_from_current=0,
            n_fetch_errors=1,
            fetch_errors=(("https://eur-lex.europa.eu/X", "URLError: timeout"),),
        )
        d = r.to_dict()
        assert d["fetch_errors"] == [["https://eur-lex.europa.eu/X", "URLError: timeout"]]
