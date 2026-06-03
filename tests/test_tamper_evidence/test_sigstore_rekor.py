"""Tests for the Sigstore Rekor anchor (v0.59.0 PR-4, R25-EU01 Task 1.4).

Every test runs WITHOUT the optional ``sigstore`` package and WITHOUT network:
a fake :class:`RekorTransport` is injected, and the backoff sleep is injected so
retries are instant + deterministic. The lazy-import / availability surface is
tested by stubbing ``importlib.util.find_spec``.
"""

from __future__ import annotations

import pytest

from graqle.config.attestation_config import RekorConfig
from graqle.governance.tamper_evidence.anchors import sigstore_rekor as sr
from graqle.governance.tamper_evidence.anchors.sigstore_rekor import (
    AnchorError,
    AnchorUnavailableError,
    RekorAnchor,
    RekorReceipt,
    RekorTransport,
)


# ---- fakes --------------------------------------------------------------------


def _receipt(i: int = 1) -> RekorReceipt:
    return RekorReceipt(
        log_index=i,
        log_id="logid",
        signed_tree_head="sth",
        inclusion_cert="cert",
        integrated_time=1_700_000_000 + i,
    )


class _OkTransport:
    """Always succeeds; records every submitted root."""

    def __init__(self):
        self.submitted: list[bytes] = []

    def submit(self, root_bytes: bytes) -> RekorReceipt:
        self.submitted.append(root_bytes)
        return _receipt(len(self.submitted))


class _FlakyTransport:
    """Fails the first ``fail_n`` calls, then succeeds."""

    def __init__(self, fail_n: int):
        self.fail_n = fail_n
        self.calls = 0

    def submit(self, root_bytes: bytes) -> RekorReceipt:
        self.calls += 1
        if self.calls <= self.fail_n:
            raise RuntimeError(f"transient rekor error {self.calls}")
        return _receipt(self.calls)


class _AlwaysFailTransport:
    def __init__(self):
        self.calls = 0

    def submit(self, root_bytes: bytes) -> RekorReceipt:
        self.calls += 1
        raise RuntimeError("rekor down")


def _no_sleep(_seconds: float) -> None:
    pass


# ---- Protocol conformance -----------------------------------------------------


def test_fakes_satisfy_transport_protocol():
    assert isinstance(_OkTransport(), RekorTransport)
    assert isinstance(_FlakyTransport(1), RekorTransport)


# ---- happy path ---------------------------------------------------------------


def test_anchor_returns_receipt_on_success():
    transport = _OkTransport()
    anchor = RekorAnchor(transport=transport, sleep=_no_sleep)
    receipt = anchor.anchor(b"\x11" * 32)
    assert isinstance(receipt, RekorReceipt)
    assert receipt.log_index == 1
    assert transport.submitted == [b"\x11" * 32]


def test_anchor_accepts_bytearray():
    transport = _OkTransport()
    anchor = RekorAnchor(transport=transport, sleep=_no_sleep)
    anchor.anchor(bytearray(b"\x22" * 32))
    assert transport.submitted == [b"\x22" * 32]


def test_anchor_rejects_non_bytes():
    anchor = RekorAnchor(transport=_OkTransport(), sleep=_no_sleep)
    with pytest.raises(AnchorError, match="must be bytes"):
        anchor.anchor("not bytes")  # type: ignore[arg-type]


# ---- retry / backoff ----------------------------------------------------------


def test_anchor_retries_then_succeeds():
    transport = _FlakyTransport(fail_n=2)
    sleeps: list[float] = []
    anchor = RekorAnchor(
        config=RekorConfig(retry_max_attempts=3),
        transport=transport,
        sleep=sleeps.append,
    )
    receipt = anchor.anchor(b"\x33" * 32)
    assert receipt.log_index == 3  # 3rd call succeeded
    assert transport.calls == 3
    # Exponential backoff between the 3 attempts: 2^0=1, 2^1=2.
    assert sleeps == [1.0, 2.0]


