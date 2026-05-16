"""Vendored OPSF PCT schema + example scenarios.

The artefacts in this directory are byte-identical copies of files in
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
    "VENDORED_OPSF_SHA",
    "VENDORED_OPSF_COMMIT_DATE",
    "VENDORED_OPSF_COMMIT_MESSAGE",
]
