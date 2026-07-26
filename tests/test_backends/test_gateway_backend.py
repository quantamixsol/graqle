"""CR-010.R4 — tests for the enterprise-gateway LLM backend.

Covers:
  - GatewayBackend headers: org header + extra_headers (extra win on collision)
  - Model allowlist: allow listed; refuse unlisted client-side (pre-HTTP, no call);
    empty list = lockdown; None = unrestricted
  - 401 refresh-once: refresh runs once -> retry -> success; second 401 raises;
    on_auth_error 'fail'/None -> no refresh, immediate GatewayAuthError;
    refresh-command failure -> original 401 surfaces (not the refresh error)
  - CustomBackend regression: _build_headers unchanged for the base class
  - No-leak: token never in headers-repr / GatewayAuthError message
  - create_gateway_backend factory wiring

Uses a fake ``httpx`` module injected into sys.modules so no network is hit and
the 401 path is fully controllable.

See: .gsm/external/Change Requests/CR-010.R4-enterprise-gateway-backend.md
"""

from __future__ import annotations

import sys
import types

import pytest

from graqle.backends.api import (
    CustomBackend,
    GatewayAuthError,
    GatewayBackend,
)

TOKEN = "TEST-MOCK-GATEWAY-TOKEN"
REFRESHED = "TEST-MOCK-REFRESHED-TOKEN"


# ─────────────── fake httpx ──────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]
        }
        self.captured_headers = None

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class _FakeClient:
    """Records POST headers and returns a scripted sequence of responses."""

    last_headers: dict | None = None
    responses: list = []
    call_count = 0

    def __init__(self, timeout=None):
        self._timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        type(self).last_headers = dict(headers or {})
        type(self).call_count += 1
        idx = min(type(self).call_count - 1, len(type(self).responses) - 1)
        return type(self).responses[idx]


def _install_fake_httpx(monkeypatch, responses):
    _FakeClient.responses = responses
    _FakeClient.call_count = 0
    _FakeClient.last_headers = None
    fake = types.ModuleType("httpx")
    fake.AsyncClient = _FakeClient
    monkeypatch.setitem(sys.modules, "httpx", fake)


# ─────────────── headers ─────────────────────────────────────────────────────


def test_headers_include_org_and_extra():
    gb = GatewayBackend(
        "http://sidecar/v1", model="ns/prod", api_key=TOKEN,
        organization="org-abc", extra_headers={"Rpc-Caller": "graqle", "Rpc-Service": "kg"},
    )
    h = gb._build_headers()
    assert h["OpenAI-Organization"] == "org-abc"
    assert h["Rpc-Caller"] == "graqle"
    assert h["Rpc-Service"] == "kg"
    assert h["Authorization"] == f"Bearer {TOKEN}"


def test_extra_headers_win_on_collision():
    gb = GatewayBackend(
        "http://x", model="m", api_key=TOKEN,
        organization="org-1", extra_headers={"OpenAI-Organization": "override"},
    )
    assert gb._build_headers()["OpenAI-Organization"] == "override"


def test_extra_headers_cannot_clobber_authorization():
    # B-1 (sentinel): extra_headers must NOT be able to null/replace the bearer token.
    gb = GatewayBackend(
        "http://x", model="m", api_key=TOKEN,
        extra_headers={"authorization": "Bearer HACKED", "Authorization": ""},
    )
    assert gb._build_headers()["Authorization"] == f"Bearer {TOKEN}"


def test_no_api_key_sends_no_auth_even_with_extra():
    gb = GatewayBackend("http://x", model="m", api_key=None, extra_headers={"X-Foo": "1"})
    assert "Authorization" not in gb._build_headers()


# ─────────────── model allowlist ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_allowlist_allows_listed(monkeypatch):
    _install_fake_httpx(monkeypatch, [_FakeResponse(200)])
    gb = GatewayBackend("http://x", model="ns/prod", api_key=TOKEN, model_allowlist=["ns/prod"])
    r = await gb.generate("hi")
    assert r.text == "ok"


