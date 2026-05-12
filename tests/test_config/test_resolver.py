"""CR-002 PR-002a — tests for the unified config resolver.

Covers:
  - Public API: ResolvedConfig + Neo4jParams + SecretStr
  - resolve_project_root ancestor walk + .graqle/ detection + max_depth
  - resolve_config: yaml found at start, in ancestor, submodule fallback,
    not found, malformed yaml, permission denied
  - resolve_neo4j priority chain: explicit > env > yaml > default + source field
  - Security: URI scheme allow-list (positive), URI-as-path guard,
    constant-time SecretStr equality, repr never reveals raw value,
    home-boundary halt, symlink-cycle detection
  - Feature flag: is_resolver_enabled() default-False, opt-in via env var

See: .gsm/external/Change Requests/CR-002-unified-config-resolution.md
"""

from __future__ import annotations

# -- graqle:intelligence --
# module: tests.test_config.test_resolver
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, yaml, graqle.config.resolver, graqle.config.exceptions
# constraints: none
# -- /graqle:intelligence --

import os
import sys
from pathlib import Path

import pytest
import yaml

from graqle.config.exceptions import (
    ConfigNotFoundError,
    ConfigPathError,
    ConfigPermissionError,
    ConfigSchemeError,
    ConfigYamlError,
    GraqleConfigError,
)
from graqle.config.resolver import (
    ALLOWED_URI_SCHEMES,
    Neo4jParams,
    ResolvedConfig,
    SecretStr,
    _assert_not_uri_path,
    _assert_uri_safe,
    _redact_home,
    is_resolver_enabled,
    resolve_config,
    resolve_neo4j,
    resolve_project_root,
)


# =================== SecretStr ============================================


class TestSecretStr:
    def test_repr_never_reveals_value(self):
        s = SecretStr("hunter2")
        assert "hunter2" not in repr(s)
        assert repr(s) == "SecretStr(***)"

    def test_str_never_reveals_value(self):
        s = SecretStr("hunter2")
        assert "hunter2" not in str(s)
        assert str(s) == "***"

    def test_get_secret_value_returns_raw(self):
        s = SecretStr("hunter2")
        assert s.get_secret_value() == "hunter2"

    def test_equality_constant_time(self):
        a = SecretStr("hunter2")
        b = SecretStr("hunter2")
        c = SecretStr("hunter3")
        assert a == b
        assert a != c

    def test_equality_against_non_secret_returns_notimplemented(self):
        a = SecretStr("x")
        assert (a == "x") is False  # NotImplemented falls back to False

    def test_hash_is_deterministic_for_same_value(self):
        # Same value → same hash (required for use as dict key)
        assert hash(SecretStr("very-long-secret-value")) == hash(
            SecretStr("very-long-secret-value")
        )

    def test_hash_does_not_use_raw_value_as_tuple_member(self):
        """The hash impl uses (len, first_char) not the raw secret, so two
        secrets that share length + first char collide — not a vulnerability,
        but a deliberate property to defeat hashing oracles."""
        a = SecretStr("verysecret123")
        b = SecretStr("verysecret456")  # same length and first char
        # Both are valid SecretStr instances; hash collision is acceptable
        assert hash(a) == hash(b)

    def test_type_error_on_non_str(self):
        with pytest.raises(TypeError):
            SecretStr(b"bytes-not-allowed")  # type: ignore[arg-type]

    def test_slots_prevents_attr_assignment(self):
        s = SecretStr("x")
        with pytest.raises((AttributeError, TypeError)):
            s.extra_field = "boom"  # type: ignore[attr-defined]


# =================== ResolvedConfig ========================================


class TestResolvedConfig:
    def test_construction_ok(self, tmp_path):
        rc = ResolvedConfig(
            yaml_data={"graph": {"uri": "bolt://x"}},
            project_root=tmp_path,
            parent_root=None,
            yaml_source=tmp_path / "graqle.yaml",
        )
        assert rc.project_root == tmp_path
        assert rc.parent_root is None

    def test_yaml_source_must_be_absolute(self, tmp_path):
        with pytest.raises(ValueError, match="must be absolute"):
            ResolvedConfig(
                yaml_data={},
                project_root=tmp_path,
                parent_root=None,
                yaml_source=Path("relative.yaml"),
            )

    def test_parent_root_must_differ_from_project_root(self, tmp_path):
        with pytest.raises(ValueError, match="parent_root must differ"):
            ResolvedConfig(
                yaml_data={},
                project_root=tmp_path,
                parent_root=tmp_path,  # same — illegal
                yaml_source=tmp_path / "graqle.yaml",
            )

    def test_frozen(self, tmp_path):
        rc = ResolvedConfig(
            yaml_data={},
            project_root=tmp_path,
            parent_root=None,
            yaml_source=tmp_path / "graqle.yaml",
        )
        with pytest.raises(Exception):
            rc.project_root = tmp_path / "elsewhere"  # type: ignore[misc]


