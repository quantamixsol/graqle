# VS Code Extension Team Handoff — graqle-vscode v0.4.0

**Date:** 2026-04-12
**From:** SDK team (graqle v0.51.0 release)
**To:** VS Code extension team (graqle-vscode)
**Reference:** ADR-154 (`.gsm/decisions/ADR-154-vscode-extension-integration-spec.md`)

---

## What the SDK team shipped for you

### v0.50.1 (already on PyPI)

| Feature | CLI command | MCP tool | Status |
|---|---|---|---|
| Windows Python interpreter probe | `graq gate-install` | built into installer | SHIPPED |
| Gate post-install self-test | `graq gate-install` | built into installer | SHIPPED |
| Unknown write-class tool fail-closed heuristic | (hook logic) | (hook logic) | SHIPPED |
| `graq init` auto-installs gate when Claude Code detected | `graq init` | N/A | SHIPPED |
| `from graqle import *` fix | N/A | N/A | SHIPPED |
| Chat floor template sanitized | N/A | N/A | SHIPPED |
| TCG seed sanitized (67/20/8/20/171 preserved) | N/A | N/A | SHIPPED |
| Distribution-lint regression guard | `pytest tests/test_distribution/` | N/A | SHIPPED |

### v0.51.0 (in PR, ready to ship after merge + tag)

| Feature | CLI command | MCP tool equivalent | Status |
|---|---|---|---|
| Gate health status reporting | `graq gate-status [--json]` | `graq_gate_status` (MCP wrapper TBD) | READY |
| Distribution lint as CLI | `graq lint-public [--json]` | `graq_lint_public_disclosure` (MCP wrapper TBD) | READY |
| 6 governance robustness fixes | N/A | N/A | READY |
| Systematic sanitization (baseline 381 -> 0) | N/A | N/A | READY |
| `graq_write` new-file allowlist (CG-03 carve-out) | N/A | built into MCP server | READY |
| ADR-154 integration spec | N/A | N/A | READY |

### Not yet shipped (deferred to v0.51.x follow-up)

| Feature | Blocker | Priority |
|---|---|---|
| `graq_route` (TCG intent -> tool recommendation) | Implementation only | HIGH — needed for Layer 3 chat routing chip |
| `graq_chat_session_trace` (RCAG ledger reader) | Implementation only | MEDIUM |
| `graq_cgi_task` (CGI Task CRUD) | CGI storage decision needed | HIGH — needed for Layer 4 Tasks view |
| `graq_cgi_checkpoint` (session handoff) | CGI storage decision needed | HIGH — needed for Layer 4 |
| `graq_dogfood_smoke` (12-point smoke) | Implementation only | LOW |

---

## What the extension team should build first

### Week 1 — Layer 1 + Layer 2 (ship as v0.4.0-alpha1)

**Layer 1: SDK handshake**
1. On activation, locate Python via the same probe order the SDK uses: `sys.executable`, `python3`, `python`, `py -3`.
2. Run `python -c "from graqle import __version__; print(__version__)"` and parse.
3. If version < 0.51.0: show modal offering upgrade.
4. Send `graq_lifecycle(event="session_start")` via MCP. Store the returned session ID.
5. Call `graq_inspect(stats=true)` and render nodes/edges/components in the status bar.

**Layer 2: Gate health chip**
1. Call `graq gate-status --json` (or future MCP `graq_gate_status`) to get the full status object.
2. Render status bar chip: green ENFORCING / yellow INSTALLED_NOT_ENFORCING / red NOT_INSTALLED.
3. Click chip -> run `graq gate-install --force` via child_process if not installed.
4. Click chip -> run `graq gate-install --fix-interpreter` if interpreter invalid.

**The `graq gate-status --json` contract is:**
```json
{
  "installed": true,
  "enforcing": true,
  "interpreter": "python3",
  "interpreter_valid": true,
  "self_test": {
    "exit_code": 2,
    "stderr_snippet": "GATE BLOCKED: Use graq_bash instead...",
    "passed": true,
    "ran_at": "2026-04-12T07:32:03.735214+00:00"
  },
  "hook_path": "/path/to/.claude/hooks/graqle-gate.py",
  "settings_path": "/path/to/.claude/settings.json"
}
```

