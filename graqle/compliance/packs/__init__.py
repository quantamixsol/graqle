"""Compliance packs — regulatory frameworks expressed as data (CR-010.R3).

Each pack is a directory of two data files (``pack.yaml`` + ``schema.json``)
describing one framework's extension namespace, its contributed claim
limits, and its field vocabulary. Adding a framework requires no Python and
no engine change.

Shipped packs:
    * ``x_sox`` — Sarbanes-Oxley / COSO internal controls.

See :mod:`graqle.compliance.packs._loader` for the loading contract and the
rationale behind directory-scan discovery (rather than entry points, which
are CR-010.R10).
"""

from __future__ import annotations

from graqle.compliance.packs._loader import (
    PACK_MANIFEST_FILENAME,
    PACK_SCHEMA_FILENAME,
    CompliancePack,
    CompliancePackError,
    discover_packs,
    load_all_packs,
    load_pack,
)

__all__ = [
    "PACK_MANIFEST_FILENAME",
    "PACK_SCHEMA_FILENAME",
    "CompliancePack",
    "CompliancePackError",
    "discover_packs",
    "load_all_packs",
    "load_pack",
]
