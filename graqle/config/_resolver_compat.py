"""CR-002 PR-002c-2a — resolver-compat helper for legacy yaml-load call sites.

A handful of GraqleConfig.from_yaml() call sites hardcode a relative
``Path("graqle.yaml")`` lookup against the current working directory. These
trigger the PendingDeprecationWarning that PR-002c-1 added in
graqle/config/settings.py when GRAQLE_USE_RESOLVER is opted in.

This helper encapsulates the "try resolver, fall back to legacy" pattern
that PR-002b already established in three CLI commands (learn, audit,
neo4j_import) so the remaining hardcoded-path sites can migrate by
replacing 4 lines of boilerplate with a single call.

EU AI Act note: behaviour is strictly additive and reversible.
  * Default OFF — the function returns the legacy result unchanged when
    GRAQLE_USE_RESOLVER is unset.
  * On any exception from the resolver path → falls back to legacy
    GraqleConfig.from_yaml(default_path).
  * No logging change, no audit-trail loss, no governance text touched.

CI safety: no importlib.util.module_from_spec, no dataclass-with-init
trickery, no sys.modules manipulation (lesson from PR #89 CI hang).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from graqle.config.settings import GraqleConfig


def load_via_resolver_or_legacy(
    default_path: str | Path = "graqle.yaml",
) -> "GraqleConfig | None":
    """Resolve a GraqleConfig honouring the GRAQLE_USE_RESOLVER feature flag.

    Behaviour matrix:

    +-----------------------+------------------------------+--------------------+
    | GRAQLE_USE_RESOLVER   | default_path on disk         | Returned config    |
    +-----------------------+------------------------------+--------------------+
    | unset / falsy         | exists                       | from_yaml(default) |
    | unset / falsy         | missing                      | None               |
    | truthy + resolver OK  | (resolver finds yaml_source) | from_yaml(yaml_src)|
    | truthy + resolver err | exists                       | from_yaml(default) |
    | truthy + resolver err | missing                      | None               |
    +-----------------------+------------------------------+--------------------+

    Returns ``None`` when neither path nor resolver can produce a config —
    callers fall back to ``GraqleConfig.default()`` (matching the prior
    inline ``if config_file.exists() ... else None`` pattern).

    Argument
    --------
    default_path:
        The legacy relative-path filename. Defaults to ``"graqle.yaml"`` for
        the existing call sites. Passing an absolute Path is accepted but
        the resolver branch is still attempted first when the flag is on.

    Returns
    -------
    GraqleConfig | None

    Notes
    -----
    The resolver is imported lazily so this helper has no module-level
    dependency on it; ImportError is treated as "resolver unavailable"
    and falls back to legacy. This keeps the helper usable in environments
    where ``graqle.config.resolver`` has not yet been bundled (e.g.
    monkey-patched test contexts).
    """
    from graqle.config.settings import GraqleConfig

    legacy_path = Path(default_path)

    # CR-002 PR-002c-2a: opt-in resolver branch.
    try:
        from graqle.config.resolver import is_resolver_enabled, resolve_config
    except ImportError:
        is_resolver_enabled = None  # type: ignore[assignment]
        resolve_config = None  # type: ignore[assignment]

    if is_resolver_enabled is not None and is_resolver_enabled():
        try:
            resolved = resolve_config()
            return GraqleConfig.from_yaml(str(resolved.yaml_source))
        except Exception:  # noqa: BLE001 — fail-safe to legacy path
            # Suppressed exception is intentional. The legacy path below is
            # the safety net. We don't log here because the deprecation
            # warning in GraqleConfig.from_yaml already surfaces the
            # opt-in state to the user when the legacy path runs with a
            # relative "graqle.yaml" — no double-logging.
            pass

    if legacy_path.exists():
        return GraqleConfig.from_yaml(str(legacy_path))
    return None
