"""RFC 8785 JSON Canonicalization Scheme (JCS) wrapper.

R25-EU01 Task 1.1. Produces the deterministic canonical byte serialization that
the Merkle leaf hash (PR-2) is computed over. Built on the ``rfc8785`` library
(pure-Python, Apache-2.0, no transitive deps) for spec-conformant JCS.

Two guarantees this module enforces beyond raw JCS:

1. **Float safety (C-P0-2):** NaN, +/-Infinity, and -0.0 are rejected at the
   ingestion boundary with :class:`InvalidFloatValueError` — never coerced.
   These values have no canonical JSON representation (RFC 8785 follows
   ECMAScript ``JSON.stringify`` which cannot represent them), so allowing them
   would make the leaf hash non-deterministic across runtimes.

2. **Leaf-input projection (C-P1-2):** :func:`canon_leaf` canonicalizes only the
   frozen leaf-hash-input field allowlist (see :mod:`leaf_input_schema`), so
   additive wrapper fields can never change the bytes that enter the Merkle leaf.
   :func:`canon` canonicalizes a full record (used for the wrapper/signature
   path, not the leaf).
"""

from __future__ import annotations

import math
from typing import Any

import rfc8785

from graqle.governance.tamper_evidence.errors import (
    InvalidFloatValueError,
    MissingLeafFieldError,
    NonCanonicalTypeError,
)
from graqle.governance.tamper_evidence.leaf_input_schema import (
    project_leaf_input,
)

# JSON-native types permitted in a tamper-evidence record. Anything else
# (Decimal, numpy scalars, datetime, sets, custom __float__ objects, etc.) has
# no stable canonical JSON form and is rejected at the boundary rather than
# being coerced — coercion would make the leaf hash non-deterministic.
# NOTE: bool is a subclass of int; both are allowed (JSON true/false and number).
_JSON_NATIVE = (dict, list, str, int, float, bool, type(None))


# Defense against stack-exhaustion DoS via maliciously deep nested input at the
# tamper-evidence ingestion boundary. Records are governed traces, not arbitrary
# user JSON, so legitimate nesting is shallow; 64 is generous headroom.
_MAX_SCAN_DEPTH = 64


def _validate_canonical(obj: Any, _key_path: tuple[Any, ...] = (), depth: int = 0) -> None:
    """Validate that ``obj`` is safe to canonicalize deterministically.

    Two checks at every node:
    1. **Type allowlist:** only JSON-native types (dict/list/str/int/float/bool/
       None) are permitted. Decimal, numpy scalars, datetime, sets, and objects
       with custom ``__float__`` are rejected with :class:`NonCanonicalTypeError`
       — they have no stable canonical JSON form and must not reach the hash.
    2. **Float safety:** NaN, +/-Infinity, and -0.0 are rejected with
       :class:`InvalidFloatValueError`.

    Bounded by ``_MAX_SCAN_DEPTH`` against stack-exhaustion DoS. The path is
    tracked as a lightweight tuple and only rendered to a string lazily when an
    error is actually raised (no per-node string allocation on the happy path).
    """
    if depth > _MAX_SCAN_DEPTH:
        raise InvalidFloatValueError(
            value=float("nan"),  # sentinel; real cause is over-deep nesting
            field_path=f"{_render_path(_key_path)} (nesting exceeds {_MAX_SCAN_DEPTH})",
        )
    # Type allowlist FIRST (bool/int/float are all instances of the tuple;
    # exact-type check rejects subclasses like numpy.float64 / IntEnum that could
    # serialize non-deterministically).
    if type(obj) not in _JSON_NATIVE:
        raise NonCanonicalTypeError(
            type_name=type(obj).__name__, field_path=_render_path(_key_path)
        )
    if isinstance(obj, float):  # bool excluded: bool is not float
        if math.isnan(obj) or math.isinf(obj):
            raise InvalidFloatValueError(value=obj, field_path=_render_path(_key_path))
        if obj == 0.0 and math.copysign(1.0, obj) < 0:  # -0.0
            raise InvalidFloatValueError(value=obj, field_path=_render_path(_key_path))
    elif isinstance(obj, dict):
        for key, value in obj.items():
            _validate_canonical(value, _key_path + (key,), depth + 1)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            _validate_canonical(value, _key_path + (index,), depth + 1)


def _render_path(key_path: tuple[Any, ...]) -> str:
    """Render a key-path tuple to a dotted string. Called only on the error path."""
    if not key_path:
        return "<root>"
    parts: list[str] = []
    for key in key_path:
        if isinstance(key, int):
            parts.append(f"[{key}]")
        else:
            parts.append(f".{key}" if parts else str(key))
    return "".join(parts)


def canon(record: dict[str, Any]) -> bytes:
    """Canonicalize a full record to RFC 8785 JCS bytes.

    Rejects non-finite floats first (C-P0-2). Use for wrapper/signature
    canonicalization. For the Merkle leaf, use :func:`canon_leaf`.
    """
    _validate_canonical(record)
    return rfc8785.dumps(record)


def canon_leaf(record: dict[str, Any]) -> bytes:
    """Canonicalize ONLY the leaf-hash-input field subset (C-P1-2).

    Projects ``record`` onto the frozen LEAF_HASH_FIELDS allowlist, then
    canonicalizes. Wrapper fields outside the allowlist are excluded, so they
    can never alter the bytes the Merkle leaf hash is computed over.

    ``proof_format_version`` MUST be present: the replay-attack defense (R25-EU08
    open question #4) depends on the version being inside the leaf hash. A
    versionless leaf could be replayed under any version banner, so its absence
    is rejected here rather than silently producing an unversioned leaf.
    """
    leaf = project_leaf_input(record)
    if "proof_format_version" not in leaf:
        raise MissingLeafFieldError("proof_format_version")
    _validate_canonical(leaf)
    return rfc8785.dumps(leaf)
