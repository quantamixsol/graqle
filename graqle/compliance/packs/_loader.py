"""Data-driven compliance-pack loader (CR-010.R3).

A **compliance pack** is a regulatory framework expressed as data rather
than code: a directory holding exactly two files.

::

    graqle/compliance/packs/<pack_dir>/
        pack.yaml      # the pack content
        schema.json    # the pack's OWN schema, which pack.yaml must satisfy

The point of the pack format is that adding the *next* framework — NIST AI
RMF, ISO/IEC 42001, SOC 2, HIPAA — requires **no Python and no engine
change**: drop in two data files and the pack loads. The typed dataclasses
in :mod:`graqle.pct.extensions` remain available as ergonomic bootstraps
for the frameworks that have them, but they are not the mechanism.

Why each pack ships its own schema
----------------------------------
Proof-spec v1.0 permits unknown top-level members, so a bundle carrying an
unrecognised extension **passes v1.0 validation without that extension
being checked at all** (``proof-spec/v1.0/SPEC.md`` § 8.1). A green v1.0
validation is therefore not assurance about fields v1.0 never defined. Each
pack closes that gap for its own namespace by publishing a schema and being
validated against it here, in addition to v1.0.

Discovery is a directory scan — deliberately
--------------------------------------------
This module uses ``importlib.resources`` over the packaged ``packs/``
directory and nothing else. It does **not** use ``importlib.metadata``,
``pkg_resources``, or entry points: third-party installable packs are a
separate, larger question (plugin discovery, trust, and versioning of
code shipped by someone else), tracked as CR-010.R10. Keeping discovery to
first-party packaged data means a pack cannot arrive from an untrusted
distribution as a side effect of installing an unrelated library.

Failure posture: **fail closed, loudly**
----------------------------------------
Every load error raises :class:`CompliancePackError`. A malformed pack is
never skipped with a warning. A silently-skipped compliance pack is a
governance regression indistinguishable from "this framework does not
apply" — the same reasoning that rejected ``skipif``-when-file-absent for
the anti-fabrication gate in CR-B10.5.

References:
    - CR-010.R3 — Compliance packs as data
    - ``graqle/pct/schema/proof-spec/v1.0/SPEC.md`` § 8.1 — extension posture
    - :mod:`graqle.compliance.claim_limits.taxonomy` — the ``x-`` namespace regex
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import jsonschema
import yaml

from graqle.compliance.claim_limits.taxonomy import is_valid_claim_limit

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Filenames a pack directory must contain.
PACK_MANIFEST_FILENAME: str = "pack.yaml"
PACK_SCHEMA_FILENAME: str = "schema.json"

#: Keys required at the top level of ``pack.yaml``.
_REQUIRED_MANIFEST_KEYS: tuple[str, ...] = (
    "namespace",
    "pack_version",
    "framework",
)

#: Namespaces a pack may not claim, mapped to the pack that owns each.
#:
#: These are first-party namespaces whose vocabulary is defined in code and
#: relied upon by governance surfaces. The extension regex alone does not
#: protect them — ``x-ai-eu`` is a perfectly well-formed ``x-`` namespace —
#: so without this check an operator-authored pack could declare
#: ``namespace: x-ai-eu`` and shadow the EU AI Act vocabulary that
#: compliance reporting reads. Reserving them is cheap; discovering the
#: shadowing during an audit is not.
RESERVED_NAMESPACES: dict[str, str] = {
    "x-ai-eu": "graqle.pct.extensions.x_ai_eu (EU AI Act)",
    "x-sox": "graqle/compliance/packs/x_sox (SOX/COSO)",
}

#: The packaged directory permitted to declare each reserved namespace.
#: ``x-ai-eu`` maps to ``None`` because it is owned by a code module, not by
#: a pack directory — no pack may claim it.
_RESERVED_OWNER_DIRS: dict[str, str | None] = {
    "x-ai-eu": None,
    "x-sox": "x_sox",
}


class CompliancePackError(Exception):
    """Raised when a compliance pack is missing, malformed, or invalid.

    One exception type for every failure mode so a caller loading untrusted
    or operator-authored packs has a single thing to catch.
    """


# ---------------------------------------------------------------------------
# Pack value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompliancePack:
    """A loaded, validated compliance pack.

    Attributes:
        namespace: The ``x-``-prefixed extension namespace, e.g. ``"x-sox"``.
            Guaranteed to satisfy the taxonomy's extension regex.
        pack_version: The pack's own version string, independent of both the
            SDK version and the proof-spec version.
        framework: Human-readable framework name, e.g.
            ``"Sarbanes-Oxley Act / COSO Internal Control"``.
        claim_limits: Namespaced claim-limit values this pack contributes.
            Every entry is guaranteed to pass
            :func:`~graqle.compliance.claim_limits.taxonomy.is_valid_claim_limit`.
        fields: The field definitions from the manifest, keyed by field name.
        manifest: The full parsed ``pack.yaml``, for callers needing a key
            this dataclass does not surface.
        schema: The parsed ``schema.json`` the manifest was validated against.
    """

    namespace: str
    pack_version: str
    framework: str
    claim_limits: tuple[str, ...] = ()
    fields: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    schema: dict[str, Any] = field(default_factory=dict)

    def qualify(self, field_name: str) -> str:
        """Return ``field_name`` prefixed with this pack's namespace.

        ``pack.qualify("control_id") -> "x-sox:control_id"`` — the same
        ``{namespace}:{field}`` shape the typed extension dataclasses emit
        from ``to_pct_extension_dict()``.
        """
        return f"{self.namespace}:{field_name}"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _packs_root() -> Any:
    """Return the packaged ``packs/`` directory as a traversable.

    Uses ``importlib.resources`` rather than ``Path(__file__).parents[N]``:
    the latter silently resolves to a *different* directory once installed
    into site-packages, which is a latent wheel bug rather than a visible
    failure.
    """
    from importlib.resources import files as _files

    return _files("graqle.compliance.packs")


def _read_pack_text(resource: Any) -> str:
    """Read a pack file as text, tolerating a UTF-8 BOM.

    Decoded via ``read_bytes()`` + ``utf-8-sig`` rather than
    ``read_text(encoding="utf-8")`` for two measured reasons:

    1. A BOM is fatal to ``json.loads`` (``Unexpected UTF-8 BOM``) even
       though ``yaml.safe_load`` tolerates one — so a ``schema.json`` saved
       by a Windows editor would fail as "not valid JSON" while its
       ``pack.yaml`` sibling loaded fine. ``utf-8-sig`` strips the BOM when
       present and is a no-op when it is not.
    2. On some Python/zipimport combinations the ``encoding`` argument to
       ``Traversable.read_text`` has been unreliable, falling back to the
       platform default (``cp1252`` on Windows). Decoding explicitly removes
       that dependency.
    """
    return resource.read_bytes().decode("utf-8-sig")


def _parse_manifest(raw: str, pack_name: str) -> dict[str, Any]:
    """Parse and shape-check ``pack.yaml`` content."""
    try:
        manifest = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise CompliancePackError(
            f"compliance pack {pack_name!r}: {PACK_MANIFEST_FILENAME} is not "
            f"valid YAML: {exc}"
        ) from exc

    if not isinstance(manifest, dict):
        raise CompliancePackError(
            f"compliance pack {pack_name!r}: {PACK_MANIFEST_FILENAME} must "
            f"contain a mapping at the top level, got "
            f"{type(manifest).__name__}."
        )

    missing = [k for k in _REQUIRED_MANIFEST_KEYS if k not in manifest]
    if missing:
        raise CompliancePackError(
            f"compliance pack {pack_name!r}: {PACK_MANIFEST_FILENAME} is "
            f"missing required key(s): {', '.join(sorted(missing))}."
        )
    return manifest


def _validate_namespace(namespace: Any, pack_name: str) -> str:
    """Validate the pack namespace against the taxonomy extension rule.

    The loader registers *through* the existing taxonomy rather than around
    it: a pack namespace is exactly an operator-extension claim-limit value,
    so the single regex in ``taxonomy.py`` remains the one authority on what
    an ``x-`` namespace may look like.
    """
    if not isinstance(namespace, str):
        raise CompliancePackError(
            f"compliance pack {pack_name!r}: namespace must be a string, got "
            f"{type(namespace).__name__}."
        )
    if not is_valid_claim_limit(namespace):
        raise CompliancePackError(
            f"compliance pack {pack_name!r}: namespace {namespace!r} is not a "
            f"valid extension namespace — it must match "
            f"^x-[a-z0-9_-]{{1,64}}$ (lowercase, 'x-' prefixed)."
        )
    # A reserved namespace may only be claimed by the first-party pack that
    # owns it. `owner_pack` is the packaged directory name; any other pack
    # declaring the same namespace would shadow a governance vocabulary.
    owner = RESERVED_NAMESPACES.get(namespace)
    if owner is not None and pack_name != _RESERVED_OWNER_DIRS.get(namespace):
        raise CompliancePackError(
            f"compliance pack {pack_name!r}: namespace {namespace!r} is "
            f"RESERVED by {owner} and may not be declared by another pack. "
            f"Shadowing a first-party namespace would silently replace the "
            f"vocabulary that compliance reporting reads."
        )
    return namespace


def load_pack(pack_name: str) -> CompliancePack:
    """Load and validate one packaged compliance pack by directory name.

    Args:
        pack_name: The pack directory name, e.g. ``"x_sox"``.

    Returns:
        CompliancePack: The loaded, validated pack.

    Raises:
        CompliancePackError: If the directory or either file is absent, the
            YAML/JSON is malformed, a required key is missing, the namespace
            is not a valid ``x-`` extension namespace, a contributed claim
            limit is invalid, or ``pack.yaml`` does not validate against the
            pack's own ``schema.json``.
    """
    root = _packs_root()
    pack_dir = root / pack_name

    if not pack_dir.is_dir():
        raise CompliancePackError(
            f"compliance pack {pack_name!r} not found — expected a directory "
            f"at graqle/compliance/packs/{pack_name}/."
        )

    manifest_file = pack_dir / PACK_MANIFEST_FILENAME
    schema_file = pack_dir / PACK_SCHEMA_FILENAME
    for required in (manifest_file, schema_file):
        if not required.is_file():
            raise CompliancePackError(
                f"compliance pack {pack_name!r} is incomplete — missing "
                f"{required.name}. A pack must ship both "
                f"{PACK_MANIFEST_FILENAME} and {PACK_SCHEMA_FILENAME}."
            )

    manifest = _parse_manifest(_read_pack_text(manifest_file), pack_name)

    try:
        schema = json.loads(_read_pack_text(schema_file))
    except json.JSONDecodeError as exc:
        raise CompliancePackError(
            f"compliance pack {pack_name!r}: {PACK_SCHEMA_FILENAME} is not "
            f"valid JSON: {exc}"
        ) from exc

    # The pack must satisfy its own published schema. This is the check that
    # proof-spec v1.0 structurally cannot perform for an extension (§ 8.1).
    try:
        jsonschema.validate(instance=manifest, schema=schema)
    except jsonschema.ValidationError as exc:
        location = "/".join(str(p) for p in exc.absolute_path) or "<root>"
        raise CompliancePackError(
            f"compliance pack {pack_name!r}: {PACK_MANIFEST_FILENAME} does not "
            f"validate against its own {PACK_SCHEMA_FILENAME} at {location}: "
            f"{exc.message}"
        ) from exc
    except jsonschema.SchemaError as exc:
        raise CompliancePackError(
            f"compliance pack {pack_name!r}: {PACK_SCHEMA_FILENAME} is not a "
            f"valid JSON Schema: {exc.message}"
        ) from exc

    namespace = _validate_namespace(manifest["namespace"], pack_name)

    raw_limits = manifest.get("claim_limits") or []
    if not isinstance(raw_limits, list):
        raise CompliancePackError(
            f"compliance pack {pack_name!r}: claim_limits must be a list, got "
            f"{type(raw_limits).__name__}."
        )
    invalid = [
        v for v in raw_limits if not isinstance(v, str) or not is_valid_claim_limit(v)
    ]
    if invalid:
        raise CompliancePackError(
            f"compliance pack {pack_name!r}: invalid claim_limits "
            f"{invalid!r} — each must be a canonical claim limit or match "
            f"^x-[a-z0-9_-]{{1,64}}$."
        )

    raw_fields = manifest.get("fields") or {}
    if not isinstance(raw_fields, dict):
        raise CompliancePackError(
            f"compliance pack {pack_name!r}: fields must be a mapping, got "
            f"{type(raw_fields).__name__}."
        )

    return CompliancePack(
        namespace=namespace,
        pack_version=str(manifest["pack_version"]),
        framework=str(manifest["framework"]),
        claim_limits=tuple(raw_limits),
        fields=dict(raw_fields),
        manifest=manifest,
        schema=schema,
    )


def discover_packs() -> tuple[str, ...]:
    """Return the names of every packaged pack directory, sorted.

    A directory counts as a pack if it contains a ``pack.yaml``. Sorted so
    the order is deterministic across platforms and filesystems.
    """
    root = _packs_root()
    names: list[str] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        if (entry / PACK_MANIFEST_FILENAME).is_file():
            names.append(entry.name)
    return tuple(sorted(names))


def load_all_packs() -> dict[str, CompliancePack]:
    """Load every discoverable pack, keyed by namespace.

    Raises:
        CompliancePackError: If any pack fails to load (fail-closed — one
            bad pack is an error, never a silent omission), or if two packs
            declare the same namespace.
    """
    packs: dict[str, CompliancePack] = {}
    for name in discover_packs():
        pack = load_pack(name)
        if pack.namespace in packs:
            raise CompliancePackError(
                f"duplicate compliance-pack namespace {pack.namespace!r} — "
                f"declared by more than one pack directory."
            )
        packs[pack.namespace] = pack
    return packs
