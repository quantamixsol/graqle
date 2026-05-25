"""Per-domain capture mapping + PII discipline for Mode B (ADR-221 §4.3 / R1).

A production decision payload carries PII; the governed audit trail must not. A
``*_mapping.yaml`` per domain declares, field by field, how each part of a
request/response payload is routed into a :meth:`GovernedRuntime.attest` call:

.. code-block:: yaml

    domain: loan
    identity:   {applicant_id: pseudonymize}   # -> stable salted hash, never raw
    hash_only:  [features, documents]           # -> folded into content_hash only
    governance: [decision, reason_code, confidence, human_review]  # -> leaf metadata
    drop:       [raw_pii, free_text_notes]      # -> never enters the record

**Fail-closed is the whole point.** Only fields *explicitly* named in ``identity``,
``hash_only`` or ``governance`` are ever routed into the record; ``drop`` is an
explicit-intent list for self-documentation, but the safety property does not depend
on it — **any field not named in identity/hash_only/governance is dropped**, even if
it is also absent from ``drop``. A middleware that sees a whole JSON payload therefore
cannot leak a newly-added PII field by omission: the default for an unmapped field is
*drop*, never *store*.

This module only decides routing; the cryptographic leaf/wrapper split is enforced
downstream by the shipped :func:`leaf_hash_for_record` (governance fields are the only
ones that enter the Merkle leaf). This module adds no cryptography — it composes
:meth:`GovernedRuntime.pseudonymize_ref` for identity hashing.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from graqle.governance.runtime.runtime import GovernedRuntime

# Field names are operator-supplied (the mapping config), not attacker-supplied — but
# we validate them anyway (defence in depth): a routed field name is interpolated into
# the derived digest keys (``f"{name}_ref"`` / ``f"{name}_hash"``), so constraining it
# to a conventional identifier shape keeps those keys predictable and rejects
# whitespace/control-character oddities at config-load time rather than at capture time.
_FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")

__all__ = [
    "DomainMapping",
    "MappingError",
    "load_mapping",
]

# The only top-level keys a mapping file may contain. Anything else is a typo or an
# attempt to smuggle behaviour past the allowlist — reject loudly (fail-closed).
_ALLOWED_KEYS = frozenset({"domain", "identity", "hash_only", "governance", "drop"})

# The only identity transform supported in R1. Declared as a set so an unknown
# transform name (e.g. a typo "pseudonimize") fails closed instead of silently
# storing raw identifiers.
_IDENTITY_TRANSFORMS = frozenset({"pseudonymize"})
# (R1 mapping transforms; extend here when a new identity transform is added.)


class MappingError(ValueError):
    """A mapping file is malformed or violates the fail-closed contract."""


@dataclass(frozen=True)
class DomainMapping:
    """A validated per-domain capture mapping (ADR-221 §4.3).

    Attributes
    ----------
    domain:
        Decision domain (``"loan"`` | ``"recruitment"`` | ``"health"`` | …). Becomes
        the ``domain`` passed to :meth:`GovernedRuntime.attest`.
    identity:
        ``{field_name: transform}`` — each named field is run through ``transform``
        (only ``"pseudonymize"`` in R1) and the pseudonym placed in the PII-safe
        ``inputs`` digest under ``"<field>_ref"``. Raw identity values never stored.
    hash_only:
        Field names whose raw values are folded into ``content_hash`` (via the
        ``inputs`` digest, hashed) but never stored on the leaf or wrapper.
    governance:
        Field names promoted into the leaf-visible ``governance_metadata`` map. These
        MUST be PII-free by the deployer's construction — this is the one map that
        enters the Merkle leaf.
    drop:
        Field names explicitly documented as never-stored. Advisory only: the
        safety property is that *unmapped fields are dropped by default*.
    """

    domain: str
    identity: dict[str, str] = field(default_factory=dict)
    hash_only: tuple[str, ...] = ()
    governance: tuple[str, ...] = ()
    drop: tuple[str, ...] = ()

    def apply(
        self,
        payload: dict[str, Any],
        runtime: GovernedRuntime,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Route a payload into attest() arguments, fail-closed.

        Returns ``(inputs_digest, output, governance_metadata)``:

        * ``inputs_digest`` — PII-safe: pseudonymised identity refs (``"<field>_ref"``)
          plus per-field SHA-256 digests of ``hash_only`` fields (``"<field>_hash"``).
          No raw values. Folded into ``content_hash`` by attest().
        * ``output`` — the governance fields, so the decision + reason are carried as
          the governed decision payload (also folded into ``content_hash``).
        * ``governance_metadata`` — the governance fields again, surfaced for promotion
          into the leaf via attest()'s ``reason_code`` / ``confidence`` / ``human_review``
          convenience args (the caller forwards recognised keys).

        Any field present in ``payload`` but not named in identity/hash_only/governance
        is dropped — including fields the deployer forgot to add to ``drop``.
        """
        if not isinstance(payload, dict):
            raise MappingError("payload to map must be a dict")

        inputs_digest: dict[str, Any] = {}
        for fieldname, transform in self.identity.items():
            if fieldname not in payload:
                continue
            raw = payload[fieldname]
            if transform == "pseudonymize":
                inputs_digest[f"{fieldname}_ref"] = runtime.pseudonymize_ref(str(raw))
            else:  # pragma: no cover - guarded at load time, defence in depth
                raise MappingError(f"unknown identity transform: {transform!r}")

        for fieldname in self.hash_only:
            if fieldname not in payload:
                continue
            raw_bytes = _stable_bytes(payload[fieldname])
            inputs_digest[f"{fieldname}_hash"] = (
                "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
            )

        governance_metadata: dict[str, Any] = {}
        for fieldname in self.governance:
            if fieldname in payload:
                governance_metadata[fieldname] = payload[fieldname]

        # output mirrors the governance view: the decision + reason are the governed
        # payload. Kept separate from governance_metadata so a future R-phase can
        # carry richer (still PII-free) output without widening the leaf map.
        output = dict(governance_metadata)
        return inputs_digest, output, governance_metadata


