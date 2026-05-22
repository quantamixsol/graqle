"""Exceptions for the Layer 5 tamper-evidence module (R25-EU01)."""

from __future__ import annotations


class TamperEvidenceError(Exception):
    """Base class for all Layer 5 tamper-evidence errors."""


class InvalidFloatValueError(TamperEvidenceError, ValueError):
    """A non-finite or non-canonical float reached the canonicalization boundary.

    Raised for NaN, +/-Infinity, and -0.0 (C-P0-2). These values have no stable
    canonical JSON representation across runtimes, so they are rejected rather
    than coerced — coercion would silently break cross-implementation leaf-hash
    determinism.

    Subclasses ``ValueError`` so callers using ``except ValueError`` (and
    Pydantic validators) catch it naturally.
    """

    def __init__(self, value: float, field_path: str) -> None:
        self.value = value
        self.field_path = field_path
        super().__init__(
            f"Non-canonical float {value!r} at field '{field_path}': NaN, "
            f"Infinity, and -0.0 are not permitted in tamper-evidence records "
            f"(no stable canonical JSON form). Remove or replace the value."
        )


class NonCanonicalTypeError(TamperEvidenceError, TypeError):
    """A value of a non-JSON-native type reached the canonicalization boundary.

    Only dict/list/str/int/float/bool/None are permitted. Decimal, numpy
    scalars, datetime, sets, and objects with custom ``__float__`` are rejected
    (C-P0-2 hardening) because they have no stable canonical JSON representation
    and would make the leaf hash non-deterministic if coerced.

    Subclasses ``TypeError`` so ``except (ValueError, TypeError)`` catches the
    full canonicalization-rejection family.
    """

    def __init__(self, type_name: str, field_path: str) -> None:
        self.type_name = type_name
        self.field_path = field_path
        super().__init__(
            f"Non-canonical type {type_name!r} at field '{field_path}': only "
            f"JSON-native types (object, array, string, number, bool, null) are "
            f"permitted in tamper-evidence records. Convert the value first."
        )


class MissingLeafFieldError(TamperEvidenceError, ValueError):
    """A required leaf-hash-input field is absent from a record.

    Currently raised when ``proof_format_version`` is missing from a record
    passed to ``canon_leaf``: the version must be inside the leaf hash so an old
    proof cannot be replayed under a new version banner (R25-EU08 open question
    #4). A versionless leaf is rejected rather than silently produced.
    """

    def __init__(self, field_name: str) -> None:
        self.field_name = field_name
        super().__init__(
            f"Required leaf-hash-input field '{field_name}' is missing. It is "
            f"part of the frozen leaf-input subset; its absence would weaken the "
            f"replay-attack defense (a leaf without it is replayable under any "
            f"version banner)."
        )
