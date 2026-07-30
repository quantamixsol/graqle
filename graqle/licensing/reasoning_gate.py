"""Reasoning-quota middleware (W3, ADR-245 Decision 8) — one wall, every surface.

The quota logic lives in :mod:`graqle.licensing.reasoning_quota`; this module is the
single *enforcement point* that the SDK reasoning primitive calls on entry.

Why a middleware and not a CLI hook: the first W3 attempt (PR #316, CLOSED) placed the
wall in ``graqle/cli/main.py`` only. The MCP server's ``graq_reason`` tool, the chat
agent, and ``api.py`` all reach :meth:`graqle.core.graph.Graqle.areason` *without* going
through the CLI — so a primary surface had free unlimited reasoning. The rule that came
out of that review: **a wall at one surface is not a wall**. Enforce at the primitive.

``Graqle.areason()`` is the sole chokepoint — sync ``reason()`` delegates to it, and
``areason_batch()`` fans out to it per query — so gating ``areason`` alone covers every
caller exactly once. ``areason_batch`` deliberately does NOT gate: doing so would charge
a 5-query batch six times.

Exemption: ``internal=True`` — reasoning invoked *by* another metered action (a W2
PR-Guardian scan, a benchmark runner). Prevents W2/W3 double-charging one user action.
``internal=True`` is the ONLY exemption. A CI environment variable is deliberately not
honoured — ``export CI=true`` is self-attested and would be a one-line bypass of the
whole wall (sentinel BLOCKER-2). A 50-query benchmark stays free because the benchmark
runners pass ``internal=True`` in code, which an end user cannot set from outside.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("graqle.licensing.reasoning_gate")

__all__ = [
    "QUOTA_DIR_ENV",
    "check_reasoning_quota",
    "quota_exempt",
    "resolve_quota_dir",
]

# Test/bench override for the project-local quota directory.
QUOTA_DIR_ENV = "GRAQLE_QUOTA_DIR"

_DEFAULT_QUOTA_DIR = ".graqle"

def _under_pytest() -> bool:
    """True only when pytest is genuinely loaded in THIS process.

    Deliberately ``sys.modules``, not an environment variable. The first attempt at
    this guard used ``PYTEST_CURRENT_TEST``, which is itself a self-attested env var —
    it merely replaced one bypass with another, and was proven forgeable:
    ``PYTEST_CURRENT_TEST=fake::call GRAQLE_QUOTA_DIR=/tmp/x`` resolved to ``/tmp/x``.
    An attacker cannot import pytest into a process that never imported it, so
    ``sys.modules`` closes what an env check cannot.

    It is also the only correct answer for TIMING. ``PYTEST_CURRENT_TEST`` is set
    per-test (setup/call/teardown) and is absent during module import, collection, and
    session-scoped fixtures — measured: at import time it is ``False`` while
    ``"pytest" in sys.modules`` is already ``True``. With the env check, a test that
    resolved the quota dir at import or in a session fixture would have silently fallen
    through to the developer's REAL ``./.graqle`` and mutated their actual quota count.
    """
    return "pytest" in sys.modules or "_pytest" in sys.modules


def resolve_quota_dir() -> Path:
    """Project-local ``.graqle`` directory holding the quota file.

    ``GRAQLE_QUOTA_DIR`` relocates the meter, but ONLY under pytest.

    ⚠️ It is deliberately INERT in normal runs. Honouring it unconditionally made it a
    one-line unlimited-reasoning bypass of this very wall: a free user at the cap who
    exported ``GRAQLE_QUOTA_DIR=$(mktemp -d)`` got a fresh empty counter on every
    invocation. That is categorically worse than the local-bypass class ADR-245 already
    accepts (deleting ``.graqle/reasoning_quota.json``), on three counts — it persists
    via a shell profile so it is set once and never repeated, it is non-destructive so
    nothing looks tampered with, and it needs no repeat action.

    It also contradicted this module's own rule: :func:`quota_exempt` refuses to honour
    ``CI=true`` precisely because "self-attested env exemption" is banned by ADR-245
    Decision 8 rule 3. An env var that relocates the counter is the same bypass wearing
    a different hat. Tests still need to redirect the meter, so the override survives —
    scoped to a real pytest process, which a production run is not.
    """
    override = os.environ.get(QUOTA_DIR_ENV)
    if override and override.strip() and _under_pytest():
        return Path(override)
    return Path(_DEFAULT_QUOTA_DIR)


def quota_exempt(internal: bool) -> bool:
    """True when this reasoning call must be neither counted nor blocked.

    ``internal`` is the ONLY exemption. A CI environment variable is deliberately
    NOT honoured: ``export CI=true`` is self-attested and would be a one-line
    unlimited-reasoning bypass of the whole wall. Tooling that legitimately must not
    be metered (the benchmark runners, governance sub-calls) passes ``internal=True``
    at the callsite, which is code the user cannot set from the outside.
    """
    return bool(internal)


def check_reasoning_quota(*, internal: bool = False) -> None:
    """Enforce the monthly reasoning quota for ONE reasoning invocation.

    Parameters
    ----------
    internal:
        True when this reasoning is invoked by another metered action (W2 scan,
        benchmark runner, or an internal SDK self-call). Exempt: not counted, never
        blocked.

    Raises
    ------
    ReasoningQuotaExceeded
        when enforcement is on, the verified tier is FREE, and the monthly quota is
        spent. This is the ONLY exception this function propagates.

    Any other failure — a missing module, an unreadable quota file, a licensing
    error — is swallowed. Reasoning must never break because metering hiccuped.
    """
    if quota_exempt(internal):
        return

    # Imported lazily: graqle.core.graph imports this module, so a module-level import
    # of anything that reaches back into core would be circular.
    try:
        from graqle.licensing.reasoning_quota import ReasoningQuota, ReasoningQuotaExceeded
    except Exception as exc:  # noqa: BLE001 — metering unavailable → fail open
        # WARNING: an un-importable meter means the wall is off for this call.
        logger.warning(
            "reasoning quota module unavailable (%s) — allowing this call", exc
        )
        return

    try:
        ReasoningQuota(resolve_quota_dir()).check_and_record(internal=False)
    except ReasoningQuotaExceeded:
        # Must escape BEFORE the broad except below — this is the wall doing its job,
        # not a metering fault. Swallowing it here would silently disable W3.
        raise
    except Exception as exc:  # noqa: BLE001 — never break reasoning on a meter fault
        # WARNING, not debug: this branch grants un-metered reasoning. It must be
        # visible in logs, otherwise a corrupt quota file or a permissions problem
        # silently disables the wall with no operational signal.
        logger.warning(
            "reasoning quota could not be enforced (%s) — allowing this call", exc
        )