@pytest.mark.asyncio
async def test_allowlist_refuses_unlisted_pre_http(monkeypatch):
    _install_fake_httpx(monkeypatch, [_FakeResponse(200)])
    gb = GatewayBackend("http://x", model="ns/dev", api_key=TOKEN, model_allowlist=["ns/prod"])
    with pytest.raises(ValueError) as ei:
        await gb.generate("hi")
    assert "not in the configured model_allowlist" in str(ei.value)
    assert _FakeClient.call_count == 0  # refused BEFORE any network call


@pytest.mark.asyncio
async def test_empty_allowlist_is_lockdown(monkeypatch):
    _install_fake_httpx(monkeypatch, [_FakeResponse(200)])
    gb = GatewayBackend("http://x", model="anything", api_key=TOKEN, model_allowlist=[])
    with pytest.raises(ValueError):
        await gb.generate("hi")
    assert _FakeClient.call_count == 0


@pytest.mark.asyncio
async def test_none_allowlist_unrestricted(monkeypatch):
    _install_fake_httpx(monkeypatch, [_FakeResponse(200)])
    gb = GatewayBackend("http://x", model="whatever", api_key=TOKEN, model_allowlist=None)
    r = await gb.generate("hi")
    assert r.text == "ok"


# ─────────────── 401 refresh-once ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_401_refresh_once_then_success(monkeypatch):
    _install_fake_httpx(monkeypatch, [_FakeResponse(401), _FakeResponse(200)])

    calls = {"n": 0}

    def fake_resolve(name, cfg=None, *, default=None, provider=None, ref=None):
        calls["n"] += 1
        from graqle.config.resolver import SecretStr
        from graqle.config.secrets import ResolvedSecret
        return ResolvedSecret(value=SecretStr(REFRESHED), provider="command", source_ref_redacted="<cmd>")

    monkeypatch.setattr("graqle.config.secrets.resolve_secret", fake_resolve)
    gb = GatewayBackend("http://x", model="m", api_key=TOKEN, on_auth_error="refresh-cmd")
    r = await gb.generate("hi")
    assert r.text == "ok"
    assert calls["n"] == 1                         # refresh ran exactly once
    assert _FakeClient.call_count == 2             # first 401, then retry
    assert gb._api_key == REFRESHED                # token updated in place
    assert _FakeClient.last_headers["Authorization"] == f"Bearer {REFRESHED}"


@pytest.mark.asyncio
async def test_second_401_raises_gateway_auth_error(monkeypatch):
    _install_fake_httpx(monkeypatch, [_FakeResponse(401), _FakeResponse(401)])

    def fake_resolve(name, cfg=None, *, default=None, provider=None, ref=None):
        from graqle.config.resolver import SecretStr
        from graqle.config.secrets import ResolvedSecret
        return ResolvedSecret(value=SecretStr(REFRESHED), provider="command", source_ref_redacted="<cmd>")

    monkeypatch.setattr("graqle.config.secrets.resolve_secret", fake_resolve)
    gb = GatewayBackend("http://x", model="m", api_key=TOKEN, on_auth_error="refresh-cmd")
    with pytest.raises(GatewayAuthError) as ei:
        await gb.generate("hi")
    assert TOKEN not in str(ei.value) and REFRESHED not in str(ei.value)  # no token in message


@pytest.mark.asyncio
async def test_on_auth_error_fail_no_refresh(monkeypatch):
    _install_fake_httpx(monkeypatch, [_FakeResponse(401)])
    gb = GatewayBackend("http://x", model="m", api_key=TOKEN, on_auth_error="fail")
    with pytest.raises(GatewayAuthError):
        await gb.generate("hi")
    assert _FakeClient.call_count == 1  # no retry


