"""Tests for ``graq compliance export`` — PR-009c.

Coverage discipline:

  * TestDateBoundParsing  — YYYY-MM-DD parsing edge cases and rejections.
  * TestSessionRangeFilter — lexical prefix comparison against session ids.
  * TestEmptyTrail        — no sessions, no audit dir → exit 0, empty out.
  * TestStdoutExport      — JSONL to stdout with various filters.
  * TestFileExport        — JSONL to file + sha256 sidecar invariants.
  * TestErrorPaths        — corrupt session JSON, unwritable output, bad dates.
  * TestSha256Sidecar     — line-for-line hash correspondence + tamper-detect.
  * TestCLIArgValidation  — typer rejects bad --since/--until/--sidecar combos.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from graqle.cli.commands.compliance import (
    _parse_iso_date_bound,
    _session_id_in_range,
    _sha256_hex,
    _stream_audit_sessions,
    compliance_app,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo_with_sessions(tmp_path: Path) -> Path:
    """Build a fake repo with three audit sessions at known dates."""
    audit_dir = tmp_path / ".graqle" / "governance" / "audit"
    audit_dir.mkdir(parents=True)
    sessions = {
        "20260801_120000": {"session_id": "20260801_120000", "task": "first", "entries": []},
        "20260815_093000": {"session_id": "20260815_093000", "task": "second", "entries": [{"tool": "graq_reason"}]},
        "20260901_181500": {"session_id": "20260901_181500", "task": "third", "entries": []},
    }
    for sid, data in sessions.items():
        (audit_dir / f"{sid}.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
    return tmp_path


# ---------------------------------------------------------------------------
# TestDateBoundParsing
# ---------------------------------------------------------------------------


class TestDateBoundParsing:
    def test_valid_iso_date_returns_yyyymmdd_prefix(self) -> None:
        assert _parse_iso_date_bound("2026-08-01", "since") == "20260801"
        assert _parse_iso_date_bound("2025-02-02", "until") == "20250202"

    def test_whitespace_tolerated(self) -> None:
        assert _parse_iso_date_bound("  2026-08-01  ", "since") == "20260801"

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "2026/08/01",
            "26-08-01",         # wrong year width
            "2026-8-01",        # wrong month padding
            "2026-08-1",        # wrong day padding
            "abcd-ef-gh",
            "2026-13-01",       # month out of range
            "2026-00-01",       # month zero
            "2026-08-32",       # day out of range
            "2026-08-00",       # day zero
            "2026-08",          # too few parts
            "2026-08-01-extra", # too many parts
            "2026-02-31",       # impossible calendar date (Feb 31)
            "2026-04-31",       # impossible calendar date (Apr 31)
            "2025-02-29",       # non-leap-year Feb 29
        ],
    )
    def test_malformed_input_raises_bad_parameter(self, bad: str) -> None:
        import typer
        with pytest.raises(typer.BadParameter):
            _parse_iso_date_bound(bad, "since")

    def test_leap_year_feb_29_accepted(self) -> None:
        """Calendar correctness: 2024-02-29 IS a valid date (leap year)."""
        assert _parse_iso_date_bound("2024-02-29", "since") == "20240229"


# ---------------------------------------------------------------------------
# TestSessionRangeFilter
# ---------------------------------------------------------------------------


class TestSessionRangeFilter:
    def test_no_bounds_accepts_everything(self) -> None:
        assert _session_id_in_range("20260801_120000", None, None) is True
        assert _session_id_in_range("19990101_000000", None, None) is True

    def test_since_bound_is_inclusive(self) -> None:
        assert _session_id_in_range("20260801_000000", "20260801", None) is True
        assert _session_id_in_range("20260801_235959", "20260801", None) is True
        assert _session_id_in_range("20260731_235959", "20260801", None) is False

    def test_until_bound_is_inclusive(self) -> None:
        assert _session_id_in_range("20260815_120000", None, "20260815") is True
        assert _session_id_in_range("20260816_000000", None, "20260815") is False

    def test_both_bounds_combined(self) -> None:
        assert _session_id_in_range("20260815_120000", "20260801", "20260831") is True
        assert _session_id_in_range("20260731_120000", "20260801", "20260831") is False
        assert _session_id_in_range("20260901_120000", "20260801", "20260831") is False

    def test_non_canonical_session_id_excluded(self) -> None:
        """Legacy session ids without YYYYMMDD prefix are skipped."""
        assert _session_id_in_range("legacy_session", None, None) is False
        assert _session_id_in_range("abc123", None, None) is False
        # Too short
        assert _session_id_in_range("2026080", None, None) is False


# ---------------------------------------------------------------------------
# TestSymlinkHardening
# ---------------------------------------------------------------------------


class TestSymlinkHardening:
    def test_symlinks_in_audit_dir_are_skipped(self, tmp_path: Path) -> None:
        """Audit trail is append-only on REAL files. Symlinks are skipped.

        A symlink in the audit dir is either an admin mistake or an
        attempt to inject foreign content; refusing to follow is the
        safe default for Article-12 integrity.
        """
        import os
        audit_dir = tmp_path / ".graqle" / "governance" / "audit"
        audit_dir.mkdir(parents=True)

        # One real session.
        real_data = {"session_id": "20260801_120000", "task": "real", "entries": []}
        (audit_dir / "20260801_120000.json").write_text(
            json.dumps(real_data, indent=2), encoding="utf-8"
        )

        # A foreign target outside the audit dir.
        foreign = tmp_path / "foreign.json"
        foreign.write_text(
            json.dumps({"session_id": "20260815_999999", "task": "INJECTED", "entries": []}),
            encoding="utf-8",
        )

        # Try to inject via symlink in the audit dir.
        symlink_path = audit_dir / "20260815_999999.json"
        try:
            os.symlink(foreign, symlink_path)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation not supported on this platform/permissions")

        # Run export — only the real session should appear.
        sessions = list(
            _stream_audit_sessions(audit_dir, None, None)
        )
        assert len(sessions) == 1
        sid, line = sessions[0]
        assert sid == "20260801_120000"
        assert "INJECTED" not in line


# ---------------------------------------------------------------------------
# TestEmptyTrail
# ---------------------------------------------------------------------------


class TestEmptyTrail:
    def test_missing_audit_dir_yields_nothing(self, tmp_path: Path) -> None:
        sessions = list(
            _stream_audit_sessions(tmp_path / "does-not-exist", None, None)
        )
        assert sessions == []

    def test_export_to_stdout_with_no_sessions_is_empty(
        self, tmp_path: Path
    ) -> None:
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            ["export", "--repo-root", str(tmp_path)],
        )
        assert result.exit_code == 0, result.output
        # Stdout output is the JSONL; should be empty (no sessions).
        # Rich console output is captured separately by typer testing.
        assert "{" not in result.stdout  # no JSONL lines


# ---------------------------------------------------------------------------
# TestStdoutExport
# ---------------------------------------------------------------------------


class TestStdoutExport:
    def test_export_all_sessions_to_stdout(self, repo_with_sessions: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            ["export", "--repo-root", str(repo_with_sessions)],
        )
        assert result.exit_code == 0, result.output
        lines = [l for l in result.stdout.strip().split("\n") if l]
        assert len(lines) == 3
        for line in lines:
            payload = json.loads(line)
            assert "session_id" in payload

    def test_since_filter_excludes_earlier_sessions(
        self, repo_with_sessions: Path
    ) -> None:
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            [
                "export",
                "--since", "2026-08-15",
                "--repo-root", str(repo_with_sessions),
            ],
        )
        assert result.exit_code == 0, result.output
        lines = [l for l in result.stdout.strip().split("\n") if l]
        # 20260801 excluded; 20260815 + 20260901 included.
        assert len(lines) == 2

    def test_until_filter_excludes_later_sessions(
        self, repo_with_sessions: Path
    ) -> None:
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            [
                "export",
                "--until", "2026-08-31",
                "--repo-root", str(repo_with_sessions),
            ],
        )
        assert result.exit_code == 0, result.output
        lines = [l for l in result.stdout.strip().split("\n") if l]
        # 20260801 + 20260815 included; 20260901 excluded.
        assert len(lines) == 2

    def test_since_until_window_extracts_one_session(
        self, repo_with_sessions: Path
    ) -> None:
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            [
                "export",
                "--since", "2026-08-10",
                "--until", "2026-08-20",
                "--repo-root", str(repo_with_sessions),
            ],
        )
        assert result.exit_code == 0, result.output
        lines = [l for l in result.stdout.strip().split("\n") if l]
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["session_id"] == "20260815_093000"


# ---------------------------------------------------------------------------
# TestFileExport
# ---------------------------------------------------------------------------


class TestFileExport:
    def test_export_to_file_writes_jsonl(
        self, repo_with_sessions: Path, tmp_path: Path
    ) -> None:
        out_file = tmp_path / "evidence.jsonl"
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            [
                "export",
                "--output", str(out_file),
                "--repo-root", str(repo_with_sessions),
            ],
        )
        assert result.exit_code == 0, result.output
        assert out_file.exists()
        lines = [l for l in out_file.read_text(encoding="utf-8").strip().split("\n") if l]
        assert len(lines) == 3
        for line in lines:
            json.loads(line)  # parses

    def test_export_creates_parent_directories(
        self, repo_with_sessions: Path, tmp_path: Path
    ) -> None:
        out_file = tmp_path / "deep" / "nested" / "evidence.jsonl"
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            [
                "export",
                "--output", str(out_file),
                "--repo-root", str(repo_with_sessions),
            ],
        )
        assert result.exit_code == 0, result.output
        assert out_file.exists()

    def test_export_to_file_succeeds_with_zero_sessions(
        self, tmp_path: Path
    ) -> None:
        out_file = tmp_path / "empty.jsonl"
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            [
                "export",
                "--output", str(out_file),
                "--repo-root", str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output
        assert out_file.exists()
        # Empty file or single empty line.
        assert out_file.read_text(encoding="utf-8") == ""


# ---------------------------------------------------------------------------
# TestSha256Sidecar
# ---------------------------------------------------------------------------


class TestSha256Sidecar:
    def test_sidecar_has_one_hash_per_jsonl_line(
        self, repo_with_sessions: Path, tmp_path: Path
    ) -> None:
        out_file = tmp_path / "evidence.jsonl"
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            [
                "export",
                "--output", str(out_file),
                "--sha256-sidecar",
                "--repo-root", str(repo_with_sessions),
            ],
        )
        assert result.exit_code == 0, result.output
        sidecar = out_file.with_suffix(out_file.suffix + ".sha256")
        assert sidecar.exists()
        sidecar_lines = [l for l in sidecar.read_text(encoding="utf-8").strip().split("\n") if l]
        jsonl_lines = [l for l in out_file.read_text(encoding="utf-8").strip().split("\n") if l]
        assert len(sidecar_lines) == len(jsonl_lines) == 3

    def test_sidecar_hashes_are_valid_sha256(
        self, repo_with_sessions: Path, tmp_path: Path
    ) -> None:
        out_file = tmp_path / "evidence.jsonl"
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            [
                "export",
                "--output", str(out_file),
                "--sha256-sidecar",
                "--repo-root", str(repo_with_sessions),
            ],
        )
        assert result.exit_code == 0
        sidecar = out_file.with_suffix(out_file.suffix + ".sha256")
        for h in sidecar.read_text(encoding="utf-8").strip().split("\n"):
            if h:
                # Each line is 64 hex chars.
                assert len(h) == 64
                int(h, 16)  # validates hex

    def test_sidecar_hash_matches_line_byte_for_byte(
        self, repo_with_sessions: Path, tmp_path: Path
    ) -> None:
        """Tamper-detection invariant: re-hashing each line must reproduce the sidecar."""
        out_file = tmp_path / "evidence.jsonl"
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            [
                "export",
                "--output", str(out_file),
                "--sha256-sidecar",
                "--repo-root", str(repo_with_sessions),
            ],
        )
        assert result.exit_code == 0
        sidecar = out_file.with_suffix(out_file.suffix + ".sha256")
        jsonl_lines = [l for l in out_file.read_text(encoding="utf-8").strip().split("\n") if l]
        sidecar_lines = [l for l in sidecar.read_text(encoding="utf-8").strip().split("\n") if l]
        for line, expected_hash in zip(jsonl_lines, sidecar_lines):
            actual = hashlib.sha256(line.encode("utf-8")).hexdigest()
            assert actual == expected_hash, (
                f"Hash mismatch — sidecar tampered or export non-deterministic"
            )

    def test_sha256_hex_helper_is_correct(self) -> None:
        assert _sha256_hex("hello") == (
            "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        )

    def test_sidecar_without_output_file_exits_2(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            [
                "export",
                "--sha256-sidecar",
                "--repo-root", str(tmp_path),
            ],
        )
        assert result.exit_code == 2, result.output


# ---------------------------------------------------------------------------
# TestErrorPaths
# ---------------------------------------------------------------------------


class TestErrorPaths:
    def test_corrupt_session_json_exits_3(self, tmp_path: Path) -> None:
        audit_dir = tmp_path / ".graqle" / "governance" / "audit"
        audit_dir.mkdir(parents=True)
        (audit_dir / "20260801_120000.json").write_text(
            "{this is not valid json", encoding="utf-8"
        )
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            ["export", "--repo-root", str(tmp_path)],
        )
        assert result.exit_code == 3, result.output

    def test_bad_since_format_exits_2(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            [
                "export",
                "--since", "not-a-date",
                "--repo-root", str(tmp_path),
            ],
        )
        assert result.exit_code == 2, result.output

    def test_since_after_until_exits_2(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            [
                "export",
                "--since", "2026-09-01",
                "--until", "2026-08-01",
                "--repo-root", str(tmp_path),
            ],
        )
        assert result.exit_code == 2, result.output


# ---------------------------------------------------------------------------
# TestDeterminism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_input_produces_identical_output(
        self, repo_with_sessions: Path, tmp_path: Path
    ) -> None:
        """Article-12 evidence integrity: re-exporting the same input must
        produce byte-identical output. Customers depend on this for archival."""
        out1 = tmp_path / "a.jsonl"
        out2 = tmp_path / "b.jsonl"
        runner = CliRunner()
        r1 = runner.invoke(compliance_app, ["export", "--output", str(out1), "--repo-root", str(repo_with_sessions)])
        r2 = runner.invoke(compliance_app, ["export", "--output", str(out2), "--repo-root", str(repo_with_sessions)])
        assert r1.exit_code == 0 and r2.exit_code == 0
        assert out1.read_bytes() == out2.read_bytes()

    def test_sort_keys_ensures_stable_field_order(
        self, repo_with_sessions: Path, tmp_path: Path
    ) -> None:
        """Even if a session dict has fields in random order on disk, the
        export must sort keys deterministically with no-whitespace separators."""
        out_file = tmp_path / "evidence.jsonl"
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            ["export", "--output", str(out_file), "--repo-root", str(repo_with_sessions)],
        )
        assert result.exit_code == 0
        for line in out_file.read_text(encoding="utf-8").strip().split("\n"):
            if not line:
                continue
            data = json.loads(line)
            # Verify canonical form: sort_keys + compact separators.
            assert json.dumps(data, sort_keys=True, separators=(",", ":")) == line

    def test_canonical_form_has_no_unnecessary_whitespace(
        self, repo_with_sessions: Path, tmp_path: Path
    ) -> None:
        """Canonical form invariant: no spaces after ',' or ':'.

        This is what makes the export stable across re-runs even when
        the on-disk JSON files have varying indentation.
        """
        out_file = tmp_path / "evidence.jsonl"
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            ["export", "--output", str(out_file), "--repo-root", str(repo_with_sessions)],
        )
        assert result.exit_code == 0
        for line in out_file.read_text(encoding="utf-8").strip().split("\n"):
            if not line:
                continue
            # No ", " or ": " sequences in the canonical form.
            assert ", " not in line, (
                "Canonical form must use no-whitespace separators."
            )
            assert ": " not in line, (
                "Canonical form must use no-whitespace separators."
            )
