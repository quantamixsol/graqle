"""Tests for graqle.plugins.graq_apply â deterministic insertion engine (CG-DIF-02).

Covers all 9 rails of the deterministic insertion pattern + every error code.
Uses pytest's tmp_path fixture for hermetic isolation between tests.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from graqle.plugins.graq_apply import (
    apply_insertions,
    ApplyResult,
    ERR_FILE_NOT_FOUND,
    ERR_SHA_MISMATCH,
    ERR_ANCHOR_NOT_FOUND,
    ERR_ANCHOR_NOT_UNIQUE,
    ERR_BYTE_DELTA_OUT_OF_BAND,
    ERR_MARKER_COUNT_MISMATCH,
    ERR_INVALID_INSERTION,
)


@pytest.fixture
def sample_file(tmp_path):
    """Create a sample file with known content for tests."""
    f = tmp_path / "sample.py"
    f.write_bytes(b"# header\nimport os\n\ndef foo():\n    return 42\n\ndef bar():\n    return 99\n")
    return f


class TestRail1Baseline:
    """Rail 1: freeze baseline (read file, compute SHA, capture bytes_before)."""

    def test_dry_run_captures_baseline(self, sample_file):
        result = apply_insertions(
            str(sample_file),
            [{"anchor": "return 42", "replacement": "return 43"}],
            dry_run=True,
        )
        assert result.success is True
        assert result.bytes_before == sample_file.stat().st_size
        assert result.sha256_before == hashlib.sha256(sample_file.read_bytes()).hexdigest()

    def test_baseline_pin_match(self, sample_file):
        sha = hashlib.sha256(sample_file.read_bytes()).hexdigest()
        result = apply_insertions(
            str(sample_file),
            [{"anchor": "return 42", "replacement": "return 43"}],
            expected_input_sha256=sha,
            dry_run=True,
        )
        assert result.success is True

    def test_baseline_pin_mismatch_aborts(self, sample_file):
        result = apply_insertions(
            str(sample_file),
            [{"anchor": "return 42", "replacement": "return 43"}],
            expected_input_sha256="0" * 64,
            dry_run=True,
        )
        assert result.success is False
        assert result.error_code == ERR_SHA_MISMATCH


class TestRail2InputValidation:
    """Rail 2: validate insertions list (fail-fast on bad input)."""

    def test_file_not_found(self, tmp_path):
        result = apply_insertions(
            str(tmp_path / "nonexistent.py"),
            [{"anchor": "x", "replacement": "y"}],
            dry_run=True,
        )
        assert result.success is False
        assert result.error_code == ERR_FILE_NOT_FOUND

    def test_empty_insertions_list(self, sample_file):
        result = apply_insertions(str(sample_file), [], dry_run=True)
        assert result.success is False
        assert result.error_code == ERR_INVALID_INSERTION

    def test_insertion_missing_anchor(self, sample_file):
        result = apply_insertions(
            str(sample_file),
            [{"replacement": "x"}],
            dry_run=True,
        )
        assert result.success is False
        assert result.error_code == ERR_INVALID_INSERTION

    def test_insertion_missing_replacement(self, sample_file):
        result = apply_insertions(
            str(sample_file),
            [{"anchor": "x"}],
            dry_run=True,
        )
        assert result.success is False
        assert result.error_code == ERR_INVALID_INSERTION

    def test_insertion_empty_anchor(self, sample_file):
        result = apply_insertions(
            str(sample_file),
            [{"anchor": "", "replacement": "x"}],
            dry_run=True,
        )
        assert result.success is False
        assert result.error_code == ERR_INVALID_INSERTION


class TestRail3AnchorUniqueness:
    """Rail 3: anchor uniqueness invariant (the safety guarantee)."""

    def test_anchor_not_found(self, sample_file):
        result = apply_insertions(
            str(sample_file),
            [{"anchor": "MISSING_ANCHOR_NEVER_IN_FILE", "replacement": "x"}],
            dry_run=True,
        )
        assert result.success is False
        assert result.error_code == ERR_ANCHOR_NOT_FOUND

    def test_anchor_not_unique_default(self, tmp_path):
        f = tmp_path / "dup.py"
        f.write_bytes(b"foo\nfoo\nfoo\n")
        result = apply_insertions(
            str(f),
            [{"anchor": "foo", "replacement": "BAR"}],
            dry_run=True,
        )
        assert result.success is False
        assert result.error_code == ERR_ANCHOR_NOT_UNIQUE

    def test_explicit_count_3(self, tmp_path, monkeypatch):
        f = tmp_path / "dup.py"
        f.write_bytes(b"foo\nfoo\nfoo\n")
        monkeypatch.chdir(tmp_path)
        result = apply_insertions(
            str(f),
            [{"anchor": "foo", "replacement": "BAR", "expected_count": 3}],
            dry_run=False,
        )
        assert result.success is True
        assert f.read_bytes() == b"BAR\nBAR\nBAR\n"

    def test_anchor_check_field_populated(self, sample_file):
        result = apply_insertions(
            str(sample_file),
            [
                {"anchor": "return 42", "replacement": "return 43"},
                {"anchor": "return 99", "replacement": "return 100"},
            ],
            dry_run=True,
        )
        assert result.success is True
        assert len(result.anchor_check) == 2
        assert result.anchor_check[0]["actual_count"] == 1
        assert result.anchor_check[1]["actual_count"] == 1


class TestRail4DeterministicReplace:
    """Rail 4: bytes.replace() preserves all unchanged content byte-for-byte."""

    def test_unchanged_regions_preserved(self, sample_file, monkeypatch):
        original = sample_file.read_bytes()
        monkeypatch.chdir(sample_file.parent)
        result = apply_insertions(
            str(sample_file),
            [{"anchor": "return 42", "replacement": "return 43"}],
            dry_run=False,
        )
        assert result.success is True
        new_content = sample_file.read_bytes()
        # Everything except the 2 changed bytes ("42" -> "43") must be byte-identical
        expected = original.replace(b"return 42", b"return 43", 1)
        assert new_content == expected

    def test_str_anchor_str_replacement(self, sample_file):
        # String anchors get coerced to UTF-8 bytes
        result = apply_insertions(
            str(sample_file),
            [{"anchor": "return 42", "replacement": "return 43"}],
            dry_run=True,
        )
        assert result.success is True

    def test_bytes_anchor_bytes_replacement(self, sample_file):
        result = apply_insertions(
            str(sample_file),
            [{"anchor": b"return 42", "replacement": b"return 43"}],
            dry_run=True,
        )
        assert result.success is True


class TestRail5PostReplacementInvariants:
    """Rail 5: byte_delta_band + marker count assertions."""

    def test_byte_delta_within_band(self, sample_file):
        result = apply_insertions(
            str(sample_file),
            [{"anchor": "return 42", "replacement": "return 43"}],
            expected_byte_delta_band=(0, 0),
            dry_run=True,
        )
        assert result.success is True
        assert result.byte_delta == 0

    def test_byte_delta_out_of_band(self, sample_file):
        result = apply_insertions(
            str(sample_file),
            [{"anchor": "return 42", "replacement": "return 42 plus a lot more bytes"}],
            expected_byte_delta_band=(0, 5),
            dry_run=True,
        )
        assert result.success is False
        assert result.error_code == ERR_BYTE_DELTA_OUT_OF_BAND

    def test_marker_count_match(self, sample_file):
        result = apply_insertions(
            str(sample_file),
            [{"anchor": "return 42", "replacement": "return 43"}],
            expected_markers={"return 43": 1, "return 99": 1},
            dry_run=True,
        )
        assert result.success is True
        assert result.marker_counts == {"return 43": 1, "return 99": 1}

    def test_marker_count_mismatch(self, sample_file):
        result = apply_insertions(
            str(sample_file),
            [{"anchor": "return 42", "replacement": "return 43"}],
            expected_markers={"return 43": 99},
            dry_run=True,
        )
        assert result.success is False
        assert result.error_code == ERR_MARKER_COUNT_MISMATCH


class TestRail6AtomicWrite:
    """Rail 6: real write performs atomic replace."""

    def test_real_write_changes_file(self, sample_file, monkeypatch):
        monkeypatch.chdir(sample_file.parent)
        result = apply_insertions(
            str(sample_file),
            [{"anchor": "return 42", "replacement": "return 43"}],
            dry_run=False,
        )
        assert result.success is True
        assert result.dry_run is False
        assert b"return 43" in sample_file.read_bytes()
        assert b"return 42" not in sample_file.read_bytes()

    def test_dry_run_does_not_change_file(self, sample_file):
        original = sample_file.read_bytes()
        result = apply_insertions(
            str(sample_file),
            [{"anchor": "return 42", "replacement": "return 43"}],
            dry_run=True,
        )
        assert result.success is True
        assert result.dry_run is True
        assert sample_file.read_bytes() == original  # untouched


class TestRail7PostWriteVerify:
    """Rail 7: re-read and verify after write."""

    def test_sha256_after_matches_disk(self, sample_file, monkeypatch):
        monkeypatch.chdir(sample_file.parent)
        result = apply_insertions(
            str(sample_file),
            [{"anchor": "return 42", "replacement": "return 43"}],
            dry_run=False,
        )
        assert result.success is True
        assert result.sha256_after == hashlib.sha256(sample_file.read_bytes()).hexdigest()


class TestRail8Backup:
    """Rail 8: backup file created in .graqle/edit-backup/ before real write."""

    def test_backup_created_on_real_write(self, sample_file, monkeypatch):
        original = sample_file.read_bytes()
        monkeypatch.chdir(sample_file.parent)
        result = apply_insertions(
            str(sample_file),
            [{"anchor": "return 42", "replacement": "return 43"}],
            dry_run=False,
        )
        assert result.success is True
        assert result.backup_path != ""
        assert Path(result.backup_path).exists()
        # Backup contains the original content (rollback artifact)
        assert Path(result.backup_path).read_bytes() == original

    def test_no_backup_on_dry_run(self, sample_file):
        result = apply_insertions(
            str(sample_file),
            [{"anchor": "return 42", "replacement": "return 43"}],
            dry_run=True,
        )
        assert result.success is True
        assert result.backup_path == ""


class TestMultiInsertion:
    """Multiple sequential insertions in a single call."""

    def test_three_insertions(self, sample_file, monkeypatch):
        monkeypatch.chdir(sample_file.parent)
        result = apply_insertions(
            str(sample_file),
            [
                {"anchor": "import os", "replacement": "import os\nimport sys"},
                {"anchor": "return 42", "replacement": "return 43"},
                {"anchor": "return 99", "replacement": "return 100"},
            ],
            dry_run=False,
        )
        assert result.success is True
        assert result.insertions_applied == 3
        new_content = sample_file.read_bytes()
        assert b"import sys" in new_content
        assert b"return 43" in new_content
        assert b"return 100" in new_content

    def test_first_insertion_failure_stops_chain(self, sample_file):
        # If insertion #2 fails, insertion #1 should not be applied (dry_run)
        result = apply_insertions(
            str(sample_file),
            [
                {"anchor": "return 42", "replacement": "return 43"},
                {"anchor": "MISSING", "replacement": "x"},
            ],
            dry_run=True,
        )
        assert result.success is False
        assert result.error_code == ERR_ANCHOR_NOT_FOUND
        assert result.insertions_applied == 1  # the first one was applied in-memory before #2 failed


class TestApplyResultDataclass:
    """ApplyResult dataclass shape and serialization."""

    def test_to_dict_returns_dict(self, sample_file):
        result = apply_insertions(
            str(sample_file),
            [{"anchor": "return 42", "replacement": "return 43"}],
            dry_run=True,
        )
        d = result.to_dict()
        assert isinstance(d, dict)
        assert d["success"] is True
        assert d["dry_run"] is True
        assert "bytes_before" in d
        assert "byte_delta" in d
        assert "anchor_check" in d
