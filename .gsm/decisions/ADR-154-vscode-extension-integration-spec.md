# ADR-154: GraQle VS Code Extension — integration spec for autonomous, frictionless operation

**Date:** 2026-04-12 | **Status:** PROPOSED — v0.51.0 deliverable, blocks no prior work
**Supersedes:** parts of ADR-124 (VS Code onboarding UX), ADR-128 (KG merge)
**Related:** ADR-152 (ChatAgentLoop v4), ADR-153 (CGI — project self-memory), ADR-151 (per-call governance topology), ADR-143 (release artifact audit)
**Target:** `quantamixsol/graqle-vscode` v0.4.0 (depends on `graqle>=0.51.0`)

---

## Context

v0.50.0 shipped the SDK + `graq` CLI + MCP server.
v0.50.1 shipped the public-disclosure sanitization + Windows gate installer + `graq init` auto-gate + distribution lint + 6 governance robustness fixes.
ADR-152 defined the three runtime chat graphs (GRAQ.md, TCG, RCAG).
ADR-153 defined the fourth persistence graph (CGI — project self-memory).

The SDK is now self-sufficient on the command line: any GraQle-aware chat session inside Claude Code routes every write-class tool call through the governance gate, and every `graq_*` tool call records to the KG + audit log.

The VS Code extension is the remaining gap. Today it:

- Registers the MCP server but does **not** route the editor's own native writes through the gate
- Has no UI for the gate self-test report, so a broken install looks green
- Does not surface the TCG, CGI, or chat-session memory anywhere in the workspace
- Does not run the 12-point post-install dogfood smoke check on upgrade
- Does not expose `graq_predict` / `graq_reason` / `graq_learn` outside of chat turns
- Does not prompt the user to run `graq gate-install` when missing, or to re-run `--fix-interpreter` when the interpreter drifted

This ADR specifies the integration surface for the extension team to close all of these gaps so that **GraQle runs autonomously inside VS Code with no terminal commands required** once the extension is installed.

## Decision

**Ship `graqle-vscode` v0.4.0 with a 7-layer integration stack on top of the v0.51.0 SDK**, using an explicit contract between extension and SDK so neither side can drift silently.

### Layer 1 — SDK version pin + handshake

The extension must declare a hard minimum SDK version and refuse to activate if unmet.

**Extension behavior on activation:**
1. Locate the workspace's Python interpreter (same probe order as `graq gate-install`: `sys.executable → python3 → python → py -3`, skip Windows Store stub).
2. Run `python -c "from graqle import __version__; print(__version__)"` and parse.
3. If version `< 0.51.0`: show a modal offering `pip install --upgrade graqle>=0.51.0`. Do **not** activate features until satisfied.
4. Call the MCP handshake: send `graq_lifecycle(event="session_start")` with `context="vscode-extension-activation"` and store the returned session id. If the handshake returns non-`ok`, surface a "GraQle backend not available" status bar entry and stop.
5. Call `graq_inspect(stats=true)` and render the KG stats in the status bar (nodes/edges/components), updated every 30 seconds while the extension is active.

**SDK contract:**
- `graq_lifecycle(event="session_start")` returns `{event, graph_loaded, graph: {nodes, edges, components, hub_nodes}, backend: {status, backend}, active_branch}` — stable since v0.50.0, guaranteed for v0.51.0+.
- `graq_inspect(stats=true)` returns the same shape as today — stable since v0.32.
- The SDK ships a `graqle-vscode-manifest.json` at `graqle/data/vscode_manifest.json` (new in v0.51.0) that declares the contract version, supported MCP tool list, and minimum extension version. Extension loads this on every activation and logs a telemetry event if the contract version has changed.

### Layer 2 — Governance gate auto-install + health check

The extension must ensure the Claude Code governance gate is installed and enforcing, not just present on disk.

