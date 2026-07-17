#!/usr/bin/env python3
"""GraQle governance gate — packaged Claude Code plugin hook (PreToolUse).

Plugin variant of the gate installed by `graq gate-install`. Because a plugin
hook activates for everyone who installs the plugin, this variant is ADVISORY
by default and only blocks when explicitly opted in.

Modes (GRAQLE_GATE_MODE env var):
  warn     (default) — advisory: prints guidance to stderr, never blocks
  enforce            — fail-closed: blocks native tools that have graq_ equivalents
  off                — gate disabled entirely

Protocol:
  stdin  = JSON with tool_name, tool_input, cwd
  exit 0 = ALLOW
  exit 2 = BLOCK (enforce mode only)
"""

from __future__ import annotations

import json
import os
import re
import sys

ALLOWED_TOOLS = {"ToolSearch", "AskUserQuestion", "EnterPlanMode", "ExitPlanMode", "Skill"}

# Unknown-tool fail-closed heuristic: any unknown tool whose name matches this
# regex is treated as write-class. In enforce mode it is blocked by default so
# new native write tools cannot silently bypass the gate; unknown read-class
# tools always fall through to allow.
_WRITE_CLASS_PATTERN = re.compile(
    r"^(Write|Edit|Delete|Exec|Run|Create|Update|Put|Post)", re.IGNORECASE
)

BLOCKED_TOOLS = {
    "Read": "graq_read",
    "Write": "graq_write",
    "Edit": "graq_edit",
    "Bash": "graq_bash",
    "Grep": "graq_grep",
    "Glob": "graq_glob",
    "WebSearch": "graq_web_search",
    "Agent": "graq_reason",
    "TodoWrite": "graq_todo",
}

CAPABILITY_GAP_TOOLS = {"WebFetch", "NotebookEdit"}


def _mode() -> str:
    mode = os.environ.get("GRAQLE_GATE_MODE", "warn").strip().lower()
    if mode not in {"warn", "enforce", "off"}:
        mode = "warn"
    return mode


def _verdict(message: str, mode: str) -> int:
    """In enforce mode a gate hit blocks (exit 2); in warn mode it advises (exit 0)."""
    if mode == "enforce":
        print(f"GATE BLOCKED: {message}", file=sys.stderr)
        return 2
    print(f"graqle-gate (advisory): {message}", file=sys.stderr)
    return 0


def main() -> int:
    mode = _mode()
    if mode == "off":
        return 0

    # GraQle VS Code extension bypass (documented in README). This is an
    # env-declared client signal, not a security boundary — client-side gates
    # are advisory outside enforce-mode Claude Code; kept for parity with the
    # `graq gate-install` gate.
    if os.environ.get("GRAQLE_CLIENT_MODE") == "vscode":
        return 0

    # Parse stdin — fail closed on any error (enforce mode only)
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError) as exc:
        return _verdict(f"invalid JSON payload: {exc}", mode)

    if not isinstance(payload, dict):
        return _verdict("invalid payload type; expected JSON object", mode)

    tool_name = payload.get("tool_name")
    if not isinstance(tool_name, str):
        return _verdict("invalid tool_name; expected string", mode)

    # GraQle MCP tools always pass through. `kogni_*` is the public legacy
    # alias family for the same `graq_*` tools on the same server (CogniGraph
    # heritage) — not a separate surface.
    if tool_name.startswith("mcp__graqle__") or tool_name.startswith("mcp__kogni__"):
        return 0

    # Explicitly allowed tools
    if tool_name in ALLOWED_TOOLS:
        return 0

    # Native tools with graq_ equivalents
    if tool_name in BLOCKED_TOOLS:
        return _verdict(
            f"Use {BLOCKED_TOOLS[tool_name]} instead of native {tool_name}. "
            f"Native tools bypass GraQle governance gates.",
            mode,
        )

    # Capability-gap tools — flagged but no equivalent yet
    if tool_name in CAPABILITY_GAP_TOOLS:
        return _verdict(
            f"Native {tool_name} has no graq_ equivalent yet. File a capability gap.",
            mode,
        )

    # Unknown write-class tools
    if _WRITE_CLASS_PATTERN.match(tool_name):
        return _verdict(
            f"Unknown write-class tool '{tool_name}'. "
            f"File a capability gap if this tool has a legitimate use.",
            mode,
        )
    return 0  # Unknown read-class tool: allow


if __name__ == "__main__":
    raise SystemExit(main())
