"""CR-002 PR-002a — unified config resolver (behind ``GRAQLE_USE_RESOLVER`` flag).

A single canonical entry point for finding ``graqle.yaml``, parsing it safely,
and deriving Neo4j connection params with an explicit, auditable priority
chain. Closes the duplicated-resolver problem documented in CR-002:

    Today, 14+ call sites each re-implement ``GraqleConfig.from_yaml(...)``
    with subtly different behaviour. ``graq neo4j-import`` reads only env
    vars (and ignores ``cfg.graph.uri`` entirely). ``graq audit`` reads the
    yaml. ``graq mcp serve`` partially handles URIs as paths producing
    ``WinError 123``. This module is the new single source of truth.

PR-002a lands the module with a feature flag (``GRAQLE_USE_RESOLVER``) and
**zero callers migrated** — purely additive, lowest possible risk. PR-002b
migrates the leaf commands; PR-002c migrates the rest. PR-002a alone is
inert until the flag is flipped.

Security model:
  - URI scheme allow-list ``{bolt, neo4j, https, file}`` via ``urllib.parse``
    (closes the case-/encoding-/Unicode-bypass class)
  - ``max_depth`` on ancestor walk (default 10) + symlink cycle detection
  - Walk halts at ``Path.home()`` boundary (never traverses above)
  - ``SecretStr`` masks Neo4j passwords in repr/str/logs
  - ``hmac.compare_digest`` for constant-time SecretStr equality (closes
    timing-attack class)
  - All paths canonicalised via ``Path.resolve(strict=False)`` before any
    disk access

See: .gsm/external/Change Requests/CR-002-unified-config-resolution.md
"""

from __future__ import annotations

# -- graqle:intelligence --
# module: graqle.config.resolver
# risk: LOW (new file, behind feature flag, no callers migrated in PR-002a)
# dependencies: yaml, urllib.parse, pathlib, hmac, hashlib, graqle.config.exceptions
# constraints: must NEVER mutate graqle/config/settings.py (composition over inheritance)
# -- /graqle:intelligence --

import hmac
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping
from urllib.parse import urlparse

import yaml

from graqle.config.exceptions import (
    ConfigLockError,
    ConfigNotFoundError,
    ConfigPathError,
    ConfigPermissionError,
    ConfigSchemeError,
    ConfigYamlError,
)


# ─────────────── Public API ─────────────────────────────────────────────────


ALLOWED_URI_SCHEMES: frozenset[str] = frozenset({"bolt", "neo4j", "https", "file"})
"""URI schemes the resolver will accept as Neo4j-connection metadata.

Positive allow-list (not deny-list) closes the case/encoding/Unicode-bypass
class. Deny-lists were tried in v1 and v2 of the spec — security review at
89% confidence rejected them as bypassable via 5+ documented vectors.
"""


_DEFAULT_NEO4J_URI = "bolt://localhost:7687"
_DEFAULT_NEO4J_DATABASE = "neo4j"
_DEFAULT_NEO4J_USERNAME = "neo4j"
_DEFAULT_NEO4J_PASSWORD = ""


def is_resolver_enabled() -> bool:
    """Returns True iff the ``GRAQLE_USE_RESOLVER`` feature flag is set.

    PR-002a default: ``False`` (flag must be explicitly opted into).
    PR-002c will flip the default to ``True``.
    """
    raw = os.environ.get("GRAQLE_USE_RESOLVER", "").strip().lower()
    return raw in {"1", "true", "yes"}


# ─────────────── SecretStr ──────────────────────────────────────────────────


