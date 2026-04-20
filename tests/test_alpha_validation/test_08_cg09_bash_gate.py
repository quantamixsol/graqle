"""ITEM 08 — CG-09 — Bash gate (Claude Code hook side).

Acceptance:
1. BLOCKED_TOOLS contains "Bash" → "graq_bash"
2. Hook's main() blocks a Bash tool payload with non-zero exit
3. VS Code bypass env var lets the same payload through (exit 0)
4. graq_bash is NOT in BLOCKED_TOOLS (it's the sanctioned replacement)
"""

from __future__ import annotations

import importlib.util
import io
import json
import time
from pathlib import Path


def _load_hook():
    """Load graqle-gate.py (hyphen in name blocks normal import)."""
    hook_path = (
        Path(__file__).resolve().parent.parent.parent
        / "graqle" / "data" / "claude_gate" / "graqle-gate.py"
    )
    spec = importlib.util.spec_from_file_location("graqle_gate_hook", hook_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _invoke(hook_mod, payload: dict, monkeypatch, env_overrides=None):
    if env_overrides:
        for k, v in env_overrides.items():
            monkeypatch.setenv(k, v)
    stdin_buf = io.StringIO(json.dumps(payload))
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    monkeypatch.setattr("sys.stdin", stdin_buf)
    monkeypatch.setattr("sys.stdout", stdout_buf)
    monkeypatch.setattr("sys.stderr", stderr_buf)
    return hook_mod.main()


def test_cg09_bash_gate(record, monkeypatch):
    t0 = time.monotonic()
    assertions = 0
    evidence: dict = {}

    hook_mod = _load_hook()

    # --- 1. BLOCKED_TOOLS mapping ---
    blocked = hook_mod.BLOCKED_TOOLS
    assert blocked.get("Bash") == "graq_bash"
    assertions += 1
    evidence["bash_mapped_to"] = blocked.get("Bash")

    # --- 2. A native Bash payload is blocked ---
    rc = _invoke(hook_mod, {"tool_name": "Bash", "tool_input": {"command": "echo hi"}}, monkeypatch)
    assert rc != 0, f"expected block (non-zero exit), got {rc}"
    assertions += 1
    evidence["native_bash_blocked_rc"] = rc

    # --- 3. VS Code bypass returns 0 ---
    rc_bypass = _invoke(
        hook_mod,
        {"tool_name": "Bash", "tool_input": {"command": "echo hi"}},
        monkeypatch,
        env_overrides={"GRAQLE_CLIENT_MODE": "vscode"},
    )
    assert rc_bypass == 0, rc_bypass
    assertions += 1
    evidence["vscode_bypass_rc"] = rc_bypass

    # --- 4. graq_bash itself is not blocked ---
    assert "graq_bash" not in blocked
    assertions += 1
    evidence["graq_bash_not_blocked"] = True

    record(
        item_id="08-cg09",
        name="CG-09 — Bash gate (Claude hook)",
        status="PASS",
        assertions=assertions,
        duration_ms=int((time.monotonic() - t0) * 1000),
        evidence=evidence,
    )
