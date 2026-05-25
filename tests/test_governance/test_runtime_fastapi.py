"""Tests for the Mode B FastAPI/Starlette attachment (ADR-221 §4.1 / R1).

Covers the @governed decorator (sync + async) and GraqleGovernanceMiddleware
(background capture, JSON-only, header overrides, fail-open vs fail-closed).

Starlette + httpx are core deps but gated with importorskip so a minimal env (or a CI
job without the web extras) skips cleanly rather than erroring at collection time
(lesson_20260430T213750: an unguarded optional-dep import blocks the whole suite).
"""

from __future__ import annotations

import logging

import pytest

# importorskip BEFORE importing the middleware builder (it imports starlette lazily,
# but TestClient needs httpx + starlette present to exercise it).
starlette = pytest.importorskip("starlette")
pytest.importorskip("httpx")

from starlette.applications import Starlette  # noqa: E402
from starlette.responses import JSONResponse, PlainTextResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from graqle.governance.runtime import (  # noqa: E402
    GovernedRuntime,
    InMemorySink,
    governed,
)
from graqle.governance.runtime.fastapi import GraqleGovernanceMiddleware  # noqa: E402
from graqle.governance.runtime.mapping import DomainMapping  # noqa: E402


def _loan_mapping() -> DomainMapping:
    return DomainMapping(
        domain="loan",
        identity={"applicant_id": "pseudonymize"},
        hash_only=("features",),
        governance=("decision", "reason_code", "confidence"),
        drop=("raw_pii",),
    )


def _runtime_with_sink():
    sink = InMemorySink()
    return GovernedRuntime(sink=sink, salt="t"), sink


# --- @governed decorator -----------------------------------------------------


class TestGovernedDecorator:
    def test_sync_function_captured(self):
        rt, sink = _runtime_with_sink()

        @governed(domain="loan", mapping=_loan_mapping(), model_id="m1", runtime=rt)
        def decide(payload):
            return {"applicant_id": payload["id"], "decision": "approve"}

        out = decide({"id": "u1"})
        assert out["decision"] == "approve"  # original return passes through
        assert len(sink.records) == 1
        assert sink.records[0]["governance_metadata"]["decision"] == "approve"

    @pytest.mark.anyio
    async def test_async_function_captured(self):
        rt, sink = _runtime_with_sink()

        @governed(mapping=_loan_mapping(), runtime=rt)
        async def decide(payload):
            return {"decision": "deny", "applicant_id": payload["id"]}

        out = await decide({"id": "u2"})
        assert out["decision"] == "deny"
        assert len(sink.records) == 1

    def test_domain_mismatch_rejected(self):
        with pytest.raises(ValueError, match="does not match mapping domain"):

            @governed(domain="recruitment", mapping=_loan_mapping())
            def f(p):
                return {}

    def test_invalid_on_error_rejected(self):
        with pytest.raises(ValueError, match="on_error"):

            @governed(mapping=_loan_mapping(), on_error="explode")
            def f(p):
                return {}

    def test_non_dict_return_fail_open_logs(self, caplog):
        rt, sink = _runtime_with_sink()

        @governed(mapping=_loan_mapping(), runtime=rt, on_error="log")
        def decide(payload):
            return "not a dict"

        with caplog.at_level(logging.ERROR):
            assert decide({}) == "not a dict"
        assert len(sink.records) == 0
        assert "capture_failed" in caplog.text

    def test_non_dict_return_fail_closed_raises(self):
        rt, _ = _runtime_with_sink()

        @governed(mapping=_loan_mapping(), runtime=rt, on_error="raise")
        def decide(payload):
            return 123

        with pytest.raises(TypeError, match="expects the decorated function"):
            decide({})

    def test_capture_error_fail_closed_raises(self):
        """A mapping/attest error propagates when on_error=raise."""
        rt, _ = _runtime_with_sink()
        # empty domain mapping -> attest raises ValueError("domain ...")
        bad = DomainMapping(domain="loan", governance=("decision",))

        @governed(mapping=bad, runtime=rt, on_error="raise", model_id="")
        def decide(payload):
            return {"decision": "x"}

        with pytest.raises(ValueError):
            decide({})


# --- GraqleGovernanceMiddleware ----------------------------------------------


def _app(middleware_kwargs, handler=None):
    if handler is None:
        def handler(request):
            return JSONResponse(
                {"applicant_id": "alice@example.com", "decision": "approve",
                 "reason_code": "R1", "features": {"income": 90000}}
            )

    app = Starlette(routes=[Route("/score", handler, methods=["GET", "POST"])])
    app.add_middleware(GraqleGovernanceMiddleware, **middleware_kwargs)
    return app