def test_anchor_raises_after_exhausting_attempts():
    transport = _AlwaysFailTransport()
    anchor = RekorAnchor(
        config=RekorConfig(retry_max_attempts=3),
        transport=transport,
        sleep=_no_sleep,
    )
    with pytest.raises(AnchorError, match="after 3 attempt"):
        anchor.anchor(b"\x44" * 32)
    assert transport.calls == 3  # all attempts used


def test_anchor_single_attempt_no_backoff():
    transport = _AlwaysFailTransport()
    sleeps: list[float] = []
    anchor = RekorAnchor(
        config=RekorConfig(retry_max_attempts=1),
        transport=transport,
        sleep=sleeps.append,
    )
    with pytest.raises(AnchorError):
        anchor.anchor(b"\x55" * 32)
    assert transport.calls == 1
    assert sleeps == []  # no backoff when only one attempt


def test_anchor_error_chains_last_transport_error():
    anchor = RekorAnchor(
        config=RekorConfig(retry_max_attempts=2),
        transport=_AlwaysFailTransport(),
        sleep=_no_sleep,
    )
    with pytest.raises(AnchorError) as exc_info:
        anchor.anchor(b"\x66" * 32)
    assert isinstance(exc_info.value.__cause__, RuntimeError)


# ---- availability / lazy optional dependency ----------------------------------


def test_available_true_when_transport_injected():
    assert RekorAnchor(transport=_OkTransport()).available is True


def test_available_reflects_sigstore_importability(monkeypatch):
    """With no transport, `available` mirrors whether sigstore can be imported."""
    monkeypatch.setattr(sr, "_sigstore_importable", lambda: True)
    assert RekorAnchor().available is True
    monkeypatch.setattr(sr, "_sigstore_importable", lambda: False)
    assert RekorAnchor().available is False


def test_anchor_raises_unavailable_when_sigstore_missing(monkeypatch):
    """No transport + sigstore not importable -> AnchorUnavailableError with remedy."""
    monkeypatch.setattr(sr, "_sigstore_importable", lambda: False)
    anchor = RekorAnchor(sleep=_no_sleep)
    with pytest.raises(AnchorUnavailableError, match="pip install graqle\\[attestation\\]"):
        anchor.anchor(b"\x77" * 32)


def test_submit_raising_unavailable_surfaces_without_retry():
    """If the TRANSPORT itself raises AnchorUnavailableError, it is not retried."""

    class _UnavailableTransport:
        def __init__(self):
            self.calls = 0

        def submit(self, root_bytes):
            self.calls += 1
            raise AnchorUnavailableError()

    transport = _UnavailableTransport()
    anchor = RekorAnchor(
        config=RekorConfig(retry_max_attempts=5), transport=transport, sleep=_no_sleep
    )
    with pytest.raises(AnchorUnavailableError):
        anchor.anchor(b"\xab" * 32)
    assert transport.calls == 1  # surfaced on first attempt, not retried


def test_unavailable_is_not_retried(monkeypatch):
    """AnchorUnavailableError surfaces immediately — retrying can't install a dep."""
    build_calls = {"n": 0}

    def fake_build(_config):
        build_calls["n"] += 1
        raise AnchorUnavailableError()

    monkeypatch.setattr(sr, "_build_sigstore_transport", fake_build)
    anchor = RekorAnchor(config=RekorConfig(retry_max_attempts=5), sleep=_no_sleep)
    with pytest.raises(AnchorUnavailableError):
        anchor.anchor(b"\x88" * 32)
    assert build_calls["n"] == 1  # built once, not retried 5x