### Week 2 — Layer 3 chat routing (after `graq_route` ships)

1. Register `@graqle` ChatParticipant.
2. Each message -> `graq_context(deep)` -> `graq_reason` -> `graq_learn(mode=outcome)`.
3. Before each tool call: `graq_route(intent=<message>)` to get suggested tool + confidence.
4. Show routing chip in chat UI: "using graq_impact because you asked about blast radius".
5. Cost envelope: target $0.079/turn, ceiling $0.10/turn per GRAQ_default.md.

### Week 3 — Layer 4 CGI Tasks (after `graq_cgi_task` ships)

1. Register Tree View "GraQle Tasks" grouped by status.
2. Click task -> detail panel with description, blocked_by, review history, artifacts.
3. Register Webview "Impact Graph" with Cytoscape.js for task dependency visualization.
4. Commands: "Create Task from Selection", "Show Next Task".

### Week 4 — Layer 6 + 7 polish

1. Wire all CLI commands through the MCP transport (for extension users who don't use terminal).
2. Local telemetry to `.graqle/vscode_telemetry.jsonl`.
3. Update prompt when `pip show graqle` version < PyPI latest.

---

## Critical integration rules

1. **Never read `.claude/settings.json` or `graqle.json` directly.** Always use MCP tools (`graq_gate_status`, `graq_inspect`, `graq_context`, etc.) so the SDK can change storage without breaking the extension.

2. **The `GRAQLE_CLIENT_MODE=vscode` env var** bypasses the Claude Code governance gate hook. Set this on any child process the extension spawns so the hook doesn't block the extension's own tool calls.

3. **The walk-up `GRAQ.md` at workspace root** is loaded by the ChatAgentLoop v4 on every session start. The extension should watch this file and hot-reload on change.

4. **TCG state (67 tools / 20 intents / 8 workflows / 20 lessons / 171 edges)** is the tool-routing table. It's loaded from the installed wheel at `graqle/chat/templates/tcg_default.json`. Do NOT ship a copy in the extension; always read through the SDK.

5. **CGI storage location is TBD** (operator decision pending between `.graqle/cgi.json` vs `graqle.json` namespace). Build the extension to query through MCP only so you're immune to this decision.

6. **The `graq_write` new-file allowlist** (CG-03 carve-out) allows `graq_write` for files that don't yet exist or are under `.tmp_*` / `scripts/` / `tests/`. Existing code files require `graq_edit`. The extension should respect this by calling `graq_edit` for modifications and `graq_write` for new scaffolding.

---

## Testing checklist for v0.4.0

Before shipping v0.4.0, verify:

- [ ] `graq gate-status --json` returns the full contract on Windows + macOS + Linux
- [ ] Gate chip goes green on a fresh `graq init` project
- [ ] Gate chip goes red when `.claude/hooks/graqle-gate.py` is deleted
- [ ] Gate chip goes yellow when interpreter is corrupted (edit settings.json command to "fake-python")
- [ ] "Fix" button runs `graq gate-install --fix-interpreter` and chip goes green
- [ ] `graq lint-public --json` returns `{"violations": [], "count": 0}` on the SDK repo
- [ ] ChatParticipant `@graqle hello` returns a response using the KG
- [ ] Status bar shows node/edge counts from `graq_inspect(stats=true)`
- [ ] Extension gracefully degrades when SDK version < 0.51.0 (modal, no crash)
- [ ] Extension works when `graqle` is not installed at all (modal, no crash)

---

## Contacts

- **SDK issues:** quantamixsol/graqle (public) or quantamixsol/research-development-graqle (private)
- **ADR-154 full spec:** `.gsm/decisions/ADR-154-vscode-extension-integration-spec.md` in the SDK repo
- **v0.51.0 implementation spec:** `.gcc/V0510-SPEC.md` (gitignored, local to the SDK dev tree)
- **Governance gap tracker:** `.gcc/OPEN-TRACKER-CAPABILITY-GAPS.md` (all CG-* items)

**The SDK side is ready. Build the extension.**
