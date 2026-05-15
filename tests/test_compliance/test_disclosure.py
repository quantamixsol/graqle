"""Tests for ``graqle.compliance.disclosure`` — PR-009d.

Coverage discipline:

  * TestAIDisclosure         — dataclass shape + to_dict round-trip.
  * TestComplianceEnvelope   — dataclass shape + parity with status CLI.
  * TestModeDetection        — env-var parsing for mode + suppress flags.
  * TestBuildHelpers         — build_ai_disclosure / build_compliance_envelope.
  * TestSessionBanner        — once-per-session emit, suppress, idempotence.
  * TestParityWithStatus     — articles_covered list matches PR-009b.
"""

from __future__ import annotations

import io
import json

import pytest

from graqle.compliance.disclosure import (
    AIDisclosure,
    ComplianceEnvelope,
    build_ai_disclosure,
    build_compliance_envelope,
    is_ai_disclosure_suppressed,
    is_eu_ai_act_mode_on,
    maybe_emit_session_banner,
    reset_session_banner_state,
)


# ---------------------------------------------------------------------------
# TestAIDisclosure
# ---------------------------------------------------------------------------


class TestAIDisclosure:
    def test_default_field_values(self) -> None:
        d = AIDisclosure()
        assert d.is_ai_generated is True
        assert d.system == "GraQle"
        assert d.version == ""
        assert d.backend == "unknown"
        assert d.ai_act_article_50_paragraph_1 is True

    def test_to_dict_contains_all_fields(self) -> None:
        d = AIDisclosure(version="0.55.0", backend="anthropic/claude-sonnet-4-6")
        out = d.to_dict()
        required = {
            "is_ai_generated",
            "system",
            "version",
            "backend",
            "ai_act_article_50_paragraph_1",
        }
        assert required == set(out.keys())

    def test_to_dict_is_json_serialisable(self) -> None:
        d = AIDisclosure(version="0.55.0", backend="ollama/llama3")
        # Round-trip via JSON — guarantees no exotic types leaked in.
        text = json.dumps(d.to_dict())
        parsed = json.loads(text)
        assert parsed["system"] == "GraQle"
        assert parsed["ai_act_article_50_paragraph_1"] is True

    def test_dataclass_is_frozen(self) -> None:
        d = AIDisclosure()
        # Frozen dataclass — mutating fields must raise.
        with pytest.raises((AttributeError, Exception)):
            d.version = "new"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestComplianceEnvelope
# ---------------------------------------------------------------------------


class TestComplianceEnvelope:
    def test_default_articles_covered_match_pr_009b(self) -> None:
        e = ComplianceEnvelope()
        # Same set as graqle.cli.commands.compliance.ARTICLES_COVERED.
        assert set(e.articles_covered) == {"4", "12", "13", "14", "15", "25", "50"}

    def test_to_dict_contains_all_fields(self) -> None:
        e = ComplianceEnvelope()
        out = e.to_dict()
        required = {"articles_covered", "system_card_url", "audit_log_export", "version"}
        assert required == set(out.keys())

    def test_articles_covered_is_list_in_dict(self) -> None:
        # The dataclass uses a tuple for immutability; to_dict converts
        # to list for JSON serialisability and downstream consumer
        # expectations (matches PR-009b status JSON shape).
        out = ComplianceEnvelope().to_dict()
        assert isinstance(out["articles_covered"], list)

    def test_audit_log_export_hint_references_pr_009c_command(self) -> None:
        out = ComplianceEnvelope().to_dict()
        assert "graq compliance export" in out["audit_log_export"]

    def test_system_card_url_points_to_compliance_readme(self) -> None:
        out = ComplianceEnvelope().to_dict()
        assert "docs/compliance/eu-ai-act/README.md" in out["system_card_url"]


# ---------------------------------------------------------------------------
# TestModeDetection
# ---------------------------------------------------------------------------