**Extension behavior:**
1. After SDK handshake succeeds, call `graq_gate_status` (new MCP tool to add in v0.51.0 — see Layer 5) to check: `installed`, `enforcing`, `interpreter_valid`, `self_test_passed`.
2. If not installed: show an info toast "GraQle governance gate not installed — click to install" that runs `graq gate-install --force` via `child_process.spawn(interpreter, ['-m', 'graqle.cli.main', 'gate-install', '--force'])`. Stream stdout to a VS Code output channel.
3. If installed but self-test failed: show a warning toast "Gate install is broken — click to fix" that runs `graq gate-install --fix-interpreter`.
4. Status bar entry shows a colored chip: 🟢 ENFORCING / 🟡 INSTALLED_NOT_ENFORCING / 🔴 NOT_INSTALLED / ⚫ UNKNOWN.
5. Click the chip → opens a webview showing the full self-test report (interpreter path, exit code, stderr snippet, last gate-install timestamp, last-known-good interpreter).

**SDK contract (v0.51.0 addition):**
- New MCP tool `graq_gate_status` that returns `{installed: bool, enforcing: bool, interpreter: str, interpreter_valid: bool, self_test: {exit_code: int, stderr_snippet: str, ran_at: str, passed: bool}, hook_path: str, settings_path: str, last_fix_interpreter_at: str | null}`.
- Implementation reads `.claude/settings.json`, checks the hook file exists, optionally runs the self-test on demand, and reports without side effects.
- Add `GATE_STATUS_UPDATED` event to `graqle-vscode-manifest.json` so extensions know they need to re-query this tool.

### Layer 3 — ChatAgentLoop v4 UI surface (uses GRAQ.md + TCG + RCAG)

The extension ships a dedicated Chat view panel backed by ADR-152's ChatAgentLoop v4.

**Extension behavior:**
1. Register a VS Code `ChatParticipant` named `@graqle` that routes every user message through `graq_context(deep)` → `graq_reason` → `graq_learn(mode=outcome)` end-to-end.
2. The walk-up `GRAQ.md` file at the workspace root (shipped in v0.50.1 Fix 2) is loaded on every chat session start and merged on top of the built-in floor. User's GRAQ.md edits are hot-reloaded on file change.
3. TCG-based tool routing: before each tool call in a chat turn, call `graq_route(intent=<user message>)` to get the suggested `graq_*` tool. Surface this as a soft chip in the chat UI ("using graq_impact because you asked about blast radius") so the user sees the reasoning.
4. RCAG memory: every turn's `graq_context` result, tool call sequence, and reasoning output is written to a per-session `.graqle/chat/rcag/<session-id>.jsonl` ledger. The extension exposes a "show session trace" command that opens this file in a tab.
5. Cost envelope chip in the chat UI: target $0.079/turn, hard ceiling $0.10/turn per GRAQ_default.md. When a turn exceeds the target, emit a yellow chip; when it exceeds the ceiling, block the next tool call and prompt the user to continue or abort.

**SDK contract (v0.51.0 addition):**
- MCP tool `graq_route(intent: str) → {recommended_tool: str, confidence: float, rationale: str, fallback_tools: list[str]}` that wraps the existing TCG routing logic from `graqle.chat.tcg`. The TCG state (67 tools / 20 intents / 8 workflows / 20 lessons / 171 edges as of v0.50.1) is the lookup table.
- MCP tool `graq_chat_session_trace(session_id: str | null) → {session_id, turns: [...], cost_usd, tools_used_count, rcag_path}` that reads the per-session JSONL ledger.
- Cost tracking hooks in the MCP handler so each tool call reports `cost_usd` in the tool result (already available for `graq_reason`; extend to all governed tools).

### Layer 4 — CGI project self-memory surface (new in v0.51.0 per ADR-153)

The extension surfaces CGI as a Tasks view + a dependency-graph webview.

