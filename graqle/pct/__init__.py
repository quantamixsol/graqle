"""GraQle PCT (Proof Claims Token) integration package.

Implements the OPSF PCT v0.1 spec — a data-obligation permit token that
travels with data through pipelines, verified BEFORE any data-handling
action is permitted. Authored per ADR-205 (CR-010 PR-010b-1) +
ADR-RT-001 (Research-Team binding decision 2026-05-23: Use B framing).

Primary surfaces:
    - :class:`graqle.pct.issuer.PctIssueRequest` + :func:`graqle.pct.issuer.issue_pct`
        Mint a PCT JWS (RS256) for a downstream data flow.
    - :class:`graqle.pct.validator.PctValidationResult` + :func:`graqle.pct.validator.validate_pct`
        Validate an incoming PCT from an upstream data source. Returns
        ALLOW or BLOCK with structured ``failure_reasons``.
    - :mod:`graqle.pct.extensions.x_ai_eu`
        Quantamix-authored EU AI Act PCT extension namespace (10 fields
        covering Article 4 / 6 / 9 / 12 / 13 / 14 / 15 / 25 / 50). Mirrors
        OPSF naming convention (``x-{framework}:{field}``).

Vendored OPSF artefacts:
    - :mod:`graqle.pct.schema` — ``pct_v0_1.json`` (8.7KB) + 4 example
      scenarios from ``opsf-org/pct-spec`` pinned to commit
      ``f04bbc4862af836a2696e635275ead4bc835d9d1`` (2026-04-27, "remove
      banner image from README (#60)"). The OPSF default branch
      ``develop`` is floating; this SHA pin gives reproducible builds
      per sentinel pass 3 MINOR-S3. Used as cross-test fixtures per
      ADR-205 §8 AC-4.

This package has NO public-comms exposure until ``x-ai-eu`` is proposed
to OPSF post-Borner-call per Option 2A (ADR-RT-001 §4 Q2). Until then,
the namespace ships vendored in the GraQle private repo only.

References:
    - ADR-205: CR-010 PR-010b-1 Implementation: PCT Issuer + Validator + x-ai-eu Extension
    - ADR-RT-001: PCT Use B Pivot + x-ai-eu Extension Authorship (Research-Team binding decision 2026-05-23)
    - OPSF PCT spec: https://github.com/opsf-org/pct-spec (CC BY 4.0, default branch ``develop``)
"""

from __future__ import annotations

from graqle.pct.issuer import PctIssueRequest, issue_pct
from graqle.pct.validator import PctValidationResult, validate_pct

__all__ = [
    "PctIssueRequest",
    "PctValidationResult",
    "issue_pct",
    "validate_pct",
]
