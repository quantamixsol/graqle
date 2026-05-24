"""Tests for the Mode A runtime-capture layer (ADR-221 §4.1 / R0).

Verifies that GovernedRuntime.attest() produces a leaf-hash-compatible GovernedTrace
record, keeps PII out of the leaf, is durable, and is byte-compatible with the
shipped Layer 5 leaf-hash primitive. No live anchoring — the sink is pluggable.
"""

from __future__ import annotations

import json
import math

import pytest

from graqle.governance.runtime import (
    AttestationSink,
    DurableJsonlSink,
    GovernedRuntime,
    InMemorySink,
    RuntimeDecision,
    pseudonymize,
)
from graqle.governance.runtime.runtime import PROOF_FORMAT_VERSION
from graqle.governance.tamper_evidence.leaf_input_schema import (
    LEAF_HASH_FIELDS,
    project_leaf_input,
)
from graqle.governance.tamper_evidence.merkle import leaf_hash_for_record


def _gov():
    sink = InMemorySink()
    return GovernedRuntime(sink=sink), sink


# ---- pseudonymize -----------------------------------------------------------


class TestPseudonymize:
    def test_stable_and_prefixed(self):
        a = pseudonymize("cust-42")
        assert a == pseudonymize("cust-42")  # deterministic
        assert a.startswith("anon-")
        assert "cust-42" not in a  # irreversible-by-inspection

    def test_salt_changes_output(self):
        assert pseudonymize("cust-42", salt="x") != pseudonymize("cust-42", salt="y")

    def test_runtime_pseudonymize_ref_uses_salt(self):
        gov = GovernedRuntime(sink=InMemorySink(), salt="deploy-salt")
        assert gov.pseudonymize_ref("cust-42") == pseudonymize("cust-42", salt="deploy-salt")


# ---- attest: record shape ---------------------------------------------------


class TestAttestRecordShape:
    def test_leaf_fields_present_and_exact(self):
        gov, sink = _gov()
        rec = gov.attest(domain="loan", model_id="m1", output={"decision": "DECLINE"})
        leaf = project_leaf_input(rec)
        assert set(leaf) == set(LEAF_HASH_FIELDS)
        assert rec["proof_format_version"] == PROOF_FORMAT_VERSION
        assert rec["governance_metadata"]["decision"] == "DECLINE"
        assert rec["governance_metadata"]["domain"] == "loan"
        assert rec["governance_metadata"]["model_id"] == "m1"

    def test_leaf_hash_matches_shipped_primitive(self):
        # The whole point: a runtime record's leaf hash == what the Layer 5
        # batcher/committer would compute for the same leaf fields.
        gov, sink = _gov()
        rec = gov.attest(domain="loan", model_id="m1", output={"decision": "APPROVE"})
        expected = leaf_hash_for_record(rec).hex()
        assert rec["leaf_hash_hex"] == expected

    def test_record_written_to_sink(self):
        gov, sink = _gov()
        rec = gov.attest(domain="loan", model_id="m1", output={"decision": "DECLINE"})
        assert sink.records == [rec]

    def test_auto_decision_id_is_unique(self):
        gov, sink = _gov()
        r1 = gov.attest(domain="loan", model_id="m1", output={"decision": "X"})
        r2 = gov.attest(domain="loan", model_id="m1", output={"decision": "X"})
        assert r1["record_id"] != r2["record_id"]

    def test_explicit_decision_id_used(self):
        gov, sink = _gov()
        rec = gov.attest(
            domain="loan", model_id="m1", output={"decision": "X"}, decision_id="app-7"
        )
        assert rec["record_id"] == "app-7"

    def test_explicit_timestamp_used(self):
        gov, sink = _gov()
        rec = gov.attest(
            domain="loan", model_id="m1", output={"decision": "X"}, timestamp_unix=1_780_000_000
        )
        assert rec["timestamp_unix"] == 1_780_000_000

    def test_wrapper_fields_present(self):
        gov, sink = _gov()
        rec = gov.attest(
            domain="health", model_id="triage-v2", output={"decision": "ADMIT"},
            policy_id="policy-9",
        )
        assert rec["domain"] == "health"
        assert rec["model_id"] == "triage-v2"
        assert rec["policy_id"] == "policy-9"
        assert rec["_runtime_attestation"] is True
        assert "created_at_iso" in rec


