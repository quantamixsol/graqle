#!/bin/bash
# CG-NATIVE-BYPASS: Block Claude Code native tools when graq_* equivalents exist.
# This hook enforces GraQle governance for external AI tools (Claude Code, Cursor, etc.)
# GraQle VS Code extension is never blocked — it sets GRAQLE_CLIENT_MODE=vscode.
#
# Protocol:
#   stdin  = JSON with tool_name, tool_input, cwd
#   exit 0 = ALLOW
#   exit 2 = BLOCK
set -e

json_input=$(cat)
tool_name=$(echo "$json_input" | jq -r '.tool_name // empty')

# ── EXEMPT: GraQle VS Code extension never blocked ──────────────
if [ "$GRAQLE_CLIENT_MODE" = "vscode" ]; then
  exit 0
fi

# ── EXEMPT: MCP tool calls (graq_*, kogni_*) pass through ───────
if [[ "$tool_name" == mcp__graqle__* ]] || [[ "$tool_name" == mcp__kogni__* ]]; then
  exit 0
fi

# ── EXEMPT: Tools with no graq_ equivalent ──────────────────────
case "$tool_name" in
  ToolSearch|AskUserQuestion|EnterPlanMode|ExitPlanMode)
    exit 0
    ;;
esac

# ── HARD BLOCK: Native tools with graq_ equivalents ─────────────
case "$tool_name" in
  Read)
    echo "GATE BLOCKED: Use graq_read instead of native Read. Native tools bypass all GraQle governance gates." >&2
    exit 2
    ;;
  Write)
    echo "GATE BLOCKED: Use graq_write instead of native Write. Native tools bypass all GraQle governance gates." >&2
    exit 2
    ;;
  Edit)
    echo "GATE BLOCKED: Use graq_edit instead of native Edit. Native tools bypass all GraQle governance gates." >&2
    exit 2
    ;;
  Bash)
    echo "GATE BLOCKED: Use graq_bash instead of native Bash. Native tools bypass all GraQle governance gates." >&2
    exit 2
    ;;
  Grep)
    echo "GATE BLOCKED: Use graq_grep instead of native Grep. Native tools bypass all GraQle governance gates." >&2
    exit 2
    ;;
  Glob)
    echo "GATE BLOCKED: Use graq_glob instead of native Glob. Native tools bypass all GraQle governance gates." >&2
    exit 2
    ;;
  WebSearch)
    echo "GATE BLOCKED: Use graq_web_search instead of native WebSearch. Native tools bypass all GraQle governance gates." >&2
    exit 2
    ;;
  Agent)
    echo "GATE BLOCKED: Use graq_reason instead of native Agent. Native tools bypass all GraQle governance gates." >&2
    exit 2
    ;;
  TodoWrite)
    echo "GATE BLOCKED: Use graq_todo instead of native TodoWrite. Native tools bypass all GraQle governance gates." >&2
    exit 2
    ;;
  WebFetch)
    echo "GATE BLOCKED: Native WebFetch blocked — graq_web_fetch not yet built. File a capability gap." >&2
    exit 2
    ;;
  NotebookEdit)
    echo "GATE BLOCKED: Native NotebookEdit blocked — graq_notebook_edit not yet built. File a capability gap." >&2
    exit 2
    ;;
esac

# ── DEFAULT: Unknown tools pass through ─────────────────────────
exit 0
