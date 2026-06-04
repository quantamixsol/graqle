"""BizQ S2 dashboard read-API (Phase 5) — proprietary Studio backend.

A read-only browser over the hosted-anchoring outputs:

* **usage** — a tenant's monthly anchor count + allowance status, from the
  DynamoDB usage table (the "X / 1,000 this month" widget).
* **proofs** — list/get the anchored proof bundles in S3 ``proofs/``, tenant-
  scoped (filtered by the ``tenant_id`` stamped inside each bundle's record).

Thin placeholder RBAC (admin / viewer / billing) gates the surfaces until S3
ships the real ``BUILT_IN_ROLES``/``CustomRole`` model (then this binds to it).

Lives OUTSIDE the importable ``graqle`` package (under ``studio_backend/``), so it
never ships in the public Community wheel. It is READ-ONLY (no mutation of proofs
or usage) and does NOT import the verifier (moat-M2): verifying a bundle is the
separate verify-at-scale Lambda's job; this only lists/returns stored data.
"""