# ---- attest: PII discipline + content hash ----------------------------------


class TestPiiDiscipline:
    def test_raw_inputs_not_in_record(self):
        gov, sink = _gov()
        rec = gov.attest(
            domain="loan", model_id="m1", output={"decision": "DECLINE"},
            inputs={"applicant_ref": pseudonymize("cust-42"), "features_hash": "sha256:abc"},
        )
        blob = json.dumps(rec)
        assert "cust-42" not in blob  # the raw id never appears
        assert "applicant_ref" not in rec  # inputs are not stored raw on the record
        assert rec["content_hash"].startswith("sha256:")

    def test_content_hash_changes_with_inputs(self):
        gov, sink = _gov()
        r1 = gov.attest(domain="loan", model_id="m1", output={"decision": "X"},
                        inputs={"f": "a"})
        r2 = gov.attest(domain="loan", model_id="m1", output={"decision": "X"},
                        inputs={"f": "b"})
        assert r1["content_hash"] != r2["content_hash"]

    def test_content_hash_changes_with_output(self):
        gov, sink = _gov()
        r1 = gov.attest(domain="loan", model_id="m1", output={"decision": "APPROVE"})
        r2 = gov.attest(domain="loan", model_id="m1", output={"decision": "DECLINE"})
        assert r1["content_hash"] != r2["content_hash"]

    def test_content_hash_deterministic(self):
        gov, sink = _gov()
        r1 = gov.attest(domain="loan", model_id="m1", output={"decision": "X"},
                        inputs={"f": "a"}, decision_id="d", timestamp_unix=1)
        r2 = gov.attest(domain="loan", model_id="m1", output={"decision": "X"},
                        inputs={"f": "a"}, decision_id="d", timestamp_unix=1)
        assert r1["content_hash"] == r2["content_hash"]
        assert r1["leaf_hash_hex"] == r2["leaf_hash_hex"]

    def test_non_canonical_payload_rejected(self):
        gov, sink = _gov()
        with pytest.raises(Exception) as ei:
            gov.attest(domain="loan", model_id="m1", output={"score": math.nan})
        assert "Float" in type(ei.value).__name__
        assert sink.records == []  # nothing recorded on failure


class TestAttestValidation:
    @pytest.mark.parametrize("bad", ["", None, 123])
    def test_empty_or_nonstring_domain_raises(self, bad):
        gov, sink = _gov()
        with pytest.raises(ValueError, match="domain"):
            gov.attest(domain=bad, model_id="m1", output={"decision": "X"})
        assert sink.records == []

    @pytest.mark.parametrize("bad", ["", None, 123])
    def test_empty_or_nonstring_model_id_raises(self, bad):
        gov, sink = _gov()
        with pytest.raises(ValueError, match="model_id"):
            gov.attest(domain="loan", model_id=bad, output={"decision": "X"})
        assert sink.records == []

    @pytest.mark.parametrize("bad", [None, "not-a-dict", 123, ["a"]])
    def test_non_dict_output_raises(self, bad):
        gov, sink = _gov()
        with pytest.raises(ValueError, match="output must be a dict"):
            gov.attest(domain="loan", model_id="m1", output=bad)
        assert sink.records == []

    @pytest.mark.parametrize("bad", ["not-a-dict", 123, ["a"]])
    def test_non_dict_inputs_raises(self, bad):
        gov, sink = _gov()
        with pytest.raises(ValueError, match="inputs must be a dict"):
            gov.attest(domain="loan", model_id="m1", output={"decision": "X"}, inputs=bad)
        assert sink.records == []

    def test_none_inputs_allowed(self):
        gov, sink = _gov()
        rec = gov.attest(domain="loan", model_id="m1", output={"decision": "X"}, inputs=None)
        assert len(sink.records) == 1
        assert rec["content_hash"].startswith("sha256:")

    def test_oversized_record_rejected(self):
        from graqle.governance.runtime.runtime import MAX_RECORD_BYTES

        gov, sink = _gov()
        # reason_code IS promoted into governance_metadata (lands in the record), so
        # an oversized one blows past the bound — unlike an arbitrary output field,
        # which is folded into the fixed-size content_hash and never stored.
        huge = "x" * (MAX_RECORD_BYTES + 1)
        with pytest.raises(ValueError, match="MAX_RECORD_BYTES"):
            gov.attest(domain="loan", model_id="m1",
                       output={"decision": "X"}, reason_code=huge)
        assert sink.records == []  # nothing written

    def test_record_at_normal_size_accepted(self):
        gov, sink = _gov()
        rec = gov.attest(domain="loan", model_id="m1",
                         output={"decision": "DECLINE", "reason_code": "DTI",
                                 "explanation": "debt-to-income above policy threshold"})
        assert len(sink.records) == 1
        assert rec["governance_metadata"]["decision"] == "DECLINE"


