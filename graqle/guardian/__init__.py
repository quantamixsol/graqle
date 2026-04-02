"""GraQle PR Guardian — AI-powered blast radius analysis & governance for PRs.

Wraps existing GovernanceMiddleware (graqle.core.governance) and
graq_impact infrastructure to produce governed PR reviews with:
  - Blast radius visualization
  - 3-tier governance verdicts (T1/T2/T3/TS-BLOCK)
  - SHACL violation detection
  - RBAC-aware approval requirements
  - Shields.io-compatible badge generation
  - DRACE audit trail

See ADR-xxx for architecture rationale.
"""

from graqle.guardian.engine import GuardianReport, PRGuardianEngine, Verdict

__all__ = ["PRGuardianEngine", "GuardianReport", "Verdict"]
