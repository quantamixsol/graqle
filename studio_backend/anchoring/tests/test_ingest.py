"""Tests for SqsAttestationSink (BizQ S2 hosted-anchoring ingress)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_ANCHORING = Path(__file__).resolve().parents[1]


def _load(modname: str, relpath: str):
    spec = importlib.util.spec_from_file_location(modname, _ANCHORING / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


ingest = _load("vas_ingest", "ingest.py")
SqsAttestationSink = ingest.SqsAttestationSink
IngestError = ingest.IngestError


class _FakeSqs:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.sent: list[dict[str, Any]] = []

    def send_message(self, *, QueueUrl, MessageBody):
        if self.fail:
            raise RuntimeError("sqs unavailable")
        self.sent.append({"QueueUrl": QueueUrl, "MessageBody": MessageBody})
        return {"MessageId": "m1"}


def _record():
    return {"proof_format_version": "1", "record_id": "r1", "content_hash": "a" * 64}


def test_write_enqueues_to_sqs():
    sqs = _FakeSqs()
    sink = SqsAttestationSink("https://q", client=sqs)
    sink.write(_record())
    assert len(sqs.sent) == 1
    assert sqs.sent[0]["QueueUrl"] == "https://q"
    body = json.loads(sqs.sent[0]["MessageBody"])
    assert body["record_id"] == "r1"


def test_write_rejects_non_dict():
    sink = SqsAttestationSink("https://q", client=_FakeSqs())
    with pytest.raises(IngestError):
        sink.write("nope")  # type: ignore[arg-type]


def test_write_rejects_missing_proof_format_version():
    sink = SqsAttestationSink("https://q", client=_FakeSqs())
    with pytest.raises(IngestError):
        sink.write({"record_id": "r1"})  # no proof_format_version


def test_write_rejects_unserialisable_record():
    sink = SqsAttestationSink("https://q", client=_FakeSqs())
    # default=str in the sink handles most, but a circular ref is unserialisable.
    circular: dict[str, Any] = {"proof_format_version": "1"}
    circular["self"] = circular
    with pytest.raises(IngestError):
        sink.write(circular)


def test_write_raises_on_sqs_failure():
    sink = SqsAttestationSink("https://q", client=_FakeSqs(fail=True))
    with pytest.raises(IngestError):
        sink.write(_record())  # a dropped record is an un-anchored proof → MUST raise


def test_empty_queue_url_rejected():
    with pytest.raises(IngestError):
        SqsAttestationSink("", client=_FakeSqs())


def test_satisfies_attestation_sink_protocol():
    """Duck-types the runtime AttestationSink (one method: write)."""
    from graqle.governance.runtime.runtime import AttestationSink

    sink = SqsAttestationSink("https://q", client=_FakeSqs())
    assert isinstance(sink, AttestationSink)  # runtime_checkable Protocol
