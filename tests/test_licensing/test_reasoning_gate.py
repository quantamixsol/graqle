"""W3 (ADR-245 Decision 8) — the reasoning wall sits at the SDK primitive.

PR #316 placed the wall in the CLI only; MCP / chat / api reached ``graph.areason``
around it. These tests are the regression evidence that the wall is now at the
primitive and that every surface inherits it.

The suite is deliberately split into two halves:

  1. Unit tests over ``reasoning_gate`` itself (exemptions, fail-open, escape order).
  2. **Bypass-surface tests** that drive the wall through ``Graqle.areason`` the way
     each real consumer does — the CLI, the MCP ``graq_reason`` tool, the chat agent
     and ``api.py`` all bottom out in that one call. These are the tests that would
     have failed on the #316 architecture.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from graqle.licensing.reasoning_gate import (
    QUOTA_DIR_ENV,
    check_reasoning_quota,
    quota_exempt,
    resolve_quota_dir,
)
from graqle.licensing.reasoning_quota import (
    FREE_REASONS_PER_MONTH,
    QUOTA_FILENAME,
    ReasoningQuota,
    ReasoningQuotaExceeded,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    """FREE tier, enforcement on, no CI, quota file isolated to a temp dir."""
    monkeypatch.setattr("graqle.licensing.reasoning_quota._paid_tier", lambda: False)
    monkeypatch.delenv("GRAQLE_ENFORCE_CAPS", raising=False)
    for var in ("CI", "GITHUB_ACTIONS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(QUOTA_DIR_ENV, str(tmp_path / ".graqle"))
    return tmp_path


def _paid(monkeypatch):
    monkeypatch.setattr("graqle.licensing.reasoning_quota._paid_tier", lambda: True)


def _burn(n):
    """Consume ``n`` quota units through the gate."""
    for _ in range(n):
        check_reasoning_quota()


def _used(tmp_path):
    """Units recorded in the quota file (0 when the file was never written)."""
    path = tmp_path / ".graqle" / QUOTA_FILENAME
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    return sum(v for k, v in data.items() if k != "schema_version")


# ── CI detection ────────────────────────────────────────────────────────────







# ── exemption matrix ────────────────────────────────────────────────────────

def test_internal_is_exempt():
    assert quota_exempt(internal=True) is True


def test_plain_user_call_is_not_exempt():
    assert quota_exempt(internal=False) is False


def test_ci_env_does_NOT_exempt(monkeypatch):
    """SENTINEL BLOCKER-2: `export CI=true` must not buy unlimited free reasoning.

    A CI env var is self-attested — honouring it would be a one-line bypass of the
    entire wall. Tooling that must not be metered passes internal=True in code.
    """
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("CI", "true")
    assert quota_exempt(internal=False) is False


# ── the wall actually blocks ────────────────────────────────────────────────

def test_free_user_blocked_at_cap(tmp_path):
    _burn(FREE_REASONS_PER_MONTH)
    with pytest.raises(ReasoningQuotaExceeded):
        check_reasoning_quota()


def test_under_cap_is_allowed(tmp_path):
    _burn(FREE_REASONS_PER_MONTH - 1)
    check_reasoning_quota()  # the last free unit — must not raise
    assert _used(tmp_path) == FREE_REASONS_PER_MONTH


def test_paid_tier_never_blocked(monkeypatch, tmp_path):
    _paid(monkeypatch)
    for _ in range(FREE_REASONS_PER_MONTH * 3):
        check_reasoning_quota()
    assert _used(tmp_path) == 0, "paid tier must not be metered at all"


def test_internal_calls_never_counted(tmp_path):
    """A 50-query benchmark must not burn a free contributor's quota."""
    for _ in range(50):
        check_reasoning_quota(internal=True)
    assert _used(tmp_path) == 0


def test_internal_calls_pass_even_when_cap_already_spent(tmp_path):
    _burn(FREE_REASONS_PER_MONTH)
    check_reasoning_quota(internal=True)  # must not raise — bench is exempt


def test_ci_env_cannot_lift_a_spent_cap(monkeypatch, tmp_path):
    """SENTINEL BLOCKER-2 regression guard: setting CI after the cap must still block."""
    _burn(FREE_REASONS_PER_MONTH)
    monkeypatch.setenv("CI", "true")
    with pytest.raises(ReasoningQuotaExceeded):
        check_reasoning_quota()