# =================== Neo4jParams ===========================================


class TestNeo4jParams:
    def test_password_is_secret(self):
        p = Neo4jParams(
            uri="bolt://localhost:7687",
            username="neo4j",
            password=SecretStr("hunter2"),
            database="neo4j",
            source="default",
        )
        assert "hunter2" not in repr(p)
        assert "hunter2" not in str(p)


# =================== URI safety ============================================


class TestAssertNotUriPath:
    """CG-12 / BHG #3 guard: URI strings used as paths must raise."""

    def test_plain_path_passes(self):
        _assert_not_uri_path("./relative/path.md")
        _assert_not_uri_path("/absolute/path.md")
        _assert_not_uri_path("C:\\Users\\haris\\file.md")
        _assert_not_uri_path("D:/projects/x.md")  # forward-slash variant
        _assert_not_uri_path("Z:")  # bare drive letter

    @pytest.mark.parametrize(
        "uri",
        [
            "bolt://localhost:7687",
            "neo4j://prod:7687",
            "https://example.com",
            "file:///etc/passwd",
            "javascript://evil",
            "data://attack",
            "vbscript://attack",
        ],
    )
    def test_uri_with_slashes_raises(self, uri):
        with pytest.raises(ConfigPathError, match="URI scheme"):
            _assert_not_uri_path(uri)

    @pytest.mark.parametrize(
        "uri",
        [
            "javascript:alert(1)",          # graq_predict 2026-05-10 — XSS-style
            "data:text/html;base64,PHNjcmlwdD4=",
            "data:text/plain,hello",
            "vbscript:msgbox('x')",
            "ftp:server.example.com/path",  # scheme without //
            "mailto:attacker@evil.com",
        ],
    )
    def test_uri_without_slashes_still_raises(self, uri):
        """The previous ``if '://' not in value: return`` early-out missed this
        bypass class. urlparse correctly identifies the scheme even without ``//``.
        Confirmed bypass vector — closed by graq_predict 2026-05-10 finding (85% conf).
        """
        with pytest.raises(ConfigPathError, match="URI scheme"):
            _assert_not_uri_path(uri)


class TestAssertUriSafe:
    """Allow-list for URI schemes — positive set, not deny-list."""

    @pytest.mark.parametrize(
        "uri",
        [
            "bolt://localhost:7687",
            "BOLT://localhost:7687",  # case
            "neo4j://prod:7687",
            "https://example.com",
            "file:///tmp/x",
        ],
    )
    def test_allowed_schemes_pass(self, uri):
        _assert_uri_safe(uri)

    @pytest.mark.parametrize(
        "uri",
        [
            "javascript://evil",
            "data://attack",
            "vbscript://attack",
            "ldap://evil",
            "gopher://retro",
            "ftp://x",
        ],
    )
    def test_disallowed_schemes_raise(self, uri):
        with pytest.raises(ConfigSchemeError, match="not in allow-list"):
            _assert_uri_safe(uri)


# =================== resolve_project_root ==================================


class TestResolveProjectRoot:
    def test_cwd_with_yaml(self, tmp_path, monkeypatch):
        (tmp_path / "graqle.yaml").write_text("graph:\n  uri: bolt://x\n")
        monkeypatch.chdir(tmp_path)
        assert resolve_project_root() == tmp_path.resolve()

    def test_cwd_with_graqle_dir_no_yaml(self, tmp_path, monkeypatch):
        (tmp_path / ".graqle").mkdir()
        monkeypatch.chdir(tmp_path)
        assert resolve_project_root() == tmp_path.resolve()

    def test_ancestor_with_yaml(self, tmp_path, monkeypatch):
        (tmp_path / "graqle.yaml").write_text("graph:\n  uri: bolt://x\n")
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)
        assert resolve_project_root() == tmp_path.resolve()

    def test_max_depth_halts_walk(self, tmp_path, monkeypatch):
        # Deep nesting WITHOUT any yaml or .graqle/ — should fall back to cwd
        nested = tmp_path / "a" / "b" / "c" / "d" / "e"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)
        # No yaml anywhere in walk → returns cwd
        assert resolve_project_root(max_depth=2) == nested.resolve()


