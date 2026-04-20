"""ITEM 01 — CG-17 / G1 — graq_memory + memory-write gate.

Acceptance:
1. `graq_memory op=write` writes a memory file + updates MEMORY.md.
2. `graq_memory op=read` returns the written content + frontmatter.
3. Write to a path OUTSIDE the memory root is rejected (CG-17 gate).
"""

from __future__ import annotations

import json
import time

import pytest


@pytest.mark.asyncio
async def test_cg17_memory_gate(server_with_plan, record, tmp_path, monkeypatch):
    t0 = time.monotonic()
    assertions = 0
    evidence: dict = {}

    # Build a valid memory layout: <home>/.claude/projects/<proj>/memory/<file>.md
    fake_home = tmp_path / "home"
    project_memory = fake_home / ".claude" / "projects" / "alpha_demo" / "memory"
    project_memory.mkdir(parents=True)
    (project_memory / "MEMORY.md").write_text("# Memory Index\n\n", encoding="utf-8")

    # Redirect HOME (POSIX) and USERPROFILE (Windows) so realpath lands in tmp
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))

    mem_file = project_memory / "feedback_alpha_demo.md"

    # --- 1. graq_memory op=write succeeds ---
    resp_raw = await server_with_plan.handle_tool(
        "graq_memory",
        {
            "op": "write",
            "file": str(mem_file),
            "content": "---\nname: alpha demo\ndescription: synthetic fact for alpha validation\ntype: feedback\n---\n\nDemo rule: alpha harness verifies governance gates.\n",
            "name": "alpha demo",
            "description": "synthetic fact for alpha validation",
            "type": "feedback",
        },
    )
    resp = json.loads(resp_raw) if isinstance(resp_raw, str) else resp_raw
    assert resp.get("ok") is True, resp
    assertions += 1
    evidence["memory_path_written"] = resp.get("path", str(mem_file))

    # --- 2. Read-back round trip ---
    rb_raw = await server_with_plan.handle_tool(
        "graq_memory",
        {"op": "read", "file": str(mem_file)},
    )
    rb = json.loads(rb_raw) if isinstance(rb_raw, str) else rb_raw
    assert rb.get("ok") is True, rb
    assert "Demo rule" in rb.get("content", ""), rb
    assertions += 1
    evidence["read_back_ok"] = True

    # --- 3. CG-17 gate: write to path OUTSIDE memory root is rejected ---
    bad_path = tmp_path / "not_under_home.md"
    bad_raw = await server_with_plan.handle_tool(
        "graq_memory",
        {
            "op": "write",
            "file": str(bad_path),
            "content": "x",
            "name": "x",
            "description": "x",
            "type": "feedback",
        },
    )
    bad = json.loads(bad_raw) if isinstance(bad_raw, str) else bad_raw
    assert bad.get("ok") is False, bad
    assert bad.get("error") in ("PATH_OUTSIDE_MEMORY_ROOT", "INVALID_FILE"), bad
    assertions += 1
    evidence["outside_root_rejected"] = True
    evidence["reject_error"] = bad.get("error")

    record(
        item_id="01-cg17",
        name="CG-17 / G1 — graq_memory + memory-write gate",
        status="PASS",
        assertions=assertions,
        duration_ms=int((time.monotonic() - t0) * 1000),
        evidence=evidence,
    )
