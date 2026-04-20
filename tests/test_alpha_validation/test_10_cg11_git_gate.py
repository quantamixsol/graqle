"""ITEM 10 — CG-11 — Git gate (MCP dispatcher routes `git <subcmd>` to graq_git_*).

Acceptance:
1. graq_bash with `git status` is blocked with remediation = graq_git_status
2. graq_bash with `git commit -m 'x'` → remediation = graq_git_commit
3. graq_bash with `git push origin main` is NOT blocked (no graq_git_push)
4. Shell wrappers (sudo, env VAR=VAL) are stripped before gate evaluation
5. `git -C /path status` resolves to `status` subcommand
"""

from __future__ import annotations

import json
import time

import pytest


async def _call_bash(server, command: str):
    raw = await server.handle_tool("graq_bash", {"command": command})
    return json.loads(raw) if isinstance(raw, str) else raw


@pytest.mark.asyncio
async def test_cg11_git_gate(server_with_plan, record):
    t0 = time.monotonic()
    assertions = 0
    evidence: dict = {}

    # --- 1. git status is routed ---
    r1 = await _call_bash(server_with_plan, "git status")
    assert r1.get("error") == "CG-11_GIT_GATE", r1
    assert r1.get("remediation") == "graq_git_status"
    assertions += 1
    evidence["status_routed_to"] = r1.get("remediation")

    # --- 2. git commit is routed ---
    r2 = await _call_bash(server_with_plan, "git commit -m 'demo'")
    assert r2.get("error") == "CG-11_GIT_GATE", r2
    assert r2.get("remediation") == "graq_git_commit"
    assertions += 1
    evidence["commit_routed_to"] = r2.get("remediation")

    # --- 3. git push is NOT intercepted (no graq_git_push) ---
    r3 = await _call_bash(server_with_plan, "git push origin main")
    # Either executes or returns a non-CG-11 error — key assertion: NOT routed
    assert r3.get("error") != "CG-11_GIT_GATE", r3
    assertions += 1
    evidence["push_passthrough"] = True

    # --- 4. Shell-wrapper stripping: sudo git status ---
    r4 = await _call_bash(server_with_plan, "sudo git status")
    assert r4.get("error") == "CG-11_GIT_GATE", r4
    assert r4.get("subcommand") == "status"
    assertions += 1
    evidence["sudo_wrapper_stripped"] = True

    # --- 5. env VAR=VAL git status ---
    r5 = await _call_bash(server_with_plan, "env FOO=1 BAR=2 git status")
    assert r5.get("error") == "CG-11_GIT_GATE", r5
    assertions += 1
    evidence["env_wrapper_stripped"] = True

    # --- 6. git -C <path> status routes correctly ---
    r6 = await _call_bash(server_with_plan, "git -C /tmp/repo status")
    assert r6.get("error") == "CG-11_GIT_GATE", r6
    assert r6.get("subcommand") == "status"
    assertions += 1
    evidence["git_C_path_stripped"] = True

    record(
        item_id="10-cg11",
        name="CG-11 — Git gate (graq_bash → graq_git_*)",
        status="PASS",
        assertions=assertions,
        duration_ms=int((time.monotonic() - t0) * 1000),
        evidence=evidence,
    )
