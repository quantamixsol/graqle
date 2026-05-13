"""CR-002 PR-002c-2a tests — ``load_via_resolver_or_legacy`` helper.

The helper encapsulates the four-line "try resolver, fall back to legacy"
pattern that PR-002b established in the three CLI commands (learn, audit,
neo4j_import). PR-002c-2a migrates the three remaining hardcoded
``Path("graqle.yaml")`` call sites (chunk_scorer + two in learn.py's
``_save_graph`` / ``_graph_lock``) by replacing four lines of boilerplate
with one call.

Behaviour matrix (mirrors helper docstring):

+-----------------------+------------------------------+--------------------+
| GRAQLE_USE_RESOLVER   | default_path on disk         | Returned config    |
+-----------------------+------------------------------+--------------------+
| unset / falsy         | exists                       | from_yaml(default) |
| unset / falsy         | missing                      | None               |
| truthy + resolver OK  | (resolver finds yaml_source) | from_yaml(yaml_src)|
| truthy + resolver err | exists                       | from_yaml(default) |
| truthy + resolver err | missing                      | None               |
+-----------------------+------------------------------+--------------------+

CI safety: only normal ``import`` statements, no
``importlib.util.module_from_spec`` (lesson from PR #89 CI hang).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from graqle.config._resolver_compat import load_via_resolver_or_legacy
from graqle.config.settings import GraqleConfig


@pytest.fixture
def yaml_in_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Place a minimal-but-valid graqle.yaml in a tmp cwd and chdir there."""
    yaml_path = tmp_path / "graqle.yaml"
    yaml_path.write_text(
        "version: '1.0'\n"
        "graph:\n"
        "  backend: json\n"
        "  uri: ./graqle.json\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return yaml_path


@pytest.fixture
def empty_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Chdir to a tmp dir with NO graqle.yaml."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _clear_resolver_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure each test starts with GRAQLE_USE_RESOLVER unset, regardless of
    the surrounding shell. Tests that need it set will re-set it explicitly."""
    monkeypatch.delenv("GRAQLE_USE_RESOLVER", raising=False)


# ─── Flag OFF (default) ─────────────────────────────────────────────────────


def test_flag_off_yaml_present_returns_from_yaml(yaml_in_cwd: Path) -> None:
    """Default OFF + file present → load via GraqleConfig.from_yaml."""
    cfg = load_via_resolver_or_legacy()
    assert cfg is not None
    assert isinstance(cfg, GraqleConfig)


def test_flag_off_yaml_missing_returns_none(empty_cwd: Path) -> None:
    """Default OFF + file missing → None (caller falls back to .default())."""
    cfg = load_via_resolver_or_legacy()
    assert cfg is None


def test_flag_off_does_not_import_resolver(yaml_in_cwd: Path) -> None:
    """When the flag is OFF, the resolver branch must NOT be entered.

    We can't test "did not import" directly without contaminating sys.modules,
    so we instead patch is_resolver_enabled and assert the resolver helpers
    were never consulted past the flag check.
    """
    with patch("graqle.config.resolver.resolve_config") as resolve_mock:
        cfg = load_via_resolver_or_legacy()
        assert cfg is not None
        resolve_mock.assert_not_called()


# ─── Flag ON, resolver succeeds ─────────────────────────────────────────────


def test_flag_on_resolver_success_uses_resolved_yaml_source(
    yaml_in_cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag ON + resolver returns a ResolvedConfig → from_yaml(yaml_source)."""
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", "1")
    cfg = load_via_resolver_or_legacy()
    assert cfg is not None
    assert isinstance(cfg, GraqleConfig)


def test_flag_on_resolver_called_with_no_args(
    yaml_in_cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When flag is ON, resolve_config() is invoked (we don't pre-pass a path).
    The helper's contract is: trust the resolver to walk + canonicalise."""
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", "1")
    with patch(
        "graqle.config.resolver.resolve_config",
        wraps=__import__("graqle.config.resolver", fromlist=["resolve_config"]).resolve_config,
    ) as resolve_spy:
        load_via_resolver_or_legacy()
        resolve_spy.assert_called_once()


# ─── Flag ON, resolver fails ────────────────────────────────────────────────


def test_flag_on_resolver_error_falls_back_to_legacy(
    yaml_in_cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag ON + resolver raises → suppress, fall through to legacy path.

    This is the EU-AI-Act fail-safe property: the resolver is opt-in, and
    if it explodes for any reason, the caller still gets the legacy config
    so the user's workflow does not break.
    """
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", "1")
    with patch(
        "graqle.config.resolver.resolve_config",
        side_effect=RuntimeError("resolver blew up"),
    ):
        cfg = load_via_resolver_or_legacy()
    assert cfg is not None
    assert isinstance(cfg, GraqleConfig)


def test_flag_on_resolver_error_yaml_missing_returns_none(
    empty_cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag ON + resolver fails + no legacy yaml → None (caller goes default)."""
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", "1")
    with patch(
        "graqle.config.resolver.resolve_config",
        side_effect=RuntimeError("resolver blew up"),
    ):
        cfg = load_via_resolver_or_legacy()
    assert cfg is None


# ─── Custom default_path argument ───────────────────────────────────────────


def test_custom_default_path_str(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pass a non-default filename as str — helper still resolves correctly."""
    yaml_path = tmp_path / "custom.yaml"
    yaml_path.write_text(
        "version: '1.0'\n"
        "graph:\n"
        "  backend: json\n"
        "  uri: ./graqle.json\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_via_resolver_or_legacy(default_path="custom.yaml")
    assert cfg is not None


def test_custom_default_path_pathobj(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pass a Path object — helper accepts it (str|Path union in signature)."""
    yaml_path = tmp_path / "custom.yaml"
    yaml_path.write_text(
        "version: '1.0'\n"
        "graph:\n"
        "  backend: json\n"
        "  uri: ./graqle.json\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_via_resolver_or_legacy(default_path=Path("custom.yaml"))
    assert cfg is not None


# ─── Resolver-unavailable (ImportError) regression ──────────────────────────


def test_resolver_import_error_falls_back_to_legacy(
    yaml_in_cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``graqle.config.resolver`` itself fails to import (e.g.
    monkey-patched test environment), the helper must still produce a
    legacy result and not raise."""
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", "1")
    # Simulate ImportError by removing the module from sys.modules and
    # blocking re-import via a meta_path finder. Simpler: patch
    # is_resolver_enabled to raise ImportError when accessed. The helper
    # catches ImportError at the import statement itself, so the only way
    # to drive that branch is to break the module reference.
    import sys

    saved = sys.modules.pop("graqle.config.resolver", None)
    try:
        # Insert a sentinel that raises ImportError on attribute access.
        class _Broken:
            def __getattr__(self, name: str) -> object:
                raise ImportError(f"simulated: cannot resolve {name}")

        sys.modules["graqle.config.resolver"] = _Broken()  # type: ignore[assignment]
        cfg = load_via_resolver_or_legacy()
    finally:
        if saved is not None:
            sys.modules["graqle.config.resolver"] = saved
        else:
            sys.modules.pop("graqle.config.resolver", None)
    assert cfg is not None
    assert isinstance(cfg, GraqleConfig)


# ─── Regression guard: helper never raises ──────────────────────────────────


@pytest.mark.parametrize("flag_value", ["1", "true", "TRUE", "yes", "on"])
def test_truthy_flag_values_all_drive_resolver_branch(
    yaml_in_cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
    flag_value: str,
) -> None:
    """All ``is_resolver_enabled`` truthy values exercise the resolver path
    cleanly — none of them cause an exception leak past the helper."""
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", flag_value)
    cfg = load_via_resolver_or_legacy()
    assert cfg is not None


@pytest.mark.parametrize("flag_value", ["", "0", "false", "FALSE", "no", "off"])
def test_falsy_flag_values_skip_resolver_branch(
    yaml_in_cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
    flag_value: str,
) -> None:
    """Falsy ``GRAQLE_USE_RESOLVER`` values must NOT enter the resolver branch."""
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", flag_value)
    with patch("graqle.config.resolver.resolve_config") as resolve_mock:
        cfg = load_via_resolver_or_legacy()
        assert cfg is not None
        resolve_mock.assert_not_called()
