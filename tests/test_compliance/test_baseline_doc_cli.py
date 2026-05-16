"""CLI tests for `graq compliance baseline-doc generate` (PR-010d AC-Q161-1+6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from graqle.cli.commands.compliance import compliance_app


runner = CliRunner()


class TestBaselineDocGenerateCLI:
    def test_jsonl_output_default(self, tmp_path):
        out = tmp_path / "baseline.jsonl"
        result = runner.invoke(
            compliance_app,
            ["baseline-doc", "generate", "--output", str(out)],
        )
        assert result.exit_code == 0, result.output
        assert out.exists()

    def test_jsonl_emits_parseable_json(self, tmp_path):
        out = tmp_path / "baseline.jsonl"
        runner.invoke(
            compliance_app,
            ["baseline-doc", "generate", "--output", str(out)],
        )
        parsed = json.loads(out.read_text(encoding="utf-8").strip())
        assert "sdk_version" in parsed
        assert "baseline_id" in parsed
        assert "quantitative_metrics" in parsed
        assert "articles_covered" in parsed

    def test_signoff_passed_through(self, tmp_path):
        out = tmp_path / "baseline.jsonl"
        result = runner.invoke(
            compliance_app,
            [
                "baseline-doc",
                "generate",
                "--output",
                str(out),
                "--signoff",
                "alice@example.com",
            ],
        )
        assert result.exit_code == 0
        parsed = json.loads(out.read_text(encoding="utf-8").strip())
        assert parsed["stakeholder_signoff"] == "alice@example.com"
        assert "alice@example.com" in result.output  # diagnostic line

    def test_unsigned_diagnostic(self, tmp_path):
        out = tmp_path / "baseline.jsonl"
        result = runner.invoke(
            compliance_app,
            ["baseline-doc", "generate", "--output", str(out)],
        )
        assert result.exit_code == 0
        assert "unsigned" in result.output

    def test_test_archive_ref_passed_through(self, tmp_path):
        out = tmp_path / "baseline.jsonl"
        ci_sha = "deadbeef" * 8  # 64 hex chars
        result = runner.invoke(
            compliance_app,
            [
                "baseline-doc",
                "generate",
                "--output",
                str(out),
                "--test-archive-ref",
                ci_sha,
            ],
        )
        assert result.exit_code == 0
        parsed = json.loads(out.read_text(encoding="utf-8").strip())
        assert parsed["test_archive_ref"] == ci_sha

    def test_invalid_format_exit_2(self, tmp_path):
        out = tmp_path / "baseline.bogus"
        result = runner.invoke(
            compliance_app,
            [
                "baseline-doc",
                "generate",
                "--output",
                str(out),
                "--format",
                "xml",
            ],
        )
        assert result.exit_code == 2
        assert "invalid" in result.output.lower()

    def test_append_mode_accumulates(self, tmp_path):
        """AC-Q161-1: JSONL is append-only — two runs = two lines."""
        out = tmp_path / "baseline.jsonl"
        runner.invoke(
            compliance_app,
            ["baseline-doc", "generate", "--output", str(out)],
        )
        runner.invoke(
            compliance_app,
            ["baseline-doc", "generate", "--output", str(out)],
        )
        lines = out.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_each_emitted_line_has_unique_timestamp(self, tmp_path):
        """Re-running yields different generated_at_iso -> different baseline_id."""
        out = tmp_path / "baseline.jsonl"
        runner.invoke(
            compliance_app,
            ["baseline-doc", "generate", "--output", str(out)],
        )
        # Small sleep to guarantee different timestamps at second granularity
        import time
        time.sleep(1.1)
        runner.invoke(
            compliance_app,
            ["baseline-doc", "generate", "--output", str(out)],
        )
        lines = out.read_text(encoding="utf-8").strip().split("\n")
        parsed1 = json.loads(lines[0])
        parsed2 = json.loads(lines[1])
        # Timestamps differ
        assert parsed1["generated_at_iso"] != parsed2["generated_at_iso"]
        # baseline_id differs (timestamp is part of the content)
        assert parsed1["baseline_id"] != parsed2["baseline_id"]

    def test_baseline_id_appears_in_diagnostic_output(self, tmp_path):
        out = tmp_path / "baseline.jsonl"
        result = runner.invoke(
            compliance_app,
            ["baseline-doc", "generate", "--output", str(out)],
        )
        # Rich console wraps tokens in ANSI colour codes; strip them
        # before substring check.
        import re as _re
        plain = _re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "baseline_id" in plain
        # And the actual hex prefix from the doc appears in the diagnostic
        parsed = json.loads(out.read_text(encoding="utf-8").strip())
        assert parsed["baseline_id"][:16] in plain
