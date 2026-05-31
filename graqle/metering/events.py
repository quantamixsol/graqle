"""The metering data model: the billable unit and the sink interface (WS-B).

This module defines *what* a billable event is and *where* it goes, with zero
proprietary or network dependencies — it ships in the Apache-2.0 ``graqle``
Community package. The Studio-backend (Session-2) implements :class:`MeterSink`
as ``StudioMeter`` (emit to the metering API + enforce allowance/overage); the
Community build ships only :class:`LocalNullMeter` (a no-op — local work is
free).

Design rules (mirror the Layer-5 / runtime composition discipline):

* **The unit is the *anchored* proof.** ADR §3.2/§3.3: the free/paid line is
  ``local = free, hosted = metered``. A :class:`MeterEvent` is therefore only
  ever recorded at the moment a proof becomes hosted/anchored — never for a
  purely-local self-commit. ``unit`` is fixed to ``"proof_anchored"`` (Q3
  locked: per-anchor only; hosted verify-at-scale ships free).
* **The idempotency key is the leaf hash.** ``idempotency_key`` is the
  governed record's Merkle ``leaf_hash`` (hex). It is globally unique per proof
  and *identical* at both count points (the runtime ``AttestationSink`` path and
  the Layer-5 ``Committer`` batch path), so the same proof reached via both
  paths — or retried — dedupes to exactly one billable event (see
  :mod:`graqle.metering.dedupe`).
* **A count point only records intent.** Emitting a :class:`MeterEvent` must
  never alter or block the governed/anchoring path; the sink decides what to do
  with it. Best-effort, never-raise wiring is the contract (see
  :mod:`graqle.metering.sinks` and :mod:`graqle.metering.committer_hook`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "PROOF_ANCHORED",
    "MeterEvent",
    "MeterSink",
]

# The single billable unit (Q3 locked). A constant rather than a free string so
# every count point and every sink agrees on the exact token, and a typo becomes
# an import error rather than a silently-unbilled event.
PROOF_ANCHORED = "proof_anchored"


def _utc_now_iso() -> str:
    """UTC ISO-8601 timestamp (timezone-aware), to seconds — the event clock."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class MeterEvent:
    """One record of *intent to bill* for a hosted/anchored proof.

    Immutable by construction (``frozen=True``): a count point produces it and
    hands it to a :class:`MeterSink`; nothing downstream may mutate the billable
    facts. The authoritative dedupe (exactly-once) lives in
    :class:`graqle.metering.dedupe.MeterDedupeStore`, keyed on
    :attr:`idempotency_key`.

    Attributes
    ----------
    idempotency_key:
        The governed record's Merkle ``leaf_hash`` (lowercase hex). Globally
        unique per proof, stable across retries, and identical at both count
        points — this is what makes exactly-once possible. Required, non-empty.
    edition:
        The edition that produced the proof (``"community"`` / ``"studio"`` /
        ``"enterprise"``). Carried so the meter API can attribute usage to a
        tenant/plan without re-deriving it. Defaults to ``"community"``.
    unit:
        The billable unit. Fixed to :data:`PROOF_ANCHORED`; constructing a
        :class:`MeterEvent` with any other unit is a programming error and is
        rejected (defence against an un-priced unit silently entering the meter).
    count:
        How many billable units this event represents. Always ``1`` for a
        per-anchor event; the field exists so a future batched-emit optimisation
        can coalesce without changing the schema. Must be a positive int.
    ts:
        UTC ISO-8601 timestamp of the anchoring moment. Auto-set if omitted.
    metadata:
        Optional non-billing context (e.g. ``batch_id``, ``rekor_log_index``)
        for the meter API's audit trail. Never affects dedupe or pricing. Copied
        defensively so the frozen event truly owns its data.
    """

    idempotency_key: str
    edition: str = "community"
    unit: str = PROOF_ANCHORED
    count: int = 1
    ts: str = field(default_factory=_utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Validate at the boundary: a malformed billable event must fail loudly
        # where it is created, not produce a mis-billed or un-billed record
        # downstream. frozen=True means we must go through object.__setattr__ to
        # normalise the defensively-copied metadata.
        if not isinstance(self.idempotency_key, str) or not self.idempotency_key:
            raise ValueError("idempotency_key must be a non-empty string (the leaf_hash hex)")
        if self.unit != PROOF_ANCHORED:
            raise ValueError(
                f"unit must be {PROOF_ANCHORED!r} (the only billable unit; "
                f"hosted verify-at-scale ships free), got {self.unit!r}"
            )
        if not isinstance(self.edition, str) or not self.edition:
            raise ValueError("edition must be a non-empty string")
        if not isinstance(self.count, int) or isinstance(self.count, bool) or self.count < 1:
            raise ValueError("count must be a positive int")
        if not isinstance(self.ts, str) or not self.ts:
            raise ValueError("ts must be a non-empty ISO-8601 string")
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be a dict")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for the meter API / audit store."""
        return {
            "idempotency_key": self.idempotency_key,
            "edition": self.edition,
            "unit": self.unit,
            "count": self.count,
            "ts": self.ts,
            "metadata": dict(self.metadata),
        }


@runtime_checkable
class MeterSink(Protocol):
    """Where a billable :class:`MeterEvent` is recorded (one-method interface).

    Mirrors the shape of ``graqle.governance.runtime.AttestationSink`` (one
    method, takes the unit of work, side-effects only): the Community build ships
    :class:`graqle.metering.sinks.LocalNullMeter` (no-op); the proprietary
    Studio-backend (Session-2) ships ``StudioMeter`` that emits to the metering
    API and enforces the free monthly hosted-anchor allowance → tiered overage.

    Contract for implementers:

    * ``record`` is called at most once per *unique* billable event — the
      exactly-once dedupe (keyed on :attr:`MeterEvent.idempotency_key`) is
      enforced *before* the sink by :class:`graqle.metering.dedupe.MeterDedupeStore`,
      so a sink may assume it never sees the same key twice for billing
      purposes. (A sink is still free to be internally idempotent.)
    * ``record`` is invoked on the governed/anchoring path. It MUST be fast and
      MUST NOT raise in a way that can break that path — the wiring wraps it
      best-effort, but a well-behaved sink defers slow/remote work (HTTP, DB)
      off the critical path itself.
    """

    def record(self, event: MeterEvent) -> None:
        """Record one billable event. Side-effects only; returns nothing."""
        ...