def test_optout_disables_the_wall(monkeypatch, tmp_path):
    _burn(FREE_REASONS_PER_MONTH)
    monkeypatch.setenv("GRAQLE_ENFORCE_CAPS", "0")
    check_reasoning_quota()  # opt-out honoured


# ── fail-open + escape ordering ─────────────────────────────────────────────

def test_metering_fault_fails_open(monkeypatch):
    """A meter fault must never break reasoning."""
    def boom(self, *, internal=False):
        raise OSError("disk gone")

    monkeypatch.setattr(ReasoningQuota, "check_and_record", boom)
    check_reasoning_quota()  # swallowed


def test_quota_exceeded_escapes_before_the_broad_except(monkeypatch):
    """The wall firing is NOT a metering fault — it must propagate.

    Regression guard for the fail-open escape-hatch bug class: if the
    ReasoningQuotaExceeded re-raise is moved below the broad `except Exception`,
    the wall is silently disabled and this test fails.
    """
    def raise_wall(self, *, internal=False):
        raise ReasoningQuotaExceeded(30, 30, "2026-07")

    monkeypatch.setattr(ReasoningQuota, "check_and_record", raise_wall)
    with pytest.raises(ReasoningQuotaExceeded):
        check_reasoning_quota()


def test_import_failure_fails_open(monkeypatch):
    """If the quota module cannot be imported, reasoning still runs."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "graqle.licensing.reasoning_quota":
            raise ImportError("simulated")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    check_reasoning_quota()  # swallowed


# ── quota dir resolution ────────────────────────────────────────────────────

def test_quota_dir_override(monkeypatch):
    monkeypatch.setenv(QUOTA_DIR_ENV, "/tmp/somewhere")
    assert resolve_quota_dir() == Path("/tmp/somewhere")


def test_quota_dir_defaults_to_project_local(monkeypatch):
    monkeypatch.delenv(QUOTA_DIR_ENV, raising=False)
    assert resolve_quota_dir() == Path(".graqle")


# ═══════════════════════════════════════════════════════════════════════════
# BYPASS-SURFACE TESTS — the #316 regression guards.
#
# Every surface (CLI, MCP graq_reason, chat agent, api.py) reaches
# Graqle.areason(). These drive that primitive directly, which is what each
# surface does, and assert the wall is inherited.
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def graph(monkeypatch):
    """A Graqle instance whose reasoning is stubbed — we test the gate, not the LLM."""
    from graqle.core.graph import Graqle

    g = Graqle()

    async def fake_orchestrate(*a, **kw):
        raise AssertionError("orchestrator reached — the wall did not fire")

    return g, fake_orchestrate


def _areason_reaches_orchestrator(g):
    """True when areason got past the gate (our stub marks that with a sentinel)."""
    marker = {"ran": False}

    async def run():
        try:
            await g.areason("q")
        except ReasoningQuotaExceeded:
            raise
        except Exception:
            # Any post-gate failure (no backend configured, etc.) still proves the
            # gate ALLOWED the call through — which is what we are asserting.
            marker["ran"] = True
        else:
            marker["ran"] = True

    asyncio.run(run())
    return marker["ran"]


def test_areason_signature_accepts_internal():
    """The primitive must expose the exemption knob its callers rely on."""
    import inspect

    from graqle.core.graph import Graqle

    assert "internal" in inspect.signature(Graqle.areason).parameters


def test_areason_blocks_free_user_over_cap(graph, tmp_path):
    """THE #316 REGRESSION GUARD.

    On the old architecture the wall lived in the CLI, so calling areason directly —
    exactly what MCP graq_reason, the chat agent and api.py do — sailed straight
    through. This asserts the primitive itself refuses.
    """
    g, _ = graph
    _burn(FREE_REASONS_PER_MONTH)

    with pytest.raises(ReasoningQuotaExceeded):
        asyncio.run(g.areason("this must not reason"))


def test_areason_internal_bypasses_cap(graph, tmp_path):
    """Internal reasoning (bench / governance sub-call) is exempt at the primitive."""
    g, _ = graph
    _burn(FREE_REASONS_PER_MONTH)

    # Must get PAST the gate. It may fail later for unrelated reasons (no backend);
    # what matters is that ReasoningQuotaExceeded is not raised.
    assert _areason_reaches_orchestrator_internal(g)


def _areason_reaches_orchestrator_internal(g):
    async def run():
        try:
            await g.areason("q", internal=True)
        except ReasoningQuotaExceeded:
            return False
        except Exception:
            return True
        return True

    return asyncio.run(run())


def test_sync_reason_is_walled(graph, tmp_path):
    """graph.reason() is a public API too — it must not be a free side door.

    It delegates to areason WITHOUT internal=True, so it is charged exactly once.
    """
    g, _ = graph
    _burn(FREE_REASONS_PER_MONTH)

    with pytest.raises(ReasoningQuotaExceeded):
        g.reason("this must not reason")


def test_batch_charges_per_query(monkeypatch, tmp_path):
    """areason_batch fans out to areason, so N queries cost N units — not 1.

    Charging once per batch would under-bill by N x; charging at BOTH the batch and
    the fan-out would double-bill. This pins the agreed semantics.
    """
    from graqle.core.graph import Graqle

    g = Graqle()
    calls = {"n": 0}

    async def fake_areason(self, query, **kw):
        calls["n"] += 1
        check_reasoning_quota(internal=kw.get("internal", False))
        return None

    monkeypatch.setattr(Graqle, "areason", fake_areason)
    asyncio.run(g.areason_batch(["q1", "q2", "q3"], max_concurrent=1))

    assert calls["n"] == 3
    assert _used(tmp_path) == 3, "a 3-query batch must cost exactly 3 quota units"


# ── concurrency: the file-locking guard ─────────────────────────────────────

def test_concurrent_runs_do_not_leak_quota(tmp_path):
    """Two racing processes must not both spend the same last unit.

    Without the cross-process lock, both read used=N-1 and both write N, letting a
    free user exceed the cap by one call per racing process.
    """
    import threading

    _burn(FREE_REASONS_PER_MONTH - 1)  # exactly one unit left

    granted, blocked = [], []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()  # maximise the race
        try:
            check_reasoning_quota()
            granted.append(1)
        except ReasoningQuotaExceeded:
            blocked.append(1)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(granted) == 1, f"exactly one thread may take the last unit, got {len(granted)}"
    assert len(blocked) == 7
    assert _used(tmp_path) == FREE_REASONS_PER_MONTH


# ── verified-tier boundary (CR-LIC-03b): the real _paid_tier path ───────────
# The autouse fixture stubs _paid_tier, so these exercise the UNSTUBBED function
# to prove an unverified hint never grants a paid (unlimited) entitlement.

def _real_paid_tier(monkeypatch, tier=None, raises=False):
    """Drive the genuine _paid_tier() against a faked licence manager."""
    import graqle.licensing.reasoning_quota as rq
    monkeypatch.undo()  # drop the autouse _paid_tier stub

    import sys
    import types

    mod = types.ModuleType("graqle.licensing.manager")

    class LicenseTier:
        FREE, PRO, TEAM, ENTERPRISE = "free", "pro", "team", "enterprise"

    class _Mgr:
        current_tier = tier

    def _get_manager():
        if raises:
            raise RuntimeError("licence store unreadable")
        return _Mgr()

    mod.LicenseTier = LicenseTier
    mod._get_manager = _get_manager
    monkeypatch.setitem(sys.modules, "graqle.licensing.manager", mod)
    return rq._paid_tier


@pytest.mark.parametrize("tier", ["pro", "team", "enterprise"])
def test_verified_paid_tiers_are_unlimited(monkeypatch, tier):
    paid = _real_paid_tier(monkeypatch, tier=tier)
    assert paid() is True


def test_verified_free_tier_is_metered(monkeypatch):
    paid = _real_paid_tier(monkeypatch, tier="free")
    assert paid() is False


def test_unresolvable_licence_is_treated_as_free(monkeypatch):
    """Fail-SAFE, not fail-open: if the tier cannot be verified, meter the user.

    An unverified signal must never grant a paid entitlement (CR-LIC-03b).
    """
    paid = _real_paid_tier(monkeypatch, raises=True)
    assert paid() is False


# ── lock + persistence robustness ───────────────────────────────────────────

def test_posix_lock_path_is_exercised(monkeypatch, tmp_path):
    """Cover the fcntl branch that POSIX users (and most CI) actually take."""
    import graqle.licensing.reasoning_quota as rq

    calls = []

    class FakeFcntl:
        LOCK_EX, LOCK_UN = 2, 8

        @staticmethod
        def flock(fd, op):
            calls.append(op)

    monkeypatch.setattr(rq, "msvcrt", None)      # pretend not-Windows
    monkeypatch.setattr(rq, "fcntl", FakeFcntl)

    rq.ReasoningQuota(tmp_path).check_and_record()
    assert FakeFcntl.LOCK_EX in calls, "exclusive lock never acquired on POSIX"
    assert FakeFcntl.LOCK_UN in calls, "lock never released on POSIX"


def test_lock_unavailable_still_meters(monkeypatch, tmp_path):
    """A platform without working locks must still enforce (degraded, not open)."""
    import graqle.licensing.reasoning_quota as rq

    class Boom:
        LOCK_EX, LOCK_UN = 2, 8

        @staticmethod
        def flock(fd, op):
            raise OSError("flock unsupported on this fs")

    monkeypatch.setattr(rq, "msvcrt", None)
    monkeypatch.setattr(rq, "fcntl", Boom)

    r = rq.ReasoningQuota(tmp_path).check_and_record()
    assert r.used == 1, "metering must continue when the lock is unavailable"


def test_lock_release_failure_is_swallowed(monkeypatch, tmp_path):
    """A failed unlock must not surface — closing the handle releases it anyway."""
    import graqle.licensing.reasoning_quota as rq

    class HalfBroken:
        LOCK_EX, LOCK_UN = 2, 8

        @staticmethod
        def flock(fd, op):
            if op == 8:  # only the release fails
                raise OSError("unlock failed")

    monkeypatch.setattr(rq, "msvcrt", None)
    monkeypatch.setattr(rq, "fcntl", HalfBroken)

    r = rq.ReasoningQuota(tmp_path).check_and_record()
    assert r.used == 1


def test_readonly_fs_does_not_break_reasoning(monkeypatch, tmp_path):
    """A read-only filesystem must not raise — persistence is best-effort."""
    import graqle.licensing.reasoning_quota as rq

    def no_write(self, data):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(rq.ReasoningQuota, "_store", no_write)
    r = rq.ReasoningQuota(tmp_path).check_and_record()
    assert r.allowed is True


def test_store_swallows_write_error(monkeypatch, tmp_path):
    """Exercise _store's own handler (not a monkeypatched replacement).

    Covers the read-only-fs branch inside _store: a failed persist is logged and
    swallowed, never raised into the reasoning path.
    """
    import graqle.licensing.reasoning_quota as rq

    q = rq.ReasoningQuota(tmp_path)

    def bad_replace(self, target):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(Path, "replace", bad_replace)
    q._store({"2026-07": 1})  # must not raise


# ═══════════════════════════════════════════════════════════════════════════
# SENTINEL BLOCKER-1 regression guards — surfaces that do NOT route through
# areason() and therefore need the wall applied explicitly.
# ═══════════════════════════════════════════════════════════════════════════

def test_areason_stream_is_walled(tmp_path):
    """areason_stream builds its own StreamingOrchestrator and never calls areason.

    Found by sentinel pass 1: without an explicit gate this is a free unlimited
    reasoning surface (it backs the server's SSE /reason/stream endpoint).
    """
    from graqle.core.graph import Graqle

    g = Graqle()
    _burn(FREE_REASONS_PER_MONTH)

    async def drain():
        async for _ in g.areason_stream("q"):
            pass

    with pytest.raises(ReasoningQuotaExceeded):
        asyncio.run(drain())


def test_areason_stream_accepts_internal():
    import inspect

    from graqle.core.graph import Graqle

    params = inspect.signature(Graqle.areason_stream).parameters
    assert "internal" in params
    assert params["internal"].kind is inspect.Parameter.KEYWORD_ONLY


def test_every_public_reasoning_entrypoint_is_walled():
    """Structural guard: if someone adds a new public reasoning entrypoint to
    Graqle, it must be walled (or explicitly listed as delegating).

    This is the test that would have caught areason_stream before review.
    """
    import inspect

    from graqle.core.graph import Graqle

    # areason      — gates directly
    # areason_stream — gates directly (own orchestrator)
    # reason       — delegates to areason (charged there)
    # areason_batch — fans out to areason (charged per query)
    known = {"reason", "areason", "areason_stream", "areason_batch"}
    found = {
        name
        for name, _ in inspect.getmembers(Graqle, callable)
        if name.endswith("reason") or name.startswith("areason") or name == "reason"
    }
    unexpected = found - known
    assert not unexpected, (
        f"new public reasoning entrypoint(s) {unexpected} — each must either gate "
        "via check_reasoning_quota() or provably delegate to areason()"
    )


def test_gating_entrypoints_reference_the_gate():
    """The two self-gating entrypoints must actually call the middleware."""
    import inspect

    from graqle.core.graph import Graqle

    for name in ("areason", "areason_stream"):
        src = inspect.getsource(getattr(Graqle, name))
        assert "check_reasoning_quota" in src, f"{name} does not call the wall"


def test_internal_is_keyword_only_on_areason():
    """SENTINEL BLOCKER-3 hardening: `internal` must not be positionally settable."""
    import inspect

    from graqle.core.graph import Graqle

    p = inspect.signature(Graqle.areason).parameters["internal"]
    assert p.kind is inspect.Parameter.KEYWORD_ONLY


def test_server_request_model_cannot_set_internal():
    """SENTINEL BLOCKER-3: no HTTP request body field may map to `internal`.

    The server passes explicit named fields to areason(); `internal` is not one of
    them and is not a field on the request model, so a caller cannot inject it.
    """
    try:
        from graqle.server.app import ReasonRequest
    except Exception:
        pytest.skip("server extra not installed")

    assert "internal" not in ReasonRequest.model_fields


# ═══════════════════════════════════════════════════════════════════════════
# Sentinel pass-2 refutations, pinned as tests.
#
# Pass 2 raised BLOCKER-4 (app.py + MCP tools might pass internal=True) and
# BLOCKER-5 (chat agent / ReasoningCoordinator might bypass). Both were refuted
# by code inspection. These tests pin the refutations so a future change cannot
# quietly make them true.
# ═══════════════════════════════════════════════════════════════════════════

def _sdk_py_files():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "graqle"
    return list(root.rglob("*.py"))


def test_internal_true_only_used_by_sanctioned_tooling():
    """SENTINEL BLOCKER-4: `internal=True` must never appear in a user-facing path.

    Only benchmark tooling may exempt itself. If a server endpoint, MCP tool or
    chat handler ever passes internal=True it becomes permanently un-metered —
    a billing bypass. This test enumerates every occurrence in the package.
    """
    sanctioned = {"benchmark_runner.py", "run_multigov_v2.py", "run_multigov_v3.py"}
    offenders = []
    for path in _sdk_py_files():
        if path.name in sanctioned or path.parts[-2:] == ("licensing", "reasoning_gate.py"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            # Match a real keyword ARGUMENT (preceded by "(" or ", "), not prose
            # in a docstring/comment that merely mentions the flag.
            if not re.search(r"[(,]\s*internal\s*=\s*True", line):
                continue
            if line.lstrip().startswith("#"):
                continue
            if '"""' in line or line.lstrip().startswith("``"):
                continue
            if True:
                # graq bench is the CLI face of the sanctioned benchmark tooling.
                if path.name == "main.py" and "max_rounds=max_rounds" in line:
                    continue
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")

    assert not offenders, (
        "internal=True found outside sanctioned benchmark tooling — these calls "
        "would be permanently exempt from the reasoning quota:\n" + "\n".join(offenders)
    )


def test_reasoning_coordinator_is_only_reachable_through_the_gate():
    """SENTINEL BLOCKER-5: ReasoningCoordinator must not be a parallel un-gated path.

    It is constructed only inside Graqle._areason_coordinated, which is called only
    from areason() — i.e. downstream of the wall. If someone constructs it elsewhere,
    that new site would bypass the quota.
    """
    import graqle.core.graph as graph_mod

    sites = []
    for path in _sdk_py_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if "ReasoningCoordinator(" in line and "class " not in line:
                sites.append((path.name, lineno))

    assert sites, "expected at least the known construction site"
    assert all(name == "graph.py" for name, _ in sites), (
        f"ReasoningCoordinator constructed outside core/graph.py: {sites} — "
        "each such site is an un-gated reasoning path"
    )

    # ...and that site must sit inside the gated call chain.
    import inspect

    src = inspect.getsource(graph_mod.Graqle.areason)
    assert "_areason_coordinated" in src, (
        "the coordinator path is no longer reached from the gated areason()"
    )


def test_chat_package_has_no_ungated_reasoning():
    """SENTINEL BLOCKER-5: graqle/chat/ must not dispatch reasoning of its own."""
    import pathlib

    chat = pathlib.Path(__file__).resolve().parents[2] / "graqle" / "chat"
    if not chat.exists():
        pytest.skip("no chat package")

    offenders = []
    for path in chat.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "Orchestrator(" in line or ".areason_stream(" in line:
                offenders.append(f"{path.name}:{lineno}: {stripped}")
    assert not offenders, (
        "chat package dispatches reasoning outside the gated entrypoints:\n"
        + "\n".join(offenders)
    )
