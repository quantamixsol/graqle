"""CR-002 PR-002a — exception hierarchy for the unified config resolver.

These exceptions all inherit from ``GraqleConfigError`` (which itself inherits
from ``GraqleError`` in graqle/core/exceptions.py) so that callers can either
catch the broad config-error class or branch on specific failure modes.

See: .gsm/external/Change Requests/CR-002-unified-config-resolution.md
"""

from __future__ import annotations

# -- graqle:intelligence --
# module: graqle.config.exceptions
# risk: LOW (impact radius: 0 modules — new file, no existing callers)
# dependencies: graqle.core.exceptions
# constraints: none
# -- /graqle:intelligence --

from pathlib import Path

from graqle.core.exceptions import GraqleError


class GraqleConfigError(GraqleError):
    """Base exception for all config resolution errors. Catch this to handle
    any resolver failure; branch on subclasses for specific recovery.
    """


class ConfigNotFoundError(GraqleConfigError):
    """Raised when ``graqle.yaml`` could not be found within the ancestor walk.

    ``searched`` is the list of paths the resolver looked at, suitable for
    logging or surfacing in error messages.
    """

    def __init__(self, searched: list[Path]) -> None:
        self.searched = list(searched)
        super().__init__(
            f"graqle.yaml not found in {len(self.searched)} ancestor "
            f"directories searched (max_depth applied)."
        )


class ConfigPathError(GraqleConfigError):
    """Raised when a value that should be a filesystem path looks like a URI,
    or vice-versa.

    Specifically guards the failure mode in BHG feedback #3 / CG-12 where the
    parent ``graqle.yaml``'s ``graph.uri`` was concatenated as a path segment
    producing ``C:\\...\\Graqle\\neo4j:\\bolt:\\<rest>``.
    """


class ConfigYamlError(GraqleConfigError):
    """Raised when a ``graqle.yaml`` file exists but is not valid YAML."""

    def __init__(self, *, file: Path, original: Exception) -> None:
        self.file = file
        self.original = original
        super().__init__(
            f"YAML parse error in {file.name}: {type(original).__name__}: {original}"
        )


class ConfigPermissionError(GraqleConfigError):
    """Raised when ``graqle.yaml`` exists but cannot be read due to permissions.

    The error message redacts ``Path.home()`` to ``~/`` to avoid leaking
    full filesystem paths into logs.
    """


class ConfigLockError(GraqleConfigError):
    """Raised when the resolver could not acquire a shared file lock on the
    yaml within the configured retry budget.
    """

    def __init__(self, *, file: Path, retries: int) -> None:
        self.file = file
        self.retries = retries
        super().__init__(
            f"Could not acquire shared read lock on {file.name} after {retries} retries."
        )


class ConfigSchemeError(GraqleConfigError):
    """Raised when a URI scheme is not in the allow-list.

    The allow-list is a positive set ``{bolt, neo4j, https, file}``; this
    closes the case-/encoding-/Unicode-bypass class that an explicit deny-list
    would leave open (security review found 5 such bypasses on v1 of the spec).
    """


# ─────────────── CR-010.R5 — secrets provider abstraction ────────────────────
# These extend the config-error hierarchy for the secrets resolver
# (graqle/config/secrets.py). Both are fail-closed by contract: the resolver
# raises rather than returning an empty credential, and NEITHER exception ever
# embeds the resolved credential value in its message — only the credential
# *name*, the provider, and a redacted reference are ever surfaced.


class SecretResolutionError(GraqleConfigError):
    """Raised when a required credential could not be resolved by any provider.

    Carries the logical credential ``name``, the ``provider`` that was tried,
    and a short human ``reason``. The underlying secret value is NEVER included
    — only metadata safe to log. Fail-closed: the resolver raises this instead
    of silently returning an empty string when a required secret is absent.
    """

    def __init__(self, *, name: str, provider: str, reason: str) -> None:
        self.name = name
        self.provider = provider
        self.reason = reason
        super().__init__(
            f"Could not resolve secret {name!r} via provider {provider!r}: {reason}"
        )


class SecretProviderUnsupportedError(GraqleConfigError):
    """Raised when a secrets provider is requested but not available here.

    The canonical case is ``keychain`` on a non-macOS host. ``platform`` records
    the running platform so the message is actionable without leaking anything.
    """

    def __init__(self, *, provider: str, platform: str) -> None:
        self.provider = provider
        self.platform = platform
        super().__init__(
            f"Secrets provider {provider!r} is not supported on platform "
            f"{platform!r}. Use provider 'file', 'env', or 'command' instead."
        )