**Extension behavior:**
1. Register a Tree View "GraQle Tasks" grouped by `status` (pending / in_progress / blocked / completed / shipped), reading CGI Task nodes via `graq_context(task="all CGI tasks", level="deep")`.
2. Click a task → opens a detail panel with: description, blocked_by, parent, review history (list of Review nodes with severity counts), artifacts produced, session provenance (which sessions touched it), lessons learned.
3. Register a Webview "GraQle Impact Graph" that visualizes a selected Task's dependency subgraph (1-hop, 2-hop, 3-hop) via Cytoscape.js, rendering `DEPENDS_ON`, `BLOCKS`, `PARENT_OF`, `VALIDATED_BY`, `PRODUCED`, `LEARNED` edges with distinct colors.
4. Register a command "GraQle: Create Task from Selection" that takes the current editor selection (typically a TODO comment), calls `graq_learn(mode=outcome, action=<selection>)` + creates a new CGI Task node via `graq_context` write mode, and links it to the current file via a `PRODUCED` edge.
5. Register a command "GraQle: Show Next Task" that runs `graq_context(task="what's next")` → picks the highest-priority pending task (by `blocked_by` count + dependency weight) → opens its detail panel.

**SDK contract (v0.51.0 addition):**
- MCP tool `graq_cgi_task(op: "create" | "read" | "update" | "list", id: str | null, fields: dict | null)` as the CGI CRUD entry point. Implementation is the ADR-153 entity-CRUD path on the existing `graqle.json` graph with `entity_type="cgi_task"`.
- MCP tool `graq_cgi_checkpoint(session_id: str | null) → {checkpoint_id, resume_brief: str, next_task_id: str, sdk_version_staged: str}` that creates or reads a CGI Checkpoint node for session handoff — this is the core value proposition of ADR-153.
- Read-through: existing `graq_context` and `graq_reason` activate CGI nodes the same way they activate code nodes; no new read tool needed.

### Layer 5 — New MCP tools to ship in v0.51.0 SDK

The extension depends on these tools being in the SDK. They must all land as part of v0.51.0 with full test coverage and a row in the governance-gate allowlist.

| Tool | Scope | Purpose | Owner |
|---|---|---|---|
| `graq_gate_status` | read | Status + self-test of the Claude Code governance gate | CLI team |
| `graq_route` | read | TCG-backed intent → tool recommendation | Chat team |
| `graq_chat_session_trace` | read | Read per-session RCAG ledger | Chat team |
| `graq_cgi_task` | write | CGI Task node CRUD | Graph team |
| `graq_cgi_checkpoint` | write | CGI Checkpoint node create/read | Graph team |
| `graq_lint_public_disclosure` | read | Run the distribution lint regex scan (Fix 9) as a standalone tool | CLI team |
| `graq_dogfood_smoke` | read | Run the 12-point post-publish smoke from a clean venv perspective | CLI team |

Each tool:
1. Must have a tool hint in `graqle-vscode-manifest.json`
2. Must be tested in `tests/test_plugins/test_mcp_dev_server.py`
3. Write-class tools must respect `CG-02_PLAN_GATE` + `CG-03_EDIT_GATE` (the latter with the v0.51.0 new-file allowlist carve-out from CG-GATES-FRICTION-01 item 2)

### Layer 6 — CLI parity commands shipped alongside MCP tools

Every new MCP tool from Layer 5 also gets a `graq` CLI subcommand so operators can run it without the MCP server:

```
graq gate status          # equivalent to MCP graq_gate_status
graq gate self-test       # runs the post-install self-test standalone
graq lint public          # runs the distribution lint (formerly pytest-only)
graq dogfood smoke        # runs the 12-point post-publish smoke
graq cgi task list --status pending
graq cgi task show <id>
graq cgi checkpoint show  # read the most recent Checkpoint
graq chat trace [session-id]
graq route "<intent>"     # uses TCG to recommend a tool
```

The CLI subcommands and the MCP tools share the same implementation functions, no duplication. This is how the v0.50.1 `gate-install` already works.

### Layer 7 — Telemetry + update prompts