# ---- governance_metadata promotions -----------------------------------------


class TestGovernanceMetadata:
    def test_promotions_into_metadata(self):
        gov, sink = _gov()
        rec = gov.attest(
            domain="recruitment", model_id="screen-v1", output={"decision": "REJECT"},
            reason_code="BELOW_BAR", confidence=0.87, human_review="not_required",
        )
        md = rec["governance_metadata"]
        assert md["reason_code"] == "BELOW_BAR"
        assert md["confidence"] == 0.87
        assert md["human_review"] == "not_required"

    def test_reason_code_falls_back_to_output(self):
        gov, sink = _gov()
        rec = gov.attest(
            domain="loan", model_id="m1",
            output={"decision": "DECLINE", "reason_code": "DTI"},
        )
        assert rec["governance_metadata"]["reason_code"] == "DTI"

    def test_explicit_reason_code_overrides_output(self):
        gov, sink = _gov()
        rec = gov.attest(
            domain="loan", model_id="m1",
            output={"decision": "DECLINE", "reason_code": "FROM_OUTPUT"},
            reason_code="EXPLICIT",
        )
        assert rec["governance_metadata"]["reason_code"] == "EXPLICIT"

    def test_no_optional_metadata_keys_when_absent(self):
        gov, sink = _gov()
        rec = gov.attest(domain="loan", model_id="m1", output={"decision": "X"})
        md = rec["governance_metadata"]
        assert "confidence" not in md
        assert "human_review" not in md
        assert "reason_code" not in md


# ---- RuntimeDecision structured form ----------------------------------------


class TestAttestDecision:
    def test_attest_decision_roundtrip(self):
        gov, sink = _gov()
        d = RuntimeDecision(
            domain="loan", model_id="m1",
            governance_metadata={"reason_code": "DTI", "confidence": 0.9},
            inputs={"f": pseudonymize("x")},
            output={"decision": "DECLINE"},
            decision_id="app-1", timestamp_unix=1_780_000_000, policy_id="p1",
        )
        rec = gov.attest_decision(d)
        assert rec["record_id"] == "app-1"
        assert rec["timestamp_unix"] == 1_780_000_000
        assert rec["policy_id"] == "p1"
        assert rec["governance_metadata"]["reason_code"] == "DTI"
        assert rec["governance_metadata"]["confidence"] == 0.9

    def test_runtime_decision_defaults(self):
        d = RuntimeDecision(domain="loan", model_id="m1", governance_metadata={})
        assert d.inputs == {}
        assert d.output == {}
        assert d.decision_id == ""
        assert d.timestamp_unix == 0
        assert d.policy_id is None


# ---- sinks ------------------------------------------------------------------


