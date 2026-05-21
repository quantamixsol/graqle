"""Frozen leaf-hash-input schema for Merkle leaves (R25-EU01 / R25-EU08).

C-P1-2. The Merkle leaf hash (PR-2) is computed over the canonical bytes of a
RECORD PROJECTED ONTO THIS FROZEN FIELD ALLOWLIST — never over the full record.
This is the "leaf-hash-input schema vs wrapper schema" separation from R25-EU08:

- Adding a field to the WRAPPER (e.g. created_at_iso, rekor_signed_tree_head) is
  a MINOR, additive change — safe, because wrapper fields never enter the leaf.
- Adding/removing/reordering a field in THIS allowlist changes the leaf bytes for
  every record, breaking forward-compat (an old verifier computes a different
  leaf hash than a new producer). Such a change is therefore a MAJOR bump that
  ships with migration tooling — NEVER additive.

``proof_format_version`` is intentionally IN the leaf input (per ADR-RT-002 §3.2
Q1 / R25-EU08 open question #4 ratification): including it inside the hash defeats
replay attacks that re-label an old proof under a new version banner.

The allowlist uses an EXPLICIT tuple (not struct/dataclass serialization) so the
frozen field set is auditable in one place and cannot drift implicitly.
"""

from __future__ import annotations

from typing import Any

# FROZEN. Changing this tuple is a MAJOR proof-format bump requiring migration
# tooling (R25-EU08). Order is part of the contract — do not reorder.
LEAF_HASH_FIELDS: tuple[str, ...] = (
    "proof_format_version",
    "record_id",
    "content_hash",
    "timestamp_unix",
    "governance_metadata",
)

# The leaf-hash-input schema version. Bump (MAJOR) only when LEAF_HASH_FIELDS
# changes; ship migration tooling in the same release.
LEAF_INPUT_VERSION = "1.0.0"


def project_leaf_input(record: dict[str, Any]) -> dict[str, Any]:
    """Project ``record`` onto the frozen leaf-hash-input allowlist.

    Returns a new dict containing ONLY the LEAF_HASH_FIELDS keys that are
    present in ``record``. Wrapper fields outside the allowlist are dropped, so
    they cannot influence the Merkle leaf hash. Keys absent from ``record`` are
    simply omitted (RFC 8785 canonicalization handles key ordering downstream).
    """
    return {key: record[key] for key in LEAF_HASH_FIELDS if key in record}
