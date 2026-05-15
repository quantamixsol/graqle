"""Integration tests for PR-009d disclosure injection in MCP envelopes.

Mirrors the test pattern from
``tests/test_plugins/test_cg_reason_diag_01.py``: builds the same
envelope as ``mcp_dev_server._handle_reason`` does (success path),
then asserts the disclosure fields are added/omitted correctly.

We avoid full async/MCP server setup because:
  * The envelope-construction logic is the actual surface under test
    (NOT the full reasoning pipeline).
  * Replicating the logic in a small helper makes the test fast and
    deterministic.
  * Drift between the real handler and the helper is mitigated by
    grepping for the disclosure-injection block in mcp_dev_server.py
    in a dedicated test (TestSourceDriftGuard).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from graqle.compliance.disclosure import (
    build_ai_disclosure,
    build_compliance_envelope,
    is_eu_ai_act_mode_on,
    maybe_emit_session_banner,
    reset_session_banner_state,
)


def _build_envelope_with_disclosure(
    base: dict[str, Any],
    backend: str = "anthropic/claude",
    confidence: float = 0.82,
) -> dict[str, Any]:
    """Replicate the disclosure-injection block from
    ``mcp_dev_server._handle_reason`` (PR-009d hook).

    Mirrors the production code path, including the broad except guard.
    Used by the integration tests below to verify field shape without
    invoking the full async reasoning pipeline.
    """
    result_dict = dict(base)
    try:
        if is_eu_ai_act_mode_on():
            result_dict["ai_disclosure"] = build_ai_disclosure(
                backend=backend
            ).to_dict()
            result_dict["compliance"] = build_compliance_envelope().to_dict()
            maybe_emit_session_banner(confidence=confidence, backend=backend)
    except Exception:
        pass
    return result_dict


@pytest.fixture(autouse=True)
def _reset_banner_state():
    reset_session_banner_state()
    yield
    reset_session_banner_state()


# ---------------------------------------------------------------------------
# TestEnvelopeShapeWhenModeOn
# ---------------------------------------------------------------------------


class TestEnvelopeShapeWhenModeOn:
    def test_envelope_gains_ai_disclosure_field_when_mode_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")
        base = {"answer": "test", "confidence": 0.82}
        env = _build_envelope_with_disclosure(base)
        assert "ai_disclosure" in env
        assert env["ai_disclosure"]["is_ai_generated"] is True
        assert env["ai_disclosure"]["system"] == "GraQle"
        assert env["ai_disclosure"]["ai_act_article_50_paragraph_1"] is True

    def test_envelope_gains_compliance_field_when_mode_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")
        base = {"answer": "test", "confidence": 0.82}
        env = _build_envelope_with_disclosure(base)
        assert "compliance" in env
        assert "articles_covered" in env["compliance"]
        assert "50" in env["compliance"]["articles_covered"]

    def test_existing_fields_preserved_when_mode_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")
        base = {
            "answer": "test",
            "confidence": 0.82,
            "rounds": 2,
            "nodes_used": 15,
            "active_nodes": ["a", "b"],
            "cost_usd": 0.012,
            "latency_ms": 1450.5,
            "mode": "semantic",
            "backend_status": "anthropic/claude",
            "backend_error": None,
        }
        env = _build_envelope_with_disclosure(base, backend="anthropic/claude")
        # All base fields preserved (additive contract).
        for key, value in base.items():
            assert env[key] == value, (
                f"Field {key!r} was mutated by disclosure injection."
            )
        # Plus the two new fields.
        assert "ai_disclosure" in env
        assert "compliance" in env

    def test_backend_label_propagates_to_ai_disclosure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")
        env = _build_envelope_with_disclosure(
            {"answer": "x"}, backend="ollama/llama3"
        )
        assert env["ai_disclosure"]["backend"] == "ollama/llama3"

    def test_envelope_is_json_round_trippable_when_mode_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MCP envelopes are wire-transported as JSON. PR-009d additive
        fields must not introduce non-JSON types."""
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")
        env = _build_envelope_with_disclosure({"answer": "x"})
        # Must serialise + deserialise lossless.
        roundtripped = json.loads(json.dumps(env))
        assert roundtripped["ai_disclosure"]["is_ai_generated"] is True
        assert "50" in roundtripped["compliance"]["articles_covered"]


# ---------------------------------------------------------------------------
# TestEnvelopeShapeWhenModeOff — backward-compat invariant
# ---------------------------------------------------------------------------


