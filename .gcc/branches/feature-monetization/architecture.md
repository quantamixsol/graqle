# Graqle Cloud Architecture — Final Decision
**Date:** 2026-03-26 | **Confidence:** 96% (33-agent unanimous consensus)

---

## VERDICT: Local-First with Async Cloud Sync

This is not a new decision — it ratifies the architecture that already exists in the codebase.

```
LOCAL GRAPH (graqle.json)          CLOUD (S3 + Neptune)
─────────────────────────          ────────────────────
Primary — always fast (<10ms)      Secondary — backup + team visibility
Source of truth                    Eventually consistent copy
Works offline / free tier          Team tier only
Never blocked by cloud failures    Async fire-and-forget push
```

### Why local-first wins (hard numbers)
| Factor | Local | Cloud (Neptune) |
|--------|-------|-----------------|
| Query latency | <10ms | 200ms+ (VPC roundtrip) |
| Cold start | 0ms | 3–5s (Lambda) |
| Idle cost | $0 | $57/month |
| Free tier | ✅ Full | ❌ Blocked |
| Offline | ✅ Works | ❌ Dead |

---

## The Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────┐
│  LAYER 1: LOCAL (every user, always)                     │
│  graqle.json  ←  graq scan / grow / learn / run         │
│  <10ms latency, atomic writes, auto-backup (.json.bak)  │
├─────────────────────────────────────────────────────────┤
│  LAYER 2: CLOUD BACKUP (free + team, auto-push)          │
│  S3 bucket  ←  graq cloud push (after every graph write)│
│  Async, non-blocking, retry on failure                   │
│  graqle.com/dashboard shows graph, metrics, lessons      │
├─────────────────────────────────────────────────────────┤
│  LAYER 3: NEPTUNE (team only, cross-project)             │
│  Neptune Serverless  ←  Lambda ingest (server-side)     │
│  Studio cross-project queries, shared lessons            │
│  Only activated when plan=team + cloud authenticated     │
└─────────────────────────────────────────────────────────┘
```

---

## How `graq cloud push` works from ANY project directory

From ANY project directory (graqle-sdk, graqle-studio, CrawlQ, etc.):
```bash
graq cloud push
```

Flow:
1. `_detect_project_name()` reads project name from graqle.yaml / package.json / dir name
2. `load_credentials()` reads `~/.graqle/credentials.json` (or `GRAQLE_API_KEY` env var)
3. `_request_presigned_urls()` → POST `graqle.com/api/cloud/presign` with project name
4. Upload `graqle.json` + intelligence files → S3 bucket (per-user, per-project prefix)
5. If plan=team → Lambda also ingests to Neptune (server-side, VPC-accessible)

**This already works.** The graqle-sdk graph (5,002 nodes) was just pushed successfully.

---

## Auto-sync: what triggers it

| Trigger | Current state | Target state |
|---------|--------------|--------------|
| `graq scan repo .` | `auto_cloud_sync()` called but needs auth | ✅ Already wired, just needs Team license |
| `graq grow` | Not wired | Wire same `auto_cloud_sync()` call |
| `graq learn` | Not wired | Wire same `auto_cloud_sync()` call |
| Every `to_json()` write | Not wired | Add `_on_graph_mutated()` hook (Team only) |
| Git post-commit hook | `graq grow` runs | `graq grow` will trigger sync |

---

## The 8 Gaps (final, prioritized)

### P1 — Wire `auto_cloud_sync` to grow/learn (1 hour, ZERO risk)
**Files:** `cli/commands/grow.py`, `cli/commands/learn.py`
**Change:** Add same 5-line try/except `auto_cloud_sync()` block already in scan.py
**Test:** Existing cloud tests cover auto_cloud_sync behavior

### P2 — Incremental backup rotation instead of single .bak (2 hours, LOW risk)
**Files:** `cli/commands/scan.py`
**Change:** Rotate 3 backups: graqle.json.bak.1, .bak.2, .bak.3 instead of overwriting single .bak
**Test:** New test for rotation

### P3 — `/lessons` Studio route (2 hours, LOW risk)
**Files:** `graqle/studio/routes/api.py`
**Change:** Add GET `/lessons` that calls existing `_find_lesson_nodes()` backend
**Test:** New Studio route test

### P4 — `SyncEngine` + `CloudTransport` (1 day, MEDIUM risk)
**New files:** `graqle/cloud/transport.py`, `graqle/cloud/sync_engine.py`
**Purpose:** Delta-push (only changed nodes/edges), retry with backoff, team-only gate
**Test:** 5 new tests (sync_failure_does_not_block_local, sync_fires_after_write, etc.)

### P5 — Studio chat → MCP tool bridge (1 day, MEDIUM risk)
**Files:** `graqle/server/app.py`, Studio chat component
**Change:** Add `/cli/exec` WebSocket endpoint → maps chat input to `handle_tool()` → streams result
**Test:** Integration test for chat→tool→response roundtrip

### P6 — CLI metrics auto-push to Lambda (1 day, MEDIUM risk)
**Files:** `graqle/plugins/mcp_dev_server.py`, `graqle/server/app.py`
**Change:** Post-reasoning hook POSTs `ReasoningResult` metrics to Lambda `/metrics` ingestion endpoint
**Test:** Mock Lambda endpoint test

### P7 — NeptuneConnector implementing GraphConnector protocol (2 days, HIGH risk)
**New files:** `graqle/connectors/neptune_connector.py`, `graqle/connectors/neptune_traversal.py`
**Purpose:** Neptune on read path for Studio cross-project queries (load() + vector_search())
**Test:** Mocked Neptune integration tests (VPC-only, no live tests in CI)

### P8 — Cross-project graph federation (3 days, HIGH risk)
**Files:** `graqle/server/app.py`, `graqle/plugins/mcp_dev_server.py`
**Change:** Multi-graph query router, project-scoped reasoning, Studio project selector
**Test:** Multi-project fixture with 2+ project graphs

---

## Instructions for other projects

To add any project to Studio, from that project's directory:

```bash
# 1. One-time: scan the project
graq scan repo .

# 2. Push to cloud (credentials already in ~/.graqle/credentials.json)
graq cloud push

# 3. View at graqle.com/dashboard (login with harish.kumar@quantamixsolutions.com)
```

Projects appear under your account automatically. No `cd` to another project needed.
The `~/.graqle/credentials.json` is shared across ALL projects on your machine.

---

## Backup strategy (incremental, no machine pressure)

Current (just shipped): `graqle.json.bak` — single backup per project directory
Target (P2): 3-rotation backup:
- `graqle.json.bak.1` — last scan
- `graqle.json.bak.2` — 2 scans ago
- `graqle.json.bak.3` — 3 scans ago (oldest, ~1-3 days for active projects)

Cloud (S3) provides infinite history via S3 versioning — every `graq cloud push` is a new version.
Neptune provides point-in-time recovery at cluster level (1-day retention, configurable).
