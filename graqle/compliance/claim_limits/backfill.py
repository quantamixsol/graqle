"""R25-EU11 v1.0 backfill migration — one-time, idempotent.

For each existing governance record (``ResponseSnapshot``,
``EvidenceStateSnapshot``, and any other ``entity_type`` flagged in
:data:`BACKFILL_ENTITY_TYPES`) that lacks a ``claim_limits`` field, this
module writes the single-value list ``["legacy_pre_R25_EU11"]`` so the
record passes the L08 / L19 default-deny constraint.

The migration is:

    - **Idempotent**: re-running over already-backfilled records is a
      no-op (existing ``claim_limits`` is left untouched).
    - **Audit-logged**: every backfilled record gets a ``backfilled_at``
      ISO-8601 timestamp + a ``backfill_source`` marker in
      ``properties`` so a post-migration auditor can answer "which
      records were backfilled and when?".
    - **Read-only by default**: ``dry_run=True`` is the safe default;
      callers must pass ``dry_run=False`` to commit.

The migration uses :func:`require_non_empty_claim_limits` with
``allow_legacy_backfill=True`` so the validator accepts the backfill
sentinel on these specific writes. New writes (outside this migration)
still reject the sentinel.

The migration is exposed via the CLI as ``graq compliance backfill-claim-limits``
in PR-010c (companion CLI surface). When called as a script, the module
runs the migration against the loaded graph.

References:
    - R25-EU11 § "Backfill protocol"
    - graqle.compliance.claim_limits.validator
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from graqle.compliance.claim_limits.taxonomy import LEGACY_BACKFILL_VALUE
from graqle.compliance.claim_limits.validator import (
    require_non_empty_claim_limits,
)

logger = logging.getLogger("graqle.compliance.claim_limits.backfill")

#: Entity types eligible for backfill. New entity types that emerge after
#: R25-EU11 v1.0 ships MUST be added here explicitly — silent extension
#: would defeat the default-deny guarantee.
BACKFILL_ENTITY_TYPES: frozenset[str] = frozenset(
    {
        "ResponseSnapshot",
        "EvidenceStateSnapshot",
        "GOVERNANCE_BYPASS",
        "TOOL_EXECUTION",
    }
)

#: Audit-marker key written into properties on every backfilled record.
BACKFILL_SOURCE_KEY: str = "claim_limits_backfill_source"
BACKFILL_SOURCE_VALUE: str = "R25-EU11-v1.0-migration"
BACKFILLED_AT_KEY: str = "claim_limits_backfilled_at"


@dataclass(frozen=True)
class BackfillStats:
    """Outcome of a backfill migration pass.

    Attributes:
        total_scanned: Total nodes inspected.
        already_compliant: Nodes that already had a non-empty
            ``claim_limits`` — left untouched.
        backfilled: Nodes that received the backfill sentinel +
            audit-marker.
        skipped_wrong_type: Nodes whose ``entity_type`` is not in
            :data:`BACKFILL_ENTITY_TYPES`.
        errors: Per-node error descriptions (rare — validator failures
            on existing data shouldn't normally occur).
    """

    total_scanned: int = 0
    already_compliant: int = 0
    backfilled: int = 0
    skipped_wrong_type: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view for CLI / audit output."""
        return {
            "total_scanned": self.total_scanned,
            "already_compliant": self.already_compliant,
            "backfilled": self.backfilled,
            "skipped_wrong_type": self.skipped_wrong_type,
            "errors": list(self.errors),
        }


def _iso_now() -> str:
    """Return current UTC time as ISO-8601 ``Z`` string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _node_already_has_claim_limits(props: dict[str, Any]) -> bool:
    """Return True iff ``props.claim_limits`` is a non-empty list of str.

    The check is intentionally narrow: a malformed ``claim_limits``
    (wrong type, mixed types, empty list) is treated as "not yet
    compliant" — the backfill will overwrite it with the sentinel and
    a future hardening pass can deal with the malformed values.
    """
    cl = props.get("claim_limits")
    if not isinstance(cl, list) or not cl:
        return False
    return all(isinstance(x, str) and x for x in cl)


def backfill_node(
    node: Any,
    *,
    dry_run: bool = True,
) -> str | None:
    """Backfill a single node, returning a short status string.

    Args:
        node: A node object exposing ``.entity_type`` (str) and
            ``.properties`` (dict-like). Used by both the in-memory
            graph backend and the Neo4j projection.
        dry_run: If True (default), validate + return what WOULD happen
            but mutate nothing.

    Returns:
        One of:
            - ``None`` — skipped (wrong entity type)
            - ``"already_compliant"`` — non-empty claim_limits already present
            - ``"backfilled"`` — sentinel written (or would be written, in dry_run)
            - ``"error:<msg>"`` — validator rejected the resulting claim_limits

    Note:
        Backfilling exclusively writes the sentinel
        ``["legacy_pre_R25_EU11"]`` — it never invents a richer
        claim-limits set. Records that need a richer set must be
        re-written by the operator's downstream pipeline after
        migration.
    """
    entity_type = getattr(node, "entity_type", None) or ""
    if entity_type not in BACKFILL_ENTITY_TYPES:
        return None

    # Get-or-create properties dict (some node implementations lazy-init).
    props = getattr(node, "properties", None)
    if props is None:
        props = {}
        if not dry_run:
            try:
                node.properties = props  # type: ignore[attr-defined]
            except (AttributeError, TypeError):
                return "error:cannot_set_properties_on_node"

    if _node_already_has_claim_limits(props):
        return "already_compliant"

    new_claim_limits = [LEGACY_BACKFILL_VALUE]

    # Validate the backfill sentinel against the validator with the
    # allow_legacy_backfill escape so it accepts the sentinel.
    try:
        require_non_empty_claim_limits(
            new_claim_limits,
            allow_legacy_backfill=True,
            field_name="claim_limits",
        )
    except Exception as exc:  # noqa: BLE001 — surface every validator path
        return f"error:{type(exc).__name__}:{exc}"

    if dry_run:
        return "backfilled"

    props["claim_limits"] = new_claim_limits
    props[BACKFILL_SOURCE_KEY] = BACKFILL_SOURCE_VALUE
    props[BACKFILLED_AT_KEY] = _iso_now()
    return "backfilled"


def backfill_graph(graph: Any, *, dry_run: bool = True) -> BackfillStats:
    """Walk every node in ``graph`` and backfill where applicable.

    Args:
        graph: A graph object exposing ``.nodes`` as an iterable of node
            objects (NetworkX-backed Tier 0 graph or the Neo4j projection
            shim — both honour this protocol).
        dry_run: If True (default), report what WOULD happen.

    Returns:
        BackfillStats summarising the pass.
    """
    stats_total = 0
    stats_already = 0
    stats_backfilled = 0
    stats_skipped = 0
    errors: list[str] = []

    # Some graph implementations expose .nodes as a dict-view (NetworkX),
    # others as an iterable of node objects. Try both.
    nodes_attr = getattr(graph, "nodes", None)
    if nodes_attr is None:
        raise ValueError(
            "backfill_graph: graph object has no .nodes attribute"
        )
    try:
        node_iter = list(nodes_attr.values()) if hasattr(nodes_attr, "values") else list(nodes_attr)
    except TypeError:
        raise ValueError(
            "backfill_graph: graph.nodes is neither a mapping nor iterable"
        )

    for node in node_iter:
        stats_total += 1
        try:
            status = backfill_node(node, dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001
            nid = getattr(node, "id", "<unknown>")
            errors.append(f"{nid}: {type(exc).__name__}: {exc}")
            continue

        if status is None:
            stats_skipped += 1
        elif status == "already_compliant":
            stats_already += 1
        elif status == "backfilled":
            stats_backfilled += 1
        elif status.startswith("error:"):
            nid = getattr(node, "id", "<unknown>")
            errors.append(f"{nid}: {status}")
        else:
            errors.append(f"unknown status: {status}")

    if not dry_run and stats_backfilled:
        logger.info(
            "claim_limits backfill complete: %d nodes backfilled, %d already "
            "compliant, %d skipped (wrong type), %d errors",
            stats_backfilled,
            stats_already,
            stats_skipped,
            len(errors),
        )

    return BackfillStats(
        total_scanned=stats_total,
        already_compliant=stats_already,
        backfilled=stats_backfilled,
        skipped_wrong_type=stats_skipped,
        errors=errors,
    )
