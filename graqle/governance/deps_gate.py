"""CG-13 Dependency Gate — supply-chain pre-checks for pip/npm/yarn installs.

Threat model (Phase 6 scope):
  - Direct installs only (transitive deps handled by manager's resolver;
    we cannot intervene without installing).
  - Supported specs: ``name``, ``name==version``, ``name>=X,<Y``, ``name~=X``.
    Rejected: git/URL/local-path refs (``-e git+``, ``./local``, URLs,
    absolute paths).
  - No source/index allowlisting in Phase 6 (deferred W2P6-R4).
  - Manager-specific normalization for typosquat comparison:
      * pip: strip [extras], lowercase, normalize dash/underscore
      * npm: accept @scope/name; typosquat runs on the ``name`` portion
      * yarn: same as npm

Validation order (STRICT):
  1. Manager enum validation.
  2. Packages is list + non-empty.
  3. Normalize per manager + dedupe (warning-only for duplicates).
  4. Reject unsupported refs (git+/URL/path).
  5. Reject whitespace-only / empty-after-normalize entries.
  6. Known-bad blocklist check.
  7. Typosquat heuristic against known-good list.
  8. Approval check (only if ``dry_run=False``).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from graqle.governance.allowlist import _validate_allowlist
from graqle.governance.config_drift import build_error_envelope

logger = logging.getLogger("graqle.governance.deps_gate")


# ─────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────

_VALID_MANAGERS: tuple[str, ...] = ("pip", "npm", "yarn")
_APPROVER_MIN_LEN: int = 3

# Unsupported package-spec forms
_UNSUPPORTED_PREFIXES: tuple[str, ...] = (
    "-e ", "-e", "git+", "hg+", "svn+", "bzr+",
    "http://", "https://", "ftp://",
    "file:", "file://",
    "./", "../", "~/",
)

# Known-bad package seed (LiteLLM-class supply-chain incident examples)
_KNOWN_BAD_PACKAGES: frozenset[str] = frozenset({
    "lietllm-proxy",       # typosquat of litellm
    "litellm-proxy",       # ambiguous — legitimate is `litellm`
    "python-openai",       # unofficial
    "openai-proxy",        # typosquat
    "anthropic-sdk",       # unofficial, legitimate is `anthropic`
    "chatgpt-api",         # typosquat
})

# Known-good canonical package names (used for typosquat baseline)
_KNOWN_GOOD_PACKAGES: frozenset[str] = frozenset({
    "openai", "anthropic", "boto3", "litellm",
    "requests", "httpx", "urllib3", "aiohttp",
    "pydantic", "fastapi", "starlette", "flask",
    "numpy", "pandas", "scipy", "matplotlib",
    "pytest", "pytest-asyncio", "pytest-xdist",
    "django", "sqlalchemy", "alembic",
    "react", "next", "vue", "svelte",
    "lodash", "axios", "express", "webpack",
})

# Approval format patterns
_APPROVAL_STRUCTURED = re.compile(
    r"^[A-Za-z0-9_.-]+:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?$"
)


# ─────────────────────────────────────────────────────────────────────────
# Manager-specific normalization
# ─────────────────────────────────────────────────────────────────────────


def _normalize_package_name(manager: str, spec: str) -> str:
    """Return the bare package name for typosquat/known-bad comparison.

    Strips version specifiers, pip extras, npm @scope prefix (for squat
    comparison we compare the ``name`` after the slash).
    Returns empty string if the spec is malformed.
    """
    if not isinstance(spec, str):
        return ""
    spec = spec.strip()
    if not spec:
        return ""
    if manager == "pip":
        # Strip version operators: ==, >=, <=, !=, ~=, <, >
        name = re.split(r"[=<>!~]", spec, maxsplit=1)[0].strip()
        # Strip [extras]
        name = re.sub(r"\[.*?\]", "", name).strip()
        # Normalize dash/underscore (PEP 503)
        name = name.replace("_", "-").lower()
        return name
    elif manager in ("npm", "yarn"):
        # Strip version: pkg@1.2.3 or @scope/pkg@1.2.3
        if spec.startswith("@"):
            # @scope/name[@version]
            parts = spec.split("/", 1)
            if len(parts) != 2:
                return ""
            scope, rest = parts
            name = rest.split("@", 1)[0]
            return f"{scope.lower()}/{name.lower()}"
        else:
            # plain name[@version]
            name = spec.split("@", 1)[0]
            return name.lower()
    return spec.lower()


def _typosquat_candidate(pkg_normalized: str, manager: str) -> str | None:
    """Return the known-good package that ``pkg_normalized`` looks like,
    or ``None`` if not a suspected typosquat.

    For npm/yarn @scope/name entries, compares the name portion only.
    """
    if not pkg_normalized:
        return None
    # For scoped npm packages, use the name after "/"
    compare_name = (
        pkg_normalized.split("/", 1)[1]
        if "/" in pkg_normalized
        else pkg_normalized
    )
    if compare_name in _KNOWN_GOOD_PACKAGES:
        return None
    for good in _KNOWN_GOOD_PACKAGES:
        if len(good) < 4:
            continue
        # Suffix variants: "openai-python", "openai_proxy", "openai-"
        if compare_name.startswith(good + "-") or compare_name.startswith(good + "_"):
            return good
        if compare_name == good + "-" or compare_name == good + "_":
            return good
        # Prefix variants: "pythonopenai", "proxyopenai"
        if compare_name.endswith("-" + good) or compare_name.endswith("_" + good):
            return good
        # Insertion variants: "open-ai" has a dash inserted into "openai"
        # Remove all dashes/underscores from compare and check equality
        stripped = compare_name.replace("-", "").replace("_", "")
        if stripped == good and compare_name != good:
            return good
        # Edit-distance 1-2 for similar-length
        if abs(len(compare_name) - len(good)) <= 2:
            diff = sum(
                a != b for a, b in zip(compare_name, good)
            ) + abs(len(compare_name) - len(good))
            if 0 < diff <= 2:
                return good
    return None


def _is_unsupported_spec(spec: str) -> bool:
    """True if the spec uses a ref form we don't support (git+, URL, path)."""
    if not isinstance(spec, str):
        return True
    s = spec.strip()
    for prefix in _UNSUPPORTED_PREFIXES:
        if s.startswith(prefix):
            return True
    # Absolute paths
    if len(s) >= 2 and s[1] == ":":  # Windows drive letter
        return True
    if s.startswith("/"):
        return True
    return False