@pytest.mark.asyncio
async def test_on_auth_error_none_no_refresh(monkeypatch):
    _install_fake_httpx(monkeypatch, [_FakeResponse(401)])
    gb = GatewayBackend("http://x", model="m", api_key=TOKEN, on_auth_error=None)
    with pytest.raises(GatewayAuthError):
        await gb.generate("hi")
    assert _FakeClient.call_count == 1


@pytest.mark.asyncio
async def test_refresh_command_failure_surfaces_original_401(monkeypatch):
    _install_fake_httpx(monkeypatch, [_FakeResponse(401)])

    def boom(name, cfg=None, *, default=None, provider=None, ref=None):
        raise RuntimeError("SECRET-REFRESH-INTERNAL-ERROR")

    monkeypatch.setattr("graqle.config.secrets.resolve_secret", boom)
    gb = GatewayBackend("http://x", model="m", api_key=TOKEN, on_auth_error="broken-cmd")
    with pytest.raises(GatewayAuthError) as ei:
        await gb.generate("hi")
    # the refresh error must NOT surface — only the 401
    assert "SECRET-REFRESH-INTERNAL-ERROR" not in str(ei.value)
    assert gb._api_key == TOKEN  # token unchanged after failed refresh


@pytest.mark.asyncio
async def test_refresh_failure_logs_warning_without_secret(monkeypatch, caplog):
    # M-1 (sentinel): a broken refresh must be visible via a WARNING log, but the
    # log must contain only the exception TYPE — never the secret or stderr.
    _install_fake_httpx(monkeypatch, [_FakeResponse(401)])

    def boom(name, cfg=None, *, default=None, provider=None, ref=None):
        raise RuntimeError("SECRET-REFRESH-INTERNAL-ERROR")

    monkeypatch.setattr("graqle.config.secrets.resolve_secret", boom)
    gb = GatewayBackend("http://x", model="m", api_key=TOKEN, on_auth_error="broken-cmd")
    import logging
    with caplog.at_level(logging.WARNING):
        with pytest.raises(GatewayAuthError):
            await gb.generate("hi")
    warned = "\n".join(r.message for r in caplog.records if r.levelno >= logging.WARNING)
    assert "refresh" in warned.lower()
    assert "SECRET-REFRESH-INTERNAL-ERROR" not in warned  # only the type name
    assert TOKEN not in warned


@pytest.mark.asyncio
async def test_on_auth_error_fail_case_insensitive(monkeypatch):
    # m-2 hardening: 'FAIL'/'Fail' must also disable refresh (no silent typo trap).
    _install_fake_httpx(monkeypatch, [_FakeResponse(401)])
    gb = GatewayBackend("http://x", model="m", api_key=TOKEN, on_auth_error="FAIL")
    with pytest.raises(GatewayAuthError):
        await gb.generate("hi")
    assert _FakeClient.call_count == 1  # no refresh attempted


# ─────────────── CustomBackend regression ────────────────────────────────────


def test_custombackend_headers_unchanged():
    cb = CustomBackend("http://x", model="m", api_key=TOKEN)
    h = cb._build_headers()
    assert h == {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}


def test_custombackend_no_key_no_auth_header():
    cb = CustomBackend("http://x", model="m", api_key=None)
    assert "Authorization" not in cb._build_headers()


# ─────────────── factory + no-leak ───────────────────────────────────────────


def test_create_gateway_backend_factory():
    from graqle.backends.providers import create_gateway_backend
    gb = create_gateway_backend(
        "http://gw/v1", "ns/prod", api_key=TOKEN, organization="org-9",
        extra_headers={"Rpc-Caller": "x"}, model_allowlist=["ns/prod"], on_auth_error="fail",
    )
    assert isinstance(gb, GatewayBackend)
    assert gb.name == "gateway:http://gw/v1"
    assert gb._organization == "org-9"


def test_token_not_in_backend_repr():
    gb = GatewayBackend("http://x", model="m", api_key=TOKEN)
    assert TOKEN not in repr(gb)
    assert TOKEN not in gb.name
