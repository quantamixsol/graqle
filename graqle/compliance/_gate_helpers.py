"""Shared validation helpers for compliance review gates (CR-010.R3).

Both review gates — :mod:`graqle.compliance.article_14_gate` (EU AI Act
Article 14) and :mod:`graqle.compliance.management_review_gate` (SOX/COSO) —
need the same three primitives: coerce an arming flag, validate a
confidence, validate a threshold.

**Why this module exists as a re-export rather than the definition site.**
The obvious refactor is to move the three helpers out of ``article_14_gate``
and have both gates import them from here. That was rejected:
``article_14_gate`` is a live EU AI Act enforcement path with four
production consumers (``mcp_dev_server.py`` at three sites,
``switch_status.py``), and moving code out of it — even code that is
module-private — means editing a file whose contract those consumers pin,
for the benefit of a brand-new module. The risk sits entirely on the
regulated path and the benefit sits entirely on the new one.

So the canonical definitions stay in ``article_14_gate`` and this module
re-exports them under stable, public (non-underscore) names. New callers
import from here and are insulated from the private spelling. If the
helpers are ever genuinely relocated, this module is the single place that
changes.

The coupling is pinned by ``test_gate_helper_contract`` so that a rename in
``article_14_gate`` fails a test rather than surfacing as an ``ImportError``
at process start — which is the failure mode that made this worth
addressing at all.
"""

from __future__ import annotations

from graqle.compliance.article_14_gate import (
    _coerce_bool as coerce_arming_flag,
)
from graqle.compliance.article_14_gate import (
    _validate_confidence as validate_confidence,
)
from graqle.compliance.article_14_gate import (
    _validate_threshold as validate_threshold,
)

__all__ = [
    "coerce_arming_flag",
    "validate_confidence",
    "validate_threshold",
]
