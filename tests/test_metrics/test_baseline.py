# V-SAVINGS-BASELINE-NATIVE-002: new test file via native Write (S-010).
"""Tests for graqle.metrics.baseline — the measured tokens-saved baseline."""

from __future__ import annotations

import pytest

from graqle.metrics import baseline as bl


class _Node:
    def __init__(self, props):
        self.properties = props


@pytest.fixture(autouse=True)
def _clear_cache():
    bl.reset_cache()
    yield
    bl.reset_cache()


def _write(tmp_path, name, chars):
    p = tmp_path / name
    p.write_text("x" * chars, encoding="utf-8")
    return str(p)


def test_measured_file_uses_real_token_count(tmp_path):
    path = _write(tmp_path, "mod.py", 8000)  # ~2000 tokens at 4 chars/token
    tokens, method = bl.baseline_for_node(_Node({"file_path": path}))
    assert method == "measured_file"
    assert tokens == pytest.approx(2000, abs=1)


def test_alternate_property_keys(tmp_path):
    path = _write(tmp_path, "s.py", 400)
    assert bl.baseline_for_node(_Node({"source_file": path}))[1] == "measured_file"
    bl.reset_cache()
    assert bl.baseline_for_node(_Node({"path": path}))[1] == "measured_file"


def test_no_path_falls_back_calibrated():
    tokens, method = bl.baseline_for_node(_Node({}))
    assert method == "calibrated_fallback"
    assert tokens == bl.CALIBRATED_FALLBACK_TOKENS


def test_missing_file_falls_back_and_never_raises():
    tokens, method = bl.baseline_for_node(_Node({"file_path": "/no/such/file.py"}))
    assert method == "calibrated_fallback"
    assert tokens == bl.CALIBRATED_FALLBACK_TOKENS


def test_non_dict_properties_falls_back():
    class Weird:
        properties = "not-a-dict"

    assert bl.baseline_for_node(Weird())[1] == "calibrated_fallback"


def test_blank_path_value_falls_back():
    assert bl.baseline_for_node(_Node({"file_path": "   "}))[1] == "calibrated_fallback"


def test_huge_file_is_capped(tmp_path):
    # A vendored/generated file must not dominate the headline.
    path = _write(tmp_path, "huge.py", bl.MAX_BASELINE_TOKENS * 4 * 5)
    tokens, method = bl.baseline_for_node(_Node({"file_path": path}))
    assert method == "measured_file"
    assert tokens == bl.MAX_BASELINE_TOKENS


def test_cache_avoids_re_reading(tmp_path, monkeypatch):
    path = _write(tmp_path, "c.py", 400)
    assert bl.baseline_for_node(_Node({"file_path": path})) == (100, "measured_file")
    # Now make Path.stat blow up — the cached result must still be returned
    # (no second filesystem hit).
    monkeypatch.setattr(
        bl.Path, "stat", lambda self, *a, **k: (_ for _ in ()).throw(OSError("boom"))
    )
    tokens, method = bl.baseline_for_node(_Node({"file_path": path}))
    assert method == "measured_file" and tokens == 100  # served from cache


def test_stat_oserror_falls_back(tmp_path, monkeypatch):
    # File exists (is_file True) but stat() raises (e.g. permission) → fail-safe.
    path = _write(tmp_path, "perm.py", 400)
    bl.reset_cache()
    monkeypatch.setattr(
        bl.Path, "stat", lambda self, *a, **k: (_ for _ in ()).throw(OSError("EACCES"))
    )
    tokens, method = bl.baseline_for_node(_Node({"file_path": path}))
    assert method == "calibrated_fallback" and tokens == bl.CALIBRATED_FALLBACK_TOKENS


def test_directory_path_is_not_a_file(tmp_path):
    assert bl.baseline_for_node(_Node({"file_path": str(tmp_path)}))[1] == "calibrated_fallback"


# ---- engine wiring: baseline provenance in the summary ----

def test_engine_summary_reports_measured_fraction(tmp_path):
    from graqle.metrics.engine import MetricsEngine

    eng = MetricsEngine(metrics_dir=tmp_path)
    eng.note_baseline_method("measured_file")
    eng.note_baseline_method("measured_file")
    eng.note_baseline_method("measured_file")
    eng.note_baseline_method("calibrated_fallback")
    s = eng.get_summary()
    assert s["baseline_measured_loads"] == 3
    assert s["baseline_fallback_loads"] == 1
    assert s["baseline_measured_pct"] == 75.0


def test_engine_summary_baseline_pct_zero_safe(tmp_path):
    from graqle.metrics.engine import MetricsEngine

    eng = MetricsEngine(metrics_dir=tmp_path)
    assert eng.get_summary()["baseline_measured_pct"] == 0.0  # no div-by-zero


def test_record_context_load_uses_measured_baseline(tmp_path):
    # End-to-end: a measured baseline of 5000 with 500 returned saves 4500.
    from graqle.metrics.engine import MetricsEngine

    eng = MetricsEngine(metrics_dir=tmp_path)
    eng.record_context_load("svc", tokens_returned=500, tokens_without=5000)
    assert eng.tokens_saved == 4500


def test_cache_is_bounded(tmp_path, monkeypatch):
    # When the cache is at capacity, new measurements still return correctly but
    # are not stored (no unbounded growth).
    monkeypatch.setattr(bl, "_CACHE_MAX", 0)
    bl.reset_cache()
    path = _write(tmp_path, "b.py", 800)
    tokens, method = bl.baseline_for_node(_Node({"file_path": path}))
    assert (tokens, method) == (200, "measured_file")
    assert path not in bl._file_token_cache  # not cached (cap reached)