class TestSinks:
    def test_durable_jsonl_sink_writes_and_reads_back(self, tmp_path):
        sink = DurableJsonlSink(directory=tmp_path)
        gov = GovernedRuntime(sink=sink)
        rec = gov.attest(domain="loan", model_id="m1", output={"decision": "DECLINE"})
        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1
        lines = files[0].read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        stored = json.loads(lines[0])
        assert stored["record_id"] == rec["record_id"]
        assert stored["leaf_hash_hex"] == rec["leaf_hash_hex"]

    def test_durable_jsonl_sink_appends(self, tmp_path):
        sink = DurableJsonlSink(directory=tmp_path)
        gov = GovernedRuntime(sink=sink)
        gov.attest(domain="loan", model_id="m1", output={"decision": "A"})
        gov.attest(domain="loan", model_id="m1", output={"decision": "B"})
        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1
        assert len(files[0].read_text(encoding="utf-8").splitlines()) == 2

    def test_default_runtime_uses_durable_sink(self):
        gov = GovernedRuntime()
        assert isinstance(gov._sink, DurableJsonlSink)

    def test_durable_sink_file_is_owner_only_on_posix(self, tmp_path):
        # On POSIX the attestation file must be 0o600 (owner-only) — audit material
        # must not be world-readable. Windows ignores POSIX perms, so assert there
        # only that the file was created.
        import os
        import stat

        sink = DurableJsonlSink(directory=tmp_path)
        GovernedRuntime(sink=sink).attest(domain="loan", model_id="m1", output={"decision": "X"})
        f = next(tmp_path.glob("*.jsonl"))
        assert f.exists()
        if os.name == "posix":
            mode = stat.S_IMODE(f.stat().st_mode)
            assert mode & 0o077 == 0, f"file is group/world-accessible: {oct(mode)}"

    def test_in_memory_sink_is_attestation_sink(self):
        # the Protocol is runtime-checkable
        assert isinstance(InMemorySink(), AttestationSink)
        assert isinstance(DurableJsonlSink(), AttestationSink)

    def test_sink_failure_propagates(self):
        class BoomSink:
            def write(self, record):
                raise RuntimeError("sink down")

        gov = GovernedRuntime(sink=BoomSink())
        with pytest.raises(RuntimeError, match="sink down"):
            gov.attest(domain="loan", model_id="m1", output={"decision": "X"})


# ---- end-to-end: a runtime record verifies like a Layer 5 leaf --------------


class TestConcurrency:
    def test_shared_runtime_attest_is_thread_safe(self):
        # GovernedRuntime is documented "safe to share"; back that claim. Many
        # threads call attest() on ONE shared runtime + sink; every decision must
        # be captured exactly once with no lost/corrupted records.
        import threading

        gov, sink = _gov()
        n_threads, per_thread = 20, 50
        barrier = threading.Barrier(n_threads)
        errors: list[BaseException] = []

        def worker(tid: int) -> None:
            try:
                barrier.wait()
                for i in range(per_thread):
                    gov.attest(
                        domain="loan", model_id="m1",
                        output={"decision": "DECLINE"},
                        decision_id=f"t{tid}-i{i}",
                    )
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"thread errors: {errors!r}"
        assert len(sink.records) == n_threads * per_thread  # none lost
        ids = {r["record_id"] for r in sink.records}
        assert len(ids) == n_threads * per_thread  # none duplicated/corrupted


class TestRuntimeRecordIsLayer5Compatible:
    def test_runtime_leaf_hash_recomputable_by_a_verifier(self):
        # A verifier holding only the record recomputes the leaf hash from the
        # frozen leaf fields — exactly the Layer 5 verification entry point.
        gov, sink = _gov()
        rec = gov.attest(domain="loan", model_id="credit-risk-v4",
                         output={"decision": "DECLINE", "reason_code": "DTI"},
                         inputs={"applicant_ref": pseudonymize("cust-9")})
        recomputed = leaf_hash_for_record(project_leaf_input(rec)).hex()
        assert recomputed == rec["leaf_hash_hex"]
