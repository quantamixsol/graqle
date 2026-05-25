"""Mode B runtime governance: attach GraQle to a FastAPI app as middleware.

ADR-221 §4.1 (R1). Every JSON decision response flowing through the app is captured
as a PII-safe, tamper-evidence-ready governed trace — with NO change to the decision
code. The capture runs as a background task (0 ms added to the user's response) and
the per-domain mapping is fail-closed (an unmapped field is never stored).

Run::

    pip install graqle[api]      # fastapi + uvicorn + httpx
    python examples/runtime_middleware_fastapi.py

It uses an in-memory sink and prints the captured record so you can see exactly what
is (and is not) stored. In production you would use the default durable JSONL sink and
the R2 ``graqle govern serve`` worker to Merkle-batch + Rekor-anchor it.
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from graqle.governance.runtime import GovernedRuntime, InMemorySink
from graqle.governance.runtime.fastapi import GraqleGovernanceMiddleware
from graqle.governance.runtime.mapping import DomainMapping


def build_app(runtime: GovernedRuntime) -> Starlette:
    # In a real app: mapping="loan_mapping.yaml" (a file). Here we build it inline.
    loan_mapping = DomainMapping(
        domain="loan",
        identity={"applicant_id": "pseudonymize"},   # never stored raw
        hash_only=("features",),                       # hashed into content_hash
        governance=("decision", "reason_code", "confidence"),  # leaf metadata
        drop=("raw_pii",),                             # never stored
    )

    def score(request):
        # The deployed AI's decision endpoint — untouched by governance.
        return JSONResponse(
            {
                "applicant_id": "alice@example.com",   # PII -> pseudonymised
                "features": {"income": 95000, "age": 41},  # PII -> hashed only
                "decision": "approve",                  # -> leaf
                "reason_code": "R12",                   # -> leaf
                "confidence": 0.91,                     # -> leaf
                "raw_pii": "SSN 123-45-6789",           # -> dropped, never stored
            }
        )

    app = Starlette(routes=[Route("/score", score, methods=["GET"])])
    app.add_middleware(
        GraqleGovernanceMiddleware,
        mapping=loan_mapping,
        model_id="credit-risk-v4",
        policy_id="loan-policy-2026Q2",
        runtime=runtime,
    )
    return app


def main() -> None:
    sink = InMemorySink()
    runtime = GovernedRuntime(sink=sink, salt="demo-salt")
    app = build_app(runtime)

    client = TestClient(app)
    resp = client.get("/score")
    print("HTTP", resp.status_code, "-> client sees full decision:", resp.json()["decision"])

    # The background capture has run by the time TestClient returns.
    assert len(sink.records) == 1, "expected exactly one captured decision"
    record = sink.records[0]

    print("\nCaptured governed-trace record (what GraQle stores):")
    for key in (
        "domain",
        "model_id",
        "policy_id",
        "record_id",
        "content_hash",
        "leaf_hash_hex",
        "governance_metadata",
    ):
        print(f"  {key}: {record[key]}")

    blob = repr(record)
    assert "alice@example.com" not in blob, "raw identity leaked!"
    assert "95000" not in blob, "raw feature leaked!"
    assert "123-45-6789" not in blob, "dropped PII leaked!"
    print("\nPII discipline verified: no raw identity / features / dropped PII in the record.")


if __name__ == "__main__":
    main()
