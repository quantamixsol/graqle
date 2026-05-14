"""CR-002 PR-002c-1 tests — GraqleConfig.from_yaml deprecation warning.

When ``GRAQLE_USE_RESOLVER`` is set to a truthy value, ``from_yaml`` emits a
``PendingDeprecationWarning`` the FIRST time each caller invokes it with the
legacy relative path ``"graqle.yaml"``. Subsequent calls from the SAME caller
frame in the same process are suppressed via ``_resolver_deprecation_warned``.

EU AI Act note: the warning is observable in audit logs via stderr capture,
but emits only when the user has explicitly opted into the resolver path —
no warning spam for users on the legacy default-OFF setup.

CI safety: only normal ``import`` statements, no ``importlib.util.module_from_spec``.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from graqle.config.settings import GraqleConfig


def _reset_warning_state() -> None:
    """Clear the process-scoped deprecation-warned set so each test starts
    from a clean state. Without this, tests would interact via the shared
    class attribute and become order-dependent."""
    GraqleConfig._resolver_deprecation_warned.clear()


@pytest.fixture(autouse=True)
def _isolate_warning_state() -> None:
    """Autouse: clear the warned set before AND after each test."""
    _reset_warning_state()
    yield
    _reset_warning_state()


@pytest.fixture
def yaml_path(tmp_path: Path) -> Path:
    """Write a minimal valid graqle.yaml at tmp_path/graqle.yaml."""
    p = tmp_path / "graqle.yaml"
    p.write_text("model:\n  backend: anthropic\n  model: claude-sonnet-4-6\n", encoding="utf-8")
    return p


# ── Behaviour when flag is OFF: no warning ─────────────────────────────────


def test_warning_fires_when_resolver_flag_unset(
    monkeypatch: pytest.MonkeyPatch, yaml_path: Path,
) -> None:
    """CR-002 PR-002c-2b: default flipped to ON. Env unset → flag ON → warning.

    Prior to PR-002c-2b the default was OFF (no warning); after the flip,
    leaving the env var unset means the resolver is enabled, which fires
    exactly one PendingDeprecationWarning when from_yaml is called with a
    relative path.
    """
    monkeypatch.delenv("GRAQLE_USE_RESOLVER", raising=False)
    monkeypatch.chdir(yaml_path.parent)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        GraqleConfig.from_yaml("graqle.yaml")

    pending = [x for x in w if issubclass(x.category, PendingDeprecationWarning)]
    assert len(pending) == 1, (
        f"Expected exactly one PendingDeprecationWarning when flag is "
        f"unset (default ON post PR-002c-2b), got {[str(x.message) for x in pending]}"
    )
    assert "GRAQLE_USE_RESOLVER" in str(pending[0].message)


def test_no_warning_when_resolver_flag_is_falsy(
    monkeypatch: pytest.MonkeyPatch, yaml_path: Path,
) -> None:
    """Falsy values like '0', 'false', 'no' must also suppress the warning."""
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", "0")
    monkeypatch.chdir(yaml_path.parent)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        GraqleConfig.from_yaml("graqle.yaml")

    pending = [x for x in w if issubclass(x.category, PendingDeprecationWarning)]
    assert pending == []


# ── Behaviour when flag is ON: warning fires on relative graqle.yaml ───────


def test_warning_fires_when_resolver_flag_on_and_legacy_path(
    monkeypatch: pytest.MonkeyPatch, yaml_path: Path,
) -> None:
    """Flag on + relative 'graqle.yaml' path → exactly one warning."""
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", "true")
    monkeypatch.chdir(yaml_path.parent)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        GraqleConfig.from_yaml("graqle.yaml")

    pending = [x for x in w if issubclass(x.category, PendingDeprecationWarning)]
    assert len(pending) == 1
    assert "resolve_config" in str(pending[0].message)
    assert "GRAQLE_USE_RESOLVER" in str(pending[0].message)


@pytest.mark.parametrize("flag_value", ["1", "true", "yes", "TRUE", "Yes"])
def test_warning_fires_for_all_truthy_flag_values(
    monkeypatch: pytest.MonkeyPatch, yaml_path: Path, flag_value: str,
) -> None:
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", flag_value)
    monkeypatch.chdir(yaml_path.parent)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        GraqleConfig.from_yaml("graqle.yaml")

    pending = [x for x in w if issubclass(x.category, PendingDeprecationWarning)]
    assert len(pending) == 1


# ── Suppression: same call site only warns once per process ────────────────


def test_warning_suppressed_on_second_call_from_same_site(
    monkeypatch: pytest.MonkeyPatch, yaml_path: Path,
) -> None:
    """Same caller frame → exactly one warning across multiple invocations.

    The warning fingerprint is ``{filename}:{lineno}`` — same line should
    warn once even when called many times. We use a loop (single call
    expression) so all invocations resolve to the same lineno.
    """
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", "true")
    monkeypatch.chdir(yaml_path.parent)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        for _ in range(5):
            GraqleConfig.from_yaml("graqle.yaml")  # same line: 5 calls, 1 site

    pending = [x for x in w if issubclass(x.category, PendingDeprecationWarning)]
    assert len(pending) == 1, (
        f"Expected exactly 1 warning (5 calls from same line), got {len(pending)}"
    )


def test_warning_fires_per_distinct_call_site(
    monkeypatch: pytest.MonkeyPatch, yaml_path: Path,
) -> None:
    """Different lines = different call sites = separate warnings.

    This is the inverse-direction property — confirms the suppression key is
    site-specific, not module-global.
    """
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", "true")
    monkeypatch.chdir(yaml_path.parent)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        GraqleConfig.from_yaml("graqle.yaml")  # site A
        GraqleConfig.from_yaml("graqle.yaml")  # site B (different lineno)

    pending = [x for x in w if issubclass(x.category, PendingDeprecationWarning)]
    assert len(pending) == 2


# ── Absolute-path callers (resolver pattern) do NOT trigger warning ────────


def test_no_warning_when_absolute_path_used(
    monkeypatch: pytest.MonkeyPatch, yaml_path: Path,
) -> None:
    """The resolver passes an ABSOLUTE path (resolved.yaml_source). That call
    pattern must NOT trigger the deprecation warning — only the relative
    legacy 'graqle.yaml' shape does."""
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", "true")

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        # Pass the absolute path — simulates resolver-driven invocation
        GraqleConfig.from_yaml(str(yaml_path))

    pending = [x for x in w if issubclass(x.category, PendingDeprecationWarning)]
    assert pending == [], (
        f"Resolver-driven absolute-path call should not warn, "
        f"got {[str(x.message) for x in pending]}"
    )


def test_no_warning_for_path_object_absolute(
    monkeypatch: pytest.MonkeyPatch, yaml_path: Path,
) -> None:
    """Passing a Path object (not str) — absolute resolves to no warning."""
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", "true")

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        GraqleConfig.from_yaml(yaml_path)

    pending = [x for x in w if issubclass(x.category, PendingDeprecationWarning)]
    assert pending == []


# ── Failure mode: warning logic itself must never break from_yaml ──────────


def test_from_yaml_still_loads_when_flag_on(
    monkeypatch: pytest.MonkeyPatch, yaml_path: Path,
) -> None:
    """Flag on, warning fires, but the actual yaml parsing still works.
    Regression guard: a bug in the warning block must not break loading."""
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", "true")
    monkeypatch.chdir(yaml_path.parent)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cfg = GraqleConfig.from_yaml("graqle.yaml")

    assert cfg.model.backend == "anthropic"


def test_class_var_is_set_collection() -> None:
    """``_resolver_deprecation_warned`` is a set we can mutate at class level
    (ClassVar contract). Module-level sanity check."""
    assert isinstance(GraqleConfig._resolver_deprecation_warned, set)
