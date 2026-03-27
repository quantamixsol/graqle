"""
tests/test_generation/test_types.py
T1.1 — Unit tests for GenerationRequest, CodeGenerationResult, DiffPatch.
8 tests — all pure Python, no I/O, no LLM calls.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from graqle.core.generation import CodeGenerationResult, DiffPatch, GenerationRequest


# ─── DiffPatch ────────────────────────────────────────────────────────────────

class TestDiffPatch:
    def test_fields_stored(self) -> None:
        patch = DiffPatch(
            file_path="graqle/cloud/sync_engine.py",
            unified_diff="--- a/graqle/cloud/sync_engine.py\n+++ b/...\n@@ -1,1 +1,2 @@\n+# added\n",
            lines_added=1,
            lines_removed=0,
            preview="@@ -1,1 +1,2 @@",
        )
        assert patch.file_path == "graqle/cloud/sync_engine.py"
        assert patch.lines_added == 1
        assert patch.lines_removed == 0
        assert patch.preview == "@@ -1,1 +1,2 @@"

    def test_unified_diff_is_string(self) -> None:
        patch = DiffPatch(
            file_path="foo.py",
            unified_diff="--- a/foo.py\n+++ b/foo.py\n",
            lines_added=0,
            lines_removed=0,
            preview="",
        )
        assert isinstance(patch.unified_diff, str)


# ─── GenerationRequest ────────────────────────────────────────────────────────

class TestGenerationRequest:
    def test_defaults(self) -> None:
        req = GenerationRequest(description="add a docstring")
        assert req.file_path == ""
        assert req.max_rounds == 2
        assert req.dry_run is False
        assert req.backend == ""

    def test_explicit_values(self) -> None:
        req = GenerationRequest(
            description="refactor SyncEngine",
            file_path="graqle/cloud/sync_engine.py",
            max_rounds=3,
            dry_run=True,
            backend="anthropic",
        )
        assert req.file_path == "graqle/cloud/sync_engine.py"
        assert req.max_rounds == 3
        assert req.dry_run is True
        assert req.backend == "anthropic"


# ─── CodeGenerationResult ─────────────────────────────────────────────────────

def _make_result(**overrides: object) -> CodeGenerationResult:
    defaults: dict = dict(
        query="add a docstring to SyncEngine",
        answer="Added docstring to SyncEngine class.",
        confidence=0.87,
        rounds_completed=1,
        active_nodes=["SyncEngine", "sync_engine_module"],
        cost_usd=0.002,
        latency_ms=1234.5,
    )
    defaults.update(overrides)
    return CodeGenerationResult(**defaults)  # type: ignore[arg-type]


class TestCodeGenerationResult:
    def test_node_count_property(self) -> None:
        result = _make_result()
        assert result.node_count == 2

    def test_total_lines_added_no_patches(self) -> None:
        result = _make_result()
        assert result.total_lines_added == 0
        assert result.total_lines_removed == 0

    def test_total_lines_with_patches(self) -> None:
        patches = [
            DiffPatch("a.py", "diff", 3, 1, ""),
            DiffPatch("b.py", "diff", 5, 2, ""),
        ]
        result = _make_result(patches=patches)
        assert result.total_lines_added == 8
        assert result.total_lines_removed == 3

    def test_to_dict_keys(self) -> None:
        result = _make_result()
        d = result.to_dict()
        expected_keys = {
            "query", "answer", "confidence", "rounds_completed",
            "active_nodes", "node_count", "cost_usd", "latency_ms",
            "patches", "files_affected", "total_lines_added",
            "total_lines_removed", "timestamp", "backend_status",
            "backend_error", "dry_run", "metadata",
        }
        assert expected_keys.issubset(d.keys())

    def test_to_dict_patches_serialised(self) -> None:
        patch = DiffPatch("foo.py", "--- a\n+++ b\n", 1, 0, "@@")
        result = _make_result(patches=[patch])
        d = result.to_dict()
        assert len(d["patches"]) == 1
        assert d["patches"][0]["file_path"] == "foo.py"
        assert d["patches"][0]["lines_added"] == 1

    def test_timestamp_is_datetime(self) -> None:
        result = _make_result()
        assert isinstance(result.timestamp, datetime)

    def test_dry_run_default_false(self) -> None:
        result = _make_result()
        assert result.dry_run is False

    def test_backend_status_default(self) -> None:
        result = _make_result()
        assert result.backend_status == "ok"
        assert result.backend_error is None
