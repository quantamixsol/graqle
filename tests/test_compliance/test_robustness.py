"""Tests for ``graqle.compliance.robustness`` — PR-009e.

Coverage discipline:

  * TestDefenceDataclass        — frozen dataclass + to_dict shape.
  * TestMeasurableClaimDataclass — frozen + to_dict.
  * TestRobustnessAttestation   — full attestation shape + invariants.
  * TestNonClaimsInvariants     — "compliant" / "certified" fields ABSENT.
  * TestCLIIntegration          — `graq compliance status --include-robustness`.
  * TestDriftGuard              — defence inventory matches the Article 15 doc.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from graqle.compliance.robustness import (
    Defence,
    MeasurableClaim,
    RobustnessAttestation,
    build_robustness_attestation,
)
from graqle.cli.commands.compliance import compliance_app


# ---------------------------------------------------------------------------
# TestDefenceDataclass
# ---------------------------------------------------------------------------


class TestDefenceDataclass:
    def test_to_dict_contains_all_fields(self) -> None:
        d = Defence(
            id="cr-003-edge-loss-shrink-guard",
            threat_class="silent_data_corruption",
            code_pointer="graqle/core/graph.py:_write_with_lock",
        )
        out = d.to_dict()
        assert set(out.keys()) == {"id", "threat_class", "code_pointer"}
        assert out["id"] == "cr-003-edge-loss-shrink-guard"

    def test_is_frozen(self) -> None:
        d = Defence(id="x", threat_class="y", code_pointer="z")
        with pytest.raises((AttributeError, Exception)):
            d.id = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestMeasurableClaimDataclass
# ---------------------------------------------------------------------------


class TestMeasurableClaimDataclass:
    def test_to_dict_contains_all_fields(self) -> None:
        m = MeasurableClaim(
            metric_id="graph_health_probe_p95_latency_ms",
            claim="< 5",
            evidence="tests/test_activation/test_graph_health_probe.py",
        )
        out = m.to_dict()
        assert set(out.keys()) == {"metric_id", "claim", "evidence"}


# ---------------------------------------------------------------------------
# TestRobustnessAttestation
# ---------------------------------------------------------------------------


class TestRobustnessAttestation:
    def test_build_returns_frozen_dataclass(self) -> None:
        a = build_robustness_attestation()
        assert isinstance(a, RobustnessAttestation)

    def test_to_dict_has_required_top_level_keys(self) -> None:
        a = build_robustness_attestation().to_dict()
        required = {
            "defences",
            "measurable_claims",
            "cybersecurity_negatives",
            "adversarial_input_boundary",
            "security_disclosure_email",
            "security_policy_url",
            "article_15_indirect",
            "article_15_aligned",
        }
        assert required.issubset(a.keys())

    def test_defences_is_non_empty_list_of_dicts(self) -> None:
        a = build_robustness_attestation().to_dict()
        assert isinstance(a["defences"], list)
        # 12 in the Article-15 doc + 5 supply-chain additions (PR-009e).
        assert len(a["defences"]) >= 12, (
            "At least 12 defences should ship — the Article 15 doc has 12, "
            "plus PR-009e adds supply-chain entries from SECURITY.md."
        )
        for d in a["defences"]:
            assert {"id", "threat_class", "code_pointer"}.issubset(d.keys())

    def test_measurable_claims_is_non_empty_list_of_dicts(self) -> None:
        a = build_robustness_attestation().to_dict()
        assert isinstance(a["measurable_claims"], list)
        assert len(a["measurable_claims"]) >= 5
        for c in a["measurable_claims"]:
            assert {"metric_id", "claim", "evidence"}.issubset(c.keys())

    def test_cybersecurity_negatives_is_dict_of_strings(self) -> None:
        a = build_robustness_attestation().to_dict()
        assert isinstance(a["cybersecurity_negatives"], dict)
        for k, v in a["cybersecurity_negatives"].items():
            assert isinstance(k, str) and isinstance(v, str)

    def test_security_disclosure_email_matches_security_md(self) -> None:
        """Email must match SECURITY.md at the repo root (drift guard)."""
        a = build_robustness_attestation().to_dict()
        assert "@" in a["security_disclosure_email"]
        # The canonical email per SECURITY.md.
        assert a["security_disclosure_email"] == "security@quantamixsolutions.com"

    def test_security_policy_url_points_to_security_md(self) -> None:
        a = build_robustness_attestation().to_dict()
        assert a["security_policy_url"].endswith("SECURITY.md")

    def test_attestation_is_json_serialisable(self) -> None:
        a = build_robustness_attestation().to_dict()
        roundtripped = json.loads(json.dumps(a))
        assert roundtripped["article_15_aligned"] is True

    def test_adversarial_input_boundary_explicit(self) -> None:
        """The non-claim must be present + name the scope."""
        a = build_robustness_attestation().to_dict()
        boundary = a["adversarial_input_boundary"]
        assert "NOT a security boundary" in boundary
        assert "adversarial" in boundary.lower()


# ---------------------------------------------------------------------------
# TestNonClaimsInvariants — what is DELIBERATELY absent
# ---------------------------------------------------------------------------


class TestNonClaimsInvariants:
    def test_no_compliant_field(self) -> None:
        """The verdict scheme is descriptive (aligned/indirect), never
        "compliant" — we don't claim compliance certification."""
        a = build_robustness_attestation().to_dict()
        # Recursively check no key named "compliant" anywhere in the dict.
        text = json.dumps(a).lower()
        # We use "compliance pipelines" in module docstrings but that
        # word lives in *documentation*, not in the attestation surface.
        # Search payload only.
        forbidden_keys = ["article_15_compliant", "compliant"]
        for key in forbidden_keys:
            assert f'"{key}"' not in text, (
                f"Forbidden claim-grade key {key!r} appears in payload."
            )

    def test_no_certified_field(self) -> None:
        a = build_robustness_attestation().to_dict()
        text = json.dumps(a).lower()
        for key in ["certified", "article_15_certified"]:
            assert f'"{key}"' not in text

    def test_article_15_indirect_is_true(self) -> None:
        """GraQle is NOT itself a high-risk AI system — this flag asserts that."""
        a = build_robustness_attestation().to_dict()
        assert a["article_15_indirect"] is True

    def test_article_15_aligned_is_true(self) -> None:
        """The marketing-claim-grade boolean — "this SDK ships these defences"."""
        a = build_robustness_attestation().to_dict()
        assert a["article_15_aligned"] is True


