"""CR-002 PR-002c-2b — verify GRAQLE_USE_RESOLVER default is now ON.

The feature flag's default was OFF in PR-002a/PR-002b/PR-002c-1/PR-002c-2a
and was flipped to ON in PR-002c-2b. This file documents and locks down the
post-flip semantics:

  * env unset            -> resolver ON
  * env set to "1"/"yes" -> resolver ON
  * env set to ""        -> resolver ON  (unknown -> default ON)
  * env set to "garbage" -> resolver ON  (unknown -> default ON)
  * env set to "0"       -> resolver OFF (explicit opt-out)
  * env set to "false"   -> resolver OFF
  * env set to "no"      -> resolver OFF
  * case-insensitive match on opt-out sentinels

These tests run in addition to the in-line ``TestIsResolverEnabled`` class
in ``tests/test_config/test_resolver.py`` and serve as the canonical
parametrised contract for the post-flip behaviour.

EU AI Act note: the opt-out is reversible (set env var; restart process)
and never silently overrides; the worst case is a fall-through to the
legacy ``GraqleConfig.from_yaml`` path via the resolver-compat helper.
"""
from __future__ import annotations

import pytest

from graqle.config.resolver import is_resolver_enabled


@pytest.fixture(autouse=True)
def _clear_flag(monkeypatch: pytest.MonkeyPatch):
    """Each test starts with the env var unset; tests that want a specific
    value re-set it explicitly. Yield-style so cleanup is automatic."""
    monkeypatch.delenv("GRAQLE_USE_RESOLVER", raising=False)
    yield


def test_default_is_on_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Env unset -> resolver ON. This is the flip's headline behaviour."""
    monkeypatch.delenv("GRAQLE_USE_RESOLVER", raising=False)
    assert is_resolver_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "no", "FALSE", "No", "fAlSe"])
def test_opt_out_values_disable(monkeypatch: pytest.MonkeyPatch, val: str) -> None:
    """Only the explicit case-insensitive opt-out sentinels disable."""
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", val)
    assert is_resolver_enabled() is False


@pytest.mark.parametrize(
    "val",
    ["1", "true", "yes", "TRUE", "Yes", "anything-else", "", "garbage", "2"],
)
def test_truthy_and_unknown_values_default_on(
    monkeypatch: pytest.MonkeyPatch, val: str,
) -> None:
    """After the flip, any non-opt-out value (including unknown/empty
    strings) means the resolver is on. This is the 'safe default' contract:
    user typos like 'tru' or 'YEs' don't accidentally disable governance."""
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", val)
    assert is_resolver_enabled() is True


def test_whitespace_around_opt_out_still_disables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``" 0 "`` with surrounding whitespace -> stripped -> opt out applies.
    Locks the .strip() invariant in the env parsing path."""
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", "  0  ")
    assert is_resolver_enabled() is False
