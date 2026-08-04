"""PCT extension namespace ``x-sox`` — SOX / COSO internal controls.

NEW extension namespace, authored by Quantamix Solutions per CR-010.R3.
Mirrors the OPSF naming convention ``x-{framework}:{field}`` and the
existing sibling :mod:`graqle.pct.extensions.x_ai_eu`.

Where ``x-ai-eu`` surfaces an operator's *EU AI Act* posture, ``x-sox``
surfaces an operator's *financial-controls* posture: which named internal
control an AI-assisted decision was performed under, which
financial-statement assertion it supports, the reporting period it falls
in, and whether the required management review happened.

The motivating use case is an AI-assisted financial close. A decision
emitted during close must be bindable to a **named control** and a
**reporting period**, and an auditor must be able to check that binding
**offline** — without GraQle, and without the operator's HR directory.

This module exports:
    - :data:`X_SOX_NAMESPACE` — the canonical namespace prefix ``"x-sox"``.
    - :class:`XSoxExtension` — frozen dataclass for the 13-field payload.
    - :func:`is_pseudonym_token` — the preparer/reviewer token predicate.
    - :data:`PSEUDONYM_OMITTED` — the explicit "not provided" sentinel.

Relationship to the signed proof (read before adding fields)
------------------------------------------------------------
Extension fields are **carried, not trusted**. The Merkle leaf is computed
over a frozen 5-field allowlist
(:data:`graqle.governance.tamper_evidence.leaf_input_schema.LEAF_HASH_FIELDS`)
and ``project_leaf_input()`` drops every other key, so **nothing in this
module can alter a leaf hash or a signed preimage**. Two consequences,
both deliberate:

1. Adding a field here is a MINOR, additive change. It cannot invalidate a
   previously-issued bundle.
2. Validating a bundle against proof-spec v1.0 does **not** validate this
   namespace (v1.0 permits unknown members — see ``proof-spec/v1.0/SPEC.md``
   § 8.1). This namespace therefore ships its own schema, in
   ``graqle/compliance/packs/x_sox/schema.json``, and must be validated
   against it *in addition* to v1.0.

Why preparer/reviewer are pseudonym tokens
------------------------------------------
SOX evidence names people. Those names would otherwise travel inside
long-lived, widely-shared audit artifacts (exported evidence files, PCT
payloads handed to external auditors) with no practical redaction path
once distributed. So this module refuses to carry them: the fields accept
a 64-char lowercase-hex HMAC-SHA256 token or the explicit sentinel
``"omit"``, and **reject raw identifiers at construction time**.

The identity-to-token mapping stays with the operator. It is never written
to a pack, a token, or an evidence artifact. GraQle never needs it: an
auditor checks that *the same* preparer token differs from *the same*
reviewer token (segregation of duties) without learning either identity.
Operators SHOULD salt per reporting period so tokens cannot be correlated
across periods.

References:
    - CR-010.R3 — Compliance packs as data (``x-sox`` first)
    - GRAQLE_SDK_ENTERPRISE_REQUIREMENTS.md:138-158 — source requirement
    - Sarbanes-Oxley Act § 302 / § 404; COSO Internal Control — Integrated
      Framework (2013); COSO ERM (2017)
    - Companion module: :mod:`graqle.pct.extensions.x_ai_eu`
    - Extension posture: ``graqle/pct/schema/proof-spec/v1.0/SPEC.md`` § 8.1
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date as _date
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Namespace constant
# ---------------------------------------------------------------------------

#: Canonical OPSF-style namespace prefix for the SOX/COSO extension.
X_SOX_NAMESPACE: str = "x-sox"


# ---------------------------------------------------------------------------
# Pseudonym discipline
# ---------------------------------------------------------------------------

#: Explicit "not provided" sentinel for the preparer/reviewer fields.
#:
#: A sentinel rather than ``None`` so that "deliberately omitted" is
#: distinguishable in an audit artifact from "field forgotten". An auditor
#: reading ``"omit"`` knows the operator made a choice.
PSEUDONYM_OMITTED: str = "omit"

#: A preparer/reviewer token is exactly a lowercase hex SHA-256/HMAC digest.
#: Uppercase is rejected so the same identity cannot produce two distinct
#: token spellings (which would silently defeat segregation-of-duties checks).
_PSEUDONYM_TOKEN_RE: re.Pattern[str] = re.compile(r"^[a-f0-9]{64}$")

#: Fields subject to the pseudonym rule.
_PSEUDONYM_FIELDS: tuple[str, ...] = ("preparer_token", "reviewer_token")


def is_pseudonym_token(value: str) -> bool:
    """Return True iff ``value`` is an acceptable pseudonym token.

    Acceptable means: the sentinel :data:`PSEUDONYM_OMITTED`, or a 64-char
    lowercase-hex digest (HMAC-SHA256 of the identity under an
    operator-held, per-period salt).

    Args:
        value: Candidate token.

    Returns:
        bool: ``True`` if acceptable, ``False`` otherwise.

    Raises:
        TypeError: If ``value`` is not a ``str``.
    """
    if not isinstance(value, str):
        raise TypeError(
            f"is_pseudonym_token expects str, got {type(value).__name__}"
        )
    if value == PSEUDONYM_OMITTED:
        return True
    return bool(_PSEUDONYM_TOKEN_RE.match(value))


# ---------------------------------------------------------------------------
# Enum literals — closed vocabularies
# ---------------------------------------------------------------------------

#: COSO framework revision the control is expressed under.
SoxControlFramework = Literal[
    "coso_2013",
    "coso_erm_2017",
    "custom",
]

#: Financial-statement assertions (the classic audit assertion set).
SoxAssertion = Literal[
    "existence",
    "completeness",
    "accuracy",
    "cutoff",
    "valuation",
    "rights_and_obligations",
    "presentation_and_disclosure",
]

#: Management-review-control status. This is the SOX-vocabulary counterpart
#: of the EU AI Act Article 14 human-oversight mode: same mechanics
#: (a human must look before the outcome is relied upon), different words.
SoxManagementReviewStatus = Literal[
    "not_required",
    "pending",
    "completed",
    "waived_with_reason",
]

#: SOX 404 operating-effectiveness conclusion, in escalating severity.
SoxOperatingEffectiveness = Literal[
    "effective",
    "deficiency",
    "significant_deficiency",
    "material_weakness",
]

#: Review statuses that REQUIRE a corroborating evidence pointer. A claim
#: that review completed (or was waived) is unfalsifiable without one, which
#: is precisely the kind of self-attestation an auditor must reject.
_REVIEW_STATUSES_REQUIRING_REF: frozenset[str] = frozenset(
    {"completed", "waived_with_reason"}
)

#: ISO-8601 calendar date, ``YYYY-MM-DD``. Deliberately date-only: a
#: reporting period is a calendar concept, and admitting timestamps would
#: invite timezone ambiguity into a period boundary.
_ISO_DATE_RE: re.Pattern[str] = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Extension dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class XSoxExtension:
    """The SOX/COSO PCT extension payload.

    All validation happens at construction time in :meth:`__post_init__`,
    so an instance that exists is an instance that is safe to emit.

    Attributes:
        control_id: REQUIRED. The operator's named internal control (e.g.
            ``"FCC-1042"``). Free-form because control catalogues are
            operator-specific, but must be non-empty and non-whitespace.
        assertion: REQUIRED. One of :data:`SoxAssertion`.
        reporting_period_start: REQUIRED. ISO-8601 ``YYYY-MM-DD``.
        reporting_period_end: REQUIRED. ISO-8601 ``YYYY-MM-DD``. Must not
            precede ``reporting_period_start``.
        management_review_status: REQUIRED. One of
            :data:`SoxManagementReviewStatus`.
        control_framework: OPTIONAL. One of :data:`SoxControlFramework`.
        fiscal_period_label: OPTIONAL. Operator's label, e.g. ``"FY2026-Q3"``.
            Carried verbatim; never parsed (fiscal calendars are not uniform).
        preparer_token: OPTIONAL pseudonym token. Defaults to
            :data:`PSEUDONYM_OMITTED`.
        reviewer_token: OPTIONAL pseudonym token. Defaults to
            :data:`PSEUDONYM_OMITTED`.
        management_review_ref: CONDITIONAL — REQUIRED when
            ``management_review_status`` is ``completed`` or
            ``waived_with_reason``. URI to the review evidence.
        control_operating_effectiveness: OPTIONAL. One of
            :data:`SoxOperatingEffectiveness`.
        icfr_scope: OPTIONAL. Whether the control is in scope for internal
            control over financial reporting.
        policy_version: OPTIONAL. Content-addressed SHA-256 of the active
            baseline-doc at issuance, mirroring
            ``x-ai-eu:policy_version``, so drift between the token and the
            baseline it was signed against is detectable.

    Raises:
        ValueError: On any violated constraint (see :meth:`__post_init__`).
        TypeError: If a field carries the wrong Python type.
    """

    control_id: str
    assertion: SoxAssertion
    reporting_period_start: str
    reporting_period_end: str
    management_review_status: SoxManagementReviewStatus
    control_framework: SoxControlFramework | None = None
    fiscal_period_label: str | None = None
    preparer_token: str = PSEUDONYM_OMITTED
    reviewer_token: str = PSEUDONYM_OMITTED
    management_review_ref: str | None = None
    control_operating_effectiveness: SoxOperatingEffectiveness | None = None
    icfr_scope: bool | None = None
    policy_version: str | None = None

    def __post_init__(self) -> None:
        """Validate every constraint that makes the payload auditable.

        Enforced, in order:

        1. ``control_id`` is a non-empty, non-whitespace string — the whole
           point of the namespace is binding to a *named* control.
        2. Both reporting-period dates are ISO-8601 ``YYYY-MM-DD``, are real
           calendar dates, and the period does not run backwards. Shape and
           calendar validity are separate checks: the regex accepts
           ``"2026-13-45"``, so the value is also parsed with
           ``date.fromisoformat()`` before comparison.
        3. Preparer/reviewer values are pseudonym tokens, never raw
           identifiers.
        4. ``management_review_ref`` is present and non-empty when the
           status asserts that review happened or was waived.

        Empty and whitespace-only strings are treated as missing throughout
        (matching :class:`~graqle.pct.extensions.x_ai_eu.XAiEuExtension`):
        a blank ``management_review_ref`` would pass a naive truthy check
        while being operationally indistinguishable from "absent" to an
        auditor.
        """
        # 1. control_id — the binding target.
        if not isinstance(self.control_id, str):
            raise TypeError(
                f"control_id must be str, got {type(self.control_id).__name__}"
            )
        if not self.control_id.strip():
            raise ValueError(
                "control_id is required and must be non-empty, non-whitespace "
                "— an x-sox payload exists to bind a decision to a NAMED control."
            )

        # 2. Reporting period — well-formed, a REAL calendar date, and not
        #    inverted. The regex alone is insufficient: it constrains shape,
        #    not calendar validity, so "2026-13-45" satisfies it. Parsing
        #    with date.fromisoformat() is what rejects an impossible date
        #    before it can be signed into an audit record.
        parsed: dict[str, _date] = {}
        for field_name in ("reporting_period_start", "reporting_period_end"):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise TypeError(
                    f"{field_name} must be str, got {type(value).__name__}"
                )
            # Shape first, so the error message names the expected format
            # rather than leaking a stdlib parser message. fromisoformat()
            # also accepts forms this field does not permit (e.g. "20260701"
            # on 3.11+, and full timestamps), so the regex is still load-bearing.
            if not _ISO_DATE_RE.match(value):
                raise ValueError(
                    f"{field_name} must be an ISO-8601 date (YYYY-MM-DD), "
                    f"got {value!r}."
                )
            try:
                parsed[field_name] = _date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(
                    f"{field_name} is not a real calendar date: {value!r} "
                    f"({exc})."
                ) from exc
        if parsed["reporting_period_end"] < parsed["reporting_period_start"]:
            raise ValueError(
                f"reporting_period_end ({self.reporting_period_end}) must not "
                f"precede reporting_period_start ({self.reporting_period_start})."
            )

        # 3. Pseudonym discipline — reject raw identifiers before they can
        #    reach any audit artifact.
        for field_name in _PSEUDONYM_FIELDS:
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise TypeError(
                    f"{field_name} must be str, got {type(value).__name__}"
                )
            if not is_pseudonym_token(value):
                raise ValueError(
                    f"{field_name} must be a 64-character lowercase-hex "
                    f"HMAC-SHA256 token or the sentinel {PSEUDONYM_OMITTED!r}; "
                    f"raw identifiers (names, emails, employee IDs) are "
                    f"prohibited because this value travels inside long-lived, "
                    f"widely-shared audit artifacts with no redaction path."
                )

        # 4. A completed/waived review must point at its evidence.
        ref = self.management_review_ref
        ref_missing = ref is None or (isinstance(ref, str) and not ref.strip())
        if self.management_review_status in _REVIEW_STATUSES_REQUIRING_REF and ref_missing:
            raise ValueError(
                f"management_review_ref is required (non-empty, non-whitespace) "
                f"when management_review_status is "
                f"{self.management_review_status!r} — a review asserted without "
                f"an evidence pointer is unverifiable."
            )

    def to_pct_extension_dict(self) -> dict[str, Any]:
        """Convert to the ``{"x-sox:<field>": <value>}`` shape.

        Returns a dict ready to be placed inside the PCT payload's
        ``extensions`` field. Fields that are ``None`` are omitted so the
        payload stays minimal.

        The pseudonym sentinel :data:`PSEUDONYM_OMITTED` **is** emitted when
        set explicitly — "the operator chose not to name a preparer" is
        itself audit-relevant, and silently dropping it would erase that
        distinction.
        """
        out: dict[str, Any] = {}
        for key, value in asdict(self).items():
            if value is None:
                continue
            if isinstance(value, list) and not value:
                continue
            out[f"{X_SOX_NAMESPACE}:{key}"] = value
        return out

    @classmethod
    def from_pct_extension_dict(cls, ext: dict[str, Any]) -> "XSoxExtension":
        """Parse a ``{"x-sox:<field>": ...}`` dict back to a dataclass.

        Keys outside this namespace, and unknown keys within it, are
        ignored — forward-compatibility with future namespace revisions,
        matching ``XAiEuExtension.from_pct_extension_dict``.

        The result is constructed through the normal ``__init__``, so a
        payload that would violate any constraint in :meth:`__post_init__`
        raises rather than yielding an invalid instance. Round-tripping is
        therefore validating, not merely mechanical.

        Raises:
            ValueError: If required fields are absent from ``ext`` or any
                constraint is violated.
        """
        prefix = f"{X_SOX_NAMESPACE}:"
        known_fields = {f for f in cls.__dataclass_fields__}
        kwargs: dict[str, Any] = {}
        for key, value in ext.items():
            if not key.startswith(prefix):
                continue
            field_name = key[len(prefix) :]
            if field_name in known_fields:
                kwargs[field_name] = value
        try:
            return cls(**kwargs)
        except TypeError as exc:
            # Missing REQUIRED fields surface as a TypeError from __init__;
            # re-raise as ValueError so callers parsing untrusted payloads
            # have one exception type to catch for "this payload is bad".
            raise ValueError(
                f"x-sox extension payload is missing required fields or has "
                f"unusable values: {exc}"
            ) from exc
