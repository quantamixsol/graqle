# ADR-123: Knowledge Graph Sync — S3 as Single Source of Truth

**Date:** 2026-03-28 | **Status:** ACCEPTED
**Triggered by:** graqle.json local file had 5,002 nodes while S3 had 5,579 — 577 learned nodes invisible to local reasoning sessions. Verified by full graqle multi-agent reasoning audit (72% confidence, zero agent contradictions, 10 failure categories identified).

---

## Context: The Complete Failure Map

graqle reasoning identified **10 categories of sync failure** (not 1, not 2 — 10):

| # | Category | Failure Mode | Severity |
|---|----------|-------------|----------|
| 1.1 | **Startup** | `_load_graph` reads local only — never fetches S3 at any startup path | CRITICAL |
| 2.1 | **Scan overwrite** | `graq scan` rebuilds from source; `--preserve-learned` is local-only merge | CRITICAL |
| 2.3 | **Scan sync** | `auto_cloud_sync` after scan swallows all exceptions with bare `except: pass` | CRITICAL |
| 3.1 | **No auto-push** | `graq_learn`, `predict --fold-back`, SCORCH, Phantom, runtime events — none push to S3 | CRITICAL |
| 3.2 | **No auto-pull** | `graq mcp serve`, `graq serve`, `graq reason`, `graq run` — none pull before loading | CRITICAL |
| 3.3 | **Stale push** | `graq cloud push` after `git reset --hard` overwrites newer cloud with older local — no conflict detection | CRITICAL |
| 4.x | **MCP restart** | Restart loads stale local; in-flight nodes in old server's memory are lost | HIGH |
| 5.x | **Git operations** | `git checkout`, `git reset --hard`, `git stash pop` silently destroy learned nodes; MCP hot-reload amplifies damage by immediately loading the git-restored stale file | HIGH |
| 6.x | **Concurrent instances** | Multiple MCP servers = last-write-wins, no merge. Cross-machine = no coordination at all | HIGH |
| 7.x | **Lambda** | Frozen snapshot at deploy; `/tmp` ephemeral; N concurrent instances = N independent graphs | HIGH |

**The structural root cause:** `graqle.json` was designed as a local-first, single-process, single-machine artifact at every layer. No hot-path mutation (learn, scan, predict, SCORCH, Phantom) contains any S3 call. Cloud sync is an opt-in afterthought requiring explicit user action.

---

## Decision

**S3 is the single source of truth. Local `graqle.json` is a write-through cache.**

The new contract:
- **Every write** to `graqle.json` triggers a background S3 push (non-blocking, best-effort)
- **Every server startup** pulls from S3 before loading local (pull-before-read)
- **`graq cloud pull`** actually downloads `graqle.json` from S3 (currently a stub)
- **`graq cloud push`** detects conflicts before overwriting (version/timestamp check)
- **`graq scan`** always pulls from S3 before scanning and pushes after (with learned node preservation)

---

## Implementation Plan (feature/kg-sync-v039)

### Phase 1 — Pull-before-read (startup safety)
**File:** `graqle/plugins/mcp_dev_server.py` → `_load_graph()`
**File:** `graqle/server/app.py` → `_load_graph_from_config()`

Add a `_try_pull_from_s3()` call before local file load:
```python
def _load_graph(self):
    self._try_pull_from_s3()   # NEW: best-effort, timeout=3s, silent on failure
    # ... existing local load logic unchanged ...
```
- Timeout: 3 seconds max. If S3 unreachable: log warning, continue with local.
- Only pulls if S3 version is NEWER than local (compare `last_modified` metadata).
- Skips pull if `GRAQLE_OFFLINE=1` env var is set (for air-gapped/CI environments).

### Phase 2 — Push-after-write (mutation safety)
**File:** `graqle/plugins/mcp_dev_server.py` → `_save_graph()`

Add async background push after every local write:
```python
def _save_graph(self, graph):
    _write_with_lock(...)      # existing: write to local
    self._background_push()    # NEW: non-blocking S3 push
```
- Fire-and-forget using `threading.Thread(daemon=True)`.
- Retry once on failure, then log and discard. Never block the learn call.
- Rate-limited: max 1 push per 5 seconds (debounce for rapid learn bursts).
- Skips push if `GRAQLE_OFFLINE=1`.

### Phase 3 — Implement `graq cloud pull` properly
**File:** `graqle/cli/commands/cloud.py` → `cloud_pull()`

