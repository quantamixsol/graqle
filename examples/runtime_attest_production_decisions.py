"""Runtime Governance Layer — Mode A: attach GraQle to a deployed AI system.

ADR-221 R0. Shows the "one added line" pattern: an AI system already in production
keeps making decisions, and `GovernedRuntime.attest()` turns each one into a durable,
PII-safe, tamper-evidence-ready governed record on the Layer 5 substrate — without
changing the model or blocking the request path.

This simulates a deployed loan-scoring service handling a stream of applications.
Each decision is attested; then we show the durable audit trail it produced and that
each record's Merkle leaf hash is recomputable by any verifier (the Layer 5 promise).

Run against the installed package:

    python -m venv demo-venv
    demo-venv/bin/python -m pip install graqle           # or graqle==0.59.0+
    demo-venv/bin/python examples/runtime_attest_production_decisions.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from graqle.governance.runtime import DurableJsonlSink, GovernedRuntime
from graqle.governance.tamper_evidence.leaf_input_schema import project_leaf_input
from graqle.governance.tamper_evidence.merkle import leaf_hash_for_record


# --- the deployed AI system (already in production, UNCHANGED) ----------------
def loan_model_predict(application: dict) -> dict:
    """Stand-in for your real deployed model. GraQle never touches this."""
    dti = application["debt_to_income"]
    if dti > 0.43:
        return {"decision": "DECLINE", "reason_code": "DTI_ABOVE_THRESHOLD", "confidence": 0.91}
    return {"decision": "APPROVE", "reason_code": "WITHIN_POLICY", "confidence": 0.88}


def main() -> None:
    # In production you'd point the sink at durable storage (and later swap in the
    # R2 anchoring worker). Here we use a temp dir so the example is self-contained.
    with tempfile.TemporaryDirectory() as d:
        gov = GovernedRuntime(sink=DurableJsonlSink(directory=d), salt="bank-deploy-salt")

        incoming = [
            {"applicant_id": "cust-1001", "debt_to_income": 0.52},
            {"applicant_id": "cust-1002", "debt_to_income": 0.31},
            {"applicant_id": "cust-1003", "debt_to_income": 0.47},
        ]

        print("=== Deployed loan service handling a stream of decisions ===")
        for app in incoming:
            decision = loan_model_predict(app)             # the AI decides
            # PII discipline: the record_id is an OPAQUE case ref (pseudonym), never
            # the raw customer id — so no personal data enters the governed record.
            case_ref = gov.pseudonymize_ref(app["applicant_id"])
            record = gov.attest(                            # <-- the one added line
                domain="loan",
                model_id="credit-risk-v4",
                inputs={
                    "applicant_ref": case_ref,             # PII-safe pseudonym
                    "dti_bucket": "high" if app["debt_to_income"] > 0.43 else "ok",
                },
                output=decision,
                decision_id=case_ref,                       # opaque, not the raw id
            )
            print(f"  {decision['decision']:8} {app['applicant_id']} -> {case_ref}  "
                  f"leaf={record['leaf_hash_hex'][:16]}...  reason={decision['reason_code']}")

        # --- the durable audit trail it produced --------------------------------
        files = list(Path(d).glob("*.jsonl"))
        lines = files[0].read_text(encoding="utf-8").splitlines()
        print(f"\n=== Durable audit trail: {len(lines)} attested records in {files[0].name} ===")

        # --- a verifier recomputes each leaf hash with ZERO access to the bank ---
        import json
        print("\n=== Verifier recomputes every leaf hash (Layer 5 promise) ===")
        all_ok = True
        for line in lines:
            rec = json.loads(line)
            recomputed = leaf_hash_for_record(project_leaf_input(rec)).hex()
            ok = recomputed == rec["leaf_hash_hex"]
            all_ok = all_ok and ok
            print(f"  {rec['record_id']}  leaf verifies: {ok}")
            # the raw applicant id must NOT be present anywhere in the record
            assert "cust-" not in line, "PII leaked into the audit record!"

        print("\n" + "#" * 66)
        print("RUNTIME ATTEST COMPLETE - every production decision is now governed:")
        print("  model decides -> attest() (PII-safe, 0ms write path) -> durable trail")
        print("  -> any verifier recomputes the leaf hash with no bank/GraQle access.")
        print("  (swap the sink for the R2 anchoring worker -> Merkle + Rekor anchor.)")
        print("#" * 66)
        assert all_ok


if __name__ == "__main__":
    main()
