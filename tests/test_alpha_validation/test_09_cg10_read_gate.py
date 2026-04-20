"""ITEM 09 — CG-10 — Read gate (global scope — Claude Code hook side).

Acceptance:
1. BLOCKED_TOOLS contains "Read" → "graq_read"
2. Read payload blocked with non-zero exit (fail-closed)
3. graq_read is not in BLOCKED_TOOLS
4. Global scope: Grep / Glob / Write / Edit / Agent / TodoWrite also blocked
5. Write-class regex catches unknown write-alikes
"""

from __future__ import annotations

import importlib.util
import io
import json
import time
from pathlib import Path


def _load_hook():
    hook_path = (
        Path(__file__).resolve().parent.parent.parent
        / "graqle" / "data" / "claude_gate" / "graqle-gate.py"
    )
    spec = importlib.util.spec_from_file_location("graqle_gate_hook_09", hook_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _invoke(hook_mod, payload, monkeypatch):
    stdin_buf = io.StringIO(json.dumps(payload))
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    monkeypatch.setattr("sys.stdin", stdin_buf)
    monkeypatch.setattr("sys.stdout", stdout_buf)
    monkeypatch.setattr("sys.stderr", stderr_buf)
    return hook_mod.main()


def test_cg10_read_gate(record, monkeypatch):
    t0 = time.monotonic()
    assertions = 0
    evidence: dict = {}

    hook_mod = _load_hook()
    blocked = hook_mod.BLOCKED_TOOLS

    # --- 1. Read mapping ---
    assert blocked.get("Read") == "graq_read"
    assertions += 1
    evidence["read_mapped_to"] = blocked.get("Read")

    # --- 2. Native Read blocked ---
    rc = _invoke(hook_mod, {"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}}, monkeypatch)
    assert rc != 0, rc
    assertions += 1
    evidence["native_read_blocked_rc"] = rc

    # --- 3. graq_read is NOT blocked ---
    assert "graq_read" not in blocked
    assertions += 1

    # --- 4. Global-scope blocks ---
    global_scope = ["Grep", "Glob", "Write", "Edit", "Agent", "TodoWrite"]
    for tool in global_scope:
        assert tool in blocked, f"{tool} missing from BLOCKED_TOOLS"
    assertions += 1
    evidence["global_scope_blocked"] = global_scope

    # --- 5. Write-class regex catches unknown write-alikes ---
    pat = hook_mod._WRITE_CLASS_PATTERN
    for ident in ["WriteSomething", "Edit2", "ExecTool", "CreateFile"]:
        assert pat.match(ident), f"{ident} should match write-class regex"
    assertions += 1
    evidence["write_class_regex_ok"] = True

    record(
        item_id="09-cg10",
        name="CG-10 — Read gate + global-scope siblings",
        status="PASS",
        assertions=assertions,
        duration_ms=int((time.monotonic() - t0) * 1000),
        evidence=evidence,
    )