Currently returns project list only. Implement actual download:
```
graq cloud pull                    # pull current project
graq cloud pull --project graqle   # pull specific project
graq cloud pull --merge            # merge instead of overwrite (preserve local learned nodes)
```
- Default: pull + merge (local learned nodes that don't exist in S3 are preserved).
- `--overwrite`: full replacement (use when S3 is authoritative).
- Shows diff summary: `+N nodes added from cloud, -N stale local nodes removed`.

### Phase 4 — Conflict detection in `graq cloud push`
**File:** `graqle/cli/commands/cloud.py` → `cloud_push()`

Before overwriting S3, check S3 `last_modified` timestamp:
```
if s3_timestamp > local_timestamp:
    warn: "Cloud is newer than local. Run 'graq cloud pull --merge' first."
    abort unless --force flag provided
```

### Phase 5 — Fix `graq scan` silent failure
**File:** `graqle/cli/commands/scan.py`

- Before scan: pull from S3 (so `--preserve-learned` has latest learned nodes)
- Replace bare `except: pass` in `auto_cloud_sync` with logged exception
- After scan: push to S3 (with retry, not silent)

### Phase 6 — Lambda startup S3 load
**File:** `graqle/server/app.py` (Lambda handler path)

On cold start: fetch `graqle.json` from S3 into `/tmp`, load from there.
On warm invocation: check S3 `ETag` vs cached version; reload only if changed.

---

## What is NOT in scope (deferred)
- Multi-user real-time merge (CRDT / operational transforms) — v0.40+
- Cross-machine concurrent write coordination (distributed lock) — v0.40+
- S3 strong consistency guarantee for LIST operations — platform behavior, not fixable in SDK
- Full offline/air-gapped mode with explicit sync points — v0.40+

---

## Edge Cases Explicitly Addressed

| Edge Case | Handling |
|-----------|----------|
| S3 unreachable at startup | Log warning, load local, continue |
| S3 unreachable after graq_learn | Log warning, local write is safe, retry on next push |
| git reset destroys local | Hot-reload loads git version; next graq_learn will push it to S3 — BUT: S3 still has pre-reset state. Use `graq cloud pull --merge` to recover |
| git reset then graq cloud push | Phase 4 conflict detection catches this — S3 is newer, abort push |
| Multiple MCP instances on same machine | Both push to S3; S3 becomes merge point. Last push wins per-node (acceptable for single-user scenario) |
| Rapid graq_learn bursts | Phase 2 rate-limiting: debounce to 1 push per 5s |
| graq scan overwrites learned nodes | Phase 5: pull before scan + preserve-learned from S3 version |
| Lambda concurrent instances | Phase 6: all read from S3 on init; no `/tmp` divergence |
| GRAQLE_OFFLINE=1 (CI, air-gapped) | All S3 calls skipped; local-only behavior preserved |

---

## Success Criteria (binary, testable)

```
□ graq_learn → graqle.json updated locally → S3 updated within 10s
□ graq mcp serve (fresh machine, no local graqle.json) → pulls from S3 → reasons over cloud graph
□ git reset --hard → graq cloud pull --merge → learned nodes restored
□ graq cloud push when S3 is newer → aborts with conflict warning
□ graq scan → preserves all learned nodes (local + cloud) → pushes merged result
□ Lambda cold start → loads from S3 → not from frozen deploy snapshot
□ GRAQLE_OFFLINE=1 → all S3 calls skipped → no errors
```

---

## Affected Files (impact radius)

| File | Change | Risk |
|------|--------|------|
| `graqle/plugins/mcp_dev_server.py` | `_load_graph`, `_save_graph` | HIGH — 45 connected components |
| `graqle/cli/commands/cloud.py` | `cloud_pull` implementation | MEDIUM |
| `graqle/cli/commands/scan.py` | pre-pull, post-push, fix silent failure | MEDIUM |
| `graqle/server/app.py` | Lambda startup S3 load | MEDIUM |
| `graqle/core/graph.py` | No changes needed | — |
| New: `graqle/core/kg_sync.py` | Background push worker, pull-before-read utility | LOW (new file) |

**Total test files to update:** `test_mcp_dev_server.py`, `test_mcp_dev_server_v015.py`, `test_cloud/test_sync.py`, `test_cli/test_scan.py`, `test_plugins/test_phantom.py` (hardcoded counts)

---

## Consequences

**Positive:**
- Single source of truth: S3
- Learned nodes survive: git operations, server restarts, machine changes, Lambda cold starts
- graqle.com Studio always shows accurate node count matching local reasoning
- New team member: `graq cloud pull` → immediately has full graph

**Negative:**
- Every `graq_learn` now has a background thread (negligible CPU, ~200KB network per push)
- Startup is ~1-3s slower when S3 is reachable (pull check)
- Requires AWS credentials configured for background push (existing requirement)
- `GRAQLE_OFFLINE=1` must be documented for CI pipelines that don't have S3 access
