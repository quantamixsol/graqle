"""PCT extension namespace ``x-ai-eu`` — EU AI Act.

NEW extension namespace, authored by Quantamix Solutions per ADR-205
§2.2 + ADR-RT-001 §4.Q1. Mirrors OPSF naming convention
(``x-{framework}:{field}`` — e.g. ``x-ai-uk``, ``x-ai-us-fed``,
``x-ai-int`` already exist in opsf-org/pct-spec@develop/extensions/;
``x-ai-eu`` does not — this module authors it).

The namespace surfaces the operator's EU AI Act compliance posture
inside a PCT token, so a downstream enforcement point can decide
whether to ALLOW or BLOCK a data-handling action based on the
operator's Article-level compliance attestations.

This module exports:
    - :data:`X_AI_EU_NAMESPACE` — the canonical namespace prefix
      ``"x-ai-eu"`` (string constant).
    - :class:`XAiEuExtension` — Pydantic v2 model + JSON-Schema-derived
      validation for the 10-field extension payload.
    - :func:`to_pct_extension_dict` — converts the dataclass to the
      ``{"x-ai-eu:<field>": <value>}`` shape that lives inside the
      PCT payload's top-level ``extensions`` field.

Public-comms status: NOT YET proposed to OPSF (per ADR-RT-001 Option
2A: propose 24-48h post-Borner-call). Until proposed + accepted,
this is a Quantamix-authored namespace shipped vendored in GraQle. The
field schema below is the **first public draft**; minor field-naming
revisions are possible during the OPSF acceptance review.

Field rationale + EU AI Act regulation anchors are documented in
:doc:`docs/compliance/eu-ai-act/article-25-value-chain.md` and the
companion :file:`extensions/README.md` in this directory.

References:
    - ADR-205 §2.2 — 10-field table (canonical scope)
    - ADR-RT-001 §4 — Q1 + Q2 binding decisions
    - OPSF naming convention: opsf-org/pct-spec@develop/extensions/x-ai-int.md
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Namespace constant
# ---------------------------------------------------------------------------

#: Canonical OPSF-style namespace prefix for the EU AI Act extension.
X_AI_EU_NAMESPACE: str = "x-ai-eu"


# ---------------------------------------------------------------------------
# Enum literals
# ---------------------------------------------------------------------------

#: Article 6 risk-classification values (per Regulation (EU) 2024/1689).
Article6Classification = Literal[
    "non_high_risk",
    "annex_iii_high_risk",
    "annex_i_high_risk",
    "gpai_model",
    "gpai_systemic_risk",
]

#: Article 14 human-oversight modes.
Article14OversightMode = Literal[
    "disabled",
    "monitor",
    "gated",
]

#: Article 50 disclosure modes (maps to GraQle env-var pair
#: ``GRAQLE_EU_AI_ACT_MODE`` + ``GRAQLE_AI_DISCLOSURE``).
Article50DisclosureMode = Literal[
    "auto_banner",
    "machine_only",
    "suppress_with_logged_reason",
]

#: The 8 Annex III high-risk categories (Regulation (EU) 2024/1689).
AnnexIiiCategory = Literal[
    "biometric",
    "critical_infrastructure",
    "education_and_vocational",
    "employment",
    "access_to_essential_services",
    "law_enforcement",
    "migration_asylum_border_control",
    "administration_of_justice_and_democratic_processes",
]


# ---------------------------------------------------------------------------
# Extension dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class XAiEuExtension:
    """The 10-field EU AI Act PCT extension payload.

    Per ADR-205 §2.2. All fields are OPTIONAL except where noted as
    CONDITIONAL — the dataclass enforces the conditional dependency at
    construction time via :meth:`__post_init__`.

    Attributes:
        article_6_classification: One of
            :data:`Article6Classification` literals. Maps to
            Article 6 risk-classification + Annex I / Annex III.
        article_9_risk_management_ref: CONDITIONAL — required when
            ``article_6_classification`` is ``annex_iii_high_risk`` or
            ``annex_i_high_risk``. URI to the operator's Article 9
            risk-management file.
        article_12_audit_log_pointer: URI to the operator's Article 12
            audit log (e.g. evidence file URL from
            ``graq compliance export``).
        article_13_transparency_doc_ref: URI to operator's Article 13
            deployer-transparency documentation.
        article_14_human_oversight_mode: One of
            :data:`Article14OversightMode` literals.
        article_50_disclosure_mode: One of
            :data:`Article50DisclosureMode` literals.
        articles_covered: Subset of ``["4", "12", "13", "14", "15",
            "25", "50"]``. Mirrors GraQle's ``compliance.articles_covered``
            envelope field.
        gpai_provider_flag: ``False`` for GraQle deployments (GraQle does
            not place a GPAI on the EU market). Future-proof for
            customers who DO place GPAI.
        annex_iii_category: CONDITIONAL — required when
            ``article_6_classification == "annex_iii_high_risk"``. One of
            :data:`AnnexIiiCategory` literals.
        cr_lookup_id: Optional pointer to a structured EU AI Act
            compliance dossier ID maintained by the operator.
    """

    article_6_classification: Article6Classification | None = None
    article_9_risk_management_ref: str | None = None
    article_12_audit_log_pointer: str | None = None
    article_13_transparency_doc_ref: str | None = None
    article_14_human_oversight_mode: Article14OversightMode | None = None
    article_50_disclosure_mode: Article50DisclosureMode | None = None
    articles_covered: list[str] = field(default_factory=list)
    gpai_provider_flag: bool = False
    annex_iii_category: AnnexIiiCategory | None = None
    cr_lookup_id: str | None = None

    def __post_init__(self) -> None:
        """Enforce conditional-field dependencies.

        Per sentinel pass 4 MINOR-C4: empty strings and whitespace-only
        strings are treated as missing for the URI/string fields,
        because an empty ``article_9_risk_management_ref`` would silently
        pass a naive truthy check but is operationally indistinguishable
        from "missing" for a regulator.

        Raises:
            ValueError: If ``article_9_risk_management_ref`` is missing,
                empty, or whitespace-only when ``article_6_classification``
                is high-risk; or if ``annex_iii_category`` is missing
                when classification is ``annex_iii_high_risk``.
        """
        cls_value = self.article_6_classification
        # MINOR-C4 fix: explicit None + empty + whitespace check on
        # article_9_risk_management_ref. .strip() handles "  " and "\n".
        art9 = self.article_9_risk_management_ref
        art9_missing = art9 is None or (isinstance(art9, str) and not art9.strip())
        if (
            cls_value in ("annex_iii_high_risk", "annex_i_high_risk")
            and art9_missing
        ):
            raise ValueError(
                f"article_9_risk_management_ref is required (non-empty, "
                f"non-whitespace) when article_6_classification is "
                f"{cls_value!r} (high-risk)."
            )
        if cls_value == "annex_iii_high_risk" and not self.annex_iii_category:
            raise ValueError(
                "annex_iii_category is required when "
                "article_6_classification == 'annex_iii_high_risk'."
            )

    def to_pct_extension_dict(self) -> dict[str, Any]:
        """Convert to the ``{"x-ai-eu:<field>": <value>}`` shape.

        Returns a dict ready to be placed inside the PCT payload's
        ``extensions`` field. Only fields with non-None / non-empty
        values are emitted so the resulting payload is minimal.
        """
        out: dict[str, Any] = {}
        for k, v in asdict(self).items():
            if v is None:
                continue
            if isinstance(v, list) and not v:
                # Skip empty lists to keep the extension payload tight.
                continue
            out[f"{X_AI_EU_NAMESPACE}:{k}"] = v
        return out

    @classmethod
    def from_pct_extension_dict(
        cls, ext: dict[str, Any]
    ) -> "XAiEuExtension":
        """Parse a ``{"x-ai-eu:<field>": ...}`` dict back to a dataclass.

        Unknown keys (any not matching ``x-ai-eu:<known-field>``) are
        ignored — forward-compatibility with future namespace revisions.
        """
        prefix = f"{X_AI_EU_NAMESPACE}:"
        kwargs: dict[str, Any] = {}
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        for key, value in ext.items():
            if not key.startswith(prefix):
                continue
            field_name = key[len(prefix) :]
            if field_name in known_fields:
                kwargs[field_name] = value
        return cls(**kwargs)
