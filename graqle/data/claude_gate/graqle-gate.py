#!/usr/bin/env python3
# graqle-gate version: {{GRAQLE_VERSION}}
"""Claude Code PreToolUse governance gate for GraQle.

Installed by `graq gate-install`. Remove .claude/hooks/graqle-gate.py to disable.
GraQle VS Code extension is never blocked (GRAQLE_CLIENT_MODE=vscode).

Protocol:
  stdin  = JSON with tool_name, tool_input, cwd
  exit 0 = ALLOW
  exit 2 = BLOCK (fail closed)
"""

from __future__ import annotations

import json
import os
import re
import sys

ALLOWED_TOOLS = {"ToolSearch", "AskUserQuestion", "EnterPlanMode", "ExitPlanMode", "Skill"}

# Unknown-tool fail-closed heuristic v0.50.1):
# Any unknown tool whose name matches this regex is treated as write-class
# and blocked by default. Unknown read-class tools still fall through to
# allow (exit 0). This prevents new Claude Code write tools from silently
# bypassing the gate.
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


def main() -> int:
    # VS Code extension bypass
    if os.environ.get("GRAQLE_CLIENT_MODE") == "vscode":
        return 0

    # Parse stdin — fail closed on any error
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"graqle-gate: invalid JSON payload: {exc}", file=sys.stderr)
        return 2

    if not isinstance(payload, dict):
        print("graqle-gate: invalid payload type; expected JSON object", file=sys.stderr)
        return 2

    tool_name = payload.get("tool_name")
    if not isinstance(tool_name, str):
        print("graqle-gate: invalid tool_name; expected string", file=sys.stderr)
        return 2

    # GraQle MCP tools always pass through
    if tool_name.startswith("mcp__graqle__") or tool_name.startswith("mcp__kogni__"):
        return 0

    # Explicitly allowed tools
    if tool_name in ALLOWED_TOOLS:
        return 0

    # Blocked native tools with graq_ equivalents
    if tool_name in BLOCKED_TOOLS:
        print(
            f"GATE BLOCKED: Use {BLOCKED_TOOLS[tool_name]} instead of native {tool_name}. "
            f"Native tools bypass all GraQle governance gates.",
            file=sys.stderr,
        )
        return 2

    # Capability gap tools — blocked but no equivalent yet
    if tool_name in CAPABILITY_GAP_TOOLS:
        print(
            f"GATE BLOCKED: Native {tool_name} blocked — no graq_ equivalent yet. "
            f"File a capability gap.",
            file=sys.stderr,
        )
        return 2

    # Unknown tools: fail-closed for write-class heuristics, allow read-class.
    # Prevents new Claude Code write tools (or renamed ones) from silently
    # bypassing the gate. File a capability gap to get a real graq_ equivalent.
    if _WRITE_CLASS_PATTERN.match(tool_name):
        print(
            f"GATE BLOCKED: Unknown write-class tool '{tool_name}' fail-closed. "
            f"File a capability gap if this tool has a legitimate use.",
            file=sys.stderr,
        )
        return 2
    return 0  # Unknown read-class tool: allow


if __name__ == "__main__":
    raise SystemExit(main())
