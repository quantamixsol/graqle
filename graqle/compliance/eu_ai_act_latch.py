"""EU AI Act configurable + irreversible-latch core (ADR-222 P5a).

This module is the **security-critical core** of GraQle's optional EU AI Act
(Regulation (EU) 2024/1689) governance layer. It is **OFF by default** and, as
of P5a, is **wired to nothing** — building it changes no runtime behaviour. P5b
wires the latched state into the governance gate as an enforced phase.

What it provides
----------------
A **one-way latch**: once a project records ``enabled: true`` for the EU AI Act
layer, that state cannot be silently turned off, and ``mode`` cannot be
downgraded ``blocking -> advisory``. The latch is NOT a hand-editable yaml flag
— it is an **ed25519-signed, hash-chained, append-only record** stored under
``.graqle/eu_ai_act_latch.jsonl``. The gate (P5b) reads the *latched* state, not
the raw yaml; if yaml says ``enabled: false`` but the latch says ``true``, the
latch wins and tampering is flagged.

Design (ADR-222 R-B1 / R-B4 / D-1):
- **Tamper-evident:** each event is canonicalised (RFC 8785 ``canon``) and signed
  with a per-project ed25519 key; each event carries ``prev_hash`` forming a
  hash chain. A broken signature or chain => the reader fails closed.
- **One-way:** ``upgrade`` events are allowed (``advisory -> blocking``,
  ``enabled false -> true``); ``downgrade`` is refused.
- **Audited override (D-1):** a wrongly-blocked action may proceed ONCE via a
  signed, logged ``override`` event carrying a justification. This is NOT a
  downgrade — the latch stays on; it only records that one action proceeded.
- **No silent edits, ever.** Every state transition is a signed chained event.

Honest framing (ADR-222 D-3 / research §2): the irreversible latch is a GraQle
design that **supports** the Act's record-keeping / traceability expectations
(Art. 12 / 72). The Act does NOT itself require an un-disableable switch — never
document it as "required by the Act".

This module performs NO blocking on its own; it records and reports state. It
never raises into a caller's hot path beyond the explicit, typed exceptions
below, which callers (P5b) handle as fail-closed.

Known residuals — addressed when P5b wires the live (multi-instance) gate
(graq_predict 30-day forecast, ADR-222 P5a):
- **Cross-process concurrency:** the in-process ``threading.RLock`` serializes
  writes within ONE process only. Concurrent writers from separate processes on
  the SAME project dir are NOT serialized — but this cannot silently corrupt
  state: ``_verify_chain`` detects any resulting chain break and ``read_state``
  fails closed. P5b adds real cross-process file locking (portalocker, as in
  ``graqle/config/resolver.py``) before the latch gates a multi-instance server.
- **File deletion:** deleting the whole ``.graqle/eu_ai_act_latch.jsonl`` resets
  to "absent/disabled". P5b anchors the latch's existence into the tamper-
  evidence substrate so deletion of an enabled latch is detectable.
- **Key-permission drift / key loss:** a lost or unreadable key only blocks
  WRITES (new transitions); reads verify off each event's embedded public key,
  and any read failure fails closed. P5b documents key custody/rotation.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from graqle.governance.tamper_evidence.canonicalize import canon

logger = logging.getLogger("graqle.compliance.eu_ai_act_latch")

# Public, stable string literals (safe to expose — ADR CLAUDE.md "SAFE TO EXPOSE").
Mode = Literal["blocking", "advisory"]
RiskClass = Literal["high", "limited", "minimal"]
EventKind = Literal["enable", "upgrade", "override"]

_LATCH_FILENAME = "eu_ai_act_latch.jsonl"
_KEY_FILENAME = "eu_ai_act_latch.key"
_GENESIS_HASH = "0" * 64

# mode ordering for the one-way ratchet: advisory < blocking (blocking is stricter)
_MODE_RANK = {"advisory": 0, "blocking": 1}


class LatchError(Exception):
    """Base error for latch operations."""


class LatchTamperError(LatchError):
    """The latch chain is broken or a signature is invalid — fail closed."""


class LatchDowngradeRefused(LatchError):
    """A request would weaken the latch (disable, or blocking->advisory)."""


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


@dataclass(frozen=True)
class LatchState:
    """The resolved, verified latch state. ``enabled=False`` means no latch."""

    enabled: bool
    mode: Mode | None
    risk_class: RiskClass | None
    event_count: int
    override_count: int
    tampered: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "risk_class": self.risk_class,
            "event_count": self.event_count,
            "override_count": self.override_count,
            "tampered": self.tampered,
        }


class EuAiActLatch:
    """Append-only, ed25519-signed, hash-chained EU AI Act latch.

    Construct with the project root; the latch lives under ``<root>/.graqle/``.
    All timestamps are passed in by the caller (UTC ISO-8601) so the latch is
    deterministic and testable — never read from the clock here.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._dir = self._root / ".graqle"
        self._path = self._dir / _LATCH_FILENAME
        self._key_path = self._dir / _KEY_FILENAME
        # P5a Sentinel MAJOR fix: serialize concurrent write transitions
        # (enable / record_override) so a read-modify-append race cannot corrupt
        # the chain. In-process serialization via a re-entrant lock. Writes are
        # deliberate, infrequent operator actions (not a hot path); cross-process
        # concurrency on the SAME project dir is out of scope for P5a and would
        # be detected as a chain break by _verify_chain (fail-closed) rather than
        # silently corrupting state.
        import threading

        self._write_lock = threading.RLock()

    # ── key management ────────────────────────────────────────────────
    # The latch key is a PER-PROJECT integrity seal: it proves the recorded
    # state was not altered after the fact. It is generated on first enable and
    # stored locally (0600). This is NOT a licence key and is not verified
    # against any server — it secures the local chain only.

    def _load_or_create_key(self) -> Ed25519PrivateKey:
        if self._key_path.exists():
            raw = self._key_path.read_bytes()
            return serialization.load_pem_private_key(raw, password=None)  # type: ignore[return-value]
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        self._dir.mkdir(parents=True, exist_ok=True)
        self._atomic_write_bytes(self._key_path, pem)
        try:
            os.chmod(self._key_path, 0o600)
        except OSError:
            pass  # best-effort on platforms without POSIX perms
        return key

    def _public_key(self) -> Ed25519PublicKey:
        return self._load_or_create_key().public_key()

    # ── low-level event IO ────────────────────────────────────────────

    def _read_raw_events(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
        return events

    def _atomic_write_bytes(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            tmp = ""  # replaced
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def _signed_record(
        self,
        priv: Ed25519PrivateKey,
        *,
        kind: EventKind,
        ts: str,
        prev_hash: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a canonicalised, signed, chained event record."""
        core = {
            "kind": kind,
            "ts": ts,
            "prev_hash": prev_hash,
            "body": body,
        }
        message = canon(core)
        signature = priv.sign(message)
        leaf_hash = _sha256_hex(message)
        pub_pem = priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        record = dict(core)
        record["sig"] = _b64(signature)
        record["hash"] = leaf_hash
        record["pub"] = _b64(pub_pem)
        return record

    def _append(self, record: dict[str, Any]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        existing = self._path.read_bytes() if self._path.exists() else b""
        line = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        self._atomic_write_bytes(self._path, existing + line)

    # ── verification ──────────────────────────────────────────────────

    def _verify_chain(self, events: list[dict[str, Any]]) -> None:
        """Verify signatures + hash chain. Raise LatchTamperError on any break.

        Fail-closed: any structural problem, bad signature, or chain mismatch is
        treated as tampering.
        """
        prev = _GENESIS_HASH
        pub_pem_first: bytes | None = None
        for idx, ev in enumerate(events):
            try:
                kind = ev["kind"]
                ts = ev["ts"]
                ev_prev = ev["prev_hash"]
                body = ev["body"]
                sig = _b64d(ev["sig"])
                claimed_hash = ev["hash"]
                pub_pem = _b64d(ev["pub"])
            except (KeyError, ValueError, TypeError) as exc:
                raise LatchTamperError(f"latch event {idx} malformed: {exc}") from exc

            # The signing key must be stable across the chain (no key swap).
            if pub_pem_first is None:
                pub_pem_first = pub_pem
            elif pub_pem != pub_pem_first:
                raise LatchTamperError(f"latch event {idx} signing key changed (key-swap attack)")

            if ev_prev != prev:
                raise LatchTamperError(
                    f"latch event {idx} chain break: prev_hash {ev_prev!r} != {prev!r}"
                )

            core = {"kind": kind, "ts": ts, "prev_hash": ev_prev, "body": body}
            message = canon(core)
            if _sha256_hex(message) != claimed_hash:
                raise LatchTamperError(f"latch event {idx} hash mismatch (content altered)")

            try:
                pub = serialization.load_pem_public_key(pub_pem)
                pub.verify(sig, message)  # type: ignore[union-attr]
            except (InvalidSignature, ValueError, TypeError) as exc:
                raise LatchTamperError(f"latch event {idx} signature invalid: {exc}") from exc

            prev = claimed_hash

    # ── public read API ───────────────────────────────────────────────

    def read_state(self) -> LatchState:
        """Return the verified latched state. Fails closed on tamper.

        If the chain is tampered, returns a LatchState with ``tampered=True`` and,
        crucially, ``enabled=True`` IF any enable event is present in the (now
        untrusted) log — so a tamper attempt can NEVER be used to silently turn
        the latch off. A clean absent latch returns ``enabled=False``.
        """
        # SECURITY (P5a Sentinel BLOCKER fix): read_state must NEVER raise into a
        # caller (the P5b gate) — an uncaught exception would bypass fail-closed.
        # ANY failure (malformed JSONL, IO error, corrupt key, unexpected bug)
        # is treated as fail-closed: tampered=True, and enabled stays True if the
        # raw bytes show any sign the latch was ever enabled. Tampering / I/O
        # damage can NEVER silently disable the latch.
        try:
            events = self._read_raw_events()
        except Exception as exc:  # noqa: BLE001 — fail closed on ANY read failure
            logger.warning("EU AI Act latch unreadable (%s) — failing closed.", exc)
            return self._fail_closed_state()

        if not events:
            return LatchState(enabled=False, mode=None, risk_class=None,
                              event_count=0, override_count=0, tampered=False)
        try:
            self._verify_chain(events)
        except LatchTamperError:
            logger.warning("EU AI Act latch FAILED verification — failing closed (tampered).")
            return self._fail_closed_state(events)
        except Exception as exc:  # noqa: BLE001 — any unexpected error = fail closed
            logger.warning("EU AI Act latch verify error (%s) — failing closed.", exc)
            return self._fail_closed_state(events)
        try:
            return self._resolve(events)
        except Exception as exc:  # noqa: BLE001 — resolve must not crash the gate
            logger.warning("EU AI Act latch resolve error (%s) — failing closed.", exc)
            return self._fail_closed_state(events)

    def _fail_closed_state(self, events: list[dict[str, Any]] | None = None) -> LatchState:
        """Build a fail-closed LatchState. If the (untrusted) log shows any
        enable/upgrade, the latch STAYS enabled+blocking — tamper/damage can
        never disable it. Best-effort raw byte probe if events couldn't parse."""
        any_enable = False
        override_count = 0
        n = 0
        try:
            if events is not None:
                n = len(events)
                any_enable = any(
                    isinstance(e, dict) and e.get("kind") in ("enable", "upgrade")
                    for e in events
                )
                override_count = sum(
                    1 for e in events if isinstance(e, dict) and e.get("kind") == "override"
                )
            elif self._path.exists():
                # raw probe — even unparseable bytes mentioning an enable event
                # keep the latch closed (conservative).
                raw = self._path.read_bytes()
                any_enable = b'"kind":"enable"' in raw or b'"enable"' in raw or b'"upgrade"' in raw
        except Exception:  # noqa: BLE001 — probing must never raise either
            any_enable = True  # most conservative: assume enabled, fail closed
        return LatchState(
            enabled=any_enable, mode="blocking" if any_enable else None,
            risk_class=None, event_count=n, override_count=override_count,
            tampered=True,
        )

    def _resolve(self, events: list[dict[str, Any]]) -> LatchState:
        """Fold verified events into the current state (one-way ratchet)."""
        enabled = False
        mode: Mode | None = None
        risk_class: RiskClass | None = None
        override_count = 0
        for ev in events:
            kind = ev["kind"]
            body = ev.get("body", {})
            if kind in ("enable", "upgrade"):
                enabled = True
                new_mode = body.get("mode")
                if new_mode in _MODE_RANK:
                    # ratchet: only ever move to a stricter-or-equal mode
                    if mode is None or _MODE_RANK[new_mode] >= _MODE_RANK[mode]:
                        mode = new_mode  # type: ignore[assignment]
                rc = body.get("risk_class")
                if rc in ("high", "limited", "minimal"):
                    risk_class = rc  # type: ignore[assignment]
            elif kind == "override":
                override_count += 1
        return LatchState(
            enabled=enabled, mode=mode, risk_class=risk_class,
            event_count=len(events), override_count=override_count, tampered=False,
        )

    # ── public write API (all transitions are signed chained events) ───

    def enable(self, *, mode: Mode, risk_class: RiskClass, ts: str) -> LatchState:
        """Record an enable/upgrade event. One-way: never weakens the latch.

        Allowed: first enable; advisory->blocking; risk_class change; re-assert.
        Refused (LatchDowngradeRefused): blocking->advisory.
        (There is intentionally no 'disable' — the latch cannot be turned off.)
        """
        if mode not in _MODE_RANK:
            raise LatchError(f"invalid mode {mode!r}")
        if risk_class not in ("high", "limited", "minimal"):
            raise LatchError(f"invalid risk_class {risk_class!r}")

        with self._write_lock:
            current = self.read_state()
            if current.tampered:
                raise LatchTamperError("refusing to write over a tampered latch chain")
            if current.enabled and current.mode is not None:
                if _MODE_RANK[mode] < _MODE_RANK[current.mode]:
                    raise LatchDowngradeRefused(
                        f"refusing to downgrade EU AI Act mode "
                        f"{current.mode!r} -> {mode!r}: the latch is one-way."
                    )

            priv = self._load_or_create_key()
            events = self._read_raw_events()
            prev = events[-1]["hash"] if events else _GENESIS_HASH
            kind: EventKind = "enable" if not current.enabled else "upgrade"
            record = self._signed_record(
                priv, kind=kind, ts=ts, prev_hash=prev,
                body={"mode": mode, "risk_class": risk_class},
            )
            self._append(record)
            return self.read_state()

    def record_override(self, *, justification: str, actor: str, action: str, ts: str) -> LatchState:
        """Record an audited per-action override (D-1).

        This does NOT turn the latch off or downgrade it — it appends a signed
        record that ONE action proceeded past a block, with a justification, for
        the audit trail. Requires the latch to be enabled.
        """
        if not justification or not justification.strip():
            raise LatchError("override requires a non-empty justification")
        with self._write_lock:
            current = self.read_state()
            if current.tampered:
                raise LatchTamperError("refusing to write over a tampered latch chain")
            if not current.enabled:
                raise LatchError("cannot record an override: EU AI Act latch is not enabled")

            priv = self._load_or_create_key()
            events = self._read_raw_events()
            prev = events[-1]["hash"] if events else _GENESIS_HASH
            record = self._signed_record(
                priv, kind="override", ts=ts, prev_hash=prev,
                body={
                    "justification": justification.strip(),
                    "actor": actor,
                    "action": action,
                },
            )
            self._append(record)
            return self.read_state()


# ── gate decision helper (ADR-222 P5b) ─────────────────────────────────
# Pure function so the enforcement logic is unit-testable without the MCP
# server. The gate (graqle/plugins/mcp_dev_server.py) calls this and acts on
# the returned decision. Cost/quality are NEVER gated here — only AIA-relevant
# writes, only when the latch is enabled, and always with the audited override
# escape valve (D-1).

# AIA-relevant write tools — the ONLY tools the EU AI Act phase may gate. Reads,
# planning, reasoning, lifecycle, learn, etc. are NEVER gated (narrow scope).
AIA_GATED_TOOLS: frozenset[str] = frozenset({
    "graq_edit", "kogni_edit",
    "graq_write", "kogni_write",
    "graq_generate", "kogni_generate",
    "graq_apply", "kogni_apply",
})


@dataclass(frozen=True)
class GateDecision:
    """Result of the EU AI Act gate evaluation for one tool call."""

    action: Literal["allow", "block", "advise"]
    reason: str = ""
    envelope: dict[str, Any] | None = None  # refusal envelope when action=="block"
    advisory: str | None = None             # advisory note when action=="advise"


def evaluate_gate(
    *,
    state: LatchState,
    tool_name: str,
    confidence: float | None,
    threshold: float,
    override_justification: str | None = None,
) -> GateDecision:
    """Decide whether an AIA-relevant write proceeds under the latch.

    Narrow scope + fail-safe-for-usability rules (ADR-222 P5b / research):
    - Latch not enabled, or tool not AIA-relevant -> ``allow`` (no-op).
    - Latch enabled but a (non-empty) override justification is present ->
      ``allow`` (the caller will have recorded the signed override).
    - ``advisory`` mode -> ``advise`` (warn + caller records), never block.
    - ``blocking`` mode + confidence below threshold -> ``block`` with a refusal
      envelope that explains how to override.
    - ``blocking`` mode + confidence >= threshold (or unknown) -> ``allow``.

    This never gates non-write tools and never blocks for cost/quality — only
    the Article-14 oversight signal on an AIA-relevant write.

    HONEST SCOPE (what this is / is NOT, per graq_predict P5b forecast): this is
    a deliberately LIGHT-TOUCH phase. It blocks ONLY when (a) the latch is
    enabled+blocking, (b) the tool is an AIA-relevant write, AND (c) an explicit
    confidence below threshold is supplied — and even then a signed override
    proceeds. In practice it RECORDS and ADVISES far more than it blocks. It is a
    compliance *traceability* aid (Art. 12/72 support), NOT a hard wall, and NOT
    a substitute for human compliance judgement. Native (non-graq_) tools bypass
    it entirely — the client-side wall + constitution address that, not this
    phase. Treat blocks as a prompt for human oversight, not a guarantee.
    """
    if not state.enabled or tool_name not in AIA_GATED_TOOLS:
        return GateDecision(action="allow")

    # An audited per-action override was supplied -> let this one through.
    if override_justification and override_justification.strip():
        return GateDecision(
            action="allow",
            reason="eu_ai_act_override_recorded",
        )

    mode = state.mode or "blocking"  # tampered/unknown -> treat as strictest

    if mode == "advisory":
        return GateDecision(
            action="advise",
            advisory=(
                f"EU AI Act ({state.risk_class or 'high'}-risk, advisory): "
                f"Article-14 human-oversight applies to '{tool_name}'. "
                "Recorded; not blocked."
            ),
        )

    # blocking mode — only refuse when oversight confidence is below threshold.
    if confidence is not None and confidence < threshold:
        envelope = {
            "error": "CG-EU-AIA_OVERSIGHT",
            "tool": tool_name,
            "message": (
                f"EU AI Act blocking mode ({state.risk_class or 'high'}-risk): "
                f"'{tool_name}' needs human oversight (Article 14) — confidence "
                f"{confidence:.2f} is below the {threshold:.2f} review threshold."
            ),
            "remediation": (
                "Re-run the same tool with an 'eu_aia_override_justification' "
                "argument to proceed with a signed, audited override. This does "
                "NOT disable the EU AI Act latch — it records that one action "
                "proceeded under human oversight."
            ),
            "eu_ai_act": {
                "mode": mode,
                "risk_class": state.risk_class,
                "confidence": confidence,
                "threshold": threshold,
                "tampered": state.tampered,
            },
        }
        return GateDecision(
            action="block",
            reason="article_14_oversight_below_threshold",
            envelope=envelope,
        )

    return GateDecision(action="allow")
