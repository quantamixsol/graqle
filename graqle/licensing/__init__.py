"""Graqle License Gating System.

Provides offline license verification with tiered feature access.
Free tier includes core innovations (1-5), GCC/GSD/Ralph protocols,
and basic MCP tools. Pro/Team/Enterprise unlock advanced features.

Usage::

    from graqle.licensing import check_license, require_license, has_feature

    # Imperative check (raises LicenseError)
    check_license("semantic_shacl_gate")

    # Boolean check
    if has_feature("tamr_connector"):
        ...

    # Decorator
    @require_license("ontology_generator")
    def generate_ontology(...):
        ...
"""

from graqle.licensing.manager import (
    License,
    LicenseError,
    LicenseManager,
    LicenseTier,
    TIER_FEATURES,
    check_license,
    has_feature,
    require_license,
)

__all__ = [
    "License",
    "LicenseError",
    "LicenseManager",
    "LicenseTier",
    "TIER_FEATURES",
    "check_license",
    "has_feature",
    "require_license",
]