class TestMiddleware:
    def test_json_response_captured_and_passthrough(self):
        rt, sink = _runtime_with_sink()
        app = _app({"mapping": _loan_mapping(), "model_id": "credit-v4", "runtime": rt})
        client = TestClient(app)
        resp = client.get("/score")
        assert resp.status_code == 200
        # response body unchanged
        assert resp.json()["decision"] == "approve"
        # capture ran as background task
        assert len(sink.records) == 1
        rec = sink.records[0]
        assert rec["domain"] == "loan"
        assert rec["model_id"] == "credit-v4"
        assert rec["governance_metadata"]["reason_code"] == "R1"
        # PII discipline: raw values never stored
        blob = repr(rec)
        assert "alice@example.com" not in blob
        assert "90000" not in blob

    def test_non_json_response_passed_through_uncaptured(self):
        rt, sink = _runtime_with_sink()

        def handler(request):
            return PlainTextResponse("plain text body")

        app = _app({"mapping": _loan_mapping(), "runtime": rt}, handler=handler)
        resp = TestClient(app).get("/score")
        assert resp.status_code == 200
        assert resp.text == "plain text body"
        assert len(sink.records) == 0  # nothing captured

    def test_header_override_model_and_policy(self):
        rt, sink = _runtime_with_sink()

        def handler(request):
            r = JSONResponse({"decision": "approve"})
            r.headers["x-graqle-model-id"] = "per-req-model"
            r.headers["x-graqle-policy-id"] = "policy-7"
            return r

        app = _app({"mapping": _loan_mapping(), "model_id": "default", "runtime": rt},
                   handler=handler)
        TestClient(app).get("/score")
        assert sink.records[0]["model_id"] == "per-req-model"
        assert sink.records[0]["policy_id"] == "policy-7"

    def test_non_object_json_fail_open_logs(self, caplog):
        rt, sink = _runtime_with_sink()

        def handler(request):
            return JSONResponse([1, 2, 3])  # JSON array, not object

        app = _app({"mapping": _loan_mapping(), "runtime": rt, "on_error": "log"},
                   handler=handler)
        with caplog.at_level(logging.ERROR):
            resp = TestClient(app).get("/score")
        assert resp.status_code == 200
        assert resp.json() == [1, 2, 3]
        assert len(sink.records) == 0
        assert "capture_failed" in caplog.text

    def test_malformed_json_body_fail_open_logs(self, caplog):
        rt, sink = _runtime_with_sink()

        def handler(request):
            # Claims JSON content-type but body is not valid JSON
            return PlainTextResponse("{not json", media_type="application/json")

        app = _app({"mapping": _loan_mapping(), "runtime": rt}, handler=handler)
        with caplog.at_level(logging.ERROR):
            resp = TestClient(app).get("/score")
        assert resp.status_code == 200
        assert len(sink.records) == 0
        assert "capture_failed" in caplog.text

    def test_invalid_on_error_rejected(self):
        # Starlette instantiates middleware lazily on first request, so the __init__
        # validation surfaces when the app is first exercised.
        app = _app({"mapping": _loan_mapping(), "on_error": "nope"})
        with pytest.raises(ValueError, match="on_error"):
            TestClient(app).get("/score")

    def test_invalid_max_body_bytes_rejected(self):
        app = _app({"mapping": _loan_mapping(), "max_body_bytes": 0})
        with pytest.raises(ValueError, match="max_body_bytes"):
            TestClient(app).get("/score")

    def test_oversized_body_skips_capture_but_returns_full_response(self, caplog):
        rt, sink = _runtime_with_sink()

        def handler(request):
            # Body larger than the 50-byte cap below
            return JSONResponse({"decision": "approve", "padding": "x" * 500})

        app = _app(
            {"mapping": _loan_mapping(), "runtime": rt, "max_body_bytes": 50},
            handler=handler,
        )
        with caplog.at_level(logging.ERROR):
            resp = TestClient(app).get("/score")
        # Client still gets the full, unmodified response
        assert resp.status_code == 200
        assert resp.json()["decision"] == "approve"
        assert len(resp.json()["padding"]) == 500
        # But nothing was captured, and the skip was logged loudly
        assert len(sink.records) == 0
        assert "capture_skipped_oversize" in caplog.text

    def test_oversized_body_never_raises_even_fail_closed(self):
        """The size cap is a deliberate bound, not an audit failure: it skips + logs
        and returns the full response, never 500s the user, even with on_error=raise."""
        rt, sink = _runtime_with_sink()

        def handler(request):
            return JSONResponse({"decision": "approve", "padding": "x" * 500})

        app = _app(
            {"mapping": _loan_mapping(), "runtime": rt, "max_body_bytes": 50,
             "on_error": "raise"},
            handler=handler,
        )
        resp = TestClient(app).get("/score")
        assert resp.status_code == 200
        assert len(sink.records) == 0

    def test_error_log_does_not_leak_exception_message(self, caplog):
        """PII safety: capture_failed log carries type+domain, never str(exc)."""
        rt, _ = _runtime_with_sink()

        def handler(request):
            # body whose JSON decode error message would include body content
            return PlainTextResponse("SECRET_TOKEN_not_json", media_type="application/json")

        app = _app({"mapping": _loan_mapping(), "runtime": rt}, handler=handler)
        with caplog.at_level(logging.ERROR):
            TestClient(app).get("/score")
        assert "capture_failed" in caplog.text
        # the raw body text must not appear in any log record
        assert "SECRET_TOKEN" not in caplog.text

    def test_default_runtime_used_when_none(self, tmp_path, monkeypatch):
        # No runtime passed -> uses the lazy default (durable sink). Point its home at
        # tmp so the test does not write to the real ~/.graqle.
        import graqle.governance.runtime.runtime as rtmod

        monkeypatch.setattr(rtmod, "_DEFAULT_ATTEST_DIR", tmp_path / "att")
        # reset cached default so it rebuilds with patched dir
        import graqle.governance.runtime.fastapi as fa

        monkeypatch.setattr(fa, "_DEFAULT_RUNTIME", None)
        app = _app({"mapping": _loan_mapping()})
        resp = TestClient(app).get("/score")
        assert resp.status_code == 200
        files = list((tmp_path / "att").glob("*.jsonl"))
        assert len(files) == 1


