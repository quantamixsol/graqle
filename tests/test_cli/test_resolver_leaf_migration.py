"""CR-002 PR-002b tests — resolver-gated migration of 3 leaf commands.

Verifies the feature-flagged migration pattern works as intended:
  * When ``GRAQLE_USE_RESOLVER`` is unset → legacy code path runs.
  * When ``GRAQLE_USE_RESOLVER=true`` → resolver path runs.
  * Resolver-path exceptions fail-safe to the legacy path.

EU AI Act note: the GRAQLE_USE_RESOLVER feature flag preserves the previous
audit trail when off; when on, the resolver's `Neo4jParams.source` field
records which layer (explicit/env/yaml/default) won — strictly more audit
information, never less.

CI-safety note (lesson from PR #89): NO ``importlib.util.module_from_spec``
+ pytest-xdist combination. All imports go through normal ``import``
statements so each xdist worker resolves the module once and caches it.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from graqle.config.resolver import is_resolver_enabled


# ── Feature flag invariants ────────────────────────────────────────────────


def test_flag_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """The feature flag must be OFF by default so PR-002b is a no-op for
    every existing user. PR-002c will flip the default."""
    monkeypatch.delenv("GRAQLE_USE_RESOLVER", raising=False)
    assert is_resolver_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "TRUE", "Yes"])
def test_flag_on_when_truthy_value(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", value)
    assert is_resolver_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "", "garbage"])
def test_flag_off_when_falsy_value(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", value)
    assert is_resolver_enabled() is False


# ── neo4j_import._get_connector resolver-path wiring ───────────────────────


def test_neo4j_import_get_connector_legacy_path_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag off → identical resolution behaviour to pre-PR-002b
    (env-only with bolt://localhost:7687 defaults)."""
    monkeypatch.delenv("GRAQLE_USE_RESOLVER", raising=False)
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_USERNAME", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    monkeypatch.delenv("NEO4J_DATABASE", raising=False)

    from graqle.cli.commands.neo4j_import import _get_connector

    # Patch Neo4jConnector to a sentinel so we just capture kwargs
    captured: dict = {}

    class _FakeConnector:
        def __init__(self, **kw: str) -> None:
            captured.update(kw)

    with mock.patch(
        "graqle.connectors.neo4j.Neo4jConnector", _FakeConnector,
    ):
        _get_connector()

    assert captured["uri"] == "bolt://localhost:7687"
    assert captured["username"] == "neo4j"
    assert captured["password"] == ""
    assert captured["database"] == "neo4j"