class TestModeDetection:
    @pytest.mark.parametrize(
        "value, expected",
        [("on", True), ("true", True), ("1", True), ("yes", True),
         ("ON", True), ("YES", True), ("  on  ", True),
         ("off", False), ("false", False), ("0", False), ("no", False),
         ("", False), ("anything-else", False)],
    )
    def test_is_eu_ai_act_mode_on(
        self, value: str, expected: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", value)
        assert is_eu_ai_act_mode_on() is expected

    def test_mode_unset_is_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GRAQLE_EU_AI_ACT_MODE", raising=False)
        assert is_eu_ai_act_mode_on() is False

    @pytest.mark.parametrize(
        "value, expected",
        [("off", True), ("OFF", True), ("Off", True), ("  off  ", True),
         ("on", False), ("true", False), ("", False), ("foo", False)],
    )
    def test_is_ai_disclosure_suppressed(
        self, value: str, expected: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GRAQLE_AI_DISCLOSURE", value)
        assert is_ai_disclosure_suppressed() is expected


# ---------------------------------------------------------------------------
# TestBuildHelpers
# ---------------------------------------------------------------------------


class TestBuildHelpers:
    def test_build_ai_disclosure_with_backend(self) -> None:
        d = build_ai_disclosure(backend="anthropic/claude-sonnet-4-6")
        assert d.backend == "anthropic/claude-sonnet-4-6"
        assert d.is_ai_generated is True
        assert d.ai_act_article_50_paragraph_1 is True

    def test_build_ai_disclosure_empty_backend_falls_back_to_unknown(self) -> None:
        d = build_ai_disclosure(backend="")
        assert d.backend == "unknown"

    def test_build_ai_disclosure_default_backend(self) -> None:
        d = build_ai_disclosure()
        assert d.backend == "unknown"

    def test_build_ai_disclosure_includes_real_version(self) -> None:
        d = build_ai_disclosure()
        # Version is not the empty-string default — it's pulled from
        # graqle.__version__.
        assert d.version != ""

    def test_build_compliance_envelope_includes_real_version(self) -> None:
        e = build_compliance_envelope()
        assert e.version != ""

    def test_build_compliance_envelope_articles_are_strings(self) -> None:
        e = build_compliance_envelope()
        for art in e.articles_covered:
            assert isinstance(art, str)


# ---------------------------------------------------------------------------
# TestSessionBanner
# ---------------------------------------------------------------------------


class TestSessionBanner:
    def setup_method(self) -> None:
        # Each test starts with a fresh banner state.
        reset_session_banner_state()

    def teardown_method(self) -> None:
        # Don't leak state into other tests.
        reset_session_banner_state()

    def test_banner_emits_when_mode_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")
        monkeypatch.delenv("GRAQLE_AI_DISCLOSURE", raising=False)
        stream = io.StringIO()
        emitted = maybe_emit_session_banner(
            confidence=0.82, backend="anthropic/claude", stream=stream
        )
        assert emitted is True
        output = stream.getvalue()
        assert "AI Act Article 50(1)" in output
        assert "0.82" in output
        assert "anthropic/claude" in output

    def test_banner_does_not_emit_when_mode_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GRAQLE_EU_AI_ACT_MODE", raising=False)
        stream = io.StringIO()
        emitted = maybe_emit_session_banner(stream=stream)
        assert emitted is False
        assert stream.getvalue() == ""

    def test_banner_does_not_emit_when_suppressed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")
        monkeypatch.setenv("GRAQLE_AI_DISCLOSURE", "off")
        stream = io.StringIO()
        emitted = maybe_emit_session_banner(stream=stream)
        assert emitted is False
        assert stream.getvalue() == ""

    def test_banner_emits_only_once_per_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")
        monkeypatch.delenv("GRAQLE_AI_DISCLOSURE", raising=False)
        s1 = io.StringIO()
        s2 = io.StringIO()
        assert maybe_emit_session_banner(stream=s1) is True
        # Second call in the same session — must not emit.
        assert maybe_emit_session_banner(stream=s2) is False
        assert s1.getvalue() != ""
        assert s2.getvalue() == ""

    def test_reset_state_re_enables_emit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")
        monkeypatch.delenv("GRAQLE_AI_DISCLOSURE", raising=False)
        s1 = io.StringIO()
        s2 = io.StringIO()
        assert maybe_emit_session_banner(stream=s1) is True
        reset_session_banner_state()
        # After reset, a fresh emit happens (mimics a new process).
        assert maybe_emit_session_banner(stream=s2) is True

    def test_banner_without_confidence_omits_confidence_segment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")
        monkeypatch.delenv("GRAQLE_AI_DISCLOSURE", raising=False)
        stream = io.StringIO()
        maybe_emit_session_banner(confidence=None, backend="ollama", stream=stream)
        output = stream.getvalue()
        assert "Confidence:" not in output
        assert "AI Act Article 50(1)" in output

    def test_banner_with_closed_stream_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If stderr is closed (e.g. test teardown), emit must NOT crash."""
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")
        monkeypatch.delenv("GRAQLE_AI_DISCLOSURE", raising=False)
        stream = io.StringIO()
        stream.close()
        # Must not raise.
        emitted = maybe_emit_session_banner(stream=stream)
        assert emitted is False

    def test_banner_mentions_suppression_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Discoverability: the banner itself names the off-switch."""
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")
        monkeypatch.delenv("GRAQLE_AI_DISCLOSURE", raising=False)
        stream = io.StringIO()
        maybe_emit_session_banner(stream=stream)
        output = stream.getvalue()
        assert "GRAQLE_AI_DISCLOSURE" in output

    def test_banner_includes_graqle_version(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")
        monkeypatch.delenv("GRAQLE_AI_DISCLOSURE", raising=False)
        stream = io.StringIO()
        maybe_emit_session_banner(stream=stream)
        output = stream.getvalue()
        # Some version string after "v" prefix.
        assert "GraQle v" in output


# ---------------------------------------------------------------------------
# TestParityWithStatus — drift guard against PR-009b
# ---------------------------------------------------------------------------


class TestParityWithStatus:
    def test_articles_covered_matches_pr_009b_constant(self) -> None:
        """The disclosure module and the CLI must claim the SAME articles.

        If you update one without the other, this test catches the drift.
        Both anchor on graqle.cli.commands.compliance.ARTICLES_COVERED
        (PR-009b) at design time, but they're independent constants in
        code (the disclosure module deliberately has no CLI dependency).
        """
        from graqle.cli.commands.compliance import ARTICLES_COVERED
        cli_articles = {a[0] for a in ARTICLES_COVERED}
        disclosure_articles = set(build_compliance_envelope().articles_covered)
        assert cli_articles == disclosure_articles, (
            f"Drift: CLI claims {cli_articles}, disclosure claims "
            f"{disclosure_articles}. Update both."
        )

    def test_system_card_url_matches_pr_009b_constant(self) -> None:
        from graqle.cli.commands.compliance import SYSTEM_CARD_URL
        assert build_compliance_envelope().system_card_url == SYSTEM_CARD_URL
