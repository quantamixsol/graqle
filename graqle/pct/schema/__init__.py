"""Vendored OPSF PCT schema + GraQle's own frozen proof spec.

This package holds artefacts from two distinct provenances. Keeping them
straight matters: one is upstream content that must stay byte-identical, the
other is GraQle-authored and versioned on its own cadence.

===========================  ==========================================
``pct_v0_1.json``,           VENDORED from ``opsf-org/pct-spec`` at
``opsf_examples/``           :data:`VENDORED_OPSF_SHA`. Byte-identical —
                             never edit in place; re-vendor instead.
``proof-spec/v{N.M}/``,      GRAQLE-AUTHORED (CR-010.R1). The frozen proof
``conformance/``             spec + its conformance corpus. Versioned by
                             directory, independent of both the OPSF SHA
                             and the GraQle SDK version. A re-vendor must
                             NOT touch these.
===========================  ==========================================

The artefacts in the vendored set are byte-identical copies of files in
``opsf-org/pct-spec`` pinned to the commit SHA below. The OPSF default
branch ``develop`` is floating; the SHA pin gives reproducible builds
per sentinel pass 3 MINOR-S3 (CR-010 PR-010b-1).

To re-vendor (when OPSF publishes spec updates):

    1. Fetch the new SHA: ``gh api repos/opsf-org/pct-spec/commits/develop``
    2. Re-pull the four files via ``gh api repos/.../contents/<path>?ref=<SHA>``
    3. Update :data:`VENDORED_OPSF_SHA` below to the new value
    4. Update the docstring in :mod:`graqle.pct.__init__` to match
    5. Re-run ``pytest tests/test_pct/`` — the OPSF example-compat tests
       must still pass against the new schema.

Per CR-009 + ADR-205 governance discipline, any re-vendor lands in
its own PR with the SHA change visible in the diff for sentinel review.
"""

from __future__ import annotations

import json
from typing import Any

#: Version of GraQle's own frozen proof spec (CR-010.R1). Deliberately
#: DECOUPLED from ``graqle.__version__``: an SDK release never implies a spec
#: change, and a spec change never forces an SDK major bump. Third parties pin
#: to this, not to the SDK version.
SPEC_VERSION: str = "1.0"

#: Schema names published at :data:`SPEC_VERSION`.
PROOF_SPEC_SCHEMAS: tuple[str, ...] = ("bundle", "keyring", "verify-result")


def proof_schema_text(name: str, version: str | None = None) -> str:
    """Return the raw JSON text of a published proof-spec schema.

    Read via ``importlib.resources`` rather than ``__file__`` so the schemas
    resolve correctly when the package is imported from a zipped wheel.

    Parameters
    ----------
    name:
        One of :data:`PROOF_SPEC_SCHEMAS` (e.g. ``"bundle"``).
    version:
        Spec version directory, defaulting to :data:`SPEC_VERSION`. Pass an
        explicit value to read a superseded spec.

    Raises
    ------
    FileNotFoundError
        If no such schema/version is published. The message names what was
        looked for, so a typo is obvious rather than silent.
    """
    from importlib.resources import files

    version = version or SPEC_VERSION
    relative = f"proof-spec/v{version}/{name}.schema.json"
    resource = files(__name__).joinpath(relative)
    if not resource.is_file():
        raise FileNotFoundError(
            f"no proof-spec schema {name!r} at spec version {version!r} "
            f"(looked for {relative}); published schemas at "
            f"v{SPEC_VERSION}: {', '.join(PROOF_SPEC_SCHEMAS)}"
        )
    return resource.read_text(encoding="utf-8")


def load_proof_schema(name: str, version: str | None = None) -> dict[str, Any]:
    """Return a published proof-spec schema parsed as a dict.

    Thin wrapper over :func:`proof_schema_text`; see it for parameters and
    the raised :class:`FileNotFoundError`.
    """
    return json.loads(proof_schema_text(name, version))


#: Pinned commit SHA in ``opsf-org/pct-spec`` from which the vendored
#: artefacts in this directory were fetched. Sentinel pass 3 MINOR-S3
#: fix (CR-010 PR-010b-1, 2026-05-23). Verifiable via
#: ``gh api repos/opsf-org/pct-spec/commits/<SHA>``.
VENDORED_OPSF_SHA: str = "f04bbc4862af836a2696e635275ead4bc835d9d1"

#: ISO date of the pinned commit (informational; SHA is authoritative).
VENDORED_OPSF_COMMIT_DATE: str = "2026-04-27"

#: Short commit message of the pinned commit (informational).
VENDORED_OPSF_COMMIT_MESSAGE: str = "remove banner image from README (#60)"

__all__ = [
    "SPEC_VERSION",
    "PROOF_SPEC_SCHEMAS",
    "proof_schema_text",
    "load_proof_schema",
    "VENDORED_OPSF_SHA",
    "VENDORED_OPSF_COMMIT_DATE",
    "VENDORED_OPSF_COMMIT_MESSAGE",
]