def _stable_bytes(value: Any) -> bytes:
    """Deterministic bytes for hashing a hash_only field value.

    Strings hash by their UTF-8 bytes; everything else by its canonical JSON form so
    that ``{"a": 1, "b": 2}`` and ``{"b": 2, "a": 1}`` hash identically.
    """
    if isinstance(value, str):
        return value.encode("utf-8")
    import json

    return json.dumps(value, sort_keys=True, default=str).encode("utf-8")


def _as_name_tuple(raw: Any, section: str) -> tuple[str, ...]:
    """Validate a list-of-field-names section; return it as a tuple of str."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise MappingError(f"'{section}' must be a list of field names")
    names: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item:
            raise MappingError(f"'{section}' entries must be non-empty strings")
        if not _FIELD_NAME_RE.match(item):
            raise MappingError(
                f"'{section}' field name {item!r} is not a valid identifier "
                f"(allowed: letters, digits, '_', '.', '-', not starting with digit)"
            )
        names.append(item)
    return tuple(names)


def load_mapping(path: str | Path) -> DomainMapping:
    """Load and validate a ``*_mapping.yaml`` into a :class:`DomainMapping`.

    Validation (all fail-closed):

    * file must exist and parse as a YAML mapping (dict);
    * ``domain`` is required and must be a non-empty string;
    * no top-level key outside ``_ALLOWED_KEYS`` (rejects typos / smuggled config);
    * ``identity`` is a ``{str: transform}`` dict, each transform in
      ``_IDENTITY_TRANSFORMS``;
    * ``hash_only`` / ``governance`` / ``drop`` are lists of non-empty strings;
    * no field name appears in more than one of identity/hash_only/governance/drop
      (an ambiguous routing is a configuration error, not a silent precedence pick).

    Raises :class:`MappingError` on any violation.
    """
    import yaml  # local import: yaml is a core dep but keep import cost off hot paths

    p = Path(path)
    if not p.is_file():
        raise MappingError(f"mapping file not found: {p}")

    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise MappingError(f"mapping file is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise MappingError("mapping file must be a YAML mapping (key: value)")

    unknown = set(raw) - _ALLOWED_KEYS
    if unknown:
        raise MappingError(
            f"unknown mapping key(s): {sorted(unknown)}; allowed: {sorted(_ALLOWED_KEYS)}"
        )

    domain = raw.get("domain")
    if not isinstance(domain, str) or not domain:
        raise MappingError("'domain' is required and must be a non-empty string")

    identity_raw = raw.get("identity") or {}
    if not isinstance(identity_raw, dict):
        raise MappingError("'identity' must be a mapping of field -> transform")
    identity: dict[str, str] = {}
    for fieldname, transform in identity_raw.items():
        if not isinstance(fieldname, str) or not fieldname:
            raise MappingError("'identity' keys must be non-empty field names")
        if not _FIELD_NAME_RE.match(fieldname):
            raise MappingError(
                f"'identity' field name {fieldname!r} is not a valid identifier"
            )
        if transform not in _IDENTITY_TRANSFORMS:
            raise MappingError(
                f"'identity.{fieldname}' transform {transform!r} unknown; "
                f"allowed: {sorted(_IDENTITY_TRANSFORMS)}"
            )
        identity[fieldname] = transform

    hash_only = _as_name_tuple(raw.get("hash_only"), "hash_only")
    governance = _as_name_tuple(raw.get("governance"), "governance")
    drop = _as_name_tuple(raw.get("drop"), "drop")

    # No field may be routed two ways — that would make the audit record's shape
    # depend on undocumented precedence. Reject it.
    seen: dict[str, str] = {}
    for section, names in (
        ("identity", tuple(identity)),
        ("hash_only", hash_only),
        ("governance", governance),
        ("drop", drop),
    ):
        for name in names:
            if name in seen:
                raise MappingError(
                    f"field {name!r} appears in both '{seen[name]}' and '{section}'; "
                    f"a field may be routed only one way"
                )
            seen[name] = section

    return DomainMapping(
        domain=domain,
        identity=identity,
        hash_only=hash_only,
        governance=governance,
        drop=drop,
    )