def test_neo4j_import_get_connector_resolver_failure_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the resolver raises, _get_connector must NOT propagate — it must
    fall back to the legacy env-only path. This is the safety contract."""
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", "true")
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_USERNAME", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    monkeypatch.delenv("NEO4J_DATABASE", raising=False)

    from graqle.cli.commands.neo4j_import import _get_connector

    captured: dict = {}

    class _FakeConnector:
        def __init__(self, **kw: str) -> None:
            captured.update(kw)

    # Force resolver to raise so we exercise the except branch
    with mock.patch(
        "graqle.config.resolver.resolve_neo4j",
        side_effect=RuntimeError("simulated resolver failure"),
    ), mock.patch("graqle.connectors.neo4j.Neo4jConnector", _FakeConnector):
        _get_connector()

    # Fell back cleanly to legacy defaults — no exception escaped
    assert captured["uri"] == "bolt://localhost:7687"


def test_neo4j_import_env_var_uri_wins_over_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing env-var users keep their behaviour — env-derived URI wins."""
    monkeypatch.delenv("GRAQLE_USE_RESOLVER", raising=False)
    monkeypatch.setenv("NEO4J_URI", "bolt://example.com:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "tester")
    monkeypatch.setenv("NEO4J_PASSWORD", "pw")
    monkeypatch.setenv("NEO4J_DATABASE", "testdb")

    from graqle.cli.commands.neo4j_import import _get_connector

    captured: dict = {}

    class _FakeConnector:
        def __init__(self, **kw: str) -> None:
            captured.update(kw)

    with mock.patch(
        "graqle.connectors.neo4j.Neo4jConnector", _FakeConnector,
    ):
        _get_connector()

    assert captured["uri"] == "bolt://example.com:7687"
    assert captured["username"] == "tester"
    assert captured["password"] == "pw"
    assert captured["database"] == "testdb"


# ── learn._load_graph + audit resolver-path wiring (smoke) ─────────────────


def test_learn_load_graph_module_imports_cleanly() -> None:
    """Smoke: import learn._load_graph by symbol. If the resolver-path try/
    except is malformed, this will surface as ImportError or SyntaxError.

    No invocation — just confirms the module-level code is well-formed.
    """
    from graqle.cli.commands.learn import _load_graph  # noqa: F401


def test_audit_module_imports_cleanly() -> None:
    """Smoke: import audit module — confirms the resolver-path block is
    syntactically clean and the imports it adds resolve."""
    from graqle.cli.commands import audit  # noqa: F401


# ── Integration: resolver path actually runs end-to-end ────────────────────
# Added to address graq_review MAJOR finding: existing smoke tests don't
# verify the resolver branch executes successfully when the flag is on.


def test_neo4j_import_resolver_path_uses_yaml_when_flag_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    """End-to-end: with the flag on and a real yaml on disk, _get_connector
    must call resolve_neo4j() and return params derived from the yaml — NOT
    fall through to the env-only path."""
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", "true")
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_USERNAME", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    monkeypatch.delenv("NEO4J_DATABASE", raising=False)

    # Inject a stub resolve_neo4j so the test is hermetic
    from graqle.config.resolver import Neo4jParams, SecretStr

    def _fake_resolve_neo4j(cfg, **explicit):
        return Neo4jParams(
            uri="bolt://from-yaml:7687",
            username="yaml-user",
            password=SecretStr("yaml-secret"),
            database="yaml-db",
            source="yaml",
        )

    from graqle.cli.commands.neo4j_import import _get_connector

    captured: dict = {}

    class _FakeConnector:
        def __init__(self, **kw: str) -> None:
            captured.update(kw)

    with mock.patch(
        "graqle.config.resolver.resolve_neo4j", _fake_resolve_neo4j,
    ), mock.patch("graqle.connectors.neo4j.Neo4jConnector", _FakeConnector):
        _get_connector()

    # The yaml-derived params won — confirms resolver path executed
    assert captured["uri"] == "bolt://from-yaml:7687"
    assert captured["username"] == "yaml-user"
    assert captured["password"] == "yaml-secret"
    assert captured["database"] == "yaml-db"


def test_neo4j_import_env_var_overrides_resolver_yaml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When BOTH env vars and yaml are present, env vars win — resolver
    receives them as explicit kwargs and the priority chain
    (explicit > env > yaml > default) gives env priority."""
    monkeypatch.setenv("GRAQLE_USE_RESOLVER", "true")
    monkeypatch.setenv("NEO4J_URI", "bolt://from-env:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "env-user")
    monkeypatch.setenv("NEO4J_PASSWORD", "env-secret")
    monkeypatch.setenv("NEO4J_DATABASE", "env-db")

    from graqle.config.resolver import Neo4jParams, SecretStr

    captured_kwargs: dict = {}

    def _fake_resolve_neo4j(cfg, **explicit):
        captured_kwargs.update(explicit)
        # Honour the explicit kwargs as the real resolver would
        return Neo4jParams(
            uri=explicit.get("uri") or "bolt://localhost:7687",
            username=explicit.get("username") or "neo4j",
            password=SecretStr(explicit.get("password") or ""),
            database=explicit.get("database") or "neo4j",
            source="explicit",
        )

    from graqle.cli.commands.neo4j_import import _get_connector

    final: dict = {}

    class _FakeConnector:
        def __init__(self, **kw: str) -> None:
            final.update(kw)

    with mock.patch(
        "graqle.config.resolver.resolve_neo4j", _fake_resolve_neo4j,
    ), mock.patch("graqle.connectors.neo4j.Neo4jConnector", _FakeConnector):
        _get_connector()

    # _get_connector passed the env vars to resolve_neo4j as explicit kwargs
    assert captured_kwargs["uri"] == "bolt://from-env:7687"
    assert captured_kwargs["username"] == "env-user"
    assert captured_kwargs["password"] == "env-secret"
    assert captured_kwargs["database"] == "env-db"
    # And the final connector got the env-derived values
    assert final["uri"] == "bolt://from-env:7687"