class TestMappingPathAndDefaults:
    def test_middleware_accepts_mapping_path(self, tmp_path):
        """mapping= can be a YAML path, not just a DomainMapping (the docs' usage)."""
        rt, sink = _runtime_with_sink()
        p = tmp_path / "loan_mapping.yaml"
        p.write_text(
            "domain: loan\nidentity: {applicant_id: pseudonymize}\n"
            "governance: [decision]\n",
            encoding="utf-8",
        )
        app = _app({"mapping": str(p), "runtime": rt})
        resp = TestClient(app).get("/score")
        assert resp.status_code == 200
        assert len(sink.records) == 1
        assert sink.records[0]["domain"] == "loan"

    def test_decorator_accepts_mapping_path(self, tmp_path):
        rt, sink = _runtime_with_sink()
        p = tmp_path / "r_mapping.yaml"
        p.write_text("domain: loan\ngovernance: [decision]\n", encoding="utf-8")

        @governed(mapping=str(p), runtime=rt)
        def decide(payload):
            return {"decision": "approve"}

        decide({})
        assert len(sink.records) == 1

    def test_middleware_capture_error_on_valid_payload_fail_open(self, caplog):
        """A valid object payload whose attest() raises is logged (fail-open path)."""
        # model_id="" makes attest() raise ValueError despite a well-formed payload.
        rt, sink = _runtime_with_sink()

        def handler(request):
            return JSONResponse({"decision": "approve"})

        app = _app(
            {"mapping": _loan_mapping(), "runtime": rt, "model_id": "", "on_error": "log"},
            handler=handler,
        )
        with caplog.at_level(logging.ERROR):
            resp = TestClient(app).get("/score")
        assert resp.status_code == 200
        assert len(sink.records) == 0
        assert "capture_failed" in caplog.text

    def test_default_runtime_is_cached(self, monkeypatch):
        """Second _default_runtime() call returns the cached instance."""
        import graqle.governance.runtime.fastapi as fa

        monkeypatch.setattr(fa, "_DEFAULT_RUNTIME", None)
        first = fa._default_runtime()
        second = fa._default_runtime()
        assert first is second

    def test_default_runtime_double_checked_lock_race(self, monkeypatch):
        """Cover the inner re-check: another caller set the global while we waited on
        the lock. Simulate deterministically with a lock whose __enter__ populates the
        global, so the inner `if _DEFAULT_RUNTIME is None` is False (no second build)."""
        import graqle.governance.runtime.fastapi as fa
        from graqle.governance.runtime import GovernedRuntime, InMemorySink

        winner = GovernedRuntime(sink=InMemorySink())
        monkeypatch.setattr(fa, "_DEFAULT_RUNTIME", None)

        class _RaceLock:
            def __enter__(self):
                # a "competing thread" wins the race while we hold no instance yet
                fa._DEFAULT_RUNTIME = winner
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(fa, "_DEFAULT_RUNTIME_LOCK", _RaceLock())
        got = fa._default_runtime()
        assert got is winner  # used the racing winner, did not build a second one

    def test_module_getattr_unknown_raises(self):
        import graqle.governance.runtime.fastapi as fa

        with pytest.raises(AttributeError, match="no attribute"):
            fa.does_not_exist


@pytest.fixture
def anyio_backend():
    return "asyncio"
