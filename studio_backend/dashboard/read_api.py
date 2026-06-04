"""Dashboard read-API core (BizQ S2 Phase 5) — usage + proof browser.

Pure functions over the hosted-anchoring stores, with injectable AWS clients so
every path is testable without the cloud. READ-ONLY: nothing here mutates a proof
or a usage counter.

Tenant scoping is the security boundary: every call takes the *caller's* tenant
and only ever returns that tenant's data. A proof bundle is attributed to a
tenant by the ``tenant_id`` stamped inside its ``record`` (by the ingress); the
read API filters on that, so one tenant can never read another's proofs.

Thin RBAC (placeholder until S3's role model): ``viewer`` can read usage + proofs;
``billing`` can read usage; ``admin`` everything. The role is supplied by the
caller (resolved from the Studio session upstream). This is intentionally minimal
— it gates the surfaces and is swapped for S3's ``BUILT_IN_ROLES`` when that lands.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("studio_backend.dashboard.read_api")

# ── thin placeholder RBAC (until S3 ships the real role model) ───────────────
ROLE_ADMIN = "admin"
ROLE_VIEWER = "viewer"
ROLE_BILLING = "billing"
_VALID_ROLES = frozenset({ROLE_ADMIN, ROLE_VIEWER, ROLE_BILLING})

# action → roles permitted (placeholder matrix; S3's role model replaces this).
_PERMISSIONS = {
    "read_usage": frozenset({ROLE_ADMIN, ROLE_VIEWER, ROLE_BILLING}),
    "read_proofs": frozenset({ROLE_ADMIN, ROLE_VIEWER}),
}

_KEY_LEN = 64
_HEX_DIGITS = frozenset("0123456789abcdef")
_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")  # strict YYYY-MM (no free-form usage_key segments)
_DEFAULT_BUCKET = "graqle-graphs-eu"
_DEFAULT_PREFIX = "proofs"
# Cap a single proof bundle read (a real bundle is a few KB; refuse an absurd object).
_MAX_BUNDLE_BYTES = 1_048_576


class DashboardError(Exception):
    """A usage/read-API request that cannot proceed (bad input)."""


class ForbiddenError(DashboardError):
    """The caller's role is not permitted the requested action."""


def require_role(role: str, action: str) -> None:
    """Raise :class:`ForbiddenError` unless ``role`` may perform ``action``.

    Fail-closed: an unknown role or an unknown action is denied.
    """
    allowed = _PERMISSIONS.get(action)
    if allowed is None or role not in allowed:
        raise ForbiddenError(f"role {role!r} may not {action}")


def _require_tenant(tenant_id: object) -> str:
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise DashboardError("tenant_id is required")
    return tenant_id.strip()


def _is_hex(s: object, n: int) -> bool:
    return isinstance(s, str) and len(s) == n and not (set(s) - _HEX_DIGITS)


@dataclass(frozen=True)
class UsageView:
    """A tenant's anchor usage for one (edition, period)."""

    tenant_id: str
    edition: str
    period: str
    used: int
    allowance: int
    remaining: int
    over_allowance: bool


def get_usage(
    *,
    tenant_id: str,
    role: str,
    edition: str = "studio",
    period: str,
    usage_table: str,
    free_allowance: int = 1000,
    client: Any = None,
    region_name: str = "eu-central-1",
) -> UsageView:
    """Read a tenant's monthly anchor usage (the dashboard usage widget).

    ``period`` is ``YYYY-MM``. Returns a :class:`UsageView` — used / allowance /
    remaining / over-allowance. A tenant with no anchors yet reads as 0 used.
    """
    require_role(role, "read_usage")
    tid = _require_tenant(tenant_id)
    if not isinstance(period, str) or not _PERIOD_RE.match(period):
        raise DashboardError("period must be 'YYYY-MM'")

    ddb = client if client is not None else _ddb(region_name)
    usage_key = f"{_safe(tid)}#{_safe(edition)}#{period}"
    resp = ddb.get_item(TableName=usage_table, Key={"usage_key": {"S": usage_key}})
    used = int(resp.get("Item", {}).get("count", {}).get("N", "0"))
    remaining = max(0, free_allowance - used)
    return UsageView(
        tenant_id=tid,
        edition=edition,
        period=period,
        used=used,
        allowance=free_allowance,
        remaining=remaining,
        over_allowance=used > free_allowance,
    )