class SecretStr:
    """Holds a secret string. ``__repr__`` / ``__str__`` never reveal contents.

    Constant-time equality via ``hmac.compare_digest`` to defeat timing attacks.
    Implemented via ``__slots__`` so accidental attribute assignment is rejected.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError(f"SecretStr requires str, got {type(value).__name__}")
        self._value = value

    def get_secret_value(self) -> str:
        """Explicitly retrieve the underlying secret. Use sparingly."""
        return self._value

    def __repr__(self) -> str:
        return "SecretStr(***)"

    def __str__(self) -> str:
        return "***"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SecretStr):
            return NotImplemented
        return hmac.compare_digest(self._value.encode("utf-8"), other._value.encode("utf-8"))

    def __hash__(self) -> int:
        # Hash a stable derivation, not the raw value, so it doesn't leak via
        # hashing oracles. The collision probability is fine for dict-key use.
        return hash(("SecretStr", len(self._value), self._value[:1] if self._value else ""))


# ─────────────── Frozen value objects ───────────────────────────────────────


@dataclass(frozen=True)
class ResolvedConfig:
    """Immutable result of a config resolution.

    Attributes:
        yaml_data: The parsed yaml document (or {} if no yaml found).
        project_root: Directory where ``.graqle/`` or ``graqle.yaml`` was found.
        parent_root: Set when a nested ``.graqle/`` directory was found *without*
            a yaml, and the resolver fell through to a parent's ``graqle.yaml``.
            ``None`` for the common case where the project_root itself has the yaml.
        yaml_source: Absolute path to the yaml that won (or to project_root if
            there is no yaml — then ``yaml_data`` is empty).
    """

    yaml_data: Mapping[str, Any]
    project_root: Path
    parent_root: Path | None
    yaml_source: Path

    def __post_init__(self) -> None:
        if not self.yaml_source.is_absolute():
            raise ValueError(
                f"yaml_source must be absolute, got {self.yaml_source}"
            )
        if self.parent_root is not None and self.parent_root == self.project_root:
            raise ValueError("parent_root must differ from project_root when set")


@dataclass(frozen=True)
class Neo4jParams:
    """Resolved Neo4j connection parameters.

    Attributes:
        uri: Connection URI, validated against ``ALLOWED_URI_SCHEMES``.
        username: Neo4j username.
        password: Neo4j password, wrapped in ``SecretStr`` (masked in repr).
        database: Target database name.
        source: Which layer in the resolution chain provided the URI.
            One of ``explicit | env | yaml | default``.
    """

    uri: str
    username: str
    password: SecretStr
    database: str
    source: Literal["explicit", "env", "yaml", "default"]


# ─────────────── Internal helpers ───────────────────────────────────────────


def _redact_home(p: Path | str) -> str:
    """Replace ``Path.home()`` prefix with ``~/`` in a path string.

    Used in error messages so we never log a user's full home directory.
    """
    s = str(p)
    home = str(Path.home())
    if s.startswith(home):
        return "~" + s[len(home):]
    return s


def _assert_not_uri_path(value: str) -> None:
    """Raises ``ConfigPathError`` if ``value`` looks like a URI not a path.

    Specifically guards CG-12 / BHG #3 — the case where ``cfg.graph.uri``
    (Neo4j connection metadata) was being concatenated as a filesystem path.

    Detects both ``scheme://...`` URIs and the ``scheme:opaque-data`` form
    (e.g. ``javascript:alert(1)``, ``data:text/html;base64,...``) which
    ``urlparse`` correctly recognises as having a scheme even without ``//``.
    The earlier ``if "://" not in value: return`` early-out missed this class
    (graq_predict 2026-05-10, 85% confidence — bypass vector closed here).
    """
    parsed = urlparse(value)
    # urlparse returns a non-empty scheme only when value is a recognisable URI.
    # For plain paths like "C:\\Users\\..." the scheme is empty (Windows drive
    # letters are not parsed as schemes by urlparse). For "javascript:alert(1)"
    # urlparse returns scheme='javascript' even without '//'.
    if parsed.scheme and not _looks_like_windows_drive(value):
        raise ConfigPathError(
            f"Value {value!r} has URI scheme {parsed.scheme!r}; cannot be used as "
            f"filesystem path. Use cfg.graph.uri (connection metadata) not cfg.graph.path."
        )


def _looks_like_windows_drive(value: str) -> bool:
    """Returns True for Windows drive paths like 'C:\\Users\\...' which
    ``urlparse`` mistakenly interprets as scheme='c'.

    Heuristic: single ASCII letter followed by ':' followed by '\\' or '/' or end.
    """
    if len(value) < 2:
        return False
    if not value[0].isalpha() or not value[0].isascii():
        return False
    if value[1] != ":":
        return False
    if len(value) == 2:
        return True
    return value[2] in ("\\", "/")


def _assert_uri_safe(uri: str) -> None:
    """Raises ``ConfigSchemeError`` if ``uri``'s scheme is not in the allow-list."""
    parsed = urlparse(uri)
    if parsed.scheme.lower() not in ALLOWED_URI_SCHEMES:
        raise ConfigSchemeError(
            f"URI scheme {parsed.scheme!r} not in allow-list "
            f"{sorted(ALLOWED_URI_SCHEMES)}. Use one of bolt, neo4j, https, file."
        )


