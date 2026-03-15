"""Graqle Governance — Transparency Layer for AI-assisted development.

Mapped from TAMR+ regulatory governance patterns to the development domain:
- audit.py → immutable reasoning session logs (from audit_trail.py)
- drace.py → DRACE scoring engine (from TRACE scoring)
- evidence.py → decision chain builder (from evidence_chains.py)
- scope_gate.py → scope boundary validation (from semantic_shacl_gate.py)

See ADR-105 §Governance Layer (Mapped from TAMR+).
"""

# ── graqle:intelligence ──
# module: graqle.intelligence.governance.__init__
# risk: LOW (impact radius: 0 modules)
# dependencies: audit, drace, evidence, scope_gate
# constraints: none
# ── /graqle:intelligence ──

from graqle.intelligence.governance.audit import (
    AuditEntry,
    AuditSession,
    AuditTrail,
)
from graqle.intelligence.governance.drace import (
    AuditabilityInput,
    ConstraintInput,
    DependencyInput,
    DRACEScore,
    DRACEScorer,
    ExplainabilityInput,
    ReasoningInput,
    evaluate_auditability,
    evaluate_constraint,
    evaluate_dependency,
    evaluate_explainability,
    evaluate_reasoning,
)
from graqle.intelligence.governance.evidence import (
    DecisionRecord,
    EvidenceChain,
    EvidenceItem,
    EvidenceStore,
)
from graqle.intelligence.governance.scope_gate import (
    ScopeDeclaration,
    ScopeGate,
    ScopeRule,
    ScopeViolation,
)

__all__ = [
    "AuditSession",
    "AuditEntry",
    "AuditTrail",
    "DRACEScore",
    "DRACEScorer",
    "EvidenceChain",
    "DecisionRecord",
    "EvidenceItem",
    "EvidenceStore",
    "ScopeDeclaration",
    "ScopeGate",
    "ScopeRule",
    "ScopeViolation",
]