def list_proofs(
    *,
    tenant_id: str,
    role: str,
    bucket: str = _DEFAULT_BUCKET,
    prefix: str = _DEFAULT_PREFIX,
    limit: int = 50,
    client: Any = None,
    region_name: str = "eu-central-1",
) -> list[dict[str, Any]]:
    """List this tenant's anchored proofs (newest-first by S3 LastModified).

    Each entry is a lightweight summary ``{batch_id, leaf_hash, key,
    last_modified, size}`` — NOT the full bundle (use :func:`get_proof`). Scans
    the ``proofs/`` prefix and keeps only objects whose bundle is attributed to
    ``tenant_id``; a v1 read-time filter (a tenant→proof index is a later
    optimisation). ``limit`` caps the returned summaries.
    """
    require_role(role, "read_proofs")
    tid = _require_tenant(tenant_id)
    if not isinstance(limit, int) or limit < 1:
        raise DashboardError("limit must be a positive int")

    ddb_s3 = client if client is not None else _s3(region_name)
    norm_prefix = prefix.rstrip("/") + "/"
    out: list[dict[str, Any]] = []
    token: str | None = None
    # Bound the scan so a huge bucket can't make one request unbounded; stop once
    # we have `limit` tenant matches or run out of pages.
    pages = 0
    while pages < 20 and len(out) < limit:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": norm_prefix, "MaxKeys": 200}
        if token:
            kwargs["ContinuationToken"] = token
        resp = ddb_s3.list_objects_v2(**kwargs)
        for obj in resp.get("Contents", []) or []:
            key = obj.get("Key", "")
            if not key.endswith(".json"):
                continue
            bundle = _read_bundle(ddb_s3, bucket, key)
            if bundle is None or _bundle_tenant(bundle) != tid:
                continue
            out.append(_proof_summary(key, obj, bundle))
            if len(out) >= limit:
                break
        token = resp.get("NextContinuationToken")
        pages += 1
        if not token:
            break
    out.sort(key=lambda e: e.get("last_modified", ""), reverse=True)
    return out


def get_proof(
    *,
    tenant_id: str,
    role: str,
    batch_id: str,
    leaf_hash: str,
    bucket: str = _DEFAULT_BUCKET,
    prefix: str = _DEFAULT_PREFIX,
    client: Any = None,
    region_name: str = "eu-central-1",
) -> dict[str, Any]:
    """Fetch one full proof bundle, enforcing tenant ownership.

    Raises :class:`ForbiddenError` if the bundle is not attributed to
    ``tenant_id`` (a tenant cannot read another's proof even with a valid key),
    and :class:`DashboardError` for a missing/oversize/malformed bundle.
    """
    require_role(role, "read_proofs")
    tid = _require_tenant(tenant_id)
    if not _is_hex(batch_id, 32):
        raise DashboardError("batch_id must be 32 hex chars")
    if not _is_hex(leaf_hash, _KEY_LEN):
        raise DashboardError("leaf_hash must be 64 hex chars")

    s3 = client if client is not None else _s3(region_name)
    key = f"{prefix.rstrip('/')}/{batch_id}/{leaf_hash}.json"
    bundle = _read_bundle(s3, bucket, key)
    if bundle is None:
        raise DashboardError("proof bundle not found or unreadable")
    # Ownership check — the security boundary for cross-tenant reads.
    if _bundle_tenant(bundle) != tid:
        raise ForbiddenError("proof bundle is not owned by this tenant")
    return bundle


# ── helpers ──────────────────────────────────────────────────────────────────
def _safe(value: str) -> str:
    """Strip the usage-key delimiter so it can't alias another segment."""
    return value.replace("#", "")


def _bundle_tenant(bundle: dict[str, Any]) -> str | None:
    record = bundle.get("record") if isinstance(bundle, dict) else None
    tid = record.get("tenant_id") if isinstance(record, dict) else None
    return tid if isinstance(tid, str) and tid else None


def _proof_summary(key: str, obj: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    leaf = bundle.get("leaf", {}) if isinstance(bundle, dict) else {}
    rekor = bundle.get("rekor", {}) if isinstance(bundle, dict) else {}
    parts = key.split("/")
    batch_id = parts[-2] if len(parts) >= 2 else ""
    lm = obj.get("LastModified")
    return {
        "key": key,
        "batch_id": batch_id,
        "leaf_hash": leaf.get("leaf_hash", ""),
        "rekor_log_index": rekor.get("log_index") if isinstance(rekor, dict) else None,
        "last_modified": lm.isoformat() if hasattr(lm, "isoformat") else str(lm or ""),
        "size": int(obj.get("Size", 0) or 0),
    }


def _read_bundle(s3: Any, bucket: str, key: str) -> dict[str, Any] | None:
    """Read + parse a proof bundle from S3. Returns None on any read/parse error."""
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
        body = resp["Body"].read(_MAX_BUNDLE_BYTES + 1)
    except Exception:
        return None
    if len(body) > _MAX_BUNDLE_BYTES:
        return None  # oversize — refuse (DoS guard)
    try:
        data = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _ddb(region_name: str) -> Any:  # pragma: no cover - real AWS only
    import boto3

    return boto3.client("dynamodb", region_name=region_name)


def _s3(region_name: str) -> Any:  # pragma: no cover - real AWS only
    import boto3

    return boto3.client("s3", region_name=region_name)


__all__ = [
    "DashboardError",
    "ForbiddenError",
    "UsageView",
    "ROLE_ADMIN",
    "ROLE_VIEWER",
    "ROLE_BILLING",
    "require_role",
    "get_usage",
    "list_proofs",
    "get_proof",
]