The extension reports health metrics to a user-owned local file `.graqle/vscode_telemetry.jsonl` (opt-out via `graqle.telemetry.enabled: false` in workspace settings). No network calls; this is purely for the user's own dashboard.

Metrics:
- Extension activation count + duration
- SDK version detected
- Gate status transitions (NOT_INSTALLED → ENFORCING, etc.)
- Chat turn count + total cost_usd
- Top 10 most-routed tool intents via TCG
- CGI Task creation / completion / shipping rate
- Capability gap hits (e.g., graq_bash Windows cmd.exe friction from CG-GATES-FRICTION-01)

Update prompts:
- When `pip show graqle` version < latest PyPI version: status bar chip flashes orange with a "GraQle update available" tooltip.
- When `graqle-vscode-manifest.json` contract version bumps: show a modal explaining what changed and requiring a workspace reload.

---

## Integration sequencing — what the VS Code team ships first

Week 1:
1. **Layer 1 handshake** (SDK version pin, lifecycle call, inspect stats status bar). Ship as v0.4.0-alpha1.
2. **Layer 2 gate status** (new `graq_gate_status` MCP tool on the SDK side first, then the chip UI on the extension side). Requires v0.51.0 SDK merged.

Week 2:
3. **Layer 5 Chat team tools** (`graq_route`, `graq_chat_session_trace`) — these are read-only and can ship independently.
4. **Layer 3 Chat view** (ChatParticipant + GRAQ.md hot reload + TCG routing chip + cost envelope). Depends on Week 1 + the two Chat team tools.

Week 3:
5. **Layer 5 Graph team tools** (`graq_cgi_task`, `graq_cgi_checkpoint`) — requires ADR-153 CGI storage path agreed (see open questions below).
6. **Layer 4 Tasks view** (Tree View + Impact Graph webview + the 2 new commands). Depends on Week 3 SDK tools.

Week 4:
7. **Layer 5 CLI team tools** (`graq_lint_public_disclosure`, `graq_dogfood_smoke`, `graq_gate_status`) — the last two are read-only parity with existing pytest logic.
8. **Layer 6 CLI parity commands** — shipped in the same v0.51.0 SDK release.
9. **Layer 7 telemetry** — local file only, no UI dependencies.

Ship order: SDK v0.51.0 merged + tagged + on PyPI first, then extension v0.4.0 in a follow-up release that pins `graqle>=0.51.0` in its version check.

---

## Open questions for the VS Code team

1. **Webview framework choice:** Cytoscape.js for the Impact Graph, or d3-force? Impact Graph shows up to 3-hop dependency subgraphs (typical node count 20-100). Cytoscape has better interactive pan/zoom; d3-force is lighter.
2. **ChatParticipant cost cap enforcement:** soft warning on $0.079/turn is clear, but what's the UX when the hard $0.10 ceiling hits mid-turn? Modal "continue / abort / raise budget"? Or just halt and surface the error? Recommend modal with 3 options.
3. **CGI storage location:** ADR-153 leaves this as an open question (`.graqle/cgi.json` vs `graqle.json` under a namespace). The extension's implementation should be neutral — query through MCP tools only, never directly read the storage file. That way the SDK can change storage without breaking the extension.
4. **Multi-workspace handling:** what happens if the user opens a folder that doesn't have `graqle` installed? Should the extension prompt to run `graq init --no-gate` (Layer 1) automatically or only on user opt-in? Recommend opt-in with a welcome message on first folder open.
5. **Gate status polling interval:** every 30s is overkill — a file watcher on `.claude/settings.json` + `.claude/hooks/graqle-gate.py` plus a manual "re-check" button is cheaper. Recommend file watcher.

---

## Consequences

