"""Layer dependency graph + config-validation rule (ADR-RT-003 §2.3, LS-3).

The five governance layers L1..L5 are not fully independent — each higher layer
builds on lower ones. This module encodes that dependency graph and the single
validation rule the SDK MUST enforce at config-validation time, in BOTH
development and production environments (LS-3):

    if layer N is enabled but a layer it depends on is disabled,
    refuse to start and point at the missing dependency.

The dependency graph (ADR-RT-003 §2.3)::

    L1 (KG substrate)            -> no dependencies, always required
    L2 (reasoning loop)          -> requires L1
    L3 (governed trace)          -> requires L1 + L2
    L4 (PCT integration)         -> requires L1 + L2 + L3
    L5 (cryptographic tamper-ev) -> requires L1 + L2 + L3
                                    (L4 recommended, NOT hard-required: L5 can
                                     commit non-PCT traces too)

This is informational data + one pure function — no I/O, no global state — so it
is trivially unit-testable and reusable by both the config layer and the
monotonic-on registry.
"""

from __future__ import annotations

from graqle.governance.tamper_evidence.errors import TamperEvidenceError

# Canonical layer ids, in dependency order. These match
# LayerSwitchConfig field names (attestation_config.py) exactly so a config can
# be validated field-for-field.
LAYER_IDS: tuple[str, ...] = (
    "l1_kg_substrate",
    "l2_reasoning_loop",
    "l3_governed_trace",
    "l4_pct_integration",
    "l5_cryptographic_tamper_evidence",
)

# Hard dependencies per ADR-RT-003 §2.3. L5 deliberately does NOT list L4 — L4 is
# recommended, not hard-required (L5 can commit non-PCT traces). Keep this the
# single source of truth; do not duplicate the edges elsewhere.
LAYER_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "l1_kg_substrate": (),
    "l2_reasoning_loop": ("l1_kg_substrate",),
    "l3_governed_trace": ("l1_kg_substrate", "l2_reasoning_loop"),
    "l4_pct_integration": (
        "l1_kg_substrate",
        "l2_reasoning_loop",
        "l3_governed_trace",
    ),
    "l5_cryptographic_tamper_evidence": (
        "l1_kg_substrate",
        "l2_reasoning_loop",
        "l3_governed_trace",
    ),
}


class LayerDependencyError(TamperEvidenceError):
    """Raised when an enabled layer has a disabled hard dependency (LS-3).

    Carries the offending layer and its first missing dependency so the operator
    error message points at the exact fix.
    """

    def __init__(self, layer_id: str, missing_dependency: str) -> None:
        self.layer_id = layer_id
        self.missing_dependency = missing_dependency
        super().__init__(
            f"layer {layer_id!r} is enabled but its dependency "
            f"{missing_dependency!r} is disabled; enable {missing_dependency!r} "
            f"or disable {layer_id!r} (ADR-RT-003 §2.3 layer dependency graph)"
        )


def dependencies_of(layer_id: str) -> tuple[str, ...]:
    """Return the hard dependencies of ``layer_id`` (empty tuple for L1).

    Raises :class:`KeyError` for an unknown layer id (programmer error — the
    caller passed a non-canonical layer name).
    """
    return LAYER_DEPENDENCIES[layer_id]


def validate_layer_config(enabled: dict[str, bool]) -> None:
    """Validate an enabled-state map against the dependency graph (LS-3).

    Parameters
    ----------
    enabled:
        Map of layer id -> enabled flag. Must contain every canonical layer id;
        a missing key is a malformed config and raises :class:`KeyError`.

    Raises
    ------
    LayerDependencyError
        For the FIRST enabled layer whose dependency is disabled. Layers are
        checked in dependency order (L1..L5) so the error names the lowest-level
        missing dependency — the most actionable fix.
    KeyError
        If ``enabled`` is missing a canonical layer id.

    The rule applies in BOTH environments (dev and prod); environment gating is
    only relevant to monotonic-on, not to dependency validation.
    """
    for layer_id in LAYER_IDS:
        if not enabled[layer_id]:
            continue
        for dependency in LAYER_DEPENDENCIES[layer_id]:
            if not enabled[dependency]:
                raise LayerDependencyError(layer_id, dependency)
