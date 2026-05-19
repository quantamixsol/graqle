"""Tests for ``graq compliance status`` — PR-009b.

Coverage discipline:

  * TestPayloadShape           — the JSON shape is stable and matches what
    PR-009d's MCP envelope ``compliance`` block will publish.
  * TestEUAIActModeDetection   — env-var parsing is permissive but correct.
  * TestAuditTrailMetadata     — reads metadata only, never reads session
    contents.
  * TestArticlesCovered        — the article list in code matches the
    article list in ``docs/compliance/eu-ai-act/README.md`` (drift guard).
  * TestCLISurface             — the typer entry point round-trips text and
    json output without raising.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from graqle.cli.commands.compliance import (
    ARTICLES_COVERED,
    SYSTEM_CARD_URL,
    _build_status_payload,
    _read_audit_trail_metadata,
    _read_eu_ai_act_mode,
    compliance_app,
)


# ---------------------------------------------------------------------------
# TestPayloadShape
# ---------------------------------------------------------------------------


class TestPayloadShape:
    def test_payload_has_all_required_top_level_keys(self, tmp_path: Path) -> None:
        payload = _build_status_payload(tmp_path)
        required = {
            "graqle_version",
            "eu_ai_act_mode",
            "articles_covered",
            "articles_detail",
            "system_card_url",
            "audit_trail",
            "schema_version",
        }
        assert required.issubset(payload.keys()), (
            f"Missing keys: {required - payload.keys()}"
        )

    def test_schema_version_is_v1(self, tmp_path: Path) -> None:
        payload = _build_status_payload(tmp_path)
        assert payload["schema_version"] == "1", (
            "schema_version must lock at '1' until a breaking change in PR-009d "
            "or later — bump deliberately, never accidentally."
        )

    def test_articles_covered_is_string_list(self, tmp_path: Path) -> None:
        payload = _build_status_payload(tmp_path)
        assert isinstance(payload["articles_covered"], list)
        for art in payload["articles_covered"]:
            assert isinstance(art, str), (
                "Each article number must be a string for stable JSON shape "
                "(matches Article 13 MCP envelope spec)."
            )

    def test_articles_detail_rows_have_required_fields(self, tmp_path: Path) -> None:
        payload = _build_status_payload(tmp_path)
        required = {"article", "applicability_date", "applies_to_graqle"}
        for row in payload["articles_detail"]:
            assert required.issubset(row.keys()), (
                f"Detail row missing keys {required - row.keys()}: {row}"
            )

    def test_applies_to_graqle_is_one_of_known_verdicts(self, tmp_path: Path) -> None:
        payload = _build_status_payload(tmp_path)
        allowed = {"YES", "INDIRECTLY", "NO"}
        for row in payload["articles_detail"]:
            assert row["applies_to_graqle"] in allowed, (
                f"Unknown verdict {row['applies_to_graqle']!r} for Art "
                f"{row['article']}. Must be one of {allowed}."
            )

    def test_system_card_url_points_to_compliance_readme(self, tmp_path: Path) -> None:
        payload = _build_status_payload(tmp_path)
        assert payload["system_card_url"] == SYSTEM_CARD_URL
        assert "docs/compliance/eu-ai-act/README.md" in payload["system_card_url"]

    def test_payload_is_json_serialisable(self, tmp_path: Path) -> None:
        payload = _build_status_payload(tmp_path)
        # Round-trip via json — guarantees no exotic types leaked in.
        round_tripped = json.loads(json.dumps(payload))
        assert round_tripped["schema_version"] == payload["schema_version"]

    def test_payload_handles_tilde_in_repo_root(self, tmp_path: Path) -> None:
        """``~`` expansion is the user-input hardening for --repo-root.

        A user typing ``--repo-root ~/my-project`` should resolve via
        ``expanduser()``, not be treated as a literal directory named "~".
        """
        # We can't easily monkeypatch HOME without polluting other tests,
        # so this is a smoke test: passing a string with ~ doesn't raise.
        payload = _build_status_payload(Path("~/non-existent-test-dir"))
        assert payload["audit_trail"]["exists"] is False
        # Absolute path, no tilde leaked through.
        assert "~" not in payload["audit_trail"]["path"]


# ---------------------------------------------------------------------------
# TestEUAIActModeDetection
# ---------------------------------------------------------------------------


class TestEUAIActModeDetection:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("on", True),
            ("ON", True),
            ("On", True),
            ("true", True),
            ("TRUE", True),
            ("1", True),
            ("yes", True),
            ("YES", True),
            ("  on  ", True),  # whitespace tolerated
        ],
    )
    def test_truthy_values_enable_mode(
        self, value: str, expected: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", value)
        assert _read_eu_ai_act_mode() is expected

    @pytest.mark.parametrize(
        "value",
        ["off", "false", "0", "no", "", "anything-else", "OFF"],
    )
    def test_falsy_values_keep_mode_off(
        self, value: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", value)
        assert _read_eu_ai_act_mode() is False

    def test_unset_env_var_keeps_mode_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GRAQLE_EU_AI_ACT_MODE", raising=False)
        assert _read_eu_ai_act_mode() is False


# ---------------------------------------------------------------------------
# TestAuditTrailMetadata
# ---------------------------------------------------------------------------


class TestAuditTrailMetadata:
    def test_missing_directory_returns_exists_false(self, tmp_path: Path) -> None:
        meta = _read_audit_trail_metadata(tmp_path / "does-not-exist")
        assert meta["exists"] is False
        assert meta["session_count"] == 0
        assert meta["last_session_id"] is None

    def test_empty_directory_reports_zero_sessions(self, tmp_path: Path) -> None:
        audit_dir = tmp_path / "audit"
        audit_dir.mkdir()
        meta = _read_audit_trail_metadata(audit_dir)
        assert meta["exists"] is True
        assert meta["session_count"] == 0
        assert meta["last_session_id"] is None

    def test_multiple_sessions_picks_lexically_greatest_id(
        self, tmp_path: Path
    ) -> None:
        audit_dir = tmp_path / "audit"
        audit_dir.mkdir()
        (audit_dir / "20260101_120000.json").write_text("{}", encoding="utf-8")
        (audit_dir / "20260514_233000.json").write_text("{}", encoding="utf-8")
        (audit_dir / "20260301_091500.json").write_text("{}", encoding="utf-8")
        meta = _read_audit_trail_metadata(audit_dir)
        assert meta["session_count"] == 3
        assert meta["last_session_id"] == "20260514_233000"

    def test_does_not_read_session_contents(self, tmp_path: Path) -> None:
        # Article-12 record-keeping requirement: status output is metadata
        # only; session contents stay sealed until graq audit export.
        audit_dir = tmp_path / "audit"
        audit_dir.mkdir()
        sensitive = '{"secret": "MUST-NOT-LEAK"}'
        (audit_dir / "20260514_120000.json").write_text(sensitive, encoding="utf-8")
        meta = _read_audit_trail_metadata(audit_dir)
        for v in meta.values():
            assert "MUST-NOT-LEAK" not in str(v), (
                "Status output leaked session content — Article 12 violation."
            )

    def test_path_field_is_absolute(self, tmp_path: Path) -> None:
        meta = _read_audit_trail_metadata(tmp_path / "rel" / "audit")
        # Even for non-existent dirs the path is resolved to absolute.
        assert Path(meta["path"]).is_absolute()

    def test_permission_error_on_glob_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Article-12: read-side observability must NEVER raise.

        If ``glob`` raises (PermissionError on Linux, OSError on Windows),
        we degrade to ``session_count=0, last_session_id=None`` and keep
        ``exists=True`` so the operator can see *something* is present
        but not readable.
        """
        audit_dir = tmp_path / "audit"
        audit_dir.mkdir()

        def _raising_glob(_self, _pattern: str):
            raise PermissionError("simulated read-denied")

        monkeypatch.setattr(Path, "glob", _raising_glob)
        meta = _read_audit_trail_metadata(audit_dir)
        assert meta["session_count"] == 0
        assert meta["last_session_id"] is None
        # Did NOT raise — that's the entire point.

    def test_resolve_failure_falls_back_to_absolute(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Symlink loops / Windows weirdness make ``.resolve()`` raise.

        The path field should still be absolute via the ``.absolute()``
        fallback.
        """
        target = tmp_path / "weird"

        def _raising_resolve(_self, strict: bool = False):
            raise OSError("simulated symlink loop")

        monkeypatch.setattr(Path, "resolve", _raising_resolve)
        meta = _read_audit_trail_metadata(target)
        assert Path(meta["path"]).is_absolute()


# ---------------------------------------------------------------------------
# TestArticlesCovered — drift guard against docs
# ---------------------------------------------------------------------------


class TestArticlesCovered:
    # cr-019: Article 43 is a PROCEDURAL / conformity-assessment article — it
    # describes HOW a provider performs Annex VI internal-control assessment,
    # not WHAT GraQle's subsystems substantively cover. GraQle's
    # ``articles_covered`` envelope lists substantive articles (6, 9, 12,
    # 13, 14, 15, 25, 50). The article-43-conformity-assessment.md doc
    # explicitly states "Applies to GraQle? INDIRECTLY", and the doc maps
    # GraQle's existing substrate to Annex VI requirements rather than
    # introducing new claims. Excluding it from the parity check encodes
    # this real architectural distinction.
    _DOCS_PARITY_EXCLUSIONS: set[str] = {"43"}

    def test_articles_covered_list_matches_compliance_readme(self) -> None:
        """The in-code article list must match the docs index.

        If you add a doc file ``article-NN-*.md`` and forget to update
        ``ARTICLES_COVERED`` in compliance.py, this test fails and points
        at the drift.

        ``_DOCS_PARITY_EXCLUSIONS`` carves out procedural / conformity
        articles whose docs exist for evidence-mapping purposes but which
        are not substantive members of ``ARTICLES_COVERED``.
        """
        repo_root = Path(__file__).resolve().parents[2]
        compliance_dir = repo_root / "docs" / "compliance" / "eu-ai-act"
        article_files = sorted(compliance_dir.glob("article-*.md"))
        in_docs = set()
        for f in article_files:
            # filename: article-04-ai-literacy.md → 4
            stem = f.stem  # article-04-ai-literacy
            parts = stem.split("-")
            num = parts[1].lstrip("0") or "0"
            in_docs.add(num)
        # Exclude procedural/conformity articles per cr-019.
        in_docs -= self._DOCS_PARITY_EXCLUSIONS
        in_code = {a[0] for a in ARTICLES_COVERED}
        assert in_docs == in_code, (
            f"Drift: docs has {in_docs}, code has {in_code}. "
            "Update ARTICLES_COVERED in graqle/cli/commands/compliance.py."
        )

    def test_no_duplicate_article_numbers(self) -> None:
        numbers = [a[0] for a in ARTICLES_COVERED]
        assert len(numbers) == len(set(numbers)), (
            f"Duplicate article numbers in ARTICLES_COVERED: {numbers}"
        )

    def test_applicability_dates_are_iso_format(self) -> None:
        for art, date, _verdict in ARTICLES_COVERED:
            # YYYY-MM-DD shape — required by Article 13 envelope spec.
            parts = date.split("-")
            assert len(parts) == 3, f"Art {art} date {date} not ISO YYYY-MM-DD"
            assert len(parts[0]) == 4 and parts[0].isdigit()
            assert len(parts[1]) == 2 and parts[1].isdigit()
            assert len(parts[2]) == 2 and parts[2].isdigit()


# ---------------------------------------------------------------------------
# TestCLISurface
# ---------------------------------------------------------------------------


class TestCLISurface:
    def test_text_output_succeeds(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            ["status", "--repo-root", str(tmp_path)],
        )
        assert result.exit_code == 0, result.output
        assert "compliance posture" in result.output.lower()

    def test_json_output_is_parseable(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            ["status", "--format", "json", "--repo-root", str(tmp_path)],
        )
        assert result.exit_code == 0, result.output
        # The JSON is printed to stdout via print() — typer's CliRunner
        # captures both. Find the first '{' and parse from there to
        # tolerate any leading log noise.
        idx = result.output.find("{")
        assert idx >= 0, f"No JSON found in output: {result.output!r}"
        payload = json.loads(result.output[idx:])
        assert payload["schema_version"] == "1"
        assert isinstance(payload["articles_covered"], list)
        assert payload["eu_ai_act_mode"] in (True, False)

    def test_unknown_format_exits_with_code_2(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            ["status", "--format", "yaml", "--repo-root", str(tmp_path)],
        )
        assert result.exit_code == 2, result.output

    def test_eu_ai_act_mode_on_is_reflected_in_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            ["status", "--format", "json", "--repo-root", str(tmp_path)],
        )
        assert result.exit_code == 0, result.output
        idx = result.output.find("{")
        payload = json.loads(result.output[idx:])
        assert payload["eu_ai_act_mode"] is True

    def test_no_args_shows_help_listing_both_commands(self) -> None:
        """Multi-command typer (status + export) shows help listing both."""
        runner = CliRunner()
        result = runner.invoke(compliance_app, [])
        assert result.exit_code in (0, 2), result.output
        haystack = result.output.lower()
        assert "status" in haystack, result.output
        assert "export" in haystack, result.output
