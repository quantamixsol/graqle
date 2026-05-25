"""Tests for the fail-closed per-domain capture mapping (ADR-221 §4.3 / R1).

The mapping is the load-bearing PII control for Mode B: a middleware sees whole
payloads, so the safety property "an unmapped field is dropped, never stored raw" is
verified here exhaustively.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from graqle.governance.runtime import GovernedRuntime, InMemorySink
from graqle.governance.runtime.mapping import (
    DomainMapping,
    MappingError,
    load_mapping,
)


def _runtime() -> GovernedRuntime:
    return GovernedRuntime(sink=InMemorySink(), salt="unit-test-salt")


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "m_mapping.yaml"
    p.write_text(text, encoding="utf-8")
    return p


# --- load_mapping validation -------------------------------------------------


class TestLoadValidation:
    def test_loads_full_mapping(self, tmp_path):
        p = _write(
            tmp_path,
            "domain: loan\n"
            "identity: {applicant_id: pseudonymize}\n"
            "hash_only: [features, documents]\n"
            "governance: [decision, reason_code, confidence, human_review]\n"
            "drop: [raw_pii]\n",
        )
        m = load_mapping(p)
        assert m.domain == "loan"
        assert m.identity == {"applicant_id": "pseudonymize"}
        assert m.hash_only == ("features", "documents")
        assert m.governance == ("decision", "reason_code", "confidence", "human_review")
        assert m.drop == ("raw_pii",)

    def test_minimal_mapping_domain_only(self, tmp_path):
        m = load_mapping(_write(tmp_path, "domain: triage\n"))
        assert m.domain == "triage"
        assert m.identity == {} and m.hash_only == () and m.governance == ()

    def test_missing_file(self, tmp_path):
        with pytest.raises(MappingError, match="not found"):
            load_mapping(tmp_path / "nope.yaml")

    def test_not_a_mapping(self, tmp_path):
        with pytest.raises(MappingError, match="YAML mapping"):
            load_mapping(_write(tmp_path, "- just\n- a\n- list\n"))

    def test_invalid_yaml(self, tmp_path):
        with pytest.raises(MappingError, match="not valid YAML"):
            load_mapping(_write(tmp_path, "domain: [unclosed\n"))

    def test_missing_domain(self, tmp_path):
        with pytest.raises(MappingError, match="domain"):
            load_mapping(_write(tmp_path, "governance: [decision]\n"))

    def test_empty_domain(self, tmp_path):
        with pytest.raises(MappingError, match="domain"):
            load_mapping(_write(tmp_path, "domain: ''\n"))

    def test_unknown_top_level_key(self, tmp_path):
        with pytest.raises(MappingError, match="unknown mapping key"):
            load_mapping(_write(tmp_path, "domain: loan\nsmuggle: [x]\n"))

    def test_identity_not_a_dict(self, tmp_path):
        with pytest.raises(MappingError, match="identity"):
            load_mapping(_write(tmp_path, "domain: loan\nidentity: [a, b]\n"))

    def test_identity_unknown_transform(self, tmp_path):
        with pytest.raises(MappingError, match="transform"):
            load_mapping(
                _write(tmp_path, "domain: loan\nidentity: {x: pseudonimize}\n")
            )

    def test_identity_empty_field_name(self, tmp_path):
        with pytest.raises(MappingError, match="non-empty field names"):
            load_mapping(_write(tmp_path, "domain: loan\nidentity: {'': pseudonymize}\n"))

    def test_hash_only_not_a_list(self, tmp_path):
        with pytest.raises(MappingError, match="hash_only.*must be a list"):
            load_mapping(_write(tmp_path, "domain: loan\nhash_only: features\n"))

    def test_governance_entries_must_be_strings(self, tmp_path):
        with pytest.raises(MappingError, match="non-empty strings"):
            load_mapping(_write(tmp_path, "domain: loan\ngovernance: [1, 2]\n"))

    def test_field_in_two_sections_rejected(self, tmp_path):
        with pytest.raises(MappingError, match="only one way"):
            load_mapping(
                _write(
                    tmp_path,
                    "domain: loan\nhash_only: [features]\ngovernance: [features]\n",
                )
            )

    def test_identity_field_collision_with_drop(self, tmp_path):
        with pytest.raises(MappingError, match="only one way"):
            load_mapping(
                _write(
                    tmp_path,
                    "domain: loan\nidentity: {x: pseudonymize}\ndrop: [x]\n",
                )
            )

    def test_accepts_pathlib_and_str(self, tmp_path):
        p = _write(tmp_path, "domain: loan\n")
        assert load_mapping(p).domain == "loan"
        assert load_mapping(str(p)).domain == "loan"

    def test_rejects_invalid_field_name_in_section(self, tmp_path):
        with pytest.raises(MappingError, match="not a valid identifier"):
            load_mapping(
                _write(tmp_path, "domain: loan\ngovernance: ['bad name with spaces']\n")
            )

    def test_rejects_invalid_identity_field_name(self, tmp_path):
        with pytest.raises(MappingError, match="not a valid identifier"):
            load_mapping(
                _write(tmp_path, "domain: loan\nidentity: {'has space': pseudonymize}\n")
            )

    def test_accepts_dotted_and_hyphenated_field_names(self, tmp_path):
        m = load_mapping(
            _write(tmp_path, "domain: loan\ngovernance: [user.decision, reason-code]\n")
        )
        assert m.governance == ("user.decision", "reason-code")


# --- DomainMapping.apply (the fail-closed router) ----------------------------


class TestApplyRouting:
    def _loan(self) -> DomainMapping:
        return DomainMapping(
            domain="loan",
            identity={"applicant_id": "pseudonymize"},
            hash_only=("features",),
            governance=("decision", "reason_code", "confidence"),
            drop=("raw_pii",),
        )

    def test_identity_is_pseudonymized_never_raw(self):
        rt = _runtime()
        payload = {"applicant_id": "alice@example.com", "decision": "approve"}
        inputs, output, gov = self._loan().apply(payload, rt)
        assert "applicant_id_ref" in inputs
        assert inputs["applicant_id_ref"].startswith("anon-")
        # raw identity value appears nowhere
        flat = repr(inputs) + repr(output) + repr(gov)
        assert "alice@example.com" not in flat

    def test_hash_only_field_hashed_not_stored(self):
        rt = _runtime()
        payload = {"features": {"income": 95000, "age": 41}, "decision": "approve"}
        inputs, output, gov = self._loan().apply(payload, rt)
        assert inputs["features_hash"].startswith("sha256:")
        # raw value not present anywhere
        flat = repr(inputs) + repr(output) + repr(gov)
        assert "95000" not in flat and "income" not in flat

    def test_governance_fields_surface_in_metadata(self):
        rt = _runtime()
        payload = {"decision": "approve", "reason_code": "R12", "confidence": 0.91}
        inputs, output, gov = self._loan().apply(payload, rt)
        assert gov == {"decision": "approve", "reason_code": "R12", "confidence": 0.91}
        assert output == gov

    def test_unmapped_field_is_dropped_even_without_drop_entry(self):
        """The core fail-closed property: a field nobody mapped is silently dropped."""
        rt = _runtime()
        # 'ssn' is in NO section at all (not even drop). Must not surface.
        payload = {"decision": "approve", "ssn": "123-45-6789", "applicant_id": "u1"}
        inputs, output, gov = self._loan().apply(payload, rt)
        flat = repr(inputs) + repr(output) + repr(gov)
        assert "123-45-6789" not in flat
        assert "ssn" not in flat

    def test_explicitly_dropped_field_not_stored(self):
        rt = _runtime()
        payload = {"decision": "deny", "raw_pii": "sensitive note"}
        inputs, output, gov = self._loan().apply(payload, rt)
        flat = repr(inputs) + repr(output) + repr(gov)
        assert "sensitive note" not in flat

    def test_absent_mapped_fields_are_skipped(self):
        rt = _runtime()
        # payload missing applicant_id/features — no KeyError, just omitted
        inputs, output, gov = self._loan().apply({"decision": "approve"}, rt)
        assert "applicant_id_ref" not in inputs
        assert "features_hash" not in inputs
        assert gov == {"decision": "approve"}

    def test_hash_only_str_and_dict_stable(self):
        rt = _runtime()
        m = DomainMapping(domain="d", hash_only=("blob",))
        # dict order should not change the hash
        a, _, _ = m.apply({"blob": {"a": 1, "b": 2}}, rt)
        b, _, _ = m.apply({"blob": {"b": 2, "a": 1}}, rt)
        assert a["blob_hash"] == b["blob_hash"]

    def test_hash_only_string_field(self):
        """A string hash_only field hashes by its UTF-8 bytes (str branch)."""
        rt = _runtime()
        m = DomainMapping(domain="d", hash_only=("note",))
        out, _, _ = m.apply({"note": "free text"}, rt)
        import hashlib

        expected = "sha256:" + hashlib.sha256(b"free text").hexdigest()
        assert out["note_hash"] == expected

    def test_apply_rejects_non_dict_payload(self):
        rt = _runtime()
        with pytest.raises(MappingError, match="must be a dict"):
            self._loan().apply(["not", "a", "dict"], rt)  # type: ignore[arg-type]

    def test_end_to_end_attest_through_mapping(self):
        """apply() output drives attest() and produces a PII-free leaf record."""
        sink = InMemorySink()
        rt = GovernedRuntime(sink=sink, salt="s")
        m = self._loan()
        payload = {
            "applicant_id": "alice@example.com",
            "features": {"income": 95000},
            "decision": "approve",
            "reason_code": "R7",
            "confidence": 0.88,
        }
        inputs, output, gov = m.apply(payload, rt)
        promoted = {k: gov[k] for k in ("reason_code", "confidence") if k in gov}
        rec = rt.attest(
            domain=m.domain, model_id="credit-v4", output=output, inputs=inputs, **promoted
        )
        assert len(sink.records) == 1
        leaf_meta = rec["governance_metadata"]
        assert leaf_meta["decision"] == "approve"
        assert leaf_meta["reason_code"] == "R7"
        # No raw PII anywhere in the stored record
        blob = repr(sink.records[0])
        assert "alice@example.com" not in blob
        assert "95000" not in blob