def test_lazy_transport_built_once_and_cached(monkeypatch):
    """The real transport is built lazily on first anchor, then reused."""
    transport = _OkTransport()
    build_calls = {"n": 0}

    def fake_build(_config):
        build_calls["n"] += 1
        return transport

    monkeypatch.setattr(sr, "_build_sigstore_transport", fake_build)
    anchor = RekorAnchor(sleep=_no_sleep)  # no transport injected
    anchor.anchor(b"\x99" * 32)
    anchor.anchor(b"\xaa" * 32)
    assert build_calls["n"] == 1  # built once, cached for the second anchor
    assert len(transport.submitted) == 2


def test_build_sigstore_transport_raises_when_missing(monkeypatch):
    monkeypatch.setattr(sr, "_sigstore_importable", lambda: False)
    with pytest.raises(AnchorUnavailableError):
        sr._build_sigstore_transport(RekorConfig())


def test_build_sigstore_transport_returns_adapter_when_present(monkeypatch):
    """When sigstore is importable, the builder returns the real adapter type."""
    monkeypatch.setattr(sr, "_sigstore_importable", lambda: True)
    transport = sr._build_sigstore_transport(RekorConfig())  # default https url
    assert isinstance(transport, sr._SigstoreRekorTransport)


# ---- SSRF guard on the Rekor URL ----------------------------------------------


def test_validate_rekor_url_accepts_default_https():
    sr._validate_rekor_url("https://rekor.sigstore.dev")  # must not raise


def test_validate_rekor_url_rejects_non_https():
    with pytest.raises(AnchorError, match="https"):
        sr._validate_rekor_url("http://rekor.sigstore.dev")