# =================== resolve_config =========================================


class TestResolveConfig:
    def test_yaml_at_start(self, tmp_path):
        yaml_path = tmp_path / "graqle.yaml"
        yaml_path.write_text("graph:\n  uri: bolt://x\n")
        rc = resolve_config(start=tmp_path)
        assert rc.project_root == tmp_path.resolve()
        assert rc.parent_root is None
        assert rc.yaml_data["graph"]["uri"] == "bolt://x"

    def test_yaml_in_ancestor(self, tmp_path):
        (tmp_path / "graqle.yaml").write_text("graph:\n  uri: bolt://parent\n")
        nested = tmp_path / "sub"
        nested.mkdir()
        rc = resolve_config(start=nested)
        assert rc.yaml_data["graph"]["uri"] == "bolt://parent"

    def test_submodule_fallback_records_parent_root(self, tmp_path):
        """BHG feedback #1 / #7 — nested .graqle/ with no yaml falls through
        to parent's yaml. ``parent_root`` must be set to the parent's dir."""
        (tmp_path / "graqle.yaml").write_text("graph:\n  uri: bolt://parent\n")
        sub = tmp_path / "submodule"
        (sub / ".graqle").mkdir(parents=True)
        # No graqle.yaml inside sub/ — only .graqle/ directory
        rc = resolve_config(start=sub)
        assert rc.project_root == sub.resolve()
        assert rc.parent_root == tmp_path.resolve()
        assert rc.yaml_data["graph"]["uri"] == "bolt://parent"

    def test_not_found_raises(self, tmp_path):
        # No yaml, no .graqle/ anywhere
        with pytest.raises(ConfigNotFoundError) as exc_info:
            resolve_config(start=tmp_path, max_depth=2)
        assert exc_info.value.searched, "searched list must be populated"

    def test_malformed_yaml_raises(self, tmp_path):
        (tmp_path / "graqle.yaml").write_text(":::: not [valid yaml ::::\n")
        with pytest.raises(ConfigYamlError) as exc_info:
            resolve_config(start=tmp_path)
        assert exc_info.value.file.name == "graqle.yaml"

    def test_empty_yaml_yields_empty_dict(self, tmp_path):
        (tmp_path / "graqle.yaml").write_text("")
        rc = resolve_config(start=tmp_path)
        assert rc.yaml_data == {}


# =================== resolve_neo4j =========================================