def _approval_is_valid(approved_by: Any) -> bool:
    """Valid if structured (``actor:ISO-timestamp``) OR bare identifier
    with stripped length >= ``_APPROVER_MIN_LEN``.

    Bare identifier is legacy fallback (W2P6-R3 — preferred form is
    structured for future Enterprise-tier enforcement).
    """
    if not isinstance(approved_by, str):
        return False
    stripped = approved_by.strip()
    if len(stripped) < _APPROVER_MIN_LEN:
        return False
    if _APPROVAL_STRUCTURED.match(stripped):
        return True
    # Bare identifier fallback (must be reasonable format)
    return bool(re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]+$", stripped))


# ─────────────────────────────────────────────────────────────────────────
# check_deps_install
# ─────────────────────────────────────────────────────────────────────────


def check_deps_install(
    manager: Any,
    packages: Any,
    *,
    dry_run: bool = True,
    approved_by: str | None = None,
) -> tuple[bool, dict | None]:
    """CG-13 supply-chain gate. Returns ``(allowed, envelope)``.

    Strict validation order; first failing check wins.
    """
    # 1. Manager enum
    if not isinstance(manager, str) or manager not in _VALID_MANAGERS:
        return False, build_error_envelope(
            "CG-13_INVALID_MANAGER",
            f"manager must be one of {_VALID_MANAGERS}, got {manager!r}",
            manager=str(manager),
        )

    # 2. Packages is list + non-empty
    if not isinstance(packages, list) or len(packages) == 0:
        return False, build_error_envelope(
            "CG-13_INVALID_PACKAGES",
            "packages must be non-empty list",
            reasons=f"got {type(packages).__name__}",
        )

    # Validate each item is a non-empty string
    valid, reasons = _validate_allowlist(packages, expected_type=str, min_length=1)
    if not valid:
        return False, build_error_envelope(
            "CG-13_INVALID_PACKAGES",
            "packages must be list of non-empty strings",
            reasons="; ".join(reasons),
        )

    # 3. Normalize + dedupe
    normalized: list[tuple[str, str]] = []  # (raw_spec, normalized_name)
    seen_names: set[str] = set()
    duplicates: list[str] = []
    for spec in packages:
        # 4. Reject unsupported refs
        if _is_unsupported_spec(spec):
            return False, build_error_envelope(
                "CG-13_UNSUPPORTED_SPEC",
                f"unsupported package spec form: {spec!r}",
                spec=str(spec),
                hint=(
                    "Only 'name', 'name==version', 'name>=X,<Y' are supported. "
                    "git+/URL/path refs are not permitted."
                ),
            )
        name = _normalize_package_name(manager, spec)
        if not name:
            return False, build_error_envelope(
                "CG-13_INVALID_PACKAGES",
                f"could not extract package name from spec {spec!r}",
                spec=str(spec),
            )
        if name in seen_names:
            duplicates.append(name)
        else:
            seen_names.add(name)
            normalized.append((spec, name))

    if duplicates:
        logger.warning(
            "CG-13: duplicate packages deduplicated: %s", duplicates,
        )

    # 5. Known-bad check
    bad_hits = [
        (spec, name) for (spec, name) in normalized
        if name in _KNOWN_BAD_PACKAGES
        or (manager in ("npm", "yarn") and name.split("/", 1)[-1] in _KNOWN_BAD_PACKAGES)
    ]
    if bad_hits:
        return False, build_error_envelope(
            "CG-13_KNOWN_BAD_PACKAGE",
            f"known-bad package(s) detected: {[s for s, _ in bad_hits]}",
            packages=str([s for s, _ in bad_hits]),
            hint="These packages are on the built-in blocklist and cannot be installed.",
        )

    # 6. Typosquat check
    squat_hits: list[str] = []
    for spec, name in normalized:
        match = _typosquat_candidate(name, manager)
        if match:
            squat_hits.append(f"{spec} (looks like {match})")
    if squat_hits:
        return False, build_error_envelope(
            "CG-13_TYPOSQUAT_SUSPECTED",
            f"possible typosquat: {squat_hits}",
            hint=(
                "If these are legitimate, verify the package name on "
                "pypi.org/npmjs.com, then retry with an explicit approved_by."
            ),
        )

    # 7. Live install requires approval
    if not dry_run:
        if not _approval_is_valid(approved_by):
            return False, build_error_envelope(
                "CG-13_APPROVAL_REQUIRED",
                "live install requires approved_by (length >= 3)",
                hint=(
                    "Pass dry_run=True to preview the plan, or set "
                    "approved_by='<reviewer-id>' (preferred: "
                    "'<actor>:<ISO-timestamp>')."
                ),
            )

    return True, None  # safe to proceed


# ─────────────────────────────────────────────────────────────────────────
# Response builders (parallel to config_drift helpers)
# ─────────────────────────────────────────────────────────────────────────


def build_deps_dry_run_response(
    manager: str,
    packages: list[str],
) -> dict[str, Any]:
    """Dry-run plan. Caller is responsible for any actual install."""
    return {
        "action": "deps_install",
        "manager": manager,
        "packages": list(packages),
        "dry_run": True,
        "status": "approved_dry_run",
        "hint": "Pass dry_run=False and approved_by=<reviewer> to execute.",
    }


def build_deps_live_response(
    manager: str,
    packages: list[str],
    approved_by: str,
) -> dict[str, Any]:
    """Live install pre-approval response. The actual subprocess call is
    NOT performed by this module — the MCP handler does that and appends
    stdout/stderr/exit_code to the response."""
    return {
        "action": "deps_install",
        "manager": manager,
        "packages": list(packages),
        "dry_run": False,
        "approved_by": approved_by,
        "status": "approved_live",
    }
