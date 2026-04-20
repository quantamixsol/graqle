"""ITEM 13 — Smoke roundtrip: full chain spanning multiple Wave 1 gaps.

This item is the integration proof. It exercises:

1. SDK-B1 — graq init scaffolds GRAQ.md for a python project
2. CG-17 — graq_memory op=write lands a memory file
3. ADR-206 — is_fast_path_candidate approves a safe .md create
4. CG-11 — graq_bash "git status" is routed to graq_git_status
5. G3 — graq_vsce_check validates an invalid semver (no network needed)

All five surfaces must work in a single test run from a single fresh
server, end-to-end, with no violations and no crashes.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_smoke_full_roundtrip(server_with_plan, record, tmp_path, monkeypatch):
    t0 = time.monotonic()
    assertions = 0
    evidence: dict = {}

    # === 1. SDK-B1 — graq init scaffold ===
    from graqle.cli.commands.init import write_graq_md
    ws = tmp_path / "roundtrip_project"
    ws.mkdir()
    (ws / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    assert write_graq_md(ws) is True
    graq_md = ws / "GRAQ.md"
    assert graq_md.exists()
    assertions += 1
    evidence["init_ok"] = True

    # === 2. CG-17 — memory write ===
    fake_home = tmp_path / "home"
    project_memory = fake_home / ".claude" / "projects" / "smoke_demo" / "memory"
    project_memory.mkdir(parents=True)
    (project_memory / "MEMORY.md").write_text("# Memory Index\n\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))

    mem_file = project_memory / "feedback_smoke_demo.md"
    mem_raw = await server_with_plan.handle_tool(
        "graq_memory",
        {
            "op": "write",
            "file": str(mem_file),
            "content": "Demo smoke content.",
            "name": "smoke demo",
            "description": "smoke-test memory entry",
            "type": "feedback",
        },
    )
    mem = json.loads(mem_raw) if isinstance(mem_raw, str) else mem_raw
    assert mem.get("ok") is True, mem
    assertions += 1
    evidence["memory_write_ok"] = True

    # === 3. ADR-206 — fast-path approves safe .md create ===
    from graqle.chat.fast_path import is_fast_path_candidate
    candidate = is_fast_path_candidate("create a file demo.md", ws)
    assert candidate is not None
    assertions += 1
    evidence["fast_path_ok"] = True

    # === 4. CG-11 — git gate routes ===
    git_raw = await server_with_plan.handle_tool(
        "graq_bash",
        {"command": "git status"},
    )
    git = json.loads(git_raw) if isinstance(git_raw, str) else git_raw
    assert git.get("error") == "CG-11_GIT_GATE"
    assert git.get("remediation") == "graq_git_status"
    assertions += 1
    evidence["git_gate_ok"] = True

    # === 5. G3 — vsce check rejects bad semver ===
    vsce_raw = await server_with_plan.handle_tool(
        "graq_vsce_check",
        {"version": "not-real"},
    )
    vsce = json.loads(vsce_raw) if isinstance(vsce_raw, str) else vsce_raw
    assert vsce.get("ok") is False
    assert vsce.get("error") == "INVALID_VERSION"
    assertions += 1
    evidence["vsce_fail_closed_ok"] = True

    record(
        item_id="13-smoke",
        name="Smoke — full roundtrip (5 surfaces in one server)",
        status="PASS",
        assertions=assertions,
        duration_ms=int((time.monotonic() - t0) * 1000),
        evidence=evidence,
    )