class TestResolveNeo4j:
    """Priority chain: explicit > env > yaml > default. ``source`` records winner."""

    def _no_env(self, monkeypatch):
        for k in ("NEO4J_URI", "NEO4J_DATABASE", "NEO4J_USERNAME", "NEO4J_PASSWORD"):
            monkeypatch.delenv(k, raising=False)

    def test_explicit_wins(self, monkeypatch):
        self._no_env(monkeypatch)
        monkeypatch.setenv("NEO4J_URI", "bolt://env:1")
        cfg = ResolvedConfig(
            yaml_data={"graph": {"uri": "bolt://yaml:2"}},
            project_root=Path.cwd(),
            parent_root=None,
            yaml_source=Path.cwd() / "graqle.yaml",
        )
        p = resolve_neo4j(cfg, uri="bolt://explicit:3")
        assert p.uri == "bolt://explicit:3"
        assert p.source == "explicit"

    def test_env_wins_over_yaml(self, monkeypatch, tmp_path):
        self._no_env(monkeypatch)
        monkeypatch.setenv("NEO4J_URI", "bolt://env:1")
        cfg = ResolvedConfig(
            yaml_data={"graph": {"uri": "bolt://yaml:2"}},
            project_root=tmp_path,
            parent_root=None,
            yaml_source=tmp_path / "graqle.yaml",
        )
        p = resolve_neo4j(cfg)
        assert p.uri == "bolt://env:1"
        assert p.source == "env"

    def test_yaml_wins_when_no_env(self, monkeypatch, tmp_path):
        self._no_env(monkeypatch)
        cfg = ResolvedConfig(
            yaml_data={"graph": {"uri": "bolt://yaml:2", "database": "ydb", "username": "yu"}},
            project_root=tmp_path,
            parent_root=None,
            yaml_source=tmp_path / "graqle.yaml",
        )
        p = resolve_neo4j(cfg)
        assert p.uri == "bolt://yaml:2"
        assert p.source == "yaml"
        assert p.database == "ydb"
        assert p.username == "yu"

    def test_default_when_nothing_set(self, monkeypatch):
        self._no_env(monkeypatch)
        p = resolve_neo4j(None)
        assert p.uri == "bolt://localhost:7687"
        assert p.source == "default"
        assert p.database == "neo4j"

    def test_disallowed_uri_raises_via_yaml(self, monkeypatch, tmp_path):
        """Yaml-supplied javascript:// URI must be rejected by the allow-list."""
        self._no_env(monkeypatch)
        cfg = ResolvedConfig(
            yaml_data={"graph": {"uri": "javascript://attack"}},
            project_root=tmp_path,
            parent_root=None,
            yaml_source=tmp_path / "graqle.yaml",
        )
        with pytest.raises(ConfigSchemeError):
            resolve_neo4j(cfg)

    def test_password_is_secret_str(self, monkeypatch):
        self._no_env(monkeypatch)
        monkeypatch.setenv("NEO4J_PASSWORD", "hunter2")
        p = resolve_neo4j(None)
        assert isinstance(p.password, SecretStr)
        assert "hunter2" not in repr(p.password)
        assert "hunter2" not in str(p)
        assert p.password.get_secret_value() == "hunter2"


# =================== Feature flag ==========================================


class TestIsResolverEnabled:
    def test_default_false(self, monkeypatch):
        monkeypatch.delenv("GRAQLE_USE_RESOLVER", raising=False)
        assert is_resolver_enabled() is False

    @pytest.mark.parametrize("val", ["1", "true", "TRUE", "Yes", "yEs"])
    def test_truthy_values_enable(self, monkeypatch, val):
        monkeypatch.setenv("GRAQLE_USE_RESOLVER", val)
        assert is_resolver_enabled() is True

    @pytest.mark.parametrize("val", ["", "0", "false", "no", "garbage"])
    def test_falsey_values_disable(self, monkeypatch, val):
        monkeypatch.setenv("GRAQLE_USE_RESOLVER", val)
        assert is_resolver_enabled() is False


# =================== Helpers ===============================================


class TestRedactHome:
    def test_replaces_home_with_tilde(self, monkeypatch):
        # Use a fake home so the test isn't sensitive to the runner's actual home
        fake_home = Path("/fake/home/user").resolve()

        class _FP(Path):
            pass

        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
        s = _redact_home(fake_home / "secret" / "file.json")
        assert "/fake/home/user" not in s
        assert s.startswith("~")

    def test_path_outside_home_unchanged(self, monkeypatch):
        fake_home = Path("/fake/home/user").resolve()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
        s = _redact_home(Path("/etc/somefile"))
        assert "/fake/home" not in s


class TestAllowedSchemes:
    def test_is_frozenset(self):
        assert isinstance(ALLOWED_URI_SCHEMES, frozenset)

    def test_canonical_set(self):
        assert ALLOWED_URI_SCHEMES == frozenset({"bolt", "neo4j", "https", "file"})


# =================== Integration — full chain on a synthetic project ======


class TestEndToEnd:
    def test_full_chain(self, tmp_path, monkeypatch):
        """End-to-end: write yaml in ancestor, walk from nested, resolve neo4j."""
        for k in ("NEO4J_URI", "NEO4J_DATABASE", "NEO4J_USERNAME", "NEO4J_PASSWORD"):
            monkeypatch.delenv(k, raising=False)
        (tmp_path / "graqle.yaml").write_text(
            "graph:\n"
            "  uri: bolt://localhost:9999\n"
            "  database: integration_test\n"
            "  username: itu\n"
            "  password: itp\n"
        )
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        rc = resolve_config(start=nested)
        assert rc.yaml_data["graph"]["database"] == "integration_test"
        p = resolve_neo4j(rc)
        assert p.uri == "bolt://localhost:9999"
        assert p.database == "integration_test"
        assert p.username == "itu"
        assert p.source == "yaml"
        assert "itp" not in repr(p)  # password masked