# ---------------------------------------------------------------------------
# TestCLIIntegration — graq compliance status --include-robustness
# ---------------------------------------------------------------------------


class TestCLIIntegration:
    def test_status_includes_robustness_when_flagged(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            [
                "status",
                "--include-robustness",
                "--format", "json",
                "--repo-root", str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output
        idx = result.output.find("{")
        payload = json.loads(result.output[idx:])
        assert "robustness" in payload
        assert payload["robustness"]["article_15_aligned"] is True

    def test_status_omits_robustness_when_not_flagged(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            ["status", "--format", "json", "--repo-root", str(tmp_path)],
        )
        assert result.exit_code == 0, result.output
        idx = result.output.find("{")
        payload = json.loads(result.output[idx:])
        # robustness only appears when --include-robustness is set.
        assert "robustness" not in payload

    def test_text_mode_renders_robustness_section(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            compliance_app,
            ["status", "--include-robustness", "--repo-root", str(tmp_path)],
        )
        assert result.exit_code == 0, result.output
        # Rich may wrap the title across lines — look for distinctive
        # phrases that appear regardless of line wrap.
        haystack = result.output.lower()
        assert "article 15" in haystack or "robustness" in haystack


# ---------------------------------------------------------------------------
# TestDriftGuard — defence inventory mirrors the Article 15 doc
# ---------------------------------------------------------------------------


class TestDriftGuard:
    def test_defence_ids_align_with_authoritative_docs(self) -> None:
        """Each defence id has at least one token in EITHER the Article 15
        doc OR SECURITY.md (for supply-chain entries).

        Token-anchor approach because the doc/SECURITY.md use prose
        like "CR-003 edge-loss shrink guard" rather than literal kebab
        ids. Either source counts as a valid anchor.
        """
        repo_root = Path(__file__).resolve().parents[2]
        article_15_doc = (
            repo_root
            / "docs"
            / "compliance"
            / "eu-ai-act"
            / "article-15-robustness.md"
        ).read_text(encoding="utf-8")
        security_md = (repo_root / "SECURITY.md").read_text(encoding="utf-8")
        combined_corpus = (article_15_doc + "\n" + security_md).lower()
        combined_upper = article_15_doc + "\n" + security_md

        a = build_robustness_attestation().to_dict()
        for d in a["defences"]:
            id_ = d["id"]
            tokens = [t for t in id_.split("-") if len(t) > 2]
            found = any(
                t.lower() in combined_corpus
                or t.upper() in combined_upper
                for t in tokens
            )
            assert found, (
                f"Defence id {id_!r} has no token in article-15-robustness.md "
                "or SECURITY.md. Either an anchor has drifted or the id "
                "should be renamed."
            )

    def test_security_email_matches_security_md(self) -> None:
        """The email in the attestation must match SECURITY.md."""
        repo_root = Path(__file__).resolve().parents[2]
        security_md = (repo_root / "SECURITY.md").read_text(encoding="utf-8")
        a = build_robustness_attestation().to_dict()
        assert a["security_disclosure_email"] in security_md, (
            f"Email {a['security_disclosure_email']!r} not present in SECURITY.md — "
            "drift between robustness attestation and canonical security policy."
        )