class TestEnvelopeShapeWhenModeOff:
    def test_envelope_omits_ai_disclosure_when_mode_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GRAQLE_EU_AI_ACT_MODE", raising=False)
        env = _build_envelope_with_disclosure({"answer": "x"})
        assert "ai_disclosure" not in env
        assert "compliance" not in env

    def test_envelope_byte_for_byte_unchanged_when_mode_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Existing consumers MUST see a bit-for-bit unchanged envelope
        when mode is off. This is the additive-schema contract from
        the VS Code extension handoff (PR-009d preserves it)."""
        monkeypatch.delenv("GRAQLE_EU_AI_ACT_MODE", raising=False)
        base = {
            "answer": "test",
            "confidence": 0.82,
            "rounds": 2,
            "nodes_used": 15,
            "active_nodes": ["a", "b"],
            "cost_usd": 0.012,
            "latency_ms": 1450.5,
            "mode": "semantic",
            "backend_status": "anthropic/claude",
            "backend_error": None,
        }
        env = _build_envelope_with_disclosure(base)
        # Exact same keys, exact same values.
        assert set(env.keys()) == set(base.keys())
        for k in base:
            assert env[k] == base[k]

    def test_envelope_omits_when_mode_explicitly_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``GRAQLE_EU_AI_ACT_MODE=off`` is functionally the same as unset."""
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "off")
        env = _build_envelope_with_disclosure({"answer": "x"})
        assert "ai_disclosure" not in env
        assert "compliance" not in env


# ---------------------------------------------------------------------------
# TestSourceDriftGuard — the integration helper must mirror prod code
# ---------------------------------------------------------------------------


class TestSourceDriftGuard:
    def test_handler_source_uses_disclosure_module(self) -> None:
        """The real ``_handle_reason`` must import and call the
        disclosure helpers we test against.

        If PR-009d's hook is reverted or moved, this test catches it
        and points at the file to check.
        """
        handler_path = (
            Path(__file__).resolve().parents[2]
            / "graqle" / "plugins" / "mcp_dev_server.py"
        )
        text = handler_path.read_text(encoding="utf-8", errors="replace")
        assert "from graqle.compliance.disclosure import" in text, (
            "mcp_dev_server.py no longer imports disclosure module — "
            "PR-009d hook may have been reverted."
        )
        assert "is_eu_ai_act_mode_on" in text
        assert "build_ai_disclosure" in text
        assert "build_compliance_envelope" in text
        assert "maybe_emit_session_banner" in text

    def test_handler_omits_fields_under_mode_off_per_source(self) -> None:
        """The hook in source code is guarded by ``if is_eu_ai_act_mode_on()``."""
        handler_path = (
            Path(__file__).resolve().parents[2]
            / "graqle" / "plugins" / "mcp_dev_server.py"
        )
        text = handler_path.read_text(encoding="utf-8", errors="replace")
        # The injection block must be inside an `if is_eu_ai_act_mode_on():`
        # — assert the literal pattern appears once near the disclosure
        # import.
        idx = text.find("from graqle.compliance.disclosure import")
        assert idx >= 0
        # Within ~600 chars of the import, the mode-on guard must appear.
        window = text[idx:idx + 1200]
        assert "is_eu_ai_act_mode_on()" in window, (
            "Disclosure block must be guarded by is_eu_ai_act_mode_on()."
        )


# ---------------------------------------------------------------------------
# TestBannerEmitInIntegration
# ---------------------------------------------------------------------------


class TestBannerEmitInIntegration:
    def test_banner_emits_once_across_multiple_envelope_builds(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Simulate two reasoning calls in one process — banner emits once."""
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")
        monkeypatch.delenv("GRAQLE_AI_DISCLOSURE", raising=False)
        # Build two envelopes — banner should appear in stderr exactly once.
        _build_envelope_with_disclosure({"answer": "first"})
        _build_envelope_with_disclosure({"answer": "second"})
        captured = capsys.readouterr()
        # AI Act Article 50(1) string appears exactly once.
        assert captured.err.count("AI Act Article 50(1)") == 1

    def test_no_banner_when_suppressed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")
        monkeypatch.setenv("GRAQLE_AI_DISCLOSURE", "off")
        _build_envelope_with_disclosure({"answer": "x"})
        captured = capsys.readouterr()
        assert "AI Act Article 50(1)" not in captured.err
        # But ai_disclosure field IS still emitted — suppression only
        # affects the banner, not the machine-readable field.
        # (Implicit: build helper returned with both fields.)