**Positive:**
- GraQle is usable inside VS Code with zero terminal commands once the extension is installed. New users run "Install extension → open folder → extension prompts for `graq init` → gate auto-installs → chat is available." Zero hand-written configuration.
- Every v0.51.0 governance improvement (gate robustness hardening, fail-safest risk mapping, self-test enforcement) is visible in the VS Code UI through the gate status chip.
- The ChatAgentLoop v4 three-graph architecture from ADR-152 has a first-class UI surface instead of being invisible behind the MCP wire.
- CGI project self-memory (ADR-153) becomes visible via the Tasks view, closing the "every session re-pays the bootstrap tax" gap that motivated ADR-153 in the first place.
- Operators can debug a broken gate install from the UI instead of SSHing into the project and running CLI commands.
- The seven new MCP tools are dual-purpose (MCP + CLI), so we don't duplicate implementation between the extension and the SDK.

**Negative:**
- The extension v0.4.0 depends on SDK v0.51.0 — releases must be coordinated or the extension will soft-break on older SDKs (mitigated by the Layer 1 version check).
- Seven new MCP tools expand the MCP surface, which requires more test coverage and more governance gate allowlist entries.
- CGI storage path (open question 3) is a design-time risk — if the SDK changes the CGI storage format mid-v0.51.x patch line, the extension must be resilient (enforced by "query through MCP only" rule above).
- VS Code ChatParticipant API is relatively new and may shift between VS Code versions; pin to a range and test against both the current release and the next Insiders build.

**Neutral:**
- Webview assets (Cytoscape.js bundle) add ~500 KB to the extension package; acceptable.
- Extension telemetry is local-only per Layer 7, which avoids privacy review but also gives us no fleet-wide dashboard — acceptable for v0.4.0, revisit for v0.5.0 if a dashboard becomes a customer ask.

---

## Validation plan

Before v0.4.0 ships:

1. **End-to-end extension test:** Install `graqle==0.51.0` in a fresh venv, install the extension in a VS Code Insiders build, open an empty workspace, confirm: (a) activation prompts for `graq init`, (b) gate auto-installs after init, (c) chat participant responds to `@graqle hello`, (d) Tasks view shows the seeded CGI tasks, (e) Impact Graph renders for a sample task.
2. **Windows Python stub test:** On a fresh Windows 11 VM with only the Windows Store Python stub installed (no real Python), confirm the extension still activates correctly and prompts the user to install a real Python before attempting `graq init`.
3. **Broken-gate recovery test:** Manually corrupt `.claude/settings.json` (delete the hook command), confirm the status chip goes red, clicking it opens the self-test report, clicking "fix" runs `graq gate-install --fix-interpreter` and the chip goes green.
4. **CGI round-trip test:** Create a Task via the "Create Task from Selection" command, confirm it appears in the Tasks view, mark it completed via the detail panel, confirm `graq_context(task="completed tasks")` returns it in the result set.
5. **Contract version bump test:** Bump the contract version in `graqle-vscode-manifest.json`, confirm the extension surfaces a modal on next activation.

---

## Dependencies

- SDK v0.51.0 must ship **first** with all 7 new MCP tools in Layer 5 and all 9 new CLI subcommands in Layer 6.
- ADR-153 CGI storage decision must be made before `graq_cgi_task` / `graq_cgi_checkpoint` implementation begins. Recommend deciding in the v0.51.0 governance kickoff.
- ADR-152 ChatAgentLoop v4 infrastructure (TCG + RCAG + GRAQ.md walk-up loader) is already in v0.50.1 — no new SDK work needed for the chat routing path.
- Windows gate installer probe from v0.50.1 Fix 5 (`_probe_python_interpreter`) is reused by the extension's Layer 1 activation.

---

## Decision log

- **2026-04-12, Opus 4.6 under autonomous v0.51.0 session:** Drafted ADR-154 as the first deliverable of the VS Code extension integration track after the operator asked for a concrete specification of what the extension team needs to do. Held off on implementation of any of the 7 new MCP tools in this autonomous window — they are tracked as v0.51.0 scope items and will land in a follow-up implementation session with proper `graq_plan` + `graq_review` chain. Pending operator review before any Layer 5 tool lands.