@pytest.mark.parametrize(
    "host",
    ["localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "metadata.google.internal"],
)
def test_validate_rekor_url_rejects_internal_hosts(host):
    """SSRF guard: loopback / link-local / metadata targets are refused."""
    with pytest.raises(AnchorError, match="loopback/internal"):
        sr._validate_rekor_url(f"https://{host}/api")


def test_validate_rekor_url_rejects_missing_host():
    with pytest.raises(AnchorError, match="no host"):
        sr._validate_rekor_url("https://")


def test_build_transport_rejects_ssrf_url(monkeypatch):
    """The SSRF guard runs at transport-build time, before any client is created."""
    monkeypatch.setattr(sr, "_sigstore_importable", lambda: True)
    with pytest.raises(AnchorError, match="loopback/internal"):
        sr._build_sigstore_transport(RekorConfig(url="https://169.254.169.254"))


# ---- root_bytes size guard ----------------------------------------------------


def test_anchor_rejects_empty_root():
    anchor = RekorAnchor(transport=_OkTransport(), sleep=_no_sleep)
    with pytest.raises(AnchorError, match="implausible length"):
        anchor.anchor(b"")


def test_anchor_rejects_oversized_root():
    anchor = RekorAnchor(transport=_OkTransport(), sleep=_no_sleep)
    with pytest.raises(AnchorError, match="implausible length"):
        anchor.anchor(b"\x00" * 65)


def test_anchor_accepts_32_byte_root():
    transport = _OkTransport()
    anchor = RekorAnchor(transport=transport, sleep=_no_sleep)
    anchor.anchor(b"\x11" * 32)  # canonical SHA-256 root size
    assert len(transport.submitted) == 1


def test_sigstore_importable_uses_find_spec(monkeypatch):
    """_sigstore_importable is a pure find_spec probe (no import side effects)."""
    import importlib.util as _ilu

    monkeypatch.setattr(_ilu, "find_spec", lambda name: object() if name == "sigstore" else None)
    assert sr._sigstore_importable() is True
    monkeypatch.setattr(_ilu, "find_spec", lambda name: None)
    assert sr._sigstore_importable() is False


# ---- RekorReceipt -------------------------------------------------------------


def test_receipt_is_frozen():
    r = _receipt()
    with pytest.raises(Exception):
        r.log_index = 99  # type: ignore[misc]


def test_unavailable_error_is_anchor_error_subclass():
    """AnchorUnavailableError is catchable as AnchorError (callers may catch broadly)."""
    assert issubclass(AnchorUnavailableError, AnchorError)


# ---- signature/public_key passthrough (hotfix: real Rekor hashedrekord) -------


class _SigAwareTransport:
    """A transport that records the signature + public_key it received."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def submit(self, root_bytes, signature=None, public_key=None) -> RekorReceipt:
        self.calls.append((bytes(root_bytes), signature, public_key))
        return _receipt()


def test_anchor_passes_signature_and_public_key_when_provided():
    t = _SigAwareTransport()
    anchor = RekorAnchor(transport=t)
    anchor.anchor(b"\x11" * 32, b"sig-bytes", b"-----BEGIN PUBLIC KEY-----\n")
    assert len(t.calls) == 1
    root, sig, pub = t.calls[0]
    assert sig == b"sig-bytes"
    assert pub == b"-----BEGIN PUBLIC KEY-----\n"


def test_anchor_backcompat_single_arg_transport_still_works():
    """A legacy 1-arg transport keeps working when anchor() is called with no sig."""

    class _LegacyTransport:
        def submit(self, root_bytes) -> RekorReceipt:  # original signature
            return _receipt()

    anchor = RekorAnchor(transport=_LegacyTransport())
    # No signature/public_key → anchor() must call submit(root) with ONE arg.
    assert anchor.anchor(b"\x22" * 32).log_index == 1


def test_real_transport_requires_signature_and_key():
    """The real sigstore transport refuses to build a hashedrekord without sig+key."""
    transport = sr._SigstoreRekorTransport(RekorConfig())
    with pytest.raises(AnchorError):
        transport.submit(b"\x33" * 32)  # no signature/public_key → cannot build entry


def test_real_transport_rejects_empty_signature():
    transport = sr._SigstoreRekorTransport(RekorConfig())
    with pytest.raises(AnchorError):
        transport.submit(b"\x33" * 32, b"", b"-----BEGIN PUBLIC KEY-----\n")


def test_real_transport_rejects_non_pem_public_key():
    transport = sr._SigstoreRekorTransport(RekorConfig())
    with pytest.raises(AnchorError):
        transport.submit(b"\x33" * 32, b"sig", b"not-a-pem")


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("rekor_types") is None,
    reason="sigstore (rekor_types) optional dependency not installed",
)
def test_real_transport_builds_valid_hashedrekord_proposal():
    """The transport builds a hashedrekord with kind+apiVersion and maps LogEntry.

    Exercises the real ``submit`` body up to (not including) the network POST by
    injecting a fake client — so a wrong proposal shape (missing kind/apiVersion,
    wrong field aliases) or a wrong LogEntry mapping is caught WITHOUT live Rekor.
    This is the regression guard for the two API-shape bugs the live smoke found.
    """
    captured = {}

    class _FakeEntries:
        def post(self, proposal):
            captured["json"] = proposal.model_dump(mode="json", by_alias=True)

            class _LE:
                log_index = 99
                log_id = "fake"
                integrated_time = 1748000000
                inclusion_proof = None

            return _LE()

    class _FakeLog:
        entries = _FakeEntries()

    class _FakeClient:
        log = _FakeLog()

    transport = sr._SigstoreRekorTransport(RekorConfig())
    transport._client = _FakeClient()  # skip TUF bootstrap + network
    root = b"\xab" * 32
    receipt = transport.submit(root, b"a-signature", b"-----BEGIN PUBLIC KEY-----\nx\n")

    j = captured["json"]
    assert j["kind"] == "hashedrekord"
    assert j["apiVersion"] == "0.0.1"
    assert j["spec"]["data"]["hash"]["algorithm"] == "sha256"
    assert j["spec"]["data"]["hash"]["value"] == root.hex()
    assert "content" in j["spec"]["signature"]
    assert "content" in j["spec"]["signature"]["publicKey"]
    # LogEntry -> RekorReceipt mapping, with the GraQle root-hex binding.
    assert receipt.log_index == 99
    assert receipt.signed_tree_head == root.hex()