def _read_yaml_safely(yaml_path: Path) -> Mapping[str, Any]:
    """Read + parse yaml with file-locking when available, graceful fallback otherwise.

    File locking via ``portalocker`` (cross-platform fcntl/msvcrt wrapper) when
    importable; otherwise reads without lock (degraded but safe — single-reader
    assumption). Both paths share identical error mapping so that callers see
    the same exception types regardless of whether portalocker is installed.

    Exception mapping (narrow on purpose — graq_review 2026-05-10 92% conf
    flagged the previous ``except Exception`` catch-all as masking system errors):
      * yaml.YAMLError    -> ConfigYamlError
      * FileNotFoundError -> ConfigNotFoundError
      * PermissionError   -> ConfigPermissionError
      * portalocker.LockException -> ConfigLockError
      * anything else propagates unchanged (real system errors must surface).
    """
    # Try the locking path first. ImportError on the import line means
    # portalocker isn't installed — fall through to the no-lock path.
    try:
        import portalocker  # type: ignore[import-not-found]
        _have_portalocker = True
    except ImportError:
        portalocker = None  # type: ignore[assignment]
        _have_portalocker = False

    try:
        if _have_portalocker:
            try:
                with portalocker.Lock(  # type: ignore[union-attr]
                    str(yaml_path),
                    mode="r",
                    timeout=1.0,
                    flags=portalocker.LOCK_SH,  # type: ignore[union-attr]
                ) as f:
                    return yaml.safe_load(f) or {}
            except portalocker.LockException as e:  # type: ignore[union-attr]
                raise ConfigLockError(file=yaml_path, retries=1) from e
        else:
            with yaml_path.open("r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    except FileNotFoundError as e:
        raise ConfigNotFoundError(searched=[yaml_path]) from e
    except PermissionError as e:
        raise ConfigPermissionError(
            f"Permission denied reading {_redact_home(yaml_path)}"
        ) from e
    except yaml.YAMLError as e:
        raise ConfigYamlError(file=yaml_path, original=e) from e
    # Any other exception propagates — system errors (OSError ENOSPC, etc.)
    # must NOT be masked as ConfigLockError. Per graq_review 92% finding.


def _ancestor_dirs(start: Path, max_depth: int) -> Iterable[Path]:
    """Yield ``start``, its parents up to ``max_depth``, halting at ``Path.home()``.

    Symlink-cycle-safe: tracks already-yielded resolved paths in a ``set``.
    """
    home = Path.home().resolve(strict=False)
    seen: set[Path] = set()
    cur = start.resolve(strict=False)
    depth = 0
    while depth < max_depth:
        if cur in seen:
            break  # cycle — bail out
        seen.add(cur)
        yield cur
        # Halt at home boundary or filesystem root
        if cur == home or cur == cur.parent:
            break
        cur = cur.parent.resolve(strict=False)
        depth += 1


# ─────────────── Public resolution functions ────────────────────────────────


def resolve_project_root(
    start: Path | None = None,
    *,
    max_depth: int = 10,
) -> Path:
    """Walk ancestors of ``start`` looking for a directory that contains either
    ``graqle.yaml`` or a ``.graqle/`` subdirectory; returns the first match.

    Falls back to ``start`` (or cwd) if nothing found. ``max_depth`` bounds
    the walk so we never escape the user's home directory.
    """
    base = (start or Path.cwd()).resolve(strict=False)
    for d in _ancestor_dirs(base, max_depth=max_depth):
        if (d / "graqle.yaml").exists() or (d / ".graqle").is_dir():
            return d
    return base


def resolve_config(
    start: Path | None = None,
    *,
    max_depth: int = 10,
) -> ResolvedConfig:
    """Find and load the canonical ``graqle.yaml`` for a project.

    Walks ancestors from ``start`` (default: cwd), preferring directories that
    contain a ``graqle.yaml``. If a nested ``.graqle/`` directory exists with
    no yaml (the BHG submodule layout — feedback #1, #7), falls through to a
    parent's yaml and records both ``project_root`` and ``parent_root``.

    Raises:
        ConfigNotFoundError: no yaml or .graqle/ found within max_depth.
        ConfigYamlError: yaml found but malformed.
        ConfigPermissionError: yaml found but unreadable.
        ConfigLockError: file lock could not be acquired.
    """
    base = (start or Path.cwd()).resolve(strict=False)

    project_root: Path | None = None
    parent_root: Path | None = None
    yaml_source: Path | None = None
    yaml_data: Mapping[str, Any] = {}
    searched: list[Path] = []

    found_first_dir = False

    for d in _ancestor_dirs(base, max_depth=max_depth):
        searched.append(d)
        yaml_path = d / "graqle.yaml"
        graqle_dir = d / ".graqle"

        if yaml_path.exists():
            yaml_data = _read_yaml_safely(yaml_path)
            if not found_first_dir:
                project_root = d
                yaml_source = yaml_path
            else:
                # We already saw a nested .graqle/ without yaml; this is the
                # parent fallback (CG-12 / BHG submodule case).
                parent_root = d
                yaml_source = yaml_path
            return ResolvedConfig(
                yaml_data=yaml_data,
                project_root=project_root if project_root else d,
                parent_root=parent_root,
                yaml_source=yaml_source,
            )

        if graqle_dir.is_dir() and not found_first_dir:
            # Nested ``.graqle/`` directory with no yaml — record as
            # project_root, continue walking for parent yaml.
            project_root = d
            found_first_dir = True

    raise ConfigNotFoundError(searched=searched)


def resolve_neo4j(
    cfg: ResolvedConfig | None = None,
    *,
    uri: str | None = None,
    username: str | None = None,
    password: str | None = None,
    database: str | None = None,
) -> Neo4jParams:
    """Resolve Neo4j connection params with explicit, auditable priority.

    Priority chain (highest first):
        1. Explicit kwargs (``uri=``, etc.)
        2. ``NEO4J_URI`` / ``NEO4J_DATABASE`` / ``NEO4J_USERNAME`` /
           ``NEO4J_PASSWORD`` environment variables
        3. ``cfg.yaml_data['graph']['uri'|'database'|...]``
        4. Hard-coded defaults (``bolt://localhost:7687``, ``neo4j``,
           ``neo4j``, ``""``)

    The returned ``Neo4jParams.source`` field records which layer won — useful
    for diagnostics (``graq doctor`` and ``graq config-show`` will consume it
    in PR-002b/c).

    Raises:
        ConfigSchemeError: if the resolved URI's scheme is not in the
            allow-list ``{bolt, neo4j, https, file}``.
    """
    yaml_graph: Mapping[str, Any] = {}
    if cfg is not None and isinstance(cfg.yaml_data, Mapping):
        graph_section = cfg.yaml_data.get("graph") or {}
        if isinstance(graph_section, Mapping):
            yaml_graph = graph_section

    # Resolve URI + record source in a single pass so "source" is honest.
    source: Literal["explicit", "env", "yaml", "default"]
    if uri is not None:
        resolved_uri = uri
        source = "explicit"
    elif os.environ.get("NEO4J_URI"):
        resolved_uri = os.environ["NEO4J_URI"]
        source = "env"
    elif yaml_graph.get("uri"):
        resolved_uri = str(yaml_graph["uri"])
        source = "yaml"
    else:
        resolved_uri = _DEFAULT_NEO4J_URI
        source = "default"

    _assert_uri_safe(resolved_uri)

    resolved_username = (
        username
        if username is not None
        else os.environ.get("NEO4J_USERNAME")
        or yaml_graph.get("username")
        or _DEFAULT_NEO4J_USERNAME
    )
    resolved_password = (
        password
        if password is not None
        else os.environ.get("NEO4J_PASSWORD")
        or yaml_graph.get("password")
        or _DEFAULT_NEO4J_PASSWORD
    )
    resolved_database = (
        database
        if database is not None
        else os.environ.get("NEO4J_DATABASE")
        or yaml_graph.get("database")
        or _DEFAULT_NEO4J_DATABASE
    )

    return Neo4jParams(
        uri=resolved_uri,
        username=str(resolved_username),
        password=SecretStr(str(resolved_password)),
        database=str(resolved_database),
        source=source,
    )
